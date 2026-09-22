"""jarvis-minecraft — a body in the world.

Registers the `mundo` toolset so the model can look at the world and move
in it, and follows the body's event stream so that what happens to it
without being asked can reach the conversation.

Registration stays pure (§12, 2026-08-24: a plugin's whole lifecycle on
the way in is `register`, and anything that opens a socket here turns a
missing dependency into a plugin that never loads). The bridge url is
read, a client is built, the tools are declared — and the threads that
talk to the body start after, off the registration path, exactly the way
`jarvis_vision` starts its cameras.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from loguru import logger

from . import mundo
from .bridge_client import BridgeClient, follow_events
from .mundo import DESCRIPCIONES, ESQUEMAS, ESTADO, IR_A, TOOLSET, make_handler

# Where the strip's conversation lives. Same constant as
# jarvis_vision/alert.py, and for the same reason: a `/new` mints a fresh
# session under the SAME key.
JARVIS_SESSION_KEY = "agent:main:jarvis:dm:jarvis"

# How often `up` is refreshed. `check_fn` reads a flag, not a probe, so
# something has to keep the flag honest, and this is it.
HEALTH_INTERVAL = 5.0

# At most one injected event per window. The reworked rate limit of
# design §6: there is no bridge→LLM call to throttle, so the thing to
# bound is how often the body may interrupt the conversation.
EVENT_COOLDOWN = 30.0

# Which events are worth a turn. Phase 1 emits none of them yet — the
# emergency routine and the death/attack feed are phase 3 — so this is
# deliberately short. It is wired now so the seam exists and is tested.
CRITICAL = {"emergency", "died", "attacked", "low_health"}

# A prompt, not a sentence (CLAUDE.md §1, and jarvis_vision/alert.py): the
# body reports a fact, and what reaches the room is his answer to it.
_TEMPLATE = (
    "Acabas de vivir algo en Minecraft. Qué: {what}. "
    "Coméntalo en una frase corta, con tus palabras, como quien lo "
    "menciona sin darle importancia. "
    "No digas herramientas, ni coordenadas, ni cómo lo sabes."
)

# One bounded schedule: try, wait, try, give up. A sighting with nowhere
# to go is dropped, never queued — queueing means reciting stale events
# the moment the strip connects.
RETRY_DELAYS: tuple[float, ...] = (1.0, 3.0, 5.0)


def register(ctx: Any) -> None:
    """Declare the tools, then start the two threads. Never raises up."""
    url = ctx.get_config("bridge", "http://127.0.0.1:8095")

    client = BridgeClient(url)
    nombres = _wire(ctx, client)

    stop = threading.Event()
    ctx.on_unload(stop.set)

    threading.Thread(
        target=_health_loop,
        args=(client, stop),
        name="jarvis-minecraft-health",
        daemon=True,
    ).start()
    threading.Thread(
        target=_events_loop,
        args=(ctx, url, stop),
        name="jarvis-minecraft-events",
        daemon=True,
    ).start()

    logger.info(f"jarvis-minecraft: registered {len(nombres)} tools (toolset {TOOLSET})")


def _wire(ctx: Any, client: Any) -> list[str]:
    """Declare the tools. Pure: no thread, no socket, no clock.

    Split out of `register` so a test can exercise registration with a
    fake context and a fake client, and no bridge in the room.
    """
    nombres: list[str] = []
    for name in (ESTADO, IR_A):
        ctx.register_tool(
            name=name,
            toolset=TOOLSET,
            description=DESCRIPCIONES[name],
            emoji="🌍",
            # `schema` IS the OpenAI function object, not its parameters.
            # Passing only the parameters is what made the model call
            # `mirar` with `{}` five times out of five (§12).
            schema={"description": DESCRIPCIONES[name], "parameters": ESQUEMAS[name]},
            handler=make_handler(client, name),
            # A tool that cannot work is not offered. Until the health
            # loop has reached the bridge once, `up` is False and the
            # model never sees these.
            check_fn=lambda: client.up,
            is_async=True,
        )
        nombres.append(name)
    return nombres


def _health_loop(client: Any, stop: threading.Event) -> None:
    """Keep `client.up` honest. Blocking reads, our own thread."""
    while not stop.is_set():
        try:
            client.state()
        except Exception:  # noqa: BLE001 — a body that is down is not a crash
            pass
        stop.wait(HEALTH_INTERVAL)


def _events_loop(ctx: Any, url: str, stop: threading.Event) -> None:
    """Follow the body's firehose and inject what is worth a turn."""
    try:
        for payload in follow_events(url, stop.is_set):
            _inject(ctx, payload, delays=RETRY_DELAYS)
    except Exception as exc:  # noqa: BLE001 — a dead follower must not cost the gateway
        logger.warning(f"jarvis-minecraft: el seguidor se detuvo — {exc}")


def _inject(
    ctx: Any,
    payload: dict,
    *,
    delays: tuple[float, ...] = (),
    sleep: Any = time.sleep,
    now: Any = time.time,
) -> bool:
    """Turn one critical event into a prompt for the conversation.

    Never raises, and never repeats within `EVENT_COOLDOWN`. Returns
    whether the gateway accepted it — not whether he said anything.
    """
    if not isinstance(payload, dict) or payload.get("event") not in CRITICAL:
        return False

    if not _within_cooldown(now()):
        logger.debug(f"jarvis-minecraft: evento {payload.get('event')} en espera")
        return False

    prompt = _TEMPLATE.format(what=_describe(payload))
    for index, delay in enumerate((0.0, *delays)):
        if delay:
            sleep(delay)
        try:
            accepted = ctx.inject_message(
                prompt, role="user", session_key=JARVIS_SESSION_KEY
            )
        except Exception as exc:  # noqa: BLE001 — the gateway is the brain
            logger.warning(f"jarvis-minecraft: la inyección falló — {exc}")
            return False
        if accepted:
            logger.info(f"jarvis-minecraft: {payload.get('event')} dicho")
            return True

    logger.warning(
        "jarvis-minecraft: no hay gateway vivo, evento descartado tras "
        f"{len(delays) + 1} intentos"
    )
    return False


# The cooldown's one piece of state. A module global, not per-client, so
# every path that injects shares it.
_last_event = {"at": 0.0}


def _within_cooldown(when: float) -> bool:
    if when - _last_event["at"] < EVENT_COOLDOWN:
        return False
    _last_event["at"] = when
    return True


def _describe(payload: dict) -> str:
    """A labelled value, not a sentence — the Ruling 14 lesson.

    A camera named `fuera` inside a prepositional phrase produced broken
    Spanish, which the model then "repaired" by inventing a place. Facts
    as labels survive; facts as grammar do not.
    """
    event = payload.get("event")
    if event == "emergency":
        return "estás en peligro y te has replegado para protegerte"
    if event == "died":
        return "te han matado"
    if event == "attacked":
        return "alguien o algo te está atacando"
    if event == "low_health":
        return "te queda muy poca vida"
    return str(event)
