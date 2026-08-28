"""Does the strip's Hermes actually have tools, and does it use them?

Not a unit test — it needs a live gateway, a live model, and it costs
API calls. Run it by hand after changing `platform_toolsets` in
`.hermes/home/config.yaml`, which is the only thing that decides what
the strip may use and is git-ignored, so it has to be redone on every
machine.

Each check is a turn plus the SIDE EFFECT it must leave behind, on
disk or in Hermes' own state. An earlier version of this probe read her
reply instead and got both answers wrong: it passed `memory` because
she repeated something she could simply have remembered from two turns
earlier in the same session, and it failed `cronjob` because the reply
was a system line — while the job had in fact been created. What a
model says about what it did is not evidence that it did it.

    python tools/probe_agentic.py

Stop the widget first: the jarvis adapter holds ONE socket, and whoever
connected last wins.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import websockets

URI = "ws://127.0.0.1:7777/ws"
TURN_TIMEOUT = 120.0
# The gateway narrates itself through ordinary token frames; the widget
# filters these and so does this.
SYSTEM_MARKERS = ("📬", "↪", "💡", "⚠️", "⚡", "🔔", "🛑")


def _find_hermes_home() -> Path:
    """Locate `.hermes/home`, which is NOT necessarily beside this file.

    `.hermes/` is git-ignored, so it exists only in the main checkout —
    run this from a worktree and the obvious `parent.parent.parent` walks
    to the worktree root, finds nothing, and reports that the agent never
    wrote anything when in fact it did. That is exactly how this probe
    lied the first time it ran.
    """
    override = os.environ.get("HERMES_HOME")
    if override:
        return Path(override)
    for base in Path(__file__).resolve().parents:
        candidate = base / ".hermes" / "home"
        if candidate.is_dir():
            return candidate
        # From inside .claude/worktrees/<name>/widget/tools, the real
        # checkout is three levels above the worktree root.
        if base.name == "worktrees" and (base.parent.parent / ".hermes").is_dir():
            return base.parent.parent / ".hermes" / "home"
    raise SystemExit("no encuentro .hermes/home — exporta HERMES_HOME")


HERMES_HOME = _find_hermes_home()
REPO = HERMES_HOME.parent.parent
MEMORIES = HERMES_HOME / "memories" / "USER.md"
RUN_GATEWAY = REPO / "Hermes" / "run-gateway.sh"


def memory_contains(*words: str):
    """The memory file on disk had better mention this afterwards."""

    def check() -> tuple[bool, str]:
        if not MEMORIES.is_file():
            return False, f"no existe {MEMORIES}"
        text = MEMORIES.read_text(errors="replace").lower()
        hit = [w for w in words if w.lower() in text]
        return bool(hit), f"USER.md menciona {hit}" if hit else "USER.md no lo recoge"

    return check


def cron_contains(*words: str):
    """`hermes cron list` had better show the job afterwards."""

    def check() -> tuple[bool, str]:
        try:
            out = subprocess.run(
                [str(RUN_GATEWAY), "cron", "list"],
                capture_output=True,
                text=True,
                timeout=120,
            ).stdout.lower()
        except Exception as exc:
            return False, f"no se pudo listar cron: {exc}"
        hit = [w for w in words if w.lower() in out]
        return bool(hit), f"cron muestra {hit}" if hit else "cron no tiene ese job"

    return check


CHECKS = [
    (
        "memory",
        "Oye, para que lo tengas: mi hermana se llama Filomena.",
        memory_contains("filomena"),
    ),
    (
        "cronjob",
        "Recuérdame comprar bombillas el sábado a las once.",
        cron_contains("bombillas"),
    ),
    (
        "session_search",
        "¿De qué estuvimos hablando antes?",
        None,  # no side effect to inspect; read the reply and judge it
    ),
]


async def drain(ws, seconds: float) -> list[str]:
    """Swallow whatever is still arriving, and say what it was.

    The gateway answers asynchronously and keeps talking after the first
    `done`. Without draining between turns, each question collects the
    PREVIOUS answer — which made a cronjob that was never finished look
    like one that was created and then lost.
    """
    out: list[str] = []
    loop = asyncio.get_running_loop()
    deadline = loop.time() + seconds
    while loop.time() < deadline:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=deadline - loop.time())
        except (TimeoutError, asyncio.TimeoutError):
            break
        msg = json.loads(raw)
        if msg.get("type") == "token":
            out.append(msg.get("token", ""))
    return out


async def one_turn(ws, text: str) -> str:
    """Send one message on an OPEN socket and collect the reply.

    The socket is shared across the whole run on purpose. Opening a fresh
    one per turn made every answer arrive one turn late — the gateway
    replies asynchronously, so a new connection picks up whatever was
    still pending. It looked like she was answering the wrong question,
    and it made a working cronjob look broken.
    """
    await ws.send(json.dumps({"type": "chat", "message": text, "user_id": "primary"}))

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
    async with websockets.connect(URI) as ws:
        return await _run_checks(ws)


async def _run_checks(ws) -> int:
    failures = 0
    for name, prompt, side_effect in CHECKS:
        print(f"\n── {name}")
        print(f"  yo     : {prompt}")
        reply = await one_turn(ws, prompt)
        print(f"  ella   : {reply or '(nada)'}")

        # Let the turn actually finish. The first `done` is not the end
        # of it: tools run after she starts talking, and the next
        # question must not arrive mid-task.
        trailing = await drain(ws, 25.0)
        for extra in trailing:
            if not extra.strip().startswith(SYSTEM_MARKERS):
                print(f"  ella + : {extra}")

        if side_effect is None:
            print("  ·  sin efecto que inspeccionar — juzga la respuesta")
            continue
        ok, detail = side_effect()
        print(f"  {'✓' if ok else '✗'} {detail}")
        if not ok:
            failures += 1

    print(f"\n{len(CHECKS)} turnos, {failures} sin efecto comprobable")
    return 1 if failures else 0


sys.exit(asyncio.run(main()))
