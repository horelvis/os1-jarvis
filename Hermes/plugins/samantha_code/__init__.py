"""samantha-code — the coding assistant, watched live on the strip.

Hermes can already CALL the assistant: `a2a_call` reaches the bridge and
comes back with the answer. What it cannot do is show the work while it
happens, because that call waits for the end.

So this plugin registers one tool, and its whole job is the difference
between those two: it opens the bridge's `message/stream`, pushes every
line the assistant writes into the strip's terminal as it is written,
and hands the model only the sentence worth saying. The picture on the
strip and the words in his mouth travel separately — the same split the
camera already makes (§12, 2026-08-25), for the same reason.

It is small on purpose. It does not run the assistant, choose the
project, or know what Claude Code is; the bridge does all of that behind
A2A, which is what keeps another assistant a configuration change.
"""

from __future__ import annotations

import threading
from typing import Any

from loguru import logger

from .sse import events, lines_of, state_of

NAME = "trabajar"
TOOLSET = "codigo"
EMOJI = "🛠"

DESCRIPTION = (
    "Encarga una tarea de programación al asistente de código y enséñala "
    "en la pantalla mientras la hace. Di en qué proyecto es y qué hay que "
    "hacer. Úsala en vez de a2a_call cuando el usuario esté delante: la "
    "diferencia es que ve el trabajo."
)

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "tarea": {
            "type": "string",
            "description": (
                "Qué hay que hacer, con el proyecto dentro. "
                "Ej: 'en barndoor, arregla el log de la cámara'."
            ),
        }
    },
    "required": ["tarea"],
}

# Where the bridge is. Not configurable on purpose, for now: it is a
# localhost service this repo starts itself
# (`systemd/samantha-code-a2a.service`), and a setting naming it would
# be one more thing to keep in step with the unit.
BRIDGE_URL = "http://127.0.0.1:9910"

# A coding task is minutes, not seconds. The stream ends when the task
# reaches a terminal state; this is the ceiling under which it must.
TIMEOUT = 1800.0

# The kiosk platform, hard-coded for the same reason `samantha_vision`
# hard-codes it: a setting naming the platform would let a picture — or
# here, the contents of somebody's repository — be routed somewhere
# else by a config change (§12, 2026-08-25).
KIOSK_PLATFORM = "samantha_kiosk"


async def _adapter():
    """The strip's adapter, or None."""
    try:
        from gateway.config import Platform
        from gateway.run import _gateway_runner_ref

        runner = _gateway_runner_ref()
        if runner is None:
            return None
        return getattr(runner, "adapters", {}).get(Platform(KIOSK_PLATFORM))
    except Exception:
        return None


async def push_console(text: str) -> bool:
    """Write one line into the strip's terminal. Never raises."""
    try:
        adapter = await _adapter()
        if adapter is None:
            return False
        return bool(await adapter.push_console(text))
    except Exception:
        return False


def _loop():
    """The gateway's own event loop, the one that lives between turns.

    The same trap `samantha_vision.live` documents and paid for: the
    loop a turn brings with it stops running when the turn ends, so
    anything scheduled onto it afterwards is silently dropped.
    """
    try:
        from gateway.config import Platform
        from gateway.run import _gateway_runner_ref

        runner = _gateway_runner_ref()
        if runner is None:
            return None
        adapter = getattr(runner, "adapters", {}).get(Platform(KIOSK_PLATFORM))
        return getattr(adapter, "loop", None)
    except Exception:
        return None


