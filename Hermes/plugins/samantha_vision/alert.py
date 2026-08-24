"""A detection becomes a turn, not a sentence.

CLAUDE.md §1: he never performs using his tools. "Persona detectada en
exterior" is a machine talking. So what the camera produces is a
*prompt*, and what reaches the user is his answer to it — in his voice,
with the conversation still in mind.

This costs one model call per event. It is affordable precisely because
the Watcher makes events rare.

The concrete handler lives here rather than in `cameras.py`: the fleet
takes `on_detections` as a parameter and knows nothing about the
gateway, which is what lets every camera test run with no gateway, no
GPU and no network in the room.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

from loguru import logger

from .vision import Watcher, describe

# Where the strip's conversation lives. Measured in Task 1 against
# `gateway/session.py::build_session_key` and every `samantha_kiosk` row
# in `state.db`: the kiosk adapter always opens its source with
# chat_id="kiosk", chat_type="dm", so the key is a constant. A `/new`
# mints a fresh session_id under the SAME key, so it stays correct.
KIOSK_SESSION_KEY = "agent:main:samantha_kiosk:dm:kiosk"

# `inject_message` returns False, silently, whenever there is nothing to
# deliver into. Two cases, and they want opposite things:
#
#   - the gateway is still starting. The injector is installed only
#     after EVERY platform adapter has connected, which on this box is
#     under a second after registration but is not a guarantee. A short
#     retry clears it.
#   - the strip has never spoken on this box. There is no session row,
#     and there never will be until the user talks, so retrying is
#     pointless.
#
# One bounded schedule covers both: try, wait, try, give up. What is NOT
# done is queueing — a detection with nowhere to go is DROPPED. Queueing
# means he recites a backlog of stale sightings the moment the strip
# connects, which is exactly the machine-talking §1 forbids. The cameras
# re-detect anyway, and the anti-spam window is three minutes.
#
# The wait happens on the camera's own thread, which is the point: a
# camera that cannot be talked about should stop sampling for those
# nine seconds rather than pile detections up behind a gateway that
# is not listening.
RETRY_DELAYS: tuple[float, ...] = (1.0, 3.0, 5.0)

# Dropping the article is deliberate. Camera names are bare nouns —
# `fuera`, `entrada` — so "en la {camera}" yields "en la fuera de casa",
# and a gender error in the prompt is an invitation to echo it. The
# prompt is instruction to the model and is never spoken aloud, so a
# clipped preposition costs nothing and a wrong article could cost a
# sentence.
_TEMPLATE = (
    "Acabas de fijarte en algo en {camera} de casa: {phrase}. "
    "Coméntalo en una frase corta, con tus palabras, como quien levanta "
    "la vista y lo menciona. "
    "No digas nunca la palabra cámara, ni detección, ni detectado, ni "
    "yolo, ni sensor, ni expliques cómo lo sabes."
)


def build_prompt(camera: str, phrase: str) -> str:
    """What he is asked when a camera sees something worth mentioning."""
    return _TEMPLATE.format(camera=camera, phrase=phrase)


def deliver(
    ctx: Any,
    prompt: str,
    *,
    delays: tuple[float, ...] = RETRY_DELAYS,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    """Hand the prompt to the gateway as a user turn. Never raises.

    True means the gateway accepted it for dispatch — not that the turn
    finished, and not that he said anything. There is no way to push a
    finished assistant message through this API at all, which is exactly
    the property that keeps him from reciting.
    """
    for index, delay in enumerate((0.0, *delays)):
        if delay:
            sleep(delay)
        try:
            accepted = ctx.inject_message(
                prompt, role="user", session_key=KIOSK_SESSION_KEY
            )
        except Exception as exc:
            # A gateway that is going down mid-injection must not take a
            # camera thread with it.
            logger.warning(f"samantha-vision: injection raised — {exc}")
            return False
        if accepted:
            if index:
                logger.debug(f"samantha-vision: delivered on attempt {index + 1}")
            return True

    # One line, and then silence. Either the gateway is not listening
    # yet, or nobody has ever spoken to the strip on this box — and in
    # the second case no amount of waiting helps.
    logger.warning(
        "samantha-vision: nobody to tell, sighting dropped "
        "(no live session on the strip?)"
    )
    return False


def make_handler(
    ctx: Any,
    *,
    watcher: Watcher | None = None,
    deliver_prompt: Callable[[str], bool] | None = None,
    now: Callable[[], float] = time.time,
    hour: Callable[[], int] = lambda: datetime.now().hour,
) -> Callable[[str, list], None]:
    """Build the `on_detections` the fleet calls. Never raises.

    One Watcher for the whole house, because it keys its anti-spam on
    (camera, label) and the cameras are threads sharing it — hence the
    lock. `deliver_prompt` is injectable so the wiring can be exercised
    without a gateway.
    """
    watcher = watcher or Watcher()
    send = deliver_prompt or (lambda prompt: deliver(ctx, prompt))
    lock = threading.Lock()

    def on_detections(camera_name: str, detections: list) -> None:
        try:
            with lock:
                worth = watcher.worth_saying(
                    detections, now(), hour(), camera=camera_name
                )
            if not worth:
                return
            phrase = describe(worth)
            if not phrase:
                return
            logger.info(f"samantha-vision: {camera_name}: {phrase}")
            send(build_prompt(camera_name, phrase))
        except Exception as exc:
            # `cameras.py` catches this too. Belt and braces on purpose:
            # this is the one handler that touches the gateway, and the
            # gateway is the brain.
            logger.warning(f"samantha-vision: {camera_name}: alert failed — {exc}")

    return on_detections
