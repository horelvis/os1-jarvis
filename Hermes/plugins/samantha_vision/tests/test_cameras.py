"""The cameras, as a named list.

The names are what he says out loud and what the user asks for, so the
parsing rules are about keeping the list speakable: nameless entries are
dropped rather than numbered, and one bad entry never takes the working
cameras with it.
"""

import threading
import time
from contextlib import contextmanager

import numpy as np

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
        # Whatever `_watch` last handed this stream as `tap`. RECORDED, not
        # discarded: a fake that silently swallows the parameter the real
        # object acts on is a sink — a typo in `_watch` (`camera.url`
        # instead of `.name`, a dropped `.get()`) would pass every test
        # here without this.
        self.tap = None

    def frames(self, every: int = 10, tap=None):
        # Set before anything that could raise or return early, so even a
        # dead or empty stream still shows what `_watch` passed it — a
        # generator's body only starts running on the first `next()`, which
        # `for frame in stream.frames(...)` triggers immediately.
        self.tap = tap
        if self._raises is not None:
            raise self._raises
        yield from self._frames

    def close(self) -> None:
        self.closed = True


class ForeverStream(FakeStream):
    """Like `FakeStream`, but `frames()` never ends on its own.

    Needed specifically for the tests proving `set_tap`/`clear_tap`
    reach an ALREADY-RUNNING stream: `FakeStream.frames()` is finite,
    so `_watch` reopens it on every iteration, and a fix that only
    refreshes the tap on reconnect would still pass those tests by
    coincidence — the finite fake cannot tell "read live" apart from
    "read fresh every time it happens to reconnect". This one keeps a
    single `frames()` call running (yielding the same frames on a
    short loop) until `stop()` sets `_stopping`, so a test built on it
    can prove something changed WITHOUT a reconnect ever happening —
    `streams` staying at length 1 is that proof.
    """

    def __init__(self, frames: list, stopping: threading.Event) -> None:
        super().__init__(frames)
        self._stopping = stopping

    def frames(self, every: int = 10, tap=None):
        self.tap = tap
        while not self._stopping.is_set():
            yield from self._frames
            time.sleep(0.005)


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


def test_the_fleet_keeps_the_detector_it_built():
    """`mirar` runs YOLO over the frame it just grabbed, and must use
    THIS session rather than loading a second one for a model already
    resident. A fleet that never started has none — and it has no
    watcher thread either, so it can never hand anybody a frame."""
    fleet = _fleet(open_stream=lambda url: FakeStream([[PERSON]]))
    assert fleet.detector is None
    fleet.start([Camera("entrada", "rtsp://x/1")], lambda name, seen: None)
    try:
        assert isinstance(fleet.detector, FakeDetector)
    finally:
        fleet.stop()


def test_a_fleet_whose_detector_will_not_build_keeps_none():
    """The tool reads this attribute; "the model failed to load" must
    not look like "a detector that finds nothing"."""

    def explode():
        raise RuntimeError("no onnxruntime")

    fleet = _fleet(make_detector=explode)
    fleet.start([Camera("entrada", "rtsp://x/1")], lambda name, seen: None)
    try:
        assert fleet.detector is None
    finally:
        fleet.stop()


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


def test_a_bare_dollar_in_a_password_is_not_a_placeholder(monkeypatch):
    """A password may contain a `$`, and passwords are what this URL
    carries. Treating a bare `$word` as a variable dropped the camera and
    wrote a FRAGMENT OF THE PASSWORD into the journal — via the very
    warning built to keep it out. Measured 2026-08-24."""
    monkeypatch.delenv("secretpart", raising=False)
    with captured_logs() as records:
        cameras = parse_cameras(
            {
                "cameras": [
                    {"name": "entrada", "url": "rtsp://admin:pa$secretpart@h/sub"}
                ]
            }
        )
    assert [c.url for c in cameras] == ["rtsp://admin:pa$secretpart@h/sub"]
    joined = " ".join(r["message"] for r in records)
    assert "secretpart" not in joined, joined


