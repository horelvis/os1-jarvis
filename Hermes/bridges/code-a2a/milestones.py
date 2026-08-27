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


# ── Raw, the way Claude Code shows it ────────────────────────────────
#
# The user, 2026-08-27: «deja de filtrar». The table above is still what
# `plain()` renders for the artifact and the tee'd file, and `feed()` is
# still the vocabulary the v1 path speaks — but the CONSOLE stops being
# a summary of the work and goes back to being the work. VS Code does
# not classify what its terminal shows, and neither should a strip whose
# whole job is that you can glance at it and see what is happening.
#
# What does NOT change: the three moments that reach the voice. Those
# come from `gates.py` and the `PreToolUse` hook, never from here, so
# showing everything costs the voice nothing.

# **The two glyphs are measured, not chosen.** The console draws in the
# desktop's own monospace font — `Ubuntu Sans Mono` on this box, read
# from `org.gnome.desktop.interface monospace-font-name`. Claude Code's
# own `⏺` (U+23FA) and `⎿` (U+23BF) are in NEITHER it nor DejaVu Sans
# Mono: `fc-list :charset=23fa` finds two fonts on this machine and
# neither is monospaced. A glyph the font lacks is substituted from
# some other font at some other width, which is why the first capture
# came back with a `⌊` where the corner should be and a bullet that did
# not line up. `•` (U+2022) and `└` (U+2514) are both in Ubuntu Sans
# Mono, measured the same way. If the console font ever changes, this
# is the check to re-run.
BULLET = "•"
CORNER = "└"

# One line of a console 900 px wide. Past this it wraps into the next
# line of twenty and the glance is gone.
MAX_LINE = 96

# Which argument of a tool call is the one worth seeing. Ordered: the
# first that is present wins.
_SALIENT = ("command", "file_path", "pattern", "path", "url", "prompt")

# Markdown the assistant writes and a plain-text console cannot draw.
# Bold and headings are stripped; BACKTICKS ARE KEPT, deliberately —
# they are the only thing left marking a fragment as code, and they
# read fine as characters. Stripping them would make
# `ImportError: cannot import name 'multiplica'` indistinguishable from
# prose.
_BOLD = re.compile(r"\*\*(.+?)\*\*|__(.+?)__")
_HEADING = re.compile(r"^#{1,6}\s+")


def _plain_text(text: str) -> str:
    """Markdown down to what a console can actually draw."""
    out = _HEADING.sub("", str(text).lstrip())
    return _BOLD.sub(lambda m: m.group(1) or m.group(2) or "", out)


def _cut(text: str, width: int = MAX_LINE) -> str:
    """One line, whitespace collapsed, truncated. Carries no prefix —
    the caller adds that afterwards, or the indent that puts a result
    under the call it belongs to is collapsed away with everything else.
    """
    text = " ".join(str(text).split())
    return text if len(text) <= width else text[: width - 1] + "…"


def _first_line(text: str) -> tuple[str, int]:
    """The first line, and how many were left behind."""
    lines = str(text or "").strip().splitlines()
    return (lines[0] if lines else ""), max(0, len(lines) - 1)


def _hidden(rest: int) -> str:
    return f" (+{rest} líneas)" if rest > 0 else ""


def tool_line(tool: str, args: dict) -> str:
    """`• Bash(pytest -q)` — the call, the way the assistant's own UI shows it.

    A multi-line argument keeps its FIRST line and says how many it hid.
    A heredoc otherwise arrives as one unreadable ninety-character run
    of collapsed newlines, which is what the first capture showed.
    """
    args = args if isinstance(args, dict) else {}
    head = f"{BULLET} {tool}"
    for key in _SALIENT:
        value = args.get(key)
        if not value:
            continue
        if key == "file_path":
            shown, rest = PurePosixPath(str(value)).name, 0
        else:
            shown, rest = _first_line(value)
        room = MAX_LINE - len(head) - len(_hidden(rest)) - 3
        return f"{head}({_cut(shown, max(room, 8))}{_hidden(rest)})"
    return head


def text_line(text: str) -> str:
    """What the assistant said, not its first sentence."""
    said = _cut(_plain_text(text), MAX_LINE - len(BULLET) - 1)
    return f"{BULLET} {said}" if said else ""


def result_line(text: str) -> str:
    """What came back, one line, indented under the call it belongs to."""
    first, rest = _first_line(text)
    if not first.strip():
        return ""
    prefix = f"  {CORNER} "
    shown = _cut(_plain_text(first), MAX_LINE - len(prefix) - len(_hidden(rest)))
    return f"{prefix}{shown}{_hidden(rest)}"
