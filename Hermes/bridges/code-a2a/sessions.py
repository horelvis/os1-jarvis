"""Which conversation belongs to which project, and where that is kept.

The assistant hands back a `session_id` when a run ends. Give it back on
the next run and the conversation continues instead of starting over, so
*"seguimos con lo de esta mañana"* costs nothing to say and nothing to
re-explain.

Keyed by project PATH, not by name: two checkouts of the same repository
are two conversations, and the path is what the run actually happened
in. Names are what the user says; paths are what is true.

Pure state and one file. No SDK import here — the store has to be
testable on a box where the assistant is not installed, and it is the
part most likely to be wrong in a way nobody notices until a morning's
context is gone.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

DEFAULT_STORE = Path.home() / ".samantha" / "code-sessions.json"

# A conversation nobody has continued in this long is not continued: it
# is resumed into a context about something else entirely. Two days
# keeps yesterday's work reachable and lets last month's go.
MAX_AGE_SECONDS = float(os.environ.get("SAMANTHA_CODE_SESSION_MAX_AGE", "172800"))


class Sessions:
    """Project path → the assistant's session id for it."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else DEFAULT_STORE
        self._entries: dict[str, dict] = {}
        self._loaded = False

    # ── the file ──────────────────────────────────────────────────────

    def load(self) -> None:
        """Read the store. A store that cannot be read is an empty one.

        Deliberately forgiving: the cost of a corrupt file is one
        conversation starting fresh, and the cost of raising here is a
        bridge that will not answer at all.
        """
        self._loaded = True
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self._entries = {}
            return
        self._entries = raw if isinstance(raw, dict) else {}

    def save(self) -> None:
        """Write the store, atomically. Never raises.

        Atomically because the bridge can be answering two projects at
        once, and a half-written file reads as no sessions at all — the
        failure would be silent and would look like the assistant simply
        forgetting.
        """
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self._entries, fh, indent=1, sort_keys=True)
            os.replace(tmp, self.path)
        except OSError:
            pass

    # ── what it is for ────────────────────────────────────────────────

    def get(self, project: str | Path, now: float) -> str | None:
        """The session to resume for this project, or None to start fresh."""
        if not self._loaded:
            self.load()
        entry = self._entries.get(str(project))
        if not isinstance(entry, dict):
            return None
        session = entry.get("session_id")
        seen = entry.get("seen_at")
        if not isinstance(session, str) or not session:
            return None
        if not isinstance(seen, (int, float)):
            return None
        if now - seen > MAX_AGE_SECONDS:
            return None
        return session

    def remember(self, project: str | Path, session_id: str, now: float) -> None:
        """Keep this session as the one to continue for this project."""
        if not session_id:
            return
        if not self._loaded:
            self.load()
        self._entries[str(project)] = {"session_id": session_id, "seen_at": now}
        self.save()

    def forget(self, project: str | Path) -> None:
        """Start the next run in this project from nothing.

        The way out of a conversation that has gone wrong — a resumed
        session carrying a bad assumption is worse than no session,
        because it is invisible from the outside.
        """
        if not self._loaded:
            self.load()
        if self._entries.pop(str(project), None) is not None:
            self.save()