def test_the_two_failure_modes_each_get_their_own_warning():
    """A camera flipping between unreachable and empty must not leave a
    stale WARNING describing the state it is no longer in."""
    state = {"n": 0}

    def open_stream(url):
        state["n"] += 1
        # unreachable, empty, unreachable, empty, ...
        if state["n"] % 2:
            return FakeStream([], raises=OSError("connection refused"))
        return FakeStream([])

    with captured_logs() as records:
        fleet = _fleet(open_stream=open_stream)
        fleet.start([Camera("entrada", "rtsp://x/1")], lambda name, dets: None)
        try:
            assert _wait(lambda: state["n"] >= 4)
        finally:
            fleet.stop()

    warnings = [
        r["message"]
        for r in records
        if r["level"].name == "WARNING" and "entrada" in r["message"]
    ]
    assert any("unreachable" in m for m in warnings), warnings
    assert any("no frames" in m for m in warnings), warnings


def test_one_persistent_failure_mode_still_costs_exactly_one_line():
    """The flip case must not undo the once-per-camera discipline."""
    attempts: list[int] = []

    def open_stream(url):
        attempts.append(1)
        return FakeStream([], raises=OSError("connection refused"))

    with captured_logs() as records:
        fleet = _fleet(open_stream=open_stream)
        fleet.start([Camera("entrada", "rtsp://x/1")], lambda name, dets: None)
        try:
            assert _wait(lambda: len(attempts) >= 4)
        finally:
            fleet.stop()

    warnings = [
        r for r in records if r["level"].name == "WARNING" and "entrada" in r["message"]
    ]
    assert len(warnings) == 1, [r["message"] for r in warnings]


# ── grab: the watcher hands over its next frame ────────────────────────
#
# "ahora" has to mean now. The watcher samples one frame in ten, so its
# last analysed frame can be 40 s old — grab() waits for the NEXT frame
# on the stream the watcher already has open, rather than reusing a
# stale one or opening a second RTSP session.


def test_grab_returns_the_next_frame_the_watcher_decodes():
    """The brief's own version of this test called `_offer` BEFORE
    `grab`, in-line, and asserted a non-None result — which contradicts
    `test_grab_never_returns_a_frame_the_watcher_already_analysed` below,
    written against the exact same call order. Both cannot pass against
    one implementation: `_offer` only fills the slot while a caller is
    already registered as waiting (see its docstring), so an `_offer`
    that precedes `grab` is dropped by design — that is the whole "no
    stale frames" point of this task.

    Fixed here to exercise what the name actually promises: a caller
    already blocked in `grab()` sees the frame the watcher hands off
    next, from a real second thread — not a call made in-line by the
    test after the fact.
    """
    fleet = _fleet()
    frame = np.zeros((4, 4, 3), dtype="uint8")
    results: list = []

    def waiter():
        results.append(fleet.grab("entrada", timeout=2.0))

    thread = threading.Thread(target=waiter)
    thread.start()
    try:
        assert _wait(lambda: "entrada" in fleet._wanted)
        fleet._offer("entrada", frame)
        thread.join(timeout=2.0)
    finally:
        if thread.is_alive():
            thread.join(timeout=0.1)

    assert len(results) == 1
    got = results[0]
    assert got is not None
    assert got.shape == (4, 4, 3)


def test_grab_times_out_rather_than_hanging():
    fleet = _fleet()
    assert fleet.grab("entrada", timeout=0.05) is None


def test_grab_on_an_unknown_camera_is_none_not_an_error():
    fleet = _fleet()
    assert fleet.grab("nonesuch", timeout=0.05) is None


def test_the_watcher_pays_nothing_when_nobody_is_waiting():
    # `_offer` must not copy or store a frame unless somebody asked. Not
    # `.get(...) is None`: that also passes if the key exists holding
    # `None`, which is exactly the shape of the bug this guards against
    # (`_offer` pinning a frame for a caller that already left) — the
    # key must be absent entirely.
    fleet = _fleet()
    fleet._offer("entrada", np.zeros((4, 4, 3), dtype="uint8"))
    assert "entrada" not in fleet._pending


