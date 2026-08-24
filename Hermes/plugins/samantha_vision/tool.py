"""`mirar` — he looks at a camera now, and answers in words.

**The return value is a sentence and nothing else.** No `MEDIA:` line, on
any platform, ever (spec §3): a tool result travels wherever the turn
travels, so a picture inside it would leave this box the first time a
turn was routed to Telegram. The picture goes to the strip and only the
strip, as a side effect, over a channel no other adapter can see.

**And no filesystem path in it either.** CosyVoice reads the answer out
loud, and this project has already had a path spoken to it once, by the
reminders' scaffolding. The path exists in this module; it never reaches
the string that comes back.

The sentence is never conditional on the picture. A full disk, a strip
that is not running, a plugin that is not installed — each costs the
photo and none of them costs the words, which is why `write_jpeg` and
`push_photo` are wrapped separately here rather than defending
themselves (Ruling 7).

This module knows nothing about the strip. `push_photo` arrives as a
callable, the way `cameras.py` takes `on_detections`, so the whole tool
runs in a test with no gateway, no camera and no GPU in the room.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from loguru import logger

from .cameras import redact
from .snapshot import write_jpeg
from .vision import describe

# What `grab` is given to wait for the next decoded frame. Two seconds,
# from the plugin spec §6.2: a question that hangs is worse than one
# answered honestly, because he simply goes quiet.
GRAB_TIMEOUT = 2.0

# The tool as the model sees it. Spanish, because the model is answering
# somebody who speaks Spanish and the camera names are Spanish nouns.
NAME = "mirar"
TOOLSET = "vision"
DESCRIPTION = "Mira una cámara de la casa ahora mismo y di qué hay."
EMOJI = "👁"
SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "camara": {
            "type": "string",
            "description": "Nombre de la cámara. Omitir para mirar todas.",
        }
    },
    "required": [],
}

PushPhoto = Callable[[str, str], Awaitable[bool]]


def _spoken_list(names: Sequence[str]) -> str:
    """`entrada y fuera` — a list somebody could say out loud."""
    names = list(names)
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + " y " + names[-1]


def _resolve(wanted: str, names: Sequence[str]) -> str | None:
    """The camera he meant, or None. Case-insensitive, exact otherwise.

    A model that writes "Entrada" means the camera called `entrada`; a
    model that writes "garaje" means a camera that does not exist, and
    inventing a match for it would answer a question about the wrong
    room.
    """
    for name in names:
        if name == wanted:
            return name
    lowered = wanted.casefold()
    for name in names:
        if name.casefold() == lowered:
            return name
    return None


def make_handler(
    fleet: Any,
    cameras: Sequence[str],
    push_photo: PushPhoto,
    *,
    now: Callable[[], float] = time.time,
) -> Callable[..., Awaitable[str]]:
    """Build the `mirar` handler. It never raises.

    `cameras` is read on every call rather than copied: `register()`
    hands over a list the supervisor thread fills in once it has read the
    config, so a handler built at registration time still knows the real
    cameras a moment later.

    The handler is a coroutine (Ruling 1) and is registered with
    `is_async=True`. `grab` blocks for up to `GRAB_TIMEOUT`, so it runs
    through `asyncio.to_thread`; `push_photo` is awaited.
    """

    def _detections(frame: Any, camera: str) -> list:
        """What YOLO finds, or nothing at all.

        The detector belongs to the fleet: it is built once, when the
        cameras start, and a second ONNX session here would claim memory
        and threads for a model already loaded. A fleet with no detector
        started no watcher thread either, so it cannot have produced a
        frame — outside a test, this returns early only if `detect`
        itself fell over.
        """
        detector = getattr(fleet, "detector", None)
        if detector is None:
            return []
        try:
            return list(detector.detect(frame))
        except Exception as exc:
            logger.warning(f"samantha-vision: {camera} detect failed — {redact(exc)}")
            return []

    async def _show(frame: Any, camera: str) -> None:
        """Put the picture on the strip. Costs the caller nothing if it fails."""
        try:
            path = write_jpeg(frame, camera, now=now())
        except Exception as exc:
            logger.warning(
                f"samantha-vision: {camera} snapshot not written — {redact(exc)}"
            )
            return
        try:
            if not await push_photo(str(path), camera):
                logger.debug(f"samantha-vision: {camera} photo not shown")
        except Exception as exc:
            # push_photo promises never to raise. Believing a promise is
            # not the same as depending on one, and the gateway is the
            # brain.
            logger.warning(f"samantha-vision: {camera} photo not shown — {redact(exc)}")

    async def _look(camera: str) -> str:
        try:
            frame = await asyncio.to_thread(fleet.grab, camera, GRAB_TIMEOUT)
        except Exception as exc:
            logger.warning(f"samantha-vision: {camera} grab failed — {redact(exc)}")
            frame = None
        if frame is None:
            return f"La cámara de {camera} no responde."
        await _show(frame, camera)
        phrase = describe(_detections(frame, camera))
        if phrase:
            return f"En {camera} hay {phrase}."
        return f"En {camera} no hay nadie."

    async def handler(args: Any = None, **_kwargs: Any) -> str:
        """`mirar`. Answers in one or more sentences, and never raises."""
        names = list(cameras)
        wanted = args.get("camara") if isinstance(args, dict) else None
        wanted = str(wanted).strip() if wanted is not None else ""

        if wanted:
            camera = _resolve(wanted, names)
            if camera is None:
                # The argument is never read back: it is model-supplied
                # text and this sentence is spoken out loud.
                if not names:
                    return "No tengo ninguna cámara."
                return f"No tengo esa cámara. Tengo {_spoken_list(names)}."
            targets = [camera]
        else:
            # No name means all of them. "¿Hay alguien?" should not force
            # him to pick one, and picking wrong is worse than looking
            # twice.
            targets = names

        if not targets:
            # `check_fn` keeps the tool out of his list when no camera is
            # configured, so this is a race with a gateway still reading
            # its config, not a normal answer.
            return "No tengo ninguna cámara."

        said = [await _look(camera) for camera in targets]
        return " ".join(said)

    return handler
