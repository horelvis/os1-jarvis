"""`mirar`: what he says when he looks, and what he never says.

Two rules are load-bearing here and both are tested rather than trusted:
the answer is a sentence with no filesystem path in it — CosyVoice reads
whatever comes back out loud — and it carries no `MEDIA:` line, because
an answer travels wherever the turn travels and a picture inside it
would leave the box on any turn routed elsewhere (spec §3).

The handler is `async` (Ruling 1): `push_photo` is a coroutine and
`grab` blocks for up to two seconds. The tests drive it with
`asyncio.run`, which is the convention `samantha_kiosk`'s own async
tests already use in this repo — no pytest-asyncio, no ini file to
configure anywhere in `Hermes/`.
"""

import asyncio
import time

import numpy as np
import pytest

from Hermes.plugins.samantha_vision import snapshot
from Hermes.plugins.samantha_vision.tool import make_handler
from Hermes.plugins.samantha_vision.vision import Detection


class _Fleet:
    """A fleet that answers grab() with a canned frame, or with None.

    `detector` is the attribute the real `CameraFleet` fills in when it
    starts, and the handler reads it through `getattr` — a fleet without
    one sees nothing, which is the honest reading of "no detector".
    """

    def __init__(self, frame: np.ndarray | None, detector=None, delay: float = 0.0):
        self._frame = frame
        self._delay = delay
        self.detector = detector
        self.grabbed: list[str] = []

    def grab(self, camera: str, timeout: float = 2.0):
        self.grabbed.append(camera)
        if self._delay:
            time.sleep(self._delay)
        return self._frame


class _Spy:
    """Stands in for KioskAdapter.push_photo. Records, never fails."""

    def __init__(self, result: bool = True) -> None:
        self.calls: list[tuple[str, str]] = []
        self._result = result

    async def __call__(self, path: str, camera: str) -> bool:
        self.calls.append((path, camera))
        return self._result


class _ExplodingPush:
    """A push that raises. It must cost the photo, never the sentence."""

    async def __call__(self, path: str, camera: str) -> bool:
        raise RuntimeError("the strip went away mid-send")


class _Detector:
    def __init__(self, detections):
        self._detections = detections

    def detect(self, frame):
        return list(self._detections)


class _ExplodingDetector:
    def detect(self, frame):
        raise RuntimeError("onnxruntime fell over")


def _raise_oserror(*_a, **_kw):
    raise OSError("disk full")


def _frame() -> np.ndarray:
    return np.zeros((360, 640, 3), dtype="uint8")


@pytest.fixture(autouse=True)
def spool(tmp_path, monkeypatch):
    """Snapshots go to a temporary directory, never to the real house."""
    monkeypatch.setattr(snapshot, "_ROOT", tmp_path)
    return tmp_path


@pytest.fixture
def fake_fleet():
    return _Fleet(_frame())


@pytest.fixture
def empty_fleet():
    # A frame with nothing YOLO recognises in it.
    return _Fleet(_frame(), detector=_Detector([]))


def SilentFleet():
    """A camera that never answers within the timeout."""
    return _Fleet(None)


@pytest.fixture
def spy_push():
    return _Spy()


@pytest.fixture
def failing_push():
    return _Spy(result=False)


def test_the_answer_is_a_sentence_with_no_path_in_it(fake_fleet, spy_push):
    handler = make_handler(fake_fleet, ["entrada"], spy_push)
    answer = asyncio.run(handler({"camara": "entrada"}))
    assert "/" not in answer  # a path read aloud is the failure
    assert "MEDIA:" not in answer  # spec §3: never, on any platform
    assert "entrada" in answer


def test_building_the_handler_looks_at_nothing(fake_fleet, spy_push):
    """Declaring a tool is not using one: `register()` builds this at
    load time, before the gateway exists."""
    make_handler(fake_fleet, ["entrada"], spy_push)
    assert fake_fleet.grabbed == []
    assert spy_push.calls == []


def test_the_handler_reads_the_camera_list_as_it_changes(fake_fleet, spy_push):
    """`register()` hands over an empty list and the supervisor thread
    fills it in a moment later, off the registration path."""
    names: list[str] = []
    handler = make_handler(fake_fleet, names, spy_push)
    assert "cámara" in asyncio.run(handler({"camara": "entrada"})).lower()
    names.append("entrada")
    assert "En entrada" in asyncio.run(handler({"camara": "entrada"}))


def test_the_photo_is_pushed_to_the_strip(fake_fleet, spy_push):
    handler = make_handler(fake_fleet, ["entrada"], spy_push)
    asyncio.run(handler({"camara": "entrada"}))
    assert len(spy_push.calls) == 1
    assert spy_push.calls[0][1] == "entrada"


def test_what_is_pushed_is_the_jpeg_that_was_just_written(fake_fleet, spy_push, spool):
    """The side effect is a real file in the spool, and only there."""
    handler = make_handler(fake_fleet, ["entrada"], spy_push, now=lambda: 1000.0)
    asyncio.run(handler({"camara": "entrada"}))
    (path, _camera) = spy_push.calls[0]
    assert path.startswith(str(spool))
    assert path.endswith(".jpg")