def test_grab_never_returns_a_frame_the_watcher_already_analysed():
    # The slot is filled only AFTER a request arrives, so a frame offered
    # before the request can never satisfy it. This is the "no stale
    # frames" constraint, as a test.
    fleet = _fleet()
    stale = np.zeros((4, 4, 3), dtype="uint8")
    fleet._offer("entrada", stale)  # nobody waiting: dropped
    assert fleet.grab("entrada", timeout=0.05) is None


def test_a_second_caller_does_not_lose_the_first_ones_frame_to_a_race():
    """Two grab() calls overlap on the SAME camera. The second one
    overwrites the shared `_wanted`/`_pending` slot with its own Event,
    so the first is left registered under an Event nobody will ever set
    and simply times out — that is an accepted "only the latest caller
    is served" limitation, not a bug.

    The bug this pins: the first caller's `grab()` returning (via its
    own short timeout) must not run cleanup that deletes the SECOND
    caller's still-live registration, or a frame already delivered to
    it. Without the identity check in `grab()`'s `finally`, the first
    caller's unconditional `pop()` does exactly that, and the second
    caller loses a frame it was correctly handed.
    """
    fleet = _fleet()
    frame = np.full((3, 3, 3), 7, dtype="uint8")
    results: dict[str, np.ndarray | None] = {}

    def first():
        results["first"] = fleet.grab("entrada", timeout=1.0)

    def second():
        results["second"] = fleet.grab("entrada", timeout=2.0)

    t1 = threading.Thread(target=first)
    t1.start()
    assert _wait(lambda: "entrada" in fleet._wanted)
    e1 = fleet._wanted["entrada"]

    t2 = threading.Thread(target=second)
    t2.start()
    # A barrier, not a guess: wait until `second` has actually overwritten
    # the slot, rather than hoping it does so before `first`'s timeout.
    # A fixed head start (as this test originally gave `t2`) proved
    # nothing on a loaded box — 0/1 s of scheduling slack either side of
    # a race is not a race any more, and the test stayed green while
    # guarding nothing. The barrier itself must not have the same flaw:
    # its own timeout (0.5 s) is well under `first`'s (1.0 s), and the
    # `is_alive()` check below proves the barrier was satisfied WHILE
    # `first` was still waiting, not after it had already timed out on
    # its own and this assertion passed on an empty coincidence.
    assert _wait(lambda: fleet._wanted.get("entrada") is not e1, timeout=0.5)
    assert t1.is_alive(), "the barrier fired after `first` had already timed out"

    # `first` now times out (its own Event, `e1`, will never be set) and
    # runs its cleanup — the exact moment the bug lived in.
    t1.join(timeout=2.0)
    assert results.get("first") is None

    fleet._offer("entrada", frame)
    t2.join(timeout=2.0)

    assert results.get("second") is not None
    assert (results["second"] == frame).all()
    # And the hand-off leaves no trace for either caller.
    assert "entrada" not in fleet._wanted
    assert "entrada" not in fleet._pending


# ── deterministic reproductions of the two lock-gap races ──────────────
#
# Both races live in a window a few bytecode instructions wide: between
# an unlocked read of `_wanted` and a locked store/read a few lines
# later. Round 2 of review argued that window couldn't be pinned without
# a test-only hook in production code — that was checked and disproven:
# `_grab_lock` is already a plain instance attribute used only as a
# context manager, so a drop-in replacement that runs a callback right
# before it actually acquires the real lock reproduces the interleaving
# exactly, with zero changes to `cameras.py` and no timing luck involved.


