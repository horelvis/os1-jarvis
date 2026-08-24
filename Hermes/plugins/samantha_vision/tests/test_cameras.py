"""The cameras, as a named list.

The names are what he says out loud and what the user asks for, so the
parsing rules are about keeping the list speakable: nameless entries are
dropped rather than numbered, and one bad entry never takes the working
cameras with it.
"""

import threading
import time
from contextlib import contextmanager

from loguru import logger

from Hermes.plugins.samantha_vision.cameras import (
    Camera,
    CameraFleet,
    parse_cameras,
    redact,
)
from Hermes.plugins.samantha_vision.vision import Detection


def test_two_named_cameras():
    cams = parse_cameras(
        {
            "cameras": [
                {"name": "fuera", "url": "rtsp://x/1"},
                {"name": "entrada", "url": "rtsp://x/2"},
            ]
        }
    )
    assert cams == [Camera("fuera", "rtsp://x/1"), Camera("entrada", "rtsp://x/2")]


def test_no_cameras_is_not_an_error():
    assert parse_cameras({}) == []
    assert parse_cameras({"cameras": []}) == []


def test_entry_without_a_name_is_dropped_not_fatal():
    # A typo in one entry must not take the working cameras with it.
    cams = parse_cameras(
        {
            "cameras": [
                {"url": "rtsp://x/1"},
                {"name": "entrada", "url": "rtsp://x/2"},
            ]
        }
    )
    assert cams == [Camera("entrada", "rtsp://x/2")]


def test_an_entry_that_is_not_a_mapping_is_dropped_not_fatal():
    # `- rtsp://x/1` instead of `- name: … / url: …` is the likeliest way
    # to write this key wrong, and it used to raise — which cost the
    # house every camera, not the bad line.
    cams = parse_cameras(
        {
            "cameras": [
                "rtsp://x/1",
                None,
                42,
                {"name": "entrada", "url": "rtsp://x/2"},
            ]
        }
    )
    assert cams == [Camera("entrada", "rtsp://x/2")]


def test_a_mapping_instead_of_a_list_is_not_fatal():
    # The other likely typo: names as keys. Nothing is watched, but the
    # gateway is told what it read rather than handed an AttributeError.
    assert parse_cameras({"cameras": {"fuera": "rtsp://x/1"}}) == []


def test_a_scalar_under_the_key_is_not_fatal():
    assert parse_cameras({"cameras": "rtsp://x/1"}) == []
    assert parse_cameras({"cameras": 7}) == []


def test_duplicate_names_keep_the_first():
    # Two cameras answering to one name makes the tool ambiguous; the
    # first wins and the second is dropped with a log line.
    cams = parse_cameras(
        {
            "cameras": [
                {"name": "fuera", "url": "rtsp://x/1"},
                {"name": "fuera", "url": "rtsp://x/2"},
            ]
        }
    )
    assert cams == [Camera("fuera", "rtsp://x/1")]


def test_a_file_path_is_a_valid_url():
    # A recording is how this is tested while the cameras are off.
    cams = parse_cameras({"cameras": [{"name": "prueba", "url": "/tmp/clip.mp4"}]})
    assert cams == [Camera("prueba", "/tmp/clip.mp4")]


# ── the fleet: one thread per camera ──────────────────────────────────
#
# Nothing here opens a camera, a socket or the GPU. `CameraFleet` takes
# the two boundaries that would — how a stream is opened and how a
# detector is built — as parameters, and these tests pass fakes.


@contextmanager
def captured_logs():
    records: list = []
    sink = logger.add(lambda message: records.append(message.record), level="DEBUG")
    try:
        yield records
    finally:
        logger.remove(sink)


class FakeStream:
    """Stands in for CameraStream: a list of frames, no decoder.

    `raises` is the shape that matters, and the shape these tests got
    wrong until 2026-08-24. `CameraStream(url)` only stores the url — it
    is `frames()` that calls `open()` and therefore `frames()` that
    raises when a camera is unreachable. Fakes that raised from
    `open_stream` were exercising a path the real code does not have,
    which is why neither the missing socket timeout nor the
    connects-but-yields-nothing case was ever caught here.
    """

    def __init__(self, frames: list, raises: Exception | None = None) -> None:
        self._frames = frames
        self._raises = raises
        self.closed = False

    def frames(self, every: int = 10):
        if self._raises is not None:
            raise self._raises
        yield from self._frames

    def close(self) -> None:
        self.closed = True


