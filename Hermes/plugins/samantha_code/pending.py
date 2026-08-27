"""Which task waits for the user, and for what kind of answer.

Thread-safe because three threads meet here: the firehose follower sets
it, the adapter's loop reads it, and the answer thread clears it.

One slot, not a queue. The bridge is single-task and asks one question
at a time, so a second question can only mean the first was answered or
abandoned — and a queue of stale questions is the same failure mode
`alert.py` refuses for sightings: the user is asked about something that
stopped mattering minutes ago.
"""

from __future__ import annotations

import threading


class Pending:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._value: tuple[str, str] | None = None

    def set(self, task_id: str, kind: str) -> None:
        with self._lock:
            self._value = (task_id, kind)

    def clear(self) -> None:
        with self._lock:
            self._value = None

    def get(self) -> tuple[str, str] | None:
        with self._lock:
            return self._value
