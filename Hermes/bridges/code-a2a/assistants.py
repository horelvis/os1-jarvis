"""The coding assistants this bridge can drive, and how to drive them.

One entry per assistant, and adding one is adding an entry — which is
the whole reason this bridge exists rather than a plugin that shells out
to `claude` directly. The user asked for A2A "por el futuro uso de
opencode" (2026-08-26): OpenCode gets a line here and JARVIS never
learns it happened.

What an entry has to answer:

- **the command**, given a prompt and a working directory;
- **how its output is read** — a stream of JSON objects, one per line,
  or plain text.

Claude Code's shape was recorded from a real run rather than read off a
manual: `stream.py` carries what those events look like and the fixture
beside it carries 38 of them.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Assistant:
    """One coding assistant, as a command and a way of reading it."""

    name: str
    binary: str
    # Built by `command()`. `{prompt}` is substituted; everything else is
    # passed through untouched.
    args: list[str] = field(default_factory=list)
    # "stream-json" — one JSON object per line, read by `stream.py`.
    # "text" — whatever it prints, shown as it comes.
    output: str = "stream-json"

    @property
    def available(self) -> bool:
        return shutil.which(self.binary) is not None

    def command(self, prompt: str) -> list[str]:
        return [self.binary] + [a.replace("{prompt}", prompt) for a in self.args]


# `--dangerously-skip-permissions` is the user's decision of 2026-08-26,
# taken with the risk stated: full scope, including pushing. It is not a
# default anybody drifted into — and the recording proves the
# alternative does not work unattended, since `acceptEdits` refused two
# commands and the edit itself, leaving the assistant describing a fix
# it could not apply.
CLAUDE = Assistant(
    name="claude",
    binary="claude",
    args=[
        "-p",
        "{prompt}",
        "--output-format",
        "stream-json",
        "--verbose",
        "--dangerously-skip-permissions",
    ],
)

# Not verified against a running OpenCode — it is not installed here.
# Written from its documented `run` subcommand so the shape is in place;
# whoever installs it should check the flags before trusting this line.
OPENCODE = Assistant(
    name="opencode",
    binary="opencode",
    args=["run", "{prompt}"],
    output="text",
)

ASSISTANTS = {a.name: a for a in (CLAUDE, OPENCODE)}


def pick(name: str = "") -> Assistant:
    """The named assistant, or the first one actually installed.

    Falling back rather than failing: a bridge that refuses to start
    because the machine has OpenCode instead of Claude Code is a bridge
    that has to be reconfigured for no reason.
    """
    if name:
        chosen = ASSISTANTS.get(name)
        if chosen is None:
            raise KeyError(f"no assistant called {name!r}")
        return chosen
    for candidate in ASSISTANTS.values():
        if candidate.available:
            return candidate
    return CLAUDE
