"""Following what the assistant is writing, and putting it on the strip.

The wrapper (`Hermes/bin/claude`) tees a non-interactive run into a
file. This follows that file the way `tail -f` does and pushes each line
into the strip's terminal, so the work is visible while it happens
instead of arriving in one lump when `terminal` returns.

Why a file and not a pipe between two processes: the assistant is
started by Hermes' own `terminal` tool, which owns the child and hands
back its output at the end. There is no seam to hook into — so the
wrapper writes, this reads, and neither has to know the other is there.
A run with nobody watching just writes a file.

The markers are the whole protocol. `\\x1eSTART` clears the console and
opens it; `\\x1eEND` closes the run. `\\x1e` is the ASCII record
separator: no assistant prints one, so a line of its output can never be
mistaken for a marker.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Iterator
from pathlib import Path

DEFAULT_LIVE = Path.home() / ".samantha" / "code-live.log"

START = "\x1eSTART"
END = "\x1eEND"

# How often the file is checked when it has nothing new. Twenty times a
# second is imperceptible on the strip and costs one `read` on an empty
# file — this thread is asleep the rest of the day.
POLL_SECONDS = 0.05

# Lines longer than this are cut. A single tool result can be a whole
# file, and the console holds ten lines: one of them being 4,000
# characters wide is not something anybody glances at.
MAX_CHARS = 200


def follow(path: Path, stop: Callable[[], bool]) -> Iterator[tuple[str, str]]:
    """Yield `(kind, text)` for every line appended to `path`.

    `kind` is "start", "end" or "line". Starts at the END of the file:
    what happened before anybody was watching is not this session's, and
    replaying it on the strip would show the last run's work as if it
    were happening now.
    """
    handle = None
    inode = None
    # Only skip the past if there IS one. A file that already existed
    # holds the previous run's work and replaying it would show old
    # output as if it were happening now; a file that appears while we
    # are watching is this run's, from its first line.
    existed = path.exists()
    while not stop():
        try:
            if handle is None:
                if not path.exists():
                    time.sleep(POLL_SECONDS)
                    continue
                handle = path.open("r", encoding="utf-8", errors="replace")
                if existed:
                    handle.seek(0, os.SEEK_END)
                    existed = False
                inode = path.stat().st_ino

            line = handle.readline()
            if not line:
                # Rotated or truncated? Reopen rather than follow a file
                # nobody is writing to any more.
                try:
                    if path.stat().st_ino != inode or path.stat().st_size < handle.tell():
                        handle.close()
                        handle = None
                        continue
                except OSError:
                    handle.close()
                    handle = None
                    continue
                time.sleep(POLL_SECONDS)
                continue

            text = line.rstrip("\n")
            if text.startswith(START):
                yield "start", text[len(START) :].strip()
            elif text.startswith(END):
                yield "end", text[len(END) :].strip()
            elif text.strip():
                yield "line", text[:MAX_CHARS]
        except Exception:
            if handle is not None:
                handle.close()
            handle = None
            time.sleep(POLL_SECONDS)
    if handle is not None:
        handle.close()


def summarise(line: str) -> str:
    """One console line out of one line of assistant output.

    When the skill asks for `--output-format stream-json` the wrapper
    tees one JSON object per line, and a raw object is unreadable at a
    glance. Plain text passes through untouched, which is what the
    skills' default produces.

    Deliberately NOT importing `bridges/code-a2a/stream.py`, which
    classifies the same events more thoroughly: that is a separate
    program with its own path, and reaching into it from inside the
    gateway would couple two things that are meant to be swappable.
    What is needed here is one short line, not a classification.
    """
    stripped = line.strip()
    if not stripped.startswith("{"):
        return line
    try:
        event = json.loads(stripped)
    except ValueError:
        return line
    if not isinstance(event, dict):
        return line

    kind = event.get("type")
    if kind == "assistant":
        for block in event.get("message", {}).get("content", []) or []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text" and block.get("text", "").strip():
                return str(block["text"]).strip()[:MAX_CHARS]
            if block.get("type") == "tool_use":
                args = block.get("input") or {}
                detail = ""
                if isinstance(args, dict):
                    for key in ("command", "file_path", "pattern", "skill"):
                        if args.get(key):
                            detail = str(args[key])
                            break
                name = block.get("name", "?")
                return (f"· {name}: {detail}" if detail else f"· {name}")[:MAX_CHARS]
        return ""
    if kind == "result":
        # A CLOSING LINE, not the text. The assistant's final `result`
        # repeats the last message it already sent, so printing both put
        # the same summary on the strip twice (seen 2026-08-26). The
        # bridge's own classifier does the same thing for the same
        # reason — the two are deliberately not shared (see the note
        # above), so the rule is written in both.
        failed = bool(event.get("is_error")) or event.get("subtype") != "success"
        return "— terminado con errores" if failed else "— terminado"
    return ""