def dead(message: str = "connection refused"):
    """A camera that is off: constructed fine, fails on the first read."""
    return lambda url: FakeStream([], raises=OSError(message))


class FakeDetector:
    """Stands in for the YOLO session: whatever the frame says it saw."""

    def detect(self, frame) -> list[Detection]:
        return list(frame)


PERSON = Detection(label="persona", confidence=0.9, x=0.5, y=0.5)


def _fleet(**kwargs) -> CameraFleet:
    kwargs.setdefault("make_detector", FakeDetector)
    kwargs.setdefault("retry_seconds", 0.01)
    return CameraFleet(**kwargs)


def _wait(predicate, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_detections_arrive_carrying_the_camera_name():
    """The name is the whole point: "en la entrada" needs to know which."""
    seen: list[tuple[str, list]] = []
    fleet = _fleet(open_stream=lambda url: FakeStream([[PERSON]]))
    fleet.start(
        [Camera("entrada", "rtsp://x/1")],
        lambda name, detections: seen.append((name, detections)),
    )
    try:
        assert _wait(lambda: seen != [])
    finally:
        fleet.stop()

    assert seen[0] == ("entrada", [PERSON])


def test_each_camera_runs_in_its_own_named_thread():
    """`journalctl` and a traceback both have to say which camera."""
    threads: set[str] = set()

    def on_detections(name, detections):
        threads.add(threading.current_thread().name)

    fleet = _fleet(open_stream=lambda url: FakeStream([[PERSON]]))
    fleet.start(
        [Camera("fuera", "rtsp://x/1"), Camera("entrada", "rtsp://x/2")],
        on_detections,
    )
    try:
        assert _wait(lambda: threads == {"camera-fuera", "camera-entrada"})
    finally:
        fleet.stop()


def test_one_dead_camera_does_not_take_the_others_with_it():
    """A camera that is off is a Tuesday. The house keeps its other eyes."""
    delivered: list[str] = []

    def open_stream(url):
        if url == "rtsp://dead/1":
            return FakeStream([], raises=OSError("connection refused"))
        return FakeStream([[PERSON]])

    fleet = _fleet(open_stream=open_stream)
    fleet.start(
        [Camera("rota", "rtsp://dead/1"), Camera("buena", "rtsp://x/2")],
        lambda name, detections: delivered.append(name),
    )
    try:
        assert _wait(lambda: "buena" in delivered)
    finally:
        fleet.stop()


def test_a_dead_camera_logs_once_not_once_per_attempt():
    """A camera off for a week would otherwise fill the journal."""
    attempts: list[int] = []

    def open_stream(url):
        attempts.append(1)
        return FakeStream([], raises=OSError("connection refused"))

    with captured_logs() as records:
        fleet = _fleet(open_stream=open_stream)
        fleet.start([Camera("rota", "rtsp://dead/1")], lambda name, dets: None)
        try:
            assert _wait(lambda: len(attempts) >= 3)
        finally:
            fleet.stop()

    warnings = [
        r for r in records if r["level"].name == "WARNING" and "rota" in r["message"]
    ]
    assert len(warnings) == 1, [r["message"] for r in warnings]


def test_a_handler_that_raises_does_not_kill_the_camera():
    """Task 5 hangs a gateway call here. It must not cost us an eye."""
    calls: list[int] = []

    def on_detections(name, detections):
        calls.append(1)
        raise RuntimeError("the gateway said no")

    fleet = _fleet(open_stream=lambda url: FakeStream([[PERSON]]))
    fleet.start([Camera("fuera", "rtsp://x/1")], on_detections)
    try:
        assert _wait(lambda: len(calls) >= 2)
    finally:
        fleet.stop()


def test_stop_ends_every_thread():
    fleet = _fleet(open_stream=lambda url: FakeStream([[PERSON]]))
    fleet.start([Camera("fuera", "rtsp://x/1")], lambda name, dets: None)
    fleet.stop()

    assert not [t for t in threading.enumerate() if t.name.startswith("camera-")]


def test_a_missing_model_starts_nothing_and_does_not_raise():
    """Manifest failure mode #3: no model file, no threads, one line."""

    def make_detector():
        raise FileNotFoundError("YOLO model not at /nowhere/yolov9-t-320.onnx")

    with captured_logs() as records:
        fleet = CameraFleet(
            make_detector=make_detector, open_stream=lambda url: FakeStream([])
        )
        fleet.start([Camera("fuera", "rtsp://x/1")], lambda name, dets: None)
        fleet.stop()

    assert not [t for t in threading.enumerate() if t.name.startswith("camera-")]
    assert any("yolov9" in r["message"] for r in records)


# ── the credential never reaches the journal ──────────────────────────
#
# PyAV puts the whole URL into the message of every failure it raises,
# and the URL carries the camera password. Found 2026-08-24, the first
# time the plugin was pointed at the real cameras: a camera that is off
# fails on a loop, so the credential lands in `journalctl` again and
# again in plaintext.


def test_redact_removes_the_password_but_keeps_the_user():
    assert (
        redact("rtsp://admin:hunter2@192.168.100.143:554/h264Preview_01_sub")
        == "rtsp://admin:***@192.168.100.143:554/h264Preview_01_sub"
    )


def test_redact_leaves_a_url_without_credentials_alone():
    assert redact("rtsp://192.168.100.143:554/x") == "rtsp://192.168.100.143:554/x"
    assert redact("/home/nexus/clip.mp4") == "/home/nexus/clip.mp4"


def test_a_dead_camera_does_not_log_its_password():
    def open_stream(url):
        return FakeStream([], raises=OSError(f"No route to host: '{url}'"))

    with captured_logs() as records:
        fleet = _fleet(open_stream=open_stream)
        fleet.start(
            [Camera("fuera", "rtsp://admin:hunter2@192.168.100.142:554/sub")],
            lambda name, dets: None,
        )
        try:
            _wait(lambda: any("fuera" in r["message"] for r in records))
        finally:
            fleet.stop()

    joined = " ".join(r["message"] for r in records)
    assert "hunter2" not in joined, joined
    assert "admin:***@" in joined, joined


def test_a_malformed_entry_does_not_log_its_password():
    with captured_logs() as records:
        # No `name`, so it is dropped — and the dropped entry is logged.
        parse_cameras({"cameras": [{"url": "rtsp://admin:hunter2@10.0.0.1/sub"}]})
    joined = " ".join(r["message"] for r in records)
    assert "hunter2" not in joined, joined


def test_redact_handles_a_password_containing_an_at_sign():
    """ffmpeg splits the authority on the LAST `@`, so this is a real URL.

    A pattern that stopped at the first one left the tail of the password
    in the journal — and a partial redaction reads as a success.
    """
    assert (
        redact("rtsp://admin:p@ssw0rd@192.168.1.5:554/sub")
        == "rtsp://admin:***@192.168.1.5:554/sub"
    )


def test_redact_handles_an_empty_username():
    assert redact("rtsp://:hunter2@192.168.1.5/sub") == "rtsp://:***@192.168.1.5/sub"


def test_redact_does_not_run_across_two_urls_in_one_message():
    """The greedy half must stay inside one URL, or it swallows the pair."""
    assert (
        redact("rtsp://admin:hunter2@h/sub and rtsp://admin:hunter3@h2/sub")
        == "rtsp://admin:***@h/sub and rtsp://admin:***@h2/sub"
    )


def test_a_bare_url_under_the_key_does_not_log_its_password():
    """`cameras: rtsp://…` — a shape an operator plausibly writes."""
    with captured_logs() as records:
        parse_cameras({"cameras": "rtsp://admin:hunter2@10.0.0.1/sub"})
    joined = " ".join(r["message"] for r in records)
    assert "hunter2" not in joined, joined
    assert "admin:***@" in joined, joined


def test_a_bare_url_as_a_list_entry_does_not_log_its_password():
    """`- rtsp://…` instead of `- name: … / url: …`."""
    with captured_logs() as records:
        parse_cameras({"cameras": ["rtsp://admin:hunter2@10.0.0.1/sub"]})
    joined = " ".join(r["message"] for r in records)
    assert "hunter2" not in joined, joined
    assert "admin:***@" in joined, joined


# ── a camera that connects and yields nothing ─────────────────────────
#
# Manifest failure mode #4, added 2026-08-24. Nothing raises, so the
# `except` never runs: without this the backoff climbs to five minutes in
# total silence and the camera is indistinguishable from one with an
# empty driveway in front of it.


def test_a_camera_that_yields_no_frames_says_so_once():
    attempts: list[int] = []

    def open_stream(url):
        attempts.append(1)
        return FakeStream([])  # opens cleanly, returns cleanly, no video

    with captured_logs() as records:
        fleet = _fleet(open_stream=open_stream)
        fleet.start([Camera("entrada", "rtsp://x/1")], lambda name, dets: None)
        try:
            assert _wait(lambda: len(attempts) >= 3)
        finally:
            fleet.stop()

    warnings = [
        r for r in records if r["level"].name == "WARNING" and "entrada" in r["message"]
    ]
    assert len(warnings) == 1, [r["message"] for r in warnings]
    assert "no frames" in warnings[0]["message"]
    # The retries are still visible, just not at a level anybody reads.
    assert any(
        r["level"].name == "DEBUG" and "still producing no frames" in r["message"]
        for r in records
    )


def test_a_camera_that_starts_yielding_frames_is_not_reported_as_empty():
    """A recording that ends is normal. Only zero frames is a symptom."""
    with captured_logs() as records:
        fleet = _fleet(open_stream=lambda url: FakeStream([[PERSON]]))
        fleet.start([Camera("entrada", "rtsp://x/1")], lambda name, dets: None)
        try:
            assert _wait(lambda: any("entrada" in r["message"] for r in records))
        finally:
            fleet.stop()

    assert not [r for r in records if "no frames" in r["message"]]


# ── the password arrives from the environment, not from the URL ───────
#
# Ruling 21. `.hermes/home/config.yaml` writes `${RTSP_PASSWORD}` and
# `Hermes/run-gateway.sh` puts the value in the environment. The trap is
# an UNSET variable: `expandvars` leaves the literal text `${…}` behind,
# which would then be used as the password and logged.


def test_a_camera_url_expands_the_password_from_the_environment(monkeypatch):
    monkeypatch.setenv("RTSP_PASSWORD", "dummy-not-the-real-one")
    cameras = parse_cameras(
        {"cameras": [{"name": "entrada", "url": "rtsp://admin:${RTSP_PASSWORD}@h/sub"}]}
    )
    assert [c.url for c in cameras] == ["rtsp://admin:dummy-not-the-real-one@h/sub"]


def test_an_unset_variable_drops_the_camera_rather_than_connecting(monkeypatch):
    monkeypatch.delenv("RTSP_PASSWORD", raising=False)
    with captured_logs() as records:
        cameras = parse_cameras(
            {
                "cameras": [
                    {"name": "entrada", "url": "rtsp://admin:${RTSP_PASSWORD}@h/sub"}
                ]
            }
        )
    assert cameras == []
    joined = " ".join(r["message"] for r in records)
    assert "RTSP_PASSWORD" in joined
    # Never the URL: the literal `${RTSP_PASSWORD}` would otherwise be
    # used as a password and written into the journal by the first failure.
    assert "rtsp://" not in joined, joined


def test_a_url_with_no_variables_is_left_exactly_alone(monkeypatch):
    monkeypatch.delenv("RTSP_PASSWORD", raising=False)
    cameras = parse_cameras(
        {"cameras": [{"name": "entrada", "url": "/home/nexus/clip.mp4"}]}
    )
    assert [c.url for c in cameras] == ["/home/nexus/clip.mp4"]


def test_a_dollar_inside_the_password_survives_expansion(monkeypatch):
    """The check runs on the RAW url, so a `$` in the VALUE is not a
    placeholder and must not drop the camera."""
    monkeypatch.setenv("RTSP_PASSWORD", "a$b-dummy")
    cameras = parse_cameras(
        {"cameras": [{"name": "entrada", "url": "rtsp://admin:${RTSP_PASSWORD}@h/sub"}]}
    )
    assert [c.url for c in cameras] == ["rtsp://admin:a$b-dummy@h/sub"]
