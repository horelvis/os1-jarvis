"""samantha-vision — the house cameras, and what is worth saying."""

from loguru import logger


def check_requirements() -> bool:
    """True when the plugin can run at all. No network, no cameras."""
    try:
        import av  # noqa: F401
        import onnxruntime  # noqa: F401
    except ImportError:
        return False
    return True


def register(ctx):
    """Declare the plugin. Start nothing.

    Registration is pure on purpose (spec §3). Anything here that
    touches the outside world turns a missing dependency into a plugin
    that never loads, and Hermes reports that as a retry-forever loop at
    DEBUG level — the failure the kiosk adapter's static-root check was
    written to avoid, reached from the other direction.

    The camera threads start in Task 3, from the hook Task 1 found.
    """
    logger.info("samantha-vision: registered")
