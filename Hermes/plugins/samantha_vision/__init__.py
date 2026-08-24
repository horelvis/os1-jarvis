"""samantha-vision — the house cameras, and what is worth saying."""

import threading

from loguru import logger

from .alert import make_handler
from .cameras import CameraFleet, parse_cameras, redact

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


def register(ctx):
    """Declare the plugin, and start the one thread that does the rest.

    Registration stays pure (spec §3) in the sense that matters: nothing
    here opens a camera, reads the network or loads the model. All of
    that happens inside the supervisor thread, because `register()` is
    the whole of a plugin's lifecycle on the way in — Task 1 proved
    there is no later hook — and a registration that blocks or raises is
    reported by Hermes as a retry-forever loop at DEBUG level.

    The alert itself lives in `alert.py` and is wired in here, so
    `cameras.py` never learns that a gateway exists.
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
        fleet.start(cameras, make_handler(ctx))
    except Exception as exc:
        logger.error(f"samantha-vision: cameras not started — {redact(exc)}")
