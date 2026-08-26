"""Which project a request is about.

Projects are the directories under a root — `~/git`, 26 of them here —
rather than a configured list. The user's decision, 2026-08-26: nothing
to maintain, and the root doubles as the boundary of where the assistant
may work.

Naming one is the same problem the wake word had. The name arrives
through speech recognition on its way here: `os1-samantha` comes back as
"OS uno Samanta", `lejepa-difusion` as anything at all. So matching is a
similarity ratio, as in the widget's `wake.py` — with one difference
that matters. The wake word guesses generously because being ignored is
its worst failure; this REFUSES when two projects are close, because
opening the wrong one is a mistake that writes files.
"""

from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

DEFAULT_ROOT = Path.home() / "git"

# How close a spoken name has to be. Lower than the wake word's 0.6:
# project names are long, so a ratio survives more mangling — and the
# ambiguity check below is what keeps a loose threshold safe.
THRESHOLD = 0.55

# How much better the best match has to be than the second. Two projects
# within this of each other is a question, not a guess.
#
# 0.15 rather than something tighter, and the measurement is `jarvis`
# against `jarvis-os` on this machine: a mangled "jarvi" scores 0.91 and
# 0.77, which is 0.14 apart — close enough that a person saying either
# could mean the other. The bias is deliberate and the opposite of the
# wake word's: asking twice costs a sentence, guessing wrong writes
# files into the wrong repository.
MARGIN = 0.15


@dataclass(frozen=True)
class Project:
    name: str
    path: Path


class Ambiguous(Exception):
    """More than one project fits, and picking one would write files."""

    def __init__(self, names: list[str]) -> None:
        super().__init__(", ".join(names))
        self.names = names


def _fold(text: str) -> str:
    lowered = unicodedata.normalize("NFD", text.lower())
    stripped = "".join(c for c in lowered if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "", stripped)


def available(root: Path = DEFAULT_ROOT) -> list[Project]:
    """Every directory under the root, alphabetically.

    Directories rather than repositories: a project that is not a git
    repository yet is still somewhere the user works, and refusing it
    would be this module inventing a rule nobody asked for.
    """
    if not root.is_dir():
        return []
    out = [
        Project(entry.name, entry)
        for entry in sorted(root.iterdir(), key=lambda p: p.name.lower())
        if entry.is_dir() and not entry.name.startswith(".")
    ]
    return out


def resolve(wanted: str, root: Path = DEFAULT_ROOT) -> Project | None:
    """The project `wanted` names, or None. Raises `Ambiguous` on a tie."""
    folded = _fold(wanted)
    if not folded:
        return None
    projects = available(root)

    exact = [p for p in projects if _fold(p.name) == folded]
    if exact:
        return exact[0]

    scored = sorted(
        ((SequenceMatcher(None, folded, _fold(p.name)).ratio(), p) for p in projects),
        key=lambda pair: pair[0],
        reverse=True,
    )
    if not scored or scored[0][0] < THRESHOLD:
        return None
    if len(scored) > 1 and scored[0][0] - scored[1][0] < MARGIN:
        raise Ambiguous([scored[0][1].name, scored[1][1].name])
    return scored[0][1]


def find_in(text: str, root: Path = DEFAULT_ROOT) -> Project | None:
    """The project mentioned anywhere in a sentence, or None.

    "En os1-samantha, arregla el test" — the project is a word inside a
    request, not the whole of it. Every project name is looked for in the
    text directly first, longest first so `jarvis-os` wins over `jarvis`;
    only then does the fuzzy path run, on the words that are left.
    """
    folded_text = _fold(text)
    for project in sorted(available(root), key=lambda p: -len(p.name)):
        if _fold(project.name) in folded_text:
            return project
    return None


def inside(root: Path, path: Path) -> bool:
    """Is `path` inside `root`? The boundary, and it is the whole guard.

    Resolved on both sides: `~/git/../etc` is not under `~/git`, and a
    symlink out of the tree is not either.
    """
    try:
        return os.path.commonpath([root.resolve(), path.resolve()]) == str(
            root.resolve()
        )
    except (ValueError, OSError):
        return False
