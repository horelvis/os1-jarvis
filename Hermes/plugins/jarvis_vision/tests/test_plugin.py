"""register() and _supervise(): the two functions Hermes actually calls.

`register()` is the whole of a plugin's lifecycle on the way in, and a
registration that blocks or raises is reported by Hermes as a
retry-forever loop at DEBUG level — i.e. invisibly. Both properties that
protect against that are tested here.

It also DECLARES the `mirar` tool, which is not the same as doing
anything: no camera is opened, no model loaded, no socket touched. The
tests below hold that line too.
"""

import threading
import time

from loguru import logger

from Hermes.plugins import jarvis_vision as plugin
from Hermes.plugins.jarvis_vision import _supervise, register


class FakeCtx:
    """A gateway context with only what `register` and `_supervise` use."""

    def __init__(self, config=None, blocker: threading.Event | None = None):
        self._config = config if config is not None else []
        self._blocker = blocker
        self.unload_hooks: list = []
        self.tools: list[dict] = []

    def on_unload(self, fn):
        self.unload_hooks.append(fn)

    def register_tool(self, **kwargs):
        self.tools.append(kwargs)

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


def _tool(ctx):
    return next(t for t in ctx.tools if t["name"] == "mirar")


def _settle(check, want, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and check() is not want:
        time.sleep(0.01)
    return check()


def test_register_declares_mirar_as_an_async_tool():
    """`grab` blocks for two seconds and the photo is pushed with an
    await; a handler registered as sync would be called and never
    awaited, so Hermes has to be told (Ruling 1)."""
    ctx = FakeCtx(config=[])
    register(ctx)
    tool = _tool(ctx)
    assert tool["is_async"] is True
    # A toolset of our own (Ruling 11): Hermes' `vision` already carries
    # `vision_analyze`, and sharing the name would have offered him an
    # image-analysis tool this box cannot serve.
    assert tool["toolset"] == "camaras"
    assert "camara" in tool["schema"]["properties"]
    assert tool["schema"]["required"] == []


def test_the_tool_is_hidden_until_a_camera_is_actually_watched():
    """He is never offered something that cannot work — and until the
    supervisor thread has read the config, nothing can."""
    ctx = FakeCtx(config=[])
    register(ctx)
    check = _tool(ctx)["check_fn"]
    assert check() is False
    assert _settle(check, True) is False, "no cameras configured, so no tool"


def test_the_tool_appears_once_the_cameras_are_known(monkeypatch):
    # A fake fleet, so the config path is exercised without loading YOLO
    # or opening an RTSP session in a unit test.
    monkeypatch.setattr(plugin, "CameraFleet", FakeFleet)
    ctx = FakeCtx(config=[{"name": "entrada", "url": "rtsp://camera/sub"}])
    register(ctx)
    assert _settle(_tool(ctx)["check_fn"], True) is True


def test_supervise_fills_in_the_camera_names_the_tool_reads():
    names: list = []
    ctx = FakeCtx(config=[{"name": "entrada", "url": "rtsp://camera/sub"}])
    _supervise(ctx, FakeFleet(), names)
    assert names == ["entrada"]


def test_register_declares_both_live_tools():
    ctx = FakeCtx(config=[])
    register(ctx)

    names = {call["name"] for call in ctx.tools}
    assert {"mirar", "ver_en_vivo", "dejar_de_ver"} <= names


def test_the_live_tools_are_hidden_until_the_cameras_are_known():
    ctx = FakeCtx(config=[])
    register(ctx)

    for call in ctx.tools:
        if call["name"] in {"ver_en_vivo", "dejar_de_ver"}:
            # Same seam `mirar` uses: an empty `names` list means the
            # config has not been read, and offering a tool that cannot
            # work is worse than not offering it.
            assert call["check_fn"]() is False
