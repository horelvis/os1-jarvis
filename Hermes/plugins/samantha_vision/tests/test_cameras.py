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
    """Stands in for CameraStream: a list of frames, no decoder."""

    def __init__(self, frames: list) -> None:
        self._frames = frames
        self.closed = False

    def frames(self, every: int = 10):
        yield from self._frames

    def close(self) -> None:
        self.closed = True


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
            raise OSError("connection refused")
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
        raise OSError("connection refused")

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
        raise OSError(f"No route to host: '{url}'")

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
