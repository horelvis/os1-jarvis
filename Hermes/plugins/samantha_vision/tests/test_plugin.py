"""register() and _supervise(): the two functions Hermes actually calls.

`register()` is the whole of a plugin's lifecycle on the way in, and a
registration that blocks or raises is reported by Hermes as a
retry-forever loop at DEBUG level — i.e. invisibly. Both properties that
protect against that are tested here.
"""

import threading
import time

from loguru import logger

from Hermes.plugins.samantha_vision import _supervise, register


class FakeCtx:
    """A gateway context with only what `register` and `_supervise` use."""

    def __init__(self, config=None, blocker: threading.Event | None = None):
        self._config = config if config is not None else []
        self._blocker = blocker
        self.unload_hooks: list = []

    def on_unload(self, fn):
        self.unload_hooks.append(fn)

    def get_config(self, key, default=None):
        if self._blocker is not None:
            self._blocker.wait(timeout=5.0)
        return self._config


class FakeFleet:
    def __init__(self):
        self.started: list = []
        self.stopped = False

    def start(self, cameras, on_detections):
        self.started.append(cameras)

    def stop(self, timeout=None):
        self.stopped = True


def test_register_returns_promptly_even_when_reading_config_blocks():
    """The camera work is off the registration path, and this is what
    proves it: a `get_config` that takes seconds must not delay
    `register()` by so much as one of them."""
    blocker = threading.Event()
    ctx = FakeCtx(blocker=blocker)

    started = time.monotonic()
    try:
        register(ctx)
        elapsed = time.monotonic() - started
    finally:
        blocker.set()

    assert elapsed < 0.5, elapsed
    # And the fleet is handed to Hermes to stop, not left running.
    assert ctx.unload_hooks, "register() must register an unload hook"


def test_register_touches_no_camera_when_nothing_is_configured():
    ctx = FakeCtx(config=[])
    register(ctx)
    # The supervisor thread is a daemon and finishes on its own; nothing
    # it does may leave a camera thread behind.
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if not [t for t in threading.enumerate() if t.name.startswith("camera-")]:
            break
        time.sleep(0.01)
    assert not [t for t in threading.enumerate() if t.name.startswith("camera-")]


def test_supervise_swallows_a_config_read_that_raises():
    """An exception here costs the house its eyes; one on the
    registration path would cost it the gateway."""

    class Exploding:
        def get_config(self, key, default=None):
            raise RuntimeError("state.db is locked")

    records: list = []
    sink = logger.add(lambda m: records.append(m.record), level="DEBUG")
    try:
        fleet = FakeFleet()
        _supervise(Exploding(), fleet)  # must not raise
    finally:
        logger.remove(sink)

    assert not fleet.started
    assert any(
        r["level"].name == "ERROR" and "cameras not started" in r["message"]
        for r in records
    ), [r["message"] for r in records]


def test_supervise_does_not_leak_the_password_of_a_raising_config():
    class Exploding:
        def get_config(self, key, default=None):
            raise RuntimeError("bad url rtsp://admin:hunter2@10.0.0.1/sub")

    records: list = []
    sink = logger.add(lambda m: records.append(m.record), level="DEBUG")
    try:
        _supervise(Exploding(), FakeFleet())
    finally:
        logger.remove(sink)

    joined = " ".join(r["message"] for r in records)
    assert "hunter2" not in joined, joined
