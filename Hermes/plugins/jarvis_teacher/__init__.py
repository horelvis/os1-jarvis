"""jarvis-teacher — he teaches a subject, from sources he went and got."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from loguru import logger

from .curso import Curso
from .fuentes import Base, Resultado
from .tool import TOOLSET, Aula

# The platform a card is allowed to reach, and the only one. A constant
# rather than a config key, for the reason the vision plugin's own
# constant carries: a setting naming the platform would put the rejected
# `MEDIA:` decision back, one edit away.
JARVIS_PLATFORM = "jarvis"

_ESQUEMAS: dict[str, dict[str, Any]] = {
    "ensename": {
        "type": "object",
        "properties": {
            "tema": {
                "type": "string",
                "description": "Qué quiere estudiar. Vacío retoma el último curso.",
            }
        },
    },
    "planificar": {
        "type": "object",
        "properties": {
            "temario": {
                "type": "string",
                "description": "El temario, como lista Markdown, un punto por línea.",
            }
        },
        "required": ["temario"],
    },
    "aprobar": {"type": "object", "properties": {}},
    "explicar": {
        "type": "object",
        "properties": {
            "concepto": {
                "type": "string",
                "description": "El punto del temario que toca.",
            },
            "ficha": {
                "type": "string",
                "description": "Markdown que enseñar mientras lo explicas. Opcional.",
            },
        },
    },
    "preguntar": {
        "type": "object",
        "properties": {
            "ficha": {
                "type": "string",
                "description": "Enunciado y opciones, en Markdown, las opciones como lista.",
            },
            "correcta": {
                "type": "string",
                "description": "La letra de la opción correcta: a, b o c.",
            },
        },
        "required": ["ficha", "correcta"],
    },
    "responder": {
        "type": "object",
        "properties": {
            "elegida": {
                "type": "string",
                "description": "Lo que ha contestado, tal cual.",
            }
        },
        "required": ["elegida"],
    },
    "terminar": {"type": "object", "properties": {}},
}

_DESCRIPCIONES = {
    "ensename": "Abre un curso sobre un tema o retoma el que hay. Devuelve por dónde vais.",
    "planificar": "Guarda el temario que propongas y lo enseña en pantalla.",
    "aprobar": "El usuario aprueba el temario y las fuentes: descarga el material y empieza.",
    "explicar": "Trae el material guardado sobre un punto del temario y lo marca como dado.",
    "preguntar": "Plantea una pregunta tipo test: la guarda, la enseña y espera respuesta.",
    "responder": "Corrige lo que ha contestado a la pregunta que está en pantalla.",
    "terminar": "Cierra la clase y resume cómo ha ido.",
}


def _home() -> Path:
    return Path(
        os.environ.get("JARVIS_TEACHER_HOME", Path.home() / ".samantha" / "teacher")
    )


def register(ctx) -> None:
    """Declare the tools. Nothing here touches disk or the network.

    The `Aula` is built lazily, on the first tool call, for exactly the
    reason `samantha_vision` starts its threads outside `register`: a
    registration that raises is reported by Hermes as a retry-forever
    loop at DEBUG level, and a plugin that never loads costs the whole
    feature silently.
    """
    aula: dict[str, Aula] = {}

    def _aula() -> Aula:
        if "it" not in aula:
            curso = Curso(_home() / "curso.db")
            base = Base(curso, _home() / "fuentes", buscar=_buscar(ctx), traer=_traer)
            instancia = Aula(curso, base, push_ficha=_push_ficha)
            instancia._traer_imagen = _traer_bytes  # the declared seam
            aula["it"] = instancia
        return aula["it"]

    for nombre, esquema in _ESQUEMAS.items():
        ctx.register_tool(
            name=nombre,
            toolset=TOOLSET,
            description=_DESCRIPCIONES[nombre],
            emoji="📚",
            schema=esquema,
            handler=_handler(_aula, nombre),
            is_async=True,
        )


def _handler(fabrica, nombre: str):
    async def handler(args: dict, *_a, **_kw) -> str:
        try:
            return await getattr(fabrica(), nombre)(args or {})
        except Exception as exc:  # noqa: BLE001 — a handler must not cost the turn
            logger.warning(f"jarvis-teacher: {nombre} falló antes de empezar: {exc}")
            return "Ahora mismo no puedo con las clases."

    return handler


async def _adaptador():
    """The strip's adapter, or None. Resolved at call time, every time.

    Mirrors `samantha_vision._adapter()` exactly, because that is the
    ONLY verified way a plugin reaches the `jarvis` platform adapter on
    this pinned Hermes — `PluginContext` has no `get_platform_adapter`
    (checked against `.hermes/src/hermes_cli/plugins.py`). `register()`
    runs before the gateway has adapters, so a reference captured then
    would be `None` for the life of the process; this resolves the
    runner fresh on every call instead.
    """
    from gateway.config import Platform
    from gateway.run import _gateway_runner_ref

    runner = _gateway_runner_ref()
    if runner is None:
        return None
    return getattr(runner, "adapters", {}).get(Platform(JARVIS_PLATFORM))


async def _push_ficha(md: str, tipo: str, **kw) -> bool:
    """Draw a card on the strip, and nowhere else. Never raises.

    Failure mode 2 of `plugin.yaml`: no strip connected means this
    returns `False` and the lesson still happens out loud — a card is
    never worth a turn.
    """
    try:
        adapter = await _adaptador()
        if adapter is None or not hasattr(adapter, "push_ficha"):
            return False
        return bool(await adapter.push_ficha(md, tipo, **kw))
    except Exception as exc:  # noqa: BLE001 — a card that fails to draw is not fatal
        logger.warning(f"jarvis-teacher: no se pudo dibujar la ficha — {exc}")
        return False


def _buscar(ctx):
    """Hermes' own web search, wrapped into `list[Resultado]`.

    THE SHAPE OF WHAT HERMES RETURNS IS NOT KNOWN YET — it is the check
    named in the spec as the earliest one that can be run, and it needs
    the network but not the GPU. Until it is run, this returns nothing
    and `ensename` refuses to invent a syllabus, which is the correct
    behaviour for a box with no search.
    """

    def buscar(consulta: str) -> list[Resultado]:
        logger.warning("jarvis-teacher: no hay buscador conectado todavía")
        return []

    return buscar


def _traer(url: str) -> str:
    import urllib.request

    with urllib.request.urlopen(url, timeout=15) as respuesta:
        return respuesta.read(2_000_000).decode("utf-8", "replace")


def _traer_bytes(url: str) -> bytes:
    import urllib.request

    with urllib.request.urlopen(url, timeout=15) as respuesta:
        return respuesta.read(4 * 1024 * 1024)
