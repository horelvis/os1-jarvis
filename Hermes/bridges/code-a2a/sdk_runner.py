"""Driving Claude Code through its own SDK, instead of by hand.

`runner.py` spawns `claude -p … --output-format stream-json` and reads
lines. This does the same thing — the SDK spawns the same process, which
is worth knowing before anybody expects it to be cheaper (the spike of
2026-08-26 has the measurement). What it buys is two things that command
line cannot express:

- **Stopping.** `interrupt()` reaches a run that is already working.
  Before this, `tasks/cancel` marked a task cancelled and the assistant
  carried on to the end, which is a lie the protocol was telling.
- **Continuing.** A run hands back a `session_id`; giving it back
  resumes the conversation. `sessions.py` keeps them per project.

**The threading is the whole difficulty and is deliberate.** The bridge
is a `ThreadingHTTPServer` — synchronous, one thread per request — and
the SDK is async. So the client lives in an event loop of its own on a
worker thread, and everything crosses between them through a queue. The
generator this exposes is ordinary and synchronous, exactly like
`runner.run()`, so `server.py` does not learn that any of this happened.

That loop is kept on the object rather than fetched when needed:
`interrupt()` is called from the HTTP thread and has to schedule work on
a loop that is running somewhere else. Reaching for the "current" loop
there gets the wrong one or none — the same failure that cost the live
camera a day (§12, 2026-08-26), in a different file.
"""

from __future__ import annotations

import asyncio
import queue
import threading
from collections.abc import Iterator
from pathlib import Path

from runner import END, START, Run, _tee
from stream import CONSOLE, VOICE, Event

# The tools the assistant is allowed to reach for. Everything, by the
# user's decision of 2026-08-26 taken with the risk stated: full scope
# including pushing. `bypassPermissions` is what
# `--dangerously-skip-permissions` was on the command line, and the
# recording proved the alternative does not work unattended —
# `acceptEdits` refused two commands and the edit itself, leaving the
# assistant describing a fix it could not apply.
PERMISSION_MODE = "bypassPermissions"

# A run that has produced nothing for this long is hung rather than
# thinking. Same number and same reasoning as `runner.SILENCE_TIMEOUT`.
SILENCE_TIMEOUT = 900.0

# Put on the queue when the run is over; nothing else uses it.
_DONE = object()


def available() -> bool:
    """Whether the SDK is installed here. False falls back to the CLI."""
    try:
        import claude_agent_sdk  # noqa: F401
    except ImportError:
        return False
    return True


