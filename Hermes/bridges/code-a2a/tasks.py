"""A2A tasks, as pure state. No sockets, no subprocesses.

The protocol's shape, and only that: a task has an id, a state, a
history and artifacts, and it moves between states in one direction.
`server.py` owns the HTTP and `runner.py` owns the child process; this
owns what they are both talking about, so both can be tested without the
other.

States are the v1.0 spelling (`TASK_STATE_WORKING`, …). The four
terminal ones end a stream: the specification says the stream "MUST
close when the task reaches a terminal state", so `terminal` here is
what closes it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

SUBMITTED = "TASK_STATE_SUBMITTED"
WORKING = "TASK_STATE_WORKING"
INPUT_REQUIRED = "TASK_STATE_INPUT_REQUIRED"
COMPLETED = "TASK_STATE_COMPLETED"
FAILED = "TASK_STATE_FAILED"
CANCELED = "TASK_STATE_CANCELED"

TERMINAL = frozenset({COMPLETED, FAILED, CANCELED})

ROLE_AGENT = "ROLE_AGENT"
ROLE_USER = "ROLE_USER"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return str(uuid.uuid4())


def message(text: str, *, role: str = ROLE_AGENT, context_id: str = "") -> dict:
    """One A2A Message carrying a line of text."""
    out: dict = {
        "messageId": new_id(),
        "role": role,
        "parts": [{"kind": "text", "text": text}],
    }
    if context_id:
        out["contextId"] = context_id
    return out


@dataclass
class Task:
    """One unit of work, and everything a client can ask about it."""

    id: str = field(default_factory=new_id)
    context_id: str = ""
    state: str = SUBMITTED
    history: list[dict] = field(default_factory=list)
    artifacts: list[dict] = field(default_factory=list)
    last_message: dict | None = None

    @property
    def terminal(self) -> bool:
        return self.state in TERMINAL

    def advance(self, state: str, text: str = "") -> dict:
        """Move to `state`, optionally saying why. Returns the status."""
        self.state = state
        status: dict = {"state": state, "timestamp": now()}
        if text:
            self.last_message = message(text, context_id=self.context_id)
            status["message"] = self.last_message
            self.history.append(self.last_message)
        return status

    def as_dict(self) -> dict:
        out: dict = {
            "id": self.id,
            "status": {"state": self.state, "timestamp": now()},
            "history": self.history,
            "artifacts": self.artifacts,
        }
        if self.context_id:
            out["contextId"] = self.context_id
        if self.last_message is not None:
            out["status"]["message"] = self.last_message
        return out


def text_of(msg: dict) -> str:
    """The text a client sent, out of whatever shape it sent it in.

    Clients differ on `kind` versus `type` for a part, and a bridge that
    reads one and not the other rejects half the callers for no reason.
    """
    parts = msg.get("parts") or []
    chunks: list[str] = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        if part.get("kind") in ("text", None) or part.get("type") == "text":
            text = part.get("text")
            if text:
                chunks.append(str(text))
    return "\n".join(chunks).strip()
