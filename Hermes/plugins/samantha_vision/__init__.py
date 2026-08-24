"""samantha-vision — the house cameras, and what is worth saying."""

import threading

from loguru import logger

from .cameras import CameraFleet, parse_cameras
from .vision import describe


def check_requirements() -> bool:
    """True when the plugin can run at all. No network, no cameras."""
    try:
        import av  # noqa: F401
        import onnxruntime  # noqa: F401
    except ImportError:
        return False
    return True


def register(ctx):
    """Declare the plugin, and start the one thread that does the rest.

    Registration stays pure (spec §3) in the sense that matters: nothing
    here opens a camera, reads the network or loads the model. All of
    that happens inside the supervisor thread, because `register()` is
    the whole of a plugin's lifecycle on the way in — Task 1 proved
    there is no later hook — and a registration that blocks or raises is
    reported by Hermes as a retry-forever loop at DEBUG level.

    The cameras still have no voice: `_only_log` is where Task 5 hangs
    the alert.
    """
    fleet = CameraFleet()
    ctx.on_unload(fleet.stop)

    threading.Thread(
        target=_supervise,
        args=(ctx, fleet),
        name="samantha-vision",
        daemon=True,
    ).start()
    logger.info("samantha-vision: registered")


def _supervise(ctx, fleet: CameraFleet) -> None:
    """Read the config, and give the fleet its cameras. Never raises.

    This runs off the registration path on purpose. It is also the only
    place allowed to fail: an exception here costs the house its eyes,
    and an exception on the registration path would cost it the gateway.
    """
    try:
        cameras = parse_cameras({"cameras": ctx.get_config("cameras", [])})
        fleet.start(cameras, _only_log)
    except Exception as exc:
        logger.error(f"samantha-vision: cameras not started — {exc}")


def _only_log(camera_name: str, detections: list) -> None:
    """What a detection does today: nothing but a line in the journal.

    Task 5 replaces this with the injection that makes him say it. Until
    then the plugin watches and keeps quiet, which is deliberate — the
    alert wants the Watcher of Task 4 in front of it, or a camera says
    "alguien" every three seconds.
    """
    logger.info(f"samantha-vision: {camera_name}: {describe(detections)}")
