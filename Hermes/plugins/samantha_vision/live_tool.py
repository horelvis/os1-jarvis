"""`ver_en_vivo` / `dejar_de_ver` — the moving picture, on request.

Both handlers return a sentence and nothing else: whatever comes back is
read out loud by CosyVoice, so there is never a path, a codec name or a
number in it. The picture travels on its own channel (spec §4); this
file only decides what he says about it.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Sequence

from loguru import logger

from .cameras import redact
from .tool import _resolve, _spoken_list, camera_argument

OPEN_NAME = "ver_en_vivo"
CLOSE_NAME = "dejar_de_ver"
EMOJI = "📹"

# The line between this and `mirar` has to be drawn in the descriptions,
# because the words are close enough for a model to confuse: `mirar` is a
# photo of right now, this is the camera in motion until told to stop.
#
# Which side "muéstrame la entrada" falls on was settled by the user on
# 2026-08-26, after measuring it land on `mirar`: showing a camera IS
# this tool. The still is now the exception, asked for by name.
OPEN_DESCRIPTION = (
    "Enseña una cámara de la casa en movimiento, hasta que pidan pararla. "
    "Es la forma normal de enseñar una cámara: úsala siempre que pidan "
    "ver una cámara, que se la enseñes o que la pongas. Solo si piden "
    "expresamente una foto o una imagen fija, usa mirar."
)
CLOSE_DESCRIPTION = "Deja de mostrar lo que se está viendo en movimiento."

OPEN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "camara": {
            "type": "string",
            # Unlike `mirar`, omitting this is not a survey: there is one
            # view. The handler asks rather than guessing (spec §5.3).
            "description": "Nombre de la cámara que se quiere ver.",
        }
    },
    "required": [],
}
CLOSE_SCHEMA: dict[str, Any] = {"type": "object", "properties": {}, "required": []}


def make_open_handler(
    session: Any, fleet: Any, cameras: Sequence[str]
) -> Callable[..., Awaitable[str]]:
    """Build the `ver_en_vivo` handler. It never raises.

    `cameras` is read on every call rather than copied, for the same
    reason `mirar`'s handler does it: the supervisor thread fills that
    list in after registration.
    """

    async def handler(camara: Any = None, **_ignored: Any) -> str:
        names = list(cameras)
        if not names:
            return "Ahora mismo no tengo ojos en la casa, señor."

        # Not `camara` itself: Hermes hands over the whole argument dict,
        # and this parameter is only usually a string. See
        # `camera_argument` — this line is the fix for a live crash.
        camara = camera_argument(camara)
        if camara is None:
            if len(names) != 1:
                # Asking is the honest answer. Guessing opens the
                # entrance when he was asked for the garage.
                return f"¿Cuál quiere ver, señor? Tengo {_spoken_list(names)}."
            wanted = names[0]
        else:
            wanted = _resolve(camara, names) or ""
            if not wanted:
                return (
                    f"No tengo ninguna con ese nombre, señor. "
                    f"Tengo {_spoken_list(names)}."
                )

        try:
            extradata, width, height = fleet.codec_parameters(wanted)
            opened = await session.open(
                wanted, extradata=extradata, size=(width, height)
            )
        except Exception as exc:
            logger.warning(f"samantha-vision: live not opened — {redact(exc)}")
            opened = False

        if not opened:
            return "Ahora mismo no puedo enseñárselo, señor."
        # Where: a labelled value he builds his own sentence around. NOT
        # inside a preposition — CLAUDE.md §12, 2026-08-24.
        return f"Dónde: {wanted}. Estado: en directo."

    return handler


def make_close_handler(session: Any) -> Callable[..., Awaitable[str]]:
    """Build the `dejar_de_ver` handler. It never raises."""

    async def handler(**_ignored: Any) -> str:
        try:
            closed = await session.close("asked")
        except Exception as exc:
            logger.warning(f"samantha-vision: live not closed — {redact(exc)}")
            closed = False
        return "Estado: retirado." if closed else "Estado: no había nada puesto."

    return handler
