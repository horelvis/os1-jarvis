"""samantha-code — the assistant's work, visible on the strip.

**It registers no tools, and that is the design.** An earlier version of
this plugin offered one, and the model called it with no arguments at
all — `args={}`, `user_task="None"`, measured six times, which is the
same failure §4 records for `mirar`. Delegating coding is done through
the skills Hermes already ships (`claude-code`, `opencode`, `codex`),
which are written on `terminal`, and the model fills THOSE arguments
correctly.

So this plugin does the one thing those skills cannot: show the work
while it happens. `terminal` returns when the command ends, so a task
that takes four minutes is four minutes of nothing on screen. The
wrapper on the gateway's PATH (`Hermes/bin/claude`) tees a
non-interactive run into a file; this follows that file and pushes each
line into the strip's terminal.

Nothing here sits in the path of a turn. If the file never appears the
thread sleeps; if the strip is not connected the lines are dropped. The
assistant works either way — what is lost is watching it.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

from loguru import logger

from .live import DEFAULT_LIVE, follow, summarise

# The kiosk platform, hard-coded for the reason `samantha_vision`
# hard-codes it: a setting naming the platform would let the contents of
# somebody's repository be routed elsewhere by a config change
# (§12, 2026-08-25).
KIOSK_PLATFORM = "samantha_kiosk"

# Clears the terminal: erase display, cursor home. Sent at the start of
# a run so one task's output does not sit under the next one's.
CLEAR = "\x1b[2J\x1b[H"


def _adapter():
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


def _push(text: str, *, done: bool = False) -> None:
    """Put one line on the strip, from a thread that is not the loop's.

    Scheduled onto the GATEWAY's loop, never the caller's: this thread
    outlives every turn, and the loop a turn brings with it stops the
    moment that turn ends — the bug that cost the live camera a day
    (§12, 2026-08-26).
    """
    import asyncio

    adapter = _adapter()
    if adapter is None:
        return
    loop = getattr(adapter, "loop", None)
    push = getattr(adapter, "push_console", None)
    if loop is None or push is None or loop.is_closed():
        return
    try:
        asyncio.run_coroutine_threadsafe(push(text, done=done), loop)
    except RuntimeError:
        pass


def watch(path: Path, stop: threading.Event) -> None:
    """Follow the file and put what appears on the strip."""
    logger.info(f"samantha-code: mirando {path}")
    for kind, text in follow(path, stop.is_set):
        if kind == "start":
            _push(CLEAR)
            continue
        if kind == "end":
            # The run is over. The strip keeps the last lines up for a
            # minute and then puts itself away — the console is the one
            # thing on the band with no natural end of its own (a photo
            # fades, a live view hits its ceiling), so it is told.
            _push("", done=True)
            continue
        line = summarise(text)
        if line:
            _push(line + "\n")


def register(ctx):
    """Start the follower. Pure: nothing here touches the network.

    The thread is a daemon and owns its own failure, like the camera
    threads: a plugin that took the gateway down because a log file went
    away would be a poor trade for a convenience.
    """
    path = Path(os.environ.get("SAMANTHA_CODE_LIVE", "") or DEFAULT_LIVE).expanduser()
    stop = threading.Event()
    try:
        ctx.on_unload(stop.set)
    except Exception:
        pass

    def run() -> None:
        try:
            watch(path, stop)
        except Exception as exc:
            logger.warning(f"samantha-code: el seguidor se detuvo — {exc}")

    threading.Thread(target=run, name="samantha-code-live", daemon=True).start()