class SdkRun:
    """One run, and the two things you can do to it while it happens."""

    def __init__(self, prompt: str, cwd: Path, *, resume: str | None = None) -> None:
        self.prompt = prompt
        self.cwd = Path(cwd)
        self.resume = resume
        self.session_id: str | None = None
        self.failed = False
        self.interrupted = False
        self._queue: queue.Queue = queue.Queue()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._client = None
        self._ready = threading.Event()

    # ── what the caller does to it ────────────────────────────────────

    def interrupt(self) -> bool:
        """Stop the run. True when the stop was actually delivered.

        Called from the HTTP thread while the work happens on another
        one. False means there was nothing running to stop — a run that
        already finished, or one whose loop never started.
        """
        loop, client = self._loop, self._client
        if loop is None or client is None or loop.is_closed():
            return False
        self.interrupted = True
        try:
            future = asyncio.run_coroutine_threadsafe(client.interrupt(), loop)
            future.result(timeout=10)
        except Exception:
            # A run that ended between the check and the call raises
            # here. It is stopped either way, which is what was asked.
            return self.interrupted
        return True

    def events(self) -> Iterator[Event]:
        """Yield what the assistant says, as it says it."""
        _tee(f"{START} {self.cwd.name}")
        thread = threading.Thread(target=self._pump, name="code-sdk", daemon=True)
        thread.start()
        try:
            while True:
                try:
                    item = self._queue.get(timeout=SILENCE_TIMEOUT)
                except queue.Empty:
                    self.failed = True
                    yield Event(CONSOLE, "! el asistente lleva demasiado callado")
                    self.interrupt()
                    return
                if item is _DONE:
                    return
                if item.destination == CONSOLE:
                    _tee(item.text)
                yield item
        finally:
            _tee(f"{END} {'1' if self.failed else '0'}")

    # ── the loop, on its own thread ───────────────────────────────────

    def _pump(self) -> None:
        try:
            asyncio.run(self._drive())
        except Exception as exc:  # noqa: BLE001 — one run must not kill the bridge
            self.failed = True
            self._queue.put(Event(CONSOLE, f"! el asistente falló: {exc}"[:200]))
            self._queue.put(
                Event(
                    VOICE, "No he podido ponerlo a trabajar.", final=True, failed=True
                )
            )
        finally:
            self._queue.put(_DONE)

    async def _drive(self) -> None:
        from claude_agent_sdk import (
            AssistantMessage,
            ClaudeAgentOptions,
            ClaudeSDKClient,
            ResultMessage,
            TextBlock,
            ToolUseBlock,
        )

        self._loop = asyncio.get_running_loop()
        options = ClaudeAgentOptions(
            cwd=str(self.cwd),
            permission_mode=PERMISSION_MODE,
            resume=self.resume,
        )
        async with ClaudeSDKClient(options=options) as client:
            self._client = client
            self._ready.set()
            await client.query(self.prompt)
            spoken = ""
            async for msg in client.receive_response():
                if isinstance(msg, AssistantMessage):
                    for block in msg.content:
                        if isinstance(block, TextBlock) and block.text.strip():
                            spoken = block.text.strip()
                            self._queue.put(Event(CONSOLE, spoken[:200]))
                        elif isinstance(block, ToolUseBlock):
                            self._queue.put(Event(CONSOLE, _tool_line(block)))
                elif isinstance(msg, ResultMessage):
                    self.session_id = getattr(msg, "session_id", None) or None
                    self.failed = bool(getattr(msg, "is_error", False))
                    text = str(getattr(msg, "result", "") or "").strip() or spoken
                    self._queue.put(self._closing(text))
                    return
        # The stream ended without a result: interrupted, or the child
        # died. Either way the caller is owed a last word.
        self._queue.put(self._closing(""))

    def _closing(self, text: str) -> Event:
        if self.interrupted:
            # Not a failure. It stopped because it was told to, and
            # saying "falló" about an obeyed instruction is the kind of
            # wrong answer that makes somebody stop trusting the rest.
            self._queue.put(Event(CONSOLE, "— parado"))
            return Event(VOICE, "Lo he dejado, señor.", final=True, failed=False)
        # The console gets a closing LINE, never the text: the result
        # repeats the assistant's last message and printing both showed
        # the summary twice (§12, 2026-08-26).
        self._queue.put(
            Event(CONSOLE, "— terminado con errores" if self.failed else "— terminado")
        )
        return Event(VOICE, text or "Terminado, señor.", final=True, failed=self.failed)


def _tool_line(block) -> str:
    """One console line for a tool call. Same shape the CLI path shows."""
    args = getattr(block, "input", None) or {}
    detail = ""
    if isinstance(args, dict):
        for key in ("command", "file_path", "pattern", "skill"):
            if args.get(key):
                detail = str(args[key])
                break
    name = getattr(block, "name", "?")
    return (f"· {name}: {detail}" if detail else f"· {name}")[:200]


def collect(run: SdkRun) -> Run:
    """Drain a run to the end. For `message/send`."""
    events = list(run.events())
    return Run(events=events, returncode=1 if run.failed else 0)


def start(prompt: str, cwd: Path, *, resume: str | None = None) -> SdkRun:
    return SdkRun(prompt, cwd, resume=resume)
