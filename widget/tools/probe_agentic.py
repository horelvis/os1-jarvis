"""Does the strip's Hermes actually have tools, and does it use them?

Not a unit test — it needs a live gateway, a live model, and it costs
API calls. Run it by hand after changing `platform_toolsets` in
`.hermes/home/config.yaml`, which is the only thing that decides what
the strip may use and is git-ignored, so it has to be redone on every
machine.

The checks are functional rather than log-scraping: each one is a turn
that CANNOT come out right unless a tool was called. Memory is the
clearest — tell her something in one turn, ask in a later turn, and if
she still knows it, the memory tool ran. Reading the log would only
prove she called something.

    python tools/probe_agentic.py

Stop the widget first: the kiosk adapter holds ONE socket, and whoever
connected last wins.
"""

from __future__ import annotations

import asyncio
import json
import sys

import websockets

URI = "ws://127.0.0.1:7777/ws"
TURN_TIMEOUT = 120.0
# The gateway narrates itself through ordinary token frames; the widget
# filters these and so does this.
SYSTEM_MARKERS = ("📬", "↪", "💡", "⚠️", "⚡", "🔔", "🛑")

CHECKS = [
    (
        "memory (guardar)",
        "Oye, para que lo tengas: el café me gusta solo y sin azúcar.",
        None,
    ),
    (
        "memory (recordar)",
        "¿Te acuerdas de cómo me gusta el café?",
        ("solo", "sin azúcar", "azúcar"),
    ),
    (
        "cronjob",
        "Recuérdame regar las plantas mañana a las ocho de la tarde.",
        ("recordar", "recuerdo", "mañana", "ocho", "plantas"),
    ),
    (
        "session_search",
        "¿De qué estuvimos hablando antes?",
        None,
    ),
]


async def one_turn(text: str) -> str:
    """Send one message, collect the reply, drop the gateway's chatter."""
    async with websockets.connect(URI) as ws:
        await ws.send(
            json.dumps({"type": "chat", "message": text, "user_id": "primary"})
        )
        reply: list[str] = []
        loop = asyncio.get_running_loop()
        deadline = loop.time() + TURN_TIMEOUT
        while loop.time() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=deadline - loop.time())
            except (TimeoutError, asyncio.TimeoutError):
                break
            msg = json.loads(raw)
            if msg.get("type") == "token":
                token = msg.get("token", "")
                if not token.strip().startswith(SYSTEM_MARKERS):
                    reply.append(token)
            elif msg.get("type") == "error":
                return f"[error] {msg.get('error', '')}"
            elif msg.get("type") == "done" and reply:
                # `done` also follows each system message, so only settle
                # once something of hers has arrived.
                break
        return " ".join(reply).strip()


async def main() -> int:
    failures = 0
    for name, prompt, expect_any in CHECKS:
        print(f"\n── {name}")
        print(f"  yo    : {prompt}")
        reply = await one_turn(prompt)
        print(f"  ella  : {reply or '(nada)'}")

        if expect_any is None:
            continue
        lowered = reply.lower()
        hit = [word for word in expect_any if word.lower() in lowered]
        if hit:
            print(f"  ✓ menciona {hit}")
        else:
            print(f"  ✗ esperaba alguna de {list(expect_any)}")
            failures += 1

    print(f"\n{len(CHECKS)} turnos, {failures} sin la señal esperada")
    return 1 if failures else 0


sys.exit(asyncio.run(main()))