class GatedLock:
    """A stand-in for `threading.Lock` that runs `hook(n)` immediately
    BEFORE the Nth acquisition actually locks.

    `_offer` and `grab` each acquire `_grab_lock` a fixed, known number
    of times per call (`_offer`: once, at the store; `grab`: registration,
    the post-wait read, `finally` — in that order). Swapping this in for
    a fleet's `_grab_lock` and matching `n` to the acquisition of
    interest lets a test simulate exactly what another thread would have
    done in that gap, deterministically — the interleaving a real race
    would only sometimes hit.
    """

    def __init__(self, hook):
        self._lock = threading.Lock()
        self._hook = hook
        self.acquisitions = 0

    def __enter__(self):
        self.acquisitions += 1
        self._hook(self.acquisitions)
        self._lock.acquire()
        return self

    def __exit__(self, *exc_info):
        self._lock.release()
        return False


def test_offer_does_not_pin_a_frame_for_a_caller_that_has_already_gone():
    """Pins the first lock-gap race: `_offer` reads `_wanted` OUTSIDE the
    lock, so a waiter that times out and finishes its own `grab()`
    cleanup in the gap before `_offer` takes the lock would, without the
    identity re-check, still get its frame stored — pinning a decoded
    frame (~6 MB at 1080p) in `_pending` for a caller that is no longer
    there, forever: nothing else ever clears a stray entry.

    `_offer` acquires `_grab_lock` exactly once, at the store, so gating
    that single acquisition and simulating the departed caller's cleanup
    inside the hook reproduces the exact window the bug lived in.
    """
    fleet = _fleet()
    event = threading.Event()
    fleet._wanted["entrada"] = event
    fleet._pending["entrada"] = None

    def hook(n):
        # The caller times out and completes its own `grab()` cleanup
        # right here, in the gap between `_offer`'s unlocked read of
        # `_wanted` (which found `event`) and this, its one lock.
        fleet._wanted.pop("entrada", None)
        fleet._pending.pop("entrada", None)

    fleet._grab_lock = GatedLock(hook)

    fleet._offer("entrada", np.zeros((1080, 1920, 3), dtype="uint8"))

    assert "entrada" not in fleet._pending, (
        "a frame was pinned in _pending for a caller that had already gone"
    )
    assert not event.is_set(), "a departed caller's Event was set anyway"


def test_a_preempted_waiter_gets_none_not_the_next_callers_frame():
    """Pins the second lock-gap race: a caller can wake — its own Event
    was set by `_offer` — and then be pre-empted by a LATER `grab()` for
    the same camera before it reaches its own post-wait read of
    `_pending`. Without the identity re-check there, it would read
    whatever the later caller's frame turned out to be — the same
    `ndarray` object, aliased between two callers — instead of the
    honest `None` a pre-empted caller is owed everywhere else in this
    design. The later caller's own registration and frame must also
    survive the pre-empted caller's `finally`.

    `grab()`'s three lock acquisitions are, in order: registration, the
    post-wait read, `finally`. Gating the SECOND and registering +
    serving a later caller inside that hook reproduces the exact window
    the bug lived in.
    """
    fleet = _fleet()
    mine = np.full((2, 2, 3), 1, dtype="uint8")
    theirs = np.full((2, 2, 3), 9, dtype="uint8")
    later_event = threading.Event()

    def hook(n):
        if n == 2:
            # A later grab() for this camera has registered and been
            # served, in the window after our own wait() already
            # returned but before we re-take the lock to read our frame.
            fleet._wanted["entrada"] = later_event
            fleet._pending["entrada"] = theirs

    fleet._grab_lock = GatedLock(hook)
    results: dict[str, np.ndarray | None] = {}

    def waiter():
        results["got"] = fleet.grab("entrada", timeout=2.0)

    thread = threading.Thread(target=waiter)
    thread.start()
    try:
        assert _wait(lambda: "entrada" in fleet._wanted)
        # Deliver OUR frame directly — standing in for the `_offer` that
        # would normally set this Event, so `event.wait()` returns True
        # and the waiter proceeds to its post-wait read, where `hook`
        # above is waiting to spring the pre-emption.
        our_event = fleet._wanted["entrada"]
        fleet._pending["entrada"] = mine
        our_event.set()
        thread.join(timeout=2.0)
    finally:
        if thread.is_alive():
            thread.join(timeout=0.1)

    assert not thread.is_alive(), "grab() deadlocked on the pre-empted path"
    got = results.get("got")
    assert got is not theirs, "a pre-empted caller got the LATER caller's array"
    assert got is None
    # And the later caller's own state must have survived our finally.
    assert fleet._wanted.get("entrada") is later_event
    assert fleet._pending.get("entrada") is theirs


