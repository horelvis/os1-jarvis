"""Short-term memory: SQLite ring buffer for the last N conversation turns.

Stored at `state.db` inside the memory persist dir. Each entry has a
role ("user" | "samantha"), text, timestamp, user_id, and a UUID id.
When capacity is exceeded for a given user_id, the oldest entry is
deleted — but its content is preserved in long-term memory (see
`Memory.remember`) so nothing is truly forgotten.
"""

from __future__ import annotations

import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from loguru import logger


_VALID_ROLES = {"user", "samantha"}


@dataclass(frozen=True)
class ShortTermEntry:
    id: str
    role: str
    text: str
    timestamp: int
    user_id: str


class ShortTermBuffer:
    def __init__(self, db_path: str | Path, *, capacity: int = 20) -> None:
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.capacity = capacity
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS short_term ("
            "  id TEXT PRIMARY KEY,"
            "  role TEXT NOT NULL,"
            "  text TEXT NOT NULL,"
            "  timestamp INTEGER NOT NULL,"
            "  user_id TEXT NOT NULL"
            ")"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_short_term_user_ts "
            "ON short_term(user_id, timestamp)"
        )
        self._conn.commit()
        logger.info(
            f"short_term: opened {self.path} (capacity={capacity})"
        )

    def append(
        self, role: str, text: str, *, user_id: str = "primary"
    ) -> str:
        return self.append_with_id(
            str(uuid.uuid4()), role, text, user_id=user_id
        )

    def append_with_id(
        self, entry_id: str, role: str, text: str, *, user_id: str = "primary"
    ) -> str:
        """Append an entry with a caller-supplied id (e.g., the chroma chunk id).

        Useful when the short-term ring and a long-term store share ids so
        the long-term recall can dedupe against the short-term buffer
        without a join.
        """
        if role not in _VALID_ROLES:
            raise ValueError(f"role must be in {_VALID_ROLES}, got {role!r}")
        if not text or not text.strip():
            return ""
        ts = int(time.time())
        with self._conn:
            self._conn.execute(
                "INSERT INTO short_term (id, role, text, timestamp, user_id) "
                "VALUES (?, ?, ?, ?, ?)",
                (entry_id, role, text.strip(), ts, user_id),
            )
            self._conn.execute(
                "DELETE FROM short_term WHERE id IN ("
                "  SELECT id FROM short_term WHERE user_id = ? "
                "  ORDER BY rowid ASC "
                "  LIMIT MAX(0, ("
                "    SELECT COUNT(*) FROM short_term WHERE user_id = ?"
                "  ) - ?)"
                ")",
                (user_id, user_id, self.capacity),
            )
        return entry_id

    def list(self, *, user_id: str = "primary") -> list[ShortTermEntry]:
        cur = self._conn.execute(
            "SELECT id, role, text, timestamp, user_id "
            "FROM short_term WHERE user_id = ? "
            "ORDER BY rowid ASC",
            (user_id,),
        )
        return [
            ShortTermEntry(id=row[0], role=row[1], text=row[2],
                           timestamp=row[3], user_id=row[4])
            for row in cur.fetchall()
        ]

    def ids(self, *, user_id: str = "primary") -> set[str]:
        cur = self._conn.execute(
            "SELECT id FROM short_term WHERE user_id = ?", (user_id,)
        )
        return {row[0] for row in cur.fetchall()}

    def clear(self, *, user_id: str = "primary") -> int:
        with self._conn:
            cur = self._conn.execute(
                "DELETE FROM short_term WHERE user_id = ?", (user_id,)
            )
            return cur.rowcount

    def close(self) -> None:
        self._conn.close()
