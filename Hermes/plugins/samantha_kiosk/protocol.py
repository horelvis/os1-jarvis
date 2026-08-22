"""The kiosk WebSocket wire format.

This is NOT a new protocol. It is the one the OS1 frontend already speaks,
defined in `frontend/src/core/types.ts:37-45`, pinned here so that a change
on either side fails a test instead of the kiosk. Field names are part of
the contract: the frontend reads `msg.token`, `msg.thinking_ms`, `msg.error`.

Audio frames are not here. They arrive in plan 3b as binary WebSocket
frames alongside these text ones, and do not change this format.
"""

from __future__ import annotations

import json
from typing import Any, Dict

_CLIENT_TYPES = {"chat", "listen"}

# Nothing a person says out loud, or types on a screen with no keyboard in
# front of it, comes near this. The cap exists because the socket is an
# unauthenticated local listener (any process on the box can open it) and
# whatever arrives goes straight into a metered LLM — aiohttp's own default
# would accept 4 MB per frame. Generous enough that a real turn can never
# hit it, small enough that a runaway one cannot cost anything.
_MAX_MESSAGE_CHARS = 4000


class ProtocolError(ValueError):
    """Raised for anything the kiosk should not have sent."""


def decode_client(raw: str) -> Dict[str, Any]:
    """Parse and validate one client message. Raises ProtocolError."""
    try:
        msg = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise ProtocolError(f"not JSON: {exc}") from exc

    if not isinstance(msg, dict):
        raise ProtocolError(f"expected an object, got {type(msg).__name__}")

    kind = msg.get("type")
    if kind not in _CLIENT_TYPES:
        raise ProtocolError(f"unknown type: {kind!r}")

    if kind == "chat":
        message = msg.get("message")
        if not isinstance(message, str) or not message.strip():
            # An empty turn would reach the model as an empty prompt.
            raise ProtocolError("chat needs a non-blank message")
        if len(message) > _MAX_MESSAGE_CHARS:
            raise ProtocolError(
                f"chat message is {len(message)} chars, over the "
                f"{_MAX_MESSAGE_CHARS} cap"
            )

        user_id = msg.get("user_id")
        if not isinstance(user_id, str) or not user_id.strip():
            # user_id flows into Hermes' build_source(), so validation is critical.
            raise ProtocolError("chat needs a non-blank user_id")

    return msg


def token(text: str) -> str:
    return json.dumps({"type": "token", "token": text})


def done(thinking_ms: int) -> str:
    return json.dumps({"type": "done", "thinking_ms": thinking_ms})


def error(message: str) -> str:
    """`message` is shown to the user, so it is Spanish and in her voice."""
    return json.dumps({"type": "error", "error": message})