def make_handler(url: str = BRIDGE_URL, timeout: float = TIMEOUT):
    """Build the `trabajar` handler. It never raises at the model."""

    async def handler(args: Any = None, **kwargs: Any) -> str:
        # Hermes hands a tool its arguments in more than one shape: the
        # whole dict as the first positional (which `mirar` has always
        # known), or by keyword. Reading only one is how this returned
        # "¿qué hay que hacer?" in 0.00s while the model was holding a
        # perfectly good task — measured 2026-08-26, and the same trap
        # `ver_en_vivo` fell into the same day.
        # One line per call, and it is what found the wall this tool is
        # currently stuck against: the model calls it with NOTHING —
        # `args={}`, and Hermes' own `user_task` arrives as the string
        # "None". Kept because the day somebody changes the model or the
        # schema, this line says immediately whether that moved.
        logger.info(
            f"samantha-code: args={type(args).__name__}:{str(args)[:80]} "
            f"user_task={str(kwargs.get('user_task'))[:60]}"
        )
        task = ""
        for candidate in (args, kwargs):
            if isinstance(candidate, dict):
                for key in ("tarea", "task", "prompt", "message"):
                    value = candidate.get(key)
                    if value:
                        task = str(value).strip()
                        break
            elif isinstance(candidate, str) and candidate.strip():
                task = candidate.strip()
            if task:
                break
        if not task:
            # Measured 2026-08-26: the model calls this with NO arguments
            # (`args={}`, kwargs `task_id session_id user_task`) and the
            # tool answered "¿qué hay que hacer?" in 0.00s while the
            # request was sitting right there. Hermes hands every tool
            # the user's own sentence as `user_task`; when the model
            # forgets to fill the schema, that is the task.
            task = str(kwargs.get("user_task") or "").strip()
        if not task:
            return "¿Qué hay que hacer, señor, y en qué proyecto?"

        import asyncio

        payload = {
            "jsonrpc": "2.0",
            "id": "1",
            "method": "message/stream",
            "params": {
                "message": {
                    "messageId": "m1",
                    "role": "ROLE_USER",
                    "parts": [{"kind": "text", "text": task}],
                }
            },
        }

        spoken: list[str] = []
        failed = threading.Event()
        # The GATEWAY's loop, not the turn's — `_loop()` exists for this
        # and the first version of this line did not use it. The turn's
        # loop is alive while the tool awaits, so it would have worked
        # by accident today and gone quiet the first time anything
        # outlived its turn.
        loop = _loop() or asyncio.get_running_loop()

        def read() -> None:
            """Drain the stream on a worker thread.

            `urllib` blocks, and the gateway's loop must not: a coding
            task holds this open for minutes and everything else — the
            cameras, a reminder, the next thing said out loud — runs on
            that loop.
            """
            seen = pushed = 0
            try:
                for event in events(url, payload, timeout):
                    seen += 1
                    destination, text = lines_of(event)
                    if not text:
                        continue
                    if destination == "voice":
                        spoken.append(text)
                        continue
                    if loop is None:
                        # The gateway's loop, not the turn's. Without it
                        # nothing can be scheduled and the console stays
                        # empty with no other symptom — the shape of the
                        # bug the live camera had (§12, 2026-08-26).
                        logger.warning("samantha-code: sin loop, la consola no verá nada")
                    else:
                        asyncio.run_coroutine_threadsafe(push_console(text), loop)
                        pushed += 1
                    state = state_of(event)
                    if state.endswith("FAILED"):
                        failed.set()
                logger.info(
                    f"samantha-code: {seen} eventos, {pushed} a la consola, "
                    f"{len(spoken)} dichos"
                )
            except Exception as exc:
                logger.warning(f"samantha-code: stream failed — {exc}")
                failed.set()

        await asyncio.to_thread(read)

        if not spoken:
            return (
                "El asistente no ha llegado a decir nada, señor."
                if failed.is_set()
                else "Hecho, sin novedades que contar."
            )
        # The last thing it said is the result; the rest were questions
        # asked and answered along the way.
        return spoken[-1]

    return handler


def register(ctx):
    """Register the tool. Pure — nothing here touches the network."""
    try:
        ctx.register_tool(
            name=NAME,
            toolset=TOOLSET,
            schema=SCHEMA,
            description=DESCRIPTION,
            handler=make_handler(),
            emoji=EMOJI,
            is_async=True,
        )
        logger.info("samantha-code: registrada la herramienta 'trabajar'")
    except Exception as exc:
        logger.warning(f"samantha-code: no se pudo registrar — {exc}")