def test_a_camera_that_does_not_answer_says_so_and_pushes_nothing(spy_push):
    handler = make_handler(SilentFleet(), ["entrada"], spy_push)
    answer = asyncio.run(handler({"camara": "entrada"}))
    assert "no responde" in answer.lower()
    assert spy_push.calls == []


def test_an_unknown_camera_names_the_ones_that_exist(fake_fleet, spy_push):
    handler = make_handler(fake_fleet, ["entrada", "fuera"], spy_push)
    answer = asyncio.run(handler({"camara": "garaje"}))
    assert "entrada" in answer and "fuera" in answer


def test_an_unknown_camera_never_reaches_grab(fake_fleet, spy_push):
    """`grab` on a name nobody watches blocks the caller for the whole
    timeout before returning None (cameras.py). A typo must cost him
    nothing, so the name is checked first."""
    handler = make_handler(fake_fleet, ["entrada"], spy_push)
    asyncio.run(handler({"camara": "garaje"}))
    assert fake_fleet.grabbed == []


def test_an_unknown_camera_is_not_read_back_out_loud(fake_fleet, spy_push):
    """The argument is model-supplied text and the answer is spoken."""
    handler = make_handler(fake_fleet, ["entrada"], spy_push)
    answer = asyncio.run(handler({"camara": "/etc/passwd"}))
    assert "/etc/passwd" not in answer
    assert "/" not in answer


def test_omitting_the_camera_looks_at_all_of_them(fake_fleet, spy_push):
    handler = make_handler(fake_fleet, ["entrada", "fuera"], spy_push)
    asyncio.run(handler({}))
    assert len(spy_push.calls) == 2


def test_omitting_the_camera_answers_about_every_one_of_them(fake_fleet, spy_push):
    handler = make_handler(fake_fleet, ["entrada", "fuera"], spy_push)
    answer = asyncio.run(handler({}))
    assert "entrada" in answer and "fuera" in answer


def test_a_failed_push_still_answers(fake_fleet, failing_push):
    # The strip may not be running. The words are not conditional on it.
    handler = make_handler(fake_fleet, ["entrada"], failing_push)
    assert asyncio.run(handler({"camara": "entrada"}))


def test_a_push_that_raises_still_answers(fake_fleet):
    # push_photo promises never to raise; the handler does not rely on it.
    handler = make_handler(fake_fleet, ["entrada"], _ExplodingPush())
    answer = asyncio.run(handler({"camara": "entrada"}))
    assert "entrada" in answer


def test_a_failed_write_still_answers(fake_fleet, spy_push, monkeypatch):
    monkeypatch.setattr(
        "Hermes.plugins.samantha_vision.tool.write_jpeg",
        _raise_oserror,
    )
    handler = make_handler(fake_fleet, ["entrada"], spy_push)
    answer = asyncio.run(handler({"camara": "entrada"}))
    assert "entrada" in answer
    assert spy_push.calls == []


def test_nothing_seen_is_an_answer_not_an_error(empty_fleet, spy_push):
    # `describe([])` is what produces the 'no hay nadie' branch.
    handler = make_handler(empty_fleet, ["entrada"], spy_push)
    assert "no hay nadie" in asyncio.run(handler({"camara": "entrada"})).lower()


def test_what_he_sees_is_what_he_says(spy_push):
    seen = [
        Detection(label="persona", confidence=0.9, x=0.5, y=0.5),
        Detection(label="perro", confidence=0.8, x=0.2, y=0.6),
    ]
    fleet = _Fleet(_frame(), detector=_Detector(seen))
    handler = make_handler(fleet, ["entrada"], spy_push)
    answer = asyncio.run(handler({"camara": "entrada"}))
    # `describe` yields bare labels — "alguien y perro", no article.
    # It is the phrase the alert path already speaks; unchanged here.
    assert answer == "En entrada hay alguien y perro."


def test_a_detector_that_raises_still_answers(spy_push):
    fleet = _Fleet(_frame(), detector=_ExplodingDetector())
    handler = make_handler(fleet, ["entrada"], spy_push)
    answer = asyncio.run(handler({"camara": "entrada"}))
    assert "entrada" in answer


def test_grab_does_not_block_the_event_loop():
    """`grab` waits up to two seconds. Two seconds of a stalled gateway
    loop is every other turn in the house stalled with it, so it runs in
    a thread — and this is what proves it did."""
    fleet = _Fleet(_frame(), delay=0.3)
    handler = make_handler(fleet, ["entrada"], _Spy())
    ticks = 0

    async def go():
        nonlocal ticks

        async def tick():
            nonlocal ticks
            while True:
                await asyncio.sleep(0.01)
                ticks += 1

        ticker = asyncio.create_task(tick())
        try:
            await handler({"camara": "entrada"})
        finally:
            ticker.cancel()

    asyncio.run(go())
    # ~30 ticks if the loop kept running; exactly 0 if grab blocked it.
    assert ticks > 5, ticks
