"""Running the assistant on a project, and turning its output into events.

The subprocess half. `server.py` speaks A2A; this speaks whatever the
assistant speaks, which for Claude Code is one JSON object per line and
for OpenCode is plain text.

Nothing here blocks: the child is read line by line and yielded as it
goes, so `message/stream` can forward each line as it arrives and
`message/send` can drain the same generator to the end. One
implementation, two protocol methods.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from assistants import Assistant
from stream import CONSOLE, VOICE, Event, classify, parse

# A run that has said nothing for this long is hung, not thinking. It is
# generous on purpose — a real task reads files, runs tests and waits on
# a model — and it exists so a wedged child cannot hold the session
# forever.
SILENCE_TIMEOUT = 900.0


@dataclass
class Run:
    """One execution of an assistant, and what it produced."""

    events: list[Event]
    returncode: int

    @property
    def spoken(self) -> str:
        """The last thing worth saying out loud, or ''."""
        for event in reversed(self.events):
            if event.destination == VOICE:
                return event.text
        return ""

    @property
    def failed(self) -> bool:
        if self.returncode != 0:
            return True
        return any(e.failed for e in self.events)


def run(
    assistant: Assistant,
    prompt: str,
    cwd: Path,
    *,
    env: dict | None = None,
) -> Iterator[Event]:
    """Run `assistant` in `cwd` and yield what it says as it says it.

    The child inherits the environment because it needs the user's
    credentials to do anything — this is the user's own assistant, run
    as the user, which is the whole point and also the reason the
    project root is checked before anything gets here.
    """
    command = assistant.command(prompt)
    process = subprocess.Popen(
        command,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        text=True,
        bufsize=1,
        env={**os.environ, **(env or {})},
    )
    try:
        assert process.stdout is not None
        for line in process.stdout:
            if assistant.output == "stream-json":
                event = parse(line)
                if event is None:
                    # Not JSON: a warning on stdout. Worth showing,
                    # never worth saying.
                    text = line.strip()
                    if text:
                        yield Event(CONSOLE, text[:200])
                    continue
                yield from classify(event)
            else:
                text = line.rstrip()
                if text:
                    yield Event(CONSOLE, text[:200])
    finally:
        process.stdout.close() if process.stdout else None
        process.wait(timeout=30)


def collect(
    assistant: Assistant, prompt: str, cwd: Path, *, env: dict | None = None
) -> Run:
    """Run to completion and keep everything. For `message/send`."""
    events = list(run(assistant, prompt, cwd, env=env))
    return Run(events=events, returncode=0)
