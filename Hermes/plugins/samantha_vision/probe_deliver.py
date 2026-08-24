"""The smallest code that proves a plugin can start a turn on its own.

Throwaway (task 1). What it demonstrates is written up in PROBE.md.
"""

import logging
import threading

logger = logging.getLogger(__name__)

# The kiosk session key is deterministic: build_session_key() joins
# namespace / platform / chat_type / chat_id, and the kiosk adapter always
# opens its source with chat_id="kiosk", chat_type="dm".
KIOSK_SESSION_KEY = "agent:main:samantha_kiosk:dm:kiosk"

PROBE_TEXT = "probe: di algo corto"

# Long enough for the gateway to reach _install_plugin_message_injector(),
# which runs after every platform adapter has connected — plugin
# registration happens well before that.
DELAY_SECONDS = 5.0


def schedule_probe(ctx) -> None:
    """Fire one injected turn, once, DELAY_SECONDS from now."""
    timer = threading.Timer(DELAY_SECONDS, _fire, args=(ctx,))
    timer.daemon = True
    timer.start()


def _fire(ctx) -> None:
    accepted = ctx.inject_message(
        PROBE_TEXT,
        role="user",
        session_key=KIOSK_SESSION_KEY,
    )
    # warning, not info: the gateway's default level must not hide the
    # one line this whole plugin exists to print.
    logger.warning("samantha-vision probe: inject_message -> %s", accepted)
