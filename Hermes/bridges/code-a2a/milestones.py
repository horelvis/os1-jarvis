"""The assistant's stream as milestones — what a glance is worth.

The spec's table made executable. One "read" per reading phase, one
"edit" per file, tests recognised and their outcome reported, everything
else a short verb — and never the same milestone twice in a row. This is
mechanical on purpose: an LLM call per event would cost VRAM and
latency, and the voice is reserved for judgement (spec, 2026-08-27).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath

READ_TOOLS = frozenset({"Read", "Grep", "Glob"})
EDIT_TOOLS = frozenset({"Edit", "Write", "MultiEdit", "NotebookEdit"})

# "12 passed", "2 failed" — pytest's summary vocabulary, first hit wins.
_OUTCOME = re.compile(r"\d+\s+(?:passed|failed|errors?)")

MAX_NOTE = 160


@dataclass(frozen=True)
class Milestone:
    kind: str
    detail: str = ""


def plain(m: Milestone) -> str:
    """The milestone as one Spanish line, for the tee'd file and the
    artifact. The plugin renders its own copy of this wording — the two
    processes are deliberately not coupled, the same way `summarise()`
    and the bridge's classifier are written twice (live.py has the note).
    """
    if m.kind == "read":
        return "Leyendo el proyecto…"
    if m.kind == "edit":
        return f"Editando {m.detail}"
    if m.kind == "tests":
        return "Pasando los tests…"
    if m.kind == "tests_out":
        return f"Tests: {m.detail}"
    if m.kind == "run":
        return f"Ejecutando: {m.detail}"
    return m.detail


class Milestones:
    """Stateful: the dedup rules ARE the product decision."""

    def __init__(self) -> None:
        self._reading = False
        self._edited: set[str] = set()
        self._last: Milestone | None = None
        self._awaiting_tests = False

    def _emit(self, m: Milestone) -> Milestone | None:
        if m == self._last:
            return None
        self._last = m
        return m

    def feed(self, tool: str, args: dict) -> Milestone | None:
        """One tool call in; at most one milestone out."""
        args = args if isinstance(args, dict) else {}
        if tool in READ_TOOLS:
            if self._reading:
                return None
            self._reading = True
            return self._emit(Milestone("read"))
        self._reading = False

        if tool in EDIT_TOOLS:
            self._awaiting_tests = False
            name = PurePosixPath(str(args.get("file_path") or "?")).name
            if name in self._edited:
                return None
            self._edited.add(name)
            return self._emit(Milestone("edit", name))

        if tool == "Bash":
            command = str(args.get("command") or "")
            if "pytest" in command or "test" in command.split():
                self._awaiting_tests = True
                return self._emit(Milestone("tests"))
            self._awaiting_tests = False
            first = command.strip().split()
            return self._emit(Milestone("run", first[0] if first else "?"))

        return None

    def note(self, text: str) -> Milestone | None:
        """The assistant thinking out loud: its first sentence, once."""
        first = text.strip().splitlines()[0] if text.strip() else ""
        sentence = first.split(". ")[0].strip()
        if sentence and not sentence.endswith((".", "…", "?", "!")):
            sentence += "."
        if not sentence:
            return None
        return self._emit(Milestone("note", sentence[:MAX_NOTE]))

    def result(self, text: str) -> Milestone | None:
        """A tool result: only a test run's outcome is worth a line."""
        if not self._awaiting_tests:
            return None
        self._awaiting_tests = False
        found = _OUTCOME.findall(str(text or ""))
        if not found:
            return None
        return self._emit(Milestone("tests_out", ", ".join(found[:2])))