# ── the tap: set_tap/clear_tap actually reach the watcher ──────────────
#
# `FakeStream.frames()` now RECORDS the `tap` it was handed (`self.tap`)
# instead of discarding it, precisely so a wiring bug — `_watch` reading
# `camera.url` instead of `camera.name`, or the `.get()` dropped so every
# camera shares one tap — fails a test instead of passing every one of
# them silently.
#
# `_watch` now hands `frames()` a live INDIRECTION (`_live_tap`) rather
# than a value read once from `self._taps` — so `streams[-1].tap` is
# never `None` and never the raw callable passed to `set_tap` any more;
# it is always that indirection. Checking identity against it (`is
# my_tap`, `is None`) stopped meaning anything the moment the fix
# landed, so these tests now CALL what they capture and look at where
# the packet arrived, exactly like `test_live.py`'s own tests treat a
# tap as something invocable rather than something to compare.
#
# The three tests below still use the plain, finite `FakeStream`, which
# means `_watch` keeps reconnecting throughout them — enough to prove
# the wiring is correct (right camera, right tap, cleared means
# cleared), but NOT enough to rule out a fix that only refreshes the
# tap on reconnect, which is exactly the bug this file used to hide
# (see the finding that follows). `ForeverStream`, below, is what rules
# that out.


def test_set_tap_reaches_the_watcher():
    """`fleet.set_tap` must be visible to the stream `_watch` opens: the
    watcher has to read `self._taps` live, not a copy taken at start()."""
    streams: list[FakeStream] = []

    def open_stream(url):
        stream = FakeStream([[PERSON]])
        streams.append(stream)
        return stream

    fleet = _fleet(open_stream=open_stream)
    fleet.start([Camera("entrada", "rtsp://x/1")], lambda name, seen: None)
    try:
        assert _wait(lambda: bool(streams))

        received: list[tuple[bytes, bool]] = []
        fleet.set_tap("entrada", lambda data, key: received.append((data, key)))

        assert _wait(lambda: bool(streams) and streams[-1].tap is not None)
        streams[-1].tap(b"packet", True)
        assert received == [(b"packet", True)]
    finally:
        fleet.stop()


def test_set_tap_is_keyed_by_camera_name_not_shared():
    """Setting the tap on one camera must not leak into another's stream —
    keying on the URL, or on nothing at all, would make every camera
    share one tap."""
    streams: dict[str, list[FakeStream]] = {"fuera": [], "entrada": []}
    urls = {"rtsp://x/1": "fuera", "rtsp://x/2": "entrada"}

    def open_stream(url):
        stream = FakeStream([[PERSON]])
        streams[urls[url]].append(stream)
        return stream

    fleet = _fleet(open_stream=open_stream)
    fleet.start(
        [Camera("fuera", "rtsp://x/1"), Camera("entrada", "rtsp://x/2")],
        lambda name, seen: None,
    )
    try:
        assert _wait(lambda: streams["fuera"] and streams["entrada"])

        received: list[tuple[bytes, bool]] = []
        fleet.set_tap("entrada", lambda data, key: received.append((data, key)))
        assert _wait(lambda: streams["entrada"][-1].tap is not None)
        streams["entrada"][-1].tap(b"packet", True)
        assert received == [(b"packet", True)]

        # "fuera" was never given a tap: its indirection must resolve to
        # nothing, no matter how many times it reopens meanwhile.
        assert _wait(lambda: streams["fuera"][-1].tap is not None)
        streams["fuera"][-1].tap(b"packet", True)
        assert received == [(b"packet", True)]  # unchanged
    finally:
        fleet.stop()


