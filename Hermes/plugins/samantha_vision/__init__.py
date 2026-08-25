"""samantha-vision — the house cameras, and what is worth saying."""

import threading

from loguru import logger

from .alert import make_handler
from .cameras import CameraFleet, parse_cameras, redact
from .live import LiveSession
from .live_tool import (
    CLOSE_DESCRIPTION,
    CLOSE_NAME,
    CLOSE_SCHEMA,
    OPEN_DESCRIPTION,
    OPEN_NAME,
    OPEN_SCHEMA,
)
from .live_tool import EMOJI as LIVE_EMOJI
from .live_tool import make_close_handler, make_open_handler
from .tool import (
    DESCRIPTION,
    EMOJI,
    NAME,
    SCHEMA,
    TOOLSET,
)
from .tool import make_handler as make_mirar

# There was a `check_requirements()` here until 2026-08-24. It was dead
# code: nothing in `hermes_cli/plugins.py` looks for it. It is a `kind:
# platform` convention — a plugin passes it as `check_fn=` to
# `register_platform(...)`, the way `samantha_kiosk` does — and this
# plugin is `kind: standalone`, so it had the shape and none of the
# wiring. Worse, the README cited it as the thing that refuses to load
# the plugin without `av` and `onnxruntime`, which it never did.
#
# What actually happens on a box without them is better: the plugin
# loads, the supervisor thread runs, and building the detector fails with
# one line — `no detector, no cameras watched — No module named
# 'onnxruntime'` (`cameras.py`). That is a named failure mode with a
# symptom, which is what the manifest asks for.

# The platform the photo is allowed to reach, and the only one. Not a
# config key on purpose: `MEDIA:` was rejected precisely because it let
# any adapter render an image, and a configurable destination would put
# that decision back (spec §3).
KIOSK_PLATFORM = "samantha_kiosk"


def register(ctx):
    """Declare the plugin, and start the one thread that does the rest.

    Registration stays pure (spec §3) in the sense that matters: nothing
    here opens a camera, reads the network or loads the model. All of
    that happens inside the supervisor thread, because `register()` is
    the whole of a plugin's lifecycle on the way in — Task 1 proved
    there is no later hook — and a registration that blocks or raises is
    reported by Hermes as a retry-forever loop at DEBUG level.

    Registering a tool is declaring one, so it belongs here. `names` is
    the seam that keeps it that way: an empty list handed to both the
    handler and `check_fn`, filled by `_supervise` once the config has
    been read. Until then `check_fn` is False and the model is not
    offered a tool that cannot work — which is also the honest answer
    while the config is still being read.

    The alert itself lives in `alert.py` and is wired in here, so
    `cameras.py` never learns that a gateway exists.
    """
    fleet = CameraFleet()
    ctx.on_unload(fleet.stop)

    names: list[str] = []
    ctx.register_tool(
        name=NAME,
        toolset=TOOLSET,
        description=DESCRIPTION,
        emoji=EMOJI,
        schema=SCHEMA,
        handler=make_mirar(fleet, names, push_photo),
        check_fn=lambda: bool(names),
        # Ruling 1. `grab` blocks for up to two seconds and `push_photo`
        # is a coroutine; Hermes bridges an async handler itself.
        is_async=True,
    )

    session = LiveSession(fleet, push_live_open, push_live_frame, push_live_close)

    ctx.register_tool(
        name=OPEN_NAME,
        toolset=TOOLSET,
        description=OPEN_DESCRIPTION,
        emoji=LIVE_EMOJI,
        schema=OPEN_SCHEMA,
        handler=make_open_handler(session, fleet, names),
        check_fn=lambda: bool(names),
        is_async=True,
    )
    ctx.register_tool(
        name=CLOSE_NAME,
        toolset=TOOLSET,
        description=CLOSE_DESCRIPTION,
        emoji=LIVE_EMOJI,
        schema=CLOSE_SCHEMA,
        handler=make_close_handler(session),
        check_fn=lambda: bool(names),
        is_async=True,
    )

    threading.Thread(
        target=_supervise,
        args=(ctx, fleet, names),
        name="samantha-vision",
        daemon=True,
    ).start()
    logger.info("samantha-vision: registered")


def _supervise(ctx, fleet: CameraFleet, names: list[str] | None = None) -> None:
    """Read the config, and give the fleet its cameras. Never raises.

    This runs off the registration path on purpose. It is also the only
    place allowed to fail: an exception here costs the house its eyes,
    and an exception on the registration path would cost it the gateway.
    """
    try:
        cameras = parse_cameras({"cameras": ctx.get_config("cameras", [])})
        if names is not None:
            # In place: `register()` handed this same list to the tool.
            names[:] = [camera.name for camera in cameras]
        fleet.start(cameras, make_handler(ctx))
    except Exception as exc:
        logger.error(f"samantha-vision: cameras not started — {redact(exc)}")


async def push_photo(path: str, camera: str) -> bool:
    """Show a photo on the strip, and nowhere else. Never raises.

    The kiosk adapter validates the path against the snapshot directory
    before it puts it on the wire, so this is not the trust boundary —
    it is the wiring, and it lives here rather than in `tool.py` for the
    same reason `alert.py` holds the gateway call: the tool must run in
    a test with no gateway in the room.

    Everything is resolved at call time. `register()` runs before the
    gateway has adapters, and a reference captured then would be None
    for the life of the process.
    """
    try:
        from gateway.config import Platform
        from gateway.run import _gateway_runner_ref

        runner = _gateway_runner_ref()
        if runner is None:
            logger.debug("samantha-vision: no gateway, photo dropped")
            return False
        adapter = getattr(runner, "adapters", {}).get(Platform(KIOSK_PLATFORM))
        if adapter is None:
            logger.debug("samantha-vision: no strip platform, photo dropped")
            return False
        return bool(await adapter.push_photo(path, camera))
    except Exception as exc:
        # A photo is never worth a turn. He has already said his sentence
        # by the time this runs, or is about to.
        logger.warning(f"samantha-vision: photo not shown — {redact(exc)}")
        return False


async def _adapter():
    """The strip's adapter, or None. Resolved at call time, every time."""
    from gateway.config import Platform
    from gateway.run import _gateway_runner_ref

    runner = _gateway_runner_ref()
    if runner is None:
        return None
    return getattr(runner, "adapters", {}).get(Platform(KIOSK_PLATFORM))


async def push_live_open(
    camera: str, epoch: int, extradata: bytes, width: int, height: int
) -> bool:
    """Open a live view on the strip, and nowhere else. Never raises."""
    try:
        adapter = await _adapter()
        if adapter is None:
            return False
        return bool(
            await adapter.push_live_open(camera, epoch, extradata, width, height)
        )
    except Exception as exc:
        logger.warning(f"samantha-vision: live not opened — {redact(exc)}")
        return False


async def push_live_frame(epoch: int, packet: bytes) -> bool:
    """One frame. Quiet on failure: this runs up to 25 times a second."""
    try:
        adapter = await _adapter()
        if adapter is None:
            return False
        return bool(await adapter.push_live_frame(epoch, packet))
    except Exception:
        return False


async def push_live_close(epoch: int, reason: str) -> bool:
    """Tell the strip the view ended. Never raises."""
    try:
        adapter = await _adapter()
        if adapter is None:
            return False
        return bool(await adapter.push_live_close(epoch, reason))
    except Exception as exc:
        logger.warning(f"samantha-vision: live not closed — {redact(exc)}")
        return False
