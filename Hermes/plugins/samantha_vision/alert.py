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

from .cameras import redact
from .vision import Watcher, describe

# Where the strip's conversation lives. Measured in Task 1 against
# `gateway/session.py::build_session_key` and every `samantha_kiosk` row
# in `state.db`: the kiosk adapter always opens its source with
# chat_id="kiosk", chat_type="dm", so the key is a constant. A `/new`
# mints a fresh session_id under the SAME key, so it stays correct.
KIOSK_SESSION_KEY = "agent:main:samantha_kiosk:dm:kiosk"

# What `False` from `inject_message` actually means — corrected
# 2026-08-24, having been stated the other way round in four places.
#
# Read against the pinned source: `inject_message`
# (`hermes_cli/plugins.py:1973`) returns False for exactly three things —
# a missing `session_key`, a denied `allow_gateway_injection`, and
# `has_gateway_message_injector` being false. The last is the one that
# matters here: the injector is installed only after EVERY platform
# adapter has connected, which on this box is under a second after
# registration but is not a guarantee. **False means the gateway is not
# up yet, and retrying helps.**
#
# A MISSING SESSION ROW DOES NOT COME BACK AS FALSE. It is resolved
# inside the coroutine: `_schedule_plugin_message_injection`
# (`gateway/run.py:18649`) returns True at `:18715` as soon as the task
# is scheduled, and `_dispatch_plugin_message_injection` only then finds
# `lookup_by_session_key` is None and returns False at `:18729`. Hermes
# logs that itself, from a done-callback at `:18708`:
#
#   Plugin message injection was not routed: plugin=… session=…
#
# So on a box whose strip has never spoken, `deliver()` returns True on
# the FIRST attempt and the warning below never fires. That line is about
# a gateway that is not listening, and only that.
#
# One bounded schedule: try, wait, try, give up. What is NOT done is
# queueing — a detection with nowhere to go is DROPPED. Queueing means he
# recites a backlog of stale sightings the moment the strip connects,
# which is exactly the machine-talking §1 forbids. The cameras re-detect
# anyway, and the anti-spam window is three minutes.
#
# The wait happens on the camera's own thread, which is the point: a
# camera that cannot be talked about should stop sampling for those
# nine seconds rather than pile detections up behind a gateway that
# is not listening.
RETRY_DELAYS: tuple[float, ...] = (1.0, 3.0, 5.0)

# The camera name is a LABELLED VALUE, not part of a sentence, and that
# shape is load-bearing (Ruling 14, measured 2026-08-24).
#
# Camera names are bare nouns — `fuera`, `entrada`, `jardín` — so they
# carry no gender and no article. Put one inside a prepositional phrase
# and something is always broken: "en la fuera de casa" is the wrong
# article, "en fuera de casa" is no Spanish at all. And a model handed
# broken Spanish does not shrug: it REPAIRS it, by inventing a place
# that fits. Measured, twice, on the live gateway with a camera named
# `fuera`:
#
#   …en fuera de casa: alguien.  ->  "Hay alguien en la entrada, señor."
#
# Somebody outside, reported as somebody at the door. In a feature whose
# whole job is telling you who is around the house, that is a wrong
# answer, not a clumsy one. Handed the same fact as a label, he keeps
# the place he was given and picks his own preposition:
#
#   Dónde: fuera. Qué: alguien.  ->  "Sigue ahí afuera, señor."
#
# So: do not "clean this up" back into a sentence.
_TEMPLATE = (
    "Acabas de fijarte en algo en casa. Dónde: {camera}. Qué: {phrase}. "
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
    finished, and not that he said anything, and NOT that a session
    existed to deliver it into (see the note on RETRY_DELAYS: that comes
    back True and surfaces as Hermes' own "Plugin message injection was
    not routed" warning). There is no way to push a finished assistant
    message through this API at all, which is exactly the property that
    keeps him from reciting.
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
            logger.warning(f"samantha-vision: injection raised — {redact(exc)}")
            return False
        if accepted:
            if index:
                logger.debug(f"samantha-vision: delivered on attempt {index + 1}")
            return True

    # One line, and then silence. The gateway is not listening: either it
    # is still starting or it is going down. A missing session row cannot
    # reach here — it comes back True and Hermes logs it itself.
    logger.warning(
        "samantha-vision: no live gateway, sighting dropped after "
        f"{len(delays) + 1} attempts"
    )
    return False


def make_handler(
    ctx: Any,
    *,
    watcher: Watcher | None = None,
    deliver_prompt: Callable[[str], bool] | None = None,
    show_frame: Callable[[Any, str], Any] | None = None,
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
    show = show_frame
    lock = threading.Lock()

    def on_detections(camera_name: str, detections: list, frame: Any = None) -> None:
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

            # The picture first, then the words: he should not be
            # describing something that is not on screen yet. It is the
            # frame YOLO just looked at — nothing is opened or grabbed
            # for it — and a failure here costs the picture, never the
            # sentence, which is the rule `mirar` already follows.
            #
            # Asked for by the user 2026-08-26. §12 (2026-08-25) had
            # left the unprompted alert deliberately mute in pictures,
            # on the grounds that an image appearing unbidden is a
            # larger thing than one you asked for. It is: it is also
            # what the user wants, and the anti-spam window is what
            # bounds how often it can happen.
            if show is not None and frame is not None:
                try:
                    show(frame, camera_name)
                except Exception as exc:
                    logger.warning(
                        f"samantha-vision: {camera_name}: photo not shown — "
                        f"{redact(exc)}"
                    )

            send(build_prompt(camera_name, phrase))
        except Exception as exc:
            # `cameras.py` catches this too. Belt and braces on purpose:
            # this is the one handler that touches the gateway, and the
            # gateway is the brain.
            logger.warning(
                f"samantha-vision: {camera_name}: alert failed — {redact(exc)}"
            )

    return on_detections