def test_clear_tap_stops_it():
    """After `clear_tap`, the indirection resolves to nothing — the next
    stream the watcher opens gets no tap either, so a leftover tap never
    keeps feeding a live view that asked to close."""
    streams: list[FakeStream] = []

    def open_stream(url):
        stream = FakeStream([[PERSON]])
        streams.append(stream)
        return stream

    fleet = _fleet(open_stream=open_stream)
    fleet.start([Camera("entrada", "rtsp://x/1")], lambda name, seen: None)
    try:
        received: list[tuple[bytes, bool]] = []
        fleet.set_tap("entrada", lambda data, key: received.append((data, key)))
        assert _wait(lambda: bool(streams) and streams[-1].tap is not None)
        streams[-1].tap(b"one", True)
        assert received == [(b"one", True)]

        fleet.clear_tap("entrada")
        assert "entrada" not in fleet._taps

        assert _wait(lambda: bool(streams) and streams[-1].tap is not None)
        streams[-1].tap(b"two", False)
        assert received == [(b"one", True)]  # nothing new arrived
    finally:
        fleet.stop()


# ── the tap, on a stream that never reconnects ──────────────────────────
#
# The three tests above use the finite `FakeStream`, so `_watch` keeps
# reopening the stream throughout them — which means a fix that only
# refreshed the captured tap ON RECONNECT would still pass every one of
# them. That is exactly how the ORIGINAL bug hid: `_watch` read
# `self._taps.get(camera.name)` once per `stream.frames()` call, which
# in this house happens once every several hours, not once per packet —
# `set_tap`/`clear_tap` on the stream already running did nothing at
# all until the next reconnect. `ForeverStream` keeps ONE connection
# running for the life of the test, so these two prove the tap is read
# live WITHIN a connection, not merely refreshed BETWEEN them.


def test_set_tap_reaches_an_already_running_stream():
    """`set_tap`, called after the stream is already open and iterating,
    must reach it without a reconnect."""
    streams: list[ForeverStream] = []

    def open_stream(url):
        stream = ForeverStream([[PERSON]], fleet._stopping)
        streams.append(stream)
        return stream

    fleet = _fleet(open_stream=open_stream)
    fleet.start([Camera("entrada", "rtsp://x/1")], lambda name, seen: None)
    try:
        assert _wait(lambda: bool(streams) and streams[-1].tap is not None)
        wrapper = streams[-1].tap  # captured BEFORE set_tap is ever called

        received: list[tuple[bytes, bool]] = []
        fleet.set_tap("entrada", lambda data, key: received.append((data, key)))
        wrapper(b"packet", True)

        assert received == [(b"packet", True)]
        # And it never had to reconnect to pick that up.
        assert len(streams) == 1
    finally:
        fleet.stop()


def test_clear_tap_stops_an_already_running_stream():
    """`clear_tap`, likewise, must silence a stream already running — a
    leftover tap on a connection that never reconnects would otherwise
    keep feeding a view that asked to close for as long as the camera
    stays up, which can be hours."""
    streams: list[ForeverStream] = []

    def open_stream(url):
        stream = ForeverStream([[PERSON]], fleet._stopping)
        streams.append(stream)
        return stream

    fleet = _fleet(open_stream=open_stream)
    fleet.start([Camera("entrada", "rtsp://x/1")], lambda name, seen: None)
    try:
        assert _wait(lambda: bool(streams) and streams[-1].tap is not None)
        wrapper = streams[-1].tap

        received: list[tuple[bytes, bool]] = []
        fleet.set_tap("entrada", lambda data, key: received.append((data, key)))
        wrapper(b"one", True)
        assert received == [(b"one", True)]

        fleet.clear_tap("entrada")
        wrapper(b"two", False)

        assert received == [(b"one", True)]  # nothing new arrived
        assert len(streams) == 1
    finally:
        fleet.stop()
