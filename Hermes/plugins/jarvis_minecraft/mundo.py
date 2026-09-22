"""The `mundo` tools: the model sees the world, and tells the body to move.

Two tools in phase 1 — `estado_del_mundo` and `ir_a`. The action tools for
mining, building and fighting come later (design §10), and `decir` already
exists in the bridge but is not offered yet: talking in the game chat is a
platform, not a tool (§7).

The names are Spanish, like `mirar` and `ensename`, and the arguments are
the ones the bridge understands. `schema` is built in `__init__.py` as the
OpenAI *function* object — passing only the parameters is the mistake that
made the model call `mirar` with `{}` five times out of five (§12).

Nothing here raises. What a handler returns is paraphrased by the model
and read out loud; an exception is a turn that goes quiet.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

from loguru import logger

TOOLSET = "mundo"

ESTADO = "estado_del_mundo"
IR_A = "ir_a"

# What the model is told, in Spanish: it is deciding when to call these,
# and a description is the only instruction it gets per tool.
DESCRIPCIONES: dict[str, str] = {
    ESTADO: (
        "Mira dónde estás en Minecraft y qué te rodea: vida, comida, "
        "posición, inventario y lo que hay cerca. Úsala cuando necesites "
        "saber dónde está él o qué tiene alrededor, por ejemplo antes de "
        "ir a algún sitio o si te preguntan por él."
    ),
    IR_A: (
        "Haz que camine hasta unas coordenadas concretas del mundo. Usa "
        "las coordenadas que te haya dado la persona o las que hayas "
        "leído con estado_del_mundo; no te las inventes."
    ),
}

ESQUEMAS: dict[str, dict[str, Any]] = {
    ESTADO: {"type": "object", "properties": {}, "required": []},
    IR_A: {
        "type": "object",
        "properties": {
            "x": {"type": "number", "description": "Coordenada X del destino."},
            "y": {"type": "number", "description": "Coordenada Y del destino."},
            "z": {"type": "number", "description": "Coordenada Z del destino."},
        },
        "required": ["x", "y", "z"],
    },
}

# What he says when the body cannot answer at all. Never a tool name, a
# coordinate or a stack trace: this sentence can be spoken.
NO_ESTADO = "Ahora mismo no sé dónde estoy."
NO_MUNDO = "Ahora mismo no puedo moverme por ahí."
FALTAN = "Necesito que me digas las tres coordenadas: x, y y z."


def coords(value: Any) -> tuple[float, float, float] | None:
    """`x`, `y`, `z` out of whatever the model actually sent.

    Hermes hands a tool the whole argument dict, and the model sometimes
    nests it — one dict, or a list holding one. This unwraps both, and
    returns None rather than raising, because asking again is a better
    answer than an exception (§12, 2026-08-26: `ver_en_vivo` named its
    parameter after one field and met the dict with `.casefold()`).
    """
    if isinstance(value, (list, tuple)):
        for item in value:
            found = coords(item)
            if found:
                return found
        return None
    if not isinstance(value, dict):
        return None
    try:
        return (float(value["x"]), float(value["y"]), float(value["z"]))
    except (KeyError, TypeError, ValueError):
        pass
    # Not the coordinates themselves; look one level in, for the model
    # that wraps them (`{"args": {...}}`).
    for item in value.values():
        found = coords(item)
        if found:
            return found
    return None


def make_handler(
    client: Any,
    name: str,
) -> Callable[..., Awaitable[str]]:
    """Build one handler. It never raises.

    `client` is a `bridge_client.BridgeClient` in production and a fake in
    tests. Its methods are blocking — `urllib` on a thread of the
    gateway's pool, not the event loop, because the loop must never block
    (§12, 2026-08-26).
    """

    async def estado(_args: Any = None, **_kwargs: Any) -> str:
        try:
            state = await asyncio.to_thread(client.state)
        except Exception as exc:  # noqa: BLE001 — a handler must not cost the turn
            logger.warning(f"jarvis-minecraft: sin estado — {exc}")
            return NO_ESTADO
        # JSON, not a sentence: the model reasons over it and paraphrases.
        # It is never read aloud (§5).
        return json.dumps(state, ensure_ascii=False)

    async def ir_a(args: Any = None, **_kwargs: Any) -> str:
        target = coords(args)
        if target is None:
            return FALTAN
        x, y, z = target
        try:
            answer = await asyncio.to_thread(client.do, IR_A, {"x": x, "y": y, "z": z})
        except Exception as exc:  # noqa: BLE001 — a handler must not cost the turn
            logger.warning(f"jarvis-minecraft: ir_a falló — {exc}")
            return NO_MUNDO
        if not isinstance(answer, dict):
            return NO_MUNDO
        # The bridge's own sentence, which already distinguishes "he
        # llegado" from "no encuentro por dónde ir".
        return str(answer.get("said") or NO_MUNDO)

    handlers = {ESTADO: estado, IR_A: ir_a}
    return handlers[name]
