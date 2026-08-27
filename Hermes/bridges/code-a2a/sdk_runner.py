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
import os
import queue
import threading
from collections.abc import Iterator
from pathlib import Path

import gates
from answers import assent
from milestones import result_line, text_line, tool_line
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

# A gate nobody answers is denied. The checkpoint's cousin lives in
# worker.py; this one is here because the hook is.
GATE_TIMEOUT = 300.0

# Put on the queue when the run is over; nothing else uses it.
_DONE = object()

# Put on the answer channel when the run is stopped while it is asking.
# A held question has no timeout, so an interrupt is the only thing that
# can end that wait — without this the hook thread blocks forever and
# the run never finishes shutting down.
_ABORTED = object()

# What the model is told when the run is stopped mid-question. It reads
# this back, so it is Spanish like every other deny reason.
_STOPPED = "El usuario ha parado la ejecución. No lo hagas y para aquí."


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
        self.patterns = gates.load_patterns(os.environ.get("SAMANTHA_CODE_GATES"))
        self.gate_timeout = GATE_TIMEOUT
        self.pending: str | None = None
        self.pending_text: str = ""
        # One channel per question, created when it is asked and dropped
        # when it is resolved: an answer given to a question that is
        # already over has nowhere to wait, so it cannot be handed to the
        # next one. `_lock` is what makes that atomic across the HTTP
        # thread (`answer`, `interrupt`) and the hook's own.
        self._answers: queue.Queue | None = None
        self._lock = threading.Lock()

    # ── what the caller does to it ────────────────────────────────────

    def interrupt(self) -> bool:
        """Stop the run. True when the stop was actually delivered.

        Called from the HTTP thread while the work happens on another
        one. False means there was nothing running to stop — a run that
        already finished, or one whose loop never started.
        """
        # First of all, let go of whatever is being asked. The hook is
        # blocked on an answer nobody is going to give now, and the CLI
        # is blocked on the hook — so `client.interrupt()` would sit out
        # its own ten seconds before anything moved.
        self._abandon()
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
                    if self.pending is not None:
                        # A held question is not a hang: the user is
                        # being asked, and nobody types under a timer.
                        continue
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

    # ── being asked, and answering back ─────────────────────────────────

    def answer(self, text: str) -> bool:
        """Resolve the held question or gate. Thread-safe; False when
        nothing waits — the caller then knows the moment has passed.

        The answer goes to the question that is open at this instant and
        to no other: once that one is resolved its channel is dropped, so
        anything left in it is dropped with it rather than being handed
        to whatever is asked next.
        """
        with self._lock:
            if self.pending is None or self._answers is None:
                return False
            self._answers.put(text)
            return True

    def _abandon(self) -> None:
        """Let go of whatever is being asked, without an answer.

        Called by `interrupt()` from the HTTP thread, so it touches only
        what the lock guards and then wakes the waiter from outside it.
        """
        with self._lock:
            channel, self._answers = self._answers, None
            self.pending, self.pending_text = None, ""
        if channel is not None:
            channel.put(_ABORTED)

    async def _await_answer(
        self, channel: queue.Queue, timeout: float | None
    ) -> object:
        """Block the hook (never the loop) until the user answers.

        Returns what was said, `None` when the wait ran out, `_ABORTED`
        when the run was stopped while it was asking.
        """

        def take() -> object:
            try:
                return channel.get(timeout=timeout)
            except queue.Empty:
                pass
            # The window shuts here, and shuts atomically: a "sí" that
            # arrives one instant later is refused rather than kept.
            with self._lock:
                if self._answers is not channel:
                    return None  # already abandoned or resolved elsewhere
                try:
                    return channel.get_nowait()  # answered at the buzzer
                except queue.Empty:
                    self._answers = None
                    return None

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, take)

    def _ask(self, qkind: str, text: str) -> queue.Queue:
        """Put the question up, and hand back the channel it answers on."""
        channel: queue.Queue = queue.Queue()
        with self._lock:
            self.pending, self.pending_text = qkind, text
            self._answers = channel
        self._queue.put(Event(CONSOLE, f"? {text}", kind=qkind, detail=text))
        return channel

    def _resolve(self) -> None:
        with self._lock:
            self.pending, self.pending_text = None, ""
            self._answers = None
        self._queue.put(Event(CONSOLE, "", kind="resolved"))

    @staticmethod
    def _deny(reason: str) -> dict:
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }

    async def _pre_tool(self, input_data, tool_use_id, context) -> dict:
        """The customs post. Sees every tool; holds two kinds of them."""
        name = str(input_data.get("tool_name") or "")
        args = input_data.get("tool_input") or {}

        if name == "AskUserQuestion":
            question = _question_text(args)
            channel = self._ask("question", question)
            # No timeout: nobody answers a question under a clock, and
            # the silence guard in `events()` knows to wait. Only an
            # interrupt ends this wait unanswered.
            reply = await self._await_answer(channel, None)
            self._resolve()
            if reply is _ABORTED:
                return self._deny(_STOPPED)
            # P2 per the probe of 2026-08-27 (docs/superpowers/specs/
            # 2026-08-27-askuserquestion-probe.md): a PreToolUse deny
            # whose reason carries the answer steers the model — there
            # is no result-injection path (can_use_tool only rewrites
            # the tool's input, and the answer is necessarily a result).
            return self._deny(
                f"El usuario responde: {reply}. Continúa con esa respuesta."
            )

        risky = gates.dangerous(name, args, self.patterns)
        if risky:
            channel = self._ask("gate", risky)
            reply = await self._await_answer(channel, self.gate_timeout)
            self._resolve()
            if reply is _ABORTED:
                return self._deny(_STOPPED)
            if reply is None:
                return self._deny(
                    "El usuario no está. No lo hagas; sigue sin ello y dilo al final."
                )
            said = str(reply)  # past the two sentinels it is what was said
            if assent(said):
                return {}
            return self._deny(f"El usuario no lo autoriza: {said}. Sigue sin ello.")

        return {}

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
            HookMatcher,
            ResultMessage,
            TextBlock,
            ToolResultBlock,
            ToolUseBlock,
        )

        try:
            from claude_agent_sdk import UserMessage
        except ImportError:  # older/newer SDK builds may not carry it
            UserMessage = ()  # isinstance() against an empty tuple is always False

        self._loop = asyncio.get_running_loop()
        options = ClaudeAgentOptions(
            cwd=str(self.cwd),
            permission_mode=PERMISSION_MODE,
            resume=self.resume,
            hooks={"PreToolUse": [HookMatcher(matcher=None, hooks=[self._pre_tool])]},
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
                            self._raw(text_line(block.text))
                        elif isinstance(block, ToolUseBlock):
                            self._raw(tool_line(block.name, block.input or {}))
                elif isinstance(msg, UserMessage):
                    content = msg.content
                    if isinstance(content, list):
                        for block in content:
                            if isinstance(block, ToolResultBlock):
                                text = block.content
                                if isinstance(text, list):
                                    text = " ".join(
                                        str(c.get("text", ""))
                                        for c in text
                                        if isinstance(c, dict)
                                    )
                                self._raw(result_line(str(text or "")))
                elif isinstance(msg, ResultMessage):
                    self.session_id = getattr(msg, "session_id", None) or None
                    self.failed = bool(getattr(msg, "is_error", False))
                    text = str(getattr(msg, "result", "") or "").strip() or spoken
                    self._queue.put(self._closing(text))
                    return
        # The stream ended without a result: interrupted, or the child
        # died. Either way the caller is owed a last word.
        self._queue.put(self._closing(""))

    def _raw(self, line: str) -> None:
        """One console line, verbatim. The user, 2026-08-27: «deja de filtrar».

        `kind="raw"` is what tells the plugin to print it as it stands
        instead of looking up a wording of its own — the strip's console
        shows the work now, not a summary of it. The three moments that
        reach the voice are untouched: they come from `gates.py` and the
        `PreToolUse` hook and never passed through here.
        """
        if line:
            self._queue.put(Event(CONSOLE, line, kind="raw"))

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


def _question_text(args: dict) -> str:
    """The question out of AskUserQuestion's input.

    Shape per the probe (docs/superpowers/specs/
    2026-08-27-askuserquestion-probe.md): `questions` is a list, each
    entry a dict with `question` and an `options` list of
    `{label, description}`. Only the first question is read — one
    `AskUserQuestion` call can carry several, and the gate is designed
    for the common case of one.
    """
    questions = args.get("questions") if isinstance(args, dict) else None
    if isinstance(questions, list) and questions and isinstance(questions[0], dict):
        q = str(questions[0].get("question") or "")
        options = questions[0].get("options")
        if isinstance(options, list):
            labels = [str(o.get("label", "")) for o in options if isinstance(o, dict)]
            if any(labels):
                return f"{q} ({' / '.join(l for l in labels if l)})"
        if q:
            return q
    return str(args)[:200]


def collect(run: SdkRun) -> Run:
    """Drain a run to the end. For `message/send`."""
    events = list(run.events())
    return Run(events=events, returncode=1 if run.failed else 0)


def start(prompt: str, cwd: Path, *, resume: str | None = None) -> SdkRun:
    return SdkRun(prompt, cwd, resume=resume)
