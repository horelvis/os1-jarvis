"""The kiosk WebSocket wire format.

This is NOT a new protocol. It is the one the OS1 frontend already speaks,
defined in `frontend/src/core/types.ts:37-45`, pinned here so that a change
on either side fails a test instead of the kiosk. Field names are part of
the contract: the frontend reads `msg.token`, `msg.thinking_ms`, `msg.error`.

Binary WebSocket frames arrive alongside these text ones: audio frames in
plan 3b, and video frames (H.264 packets) immediately — with the `live`,
`live_end`, and `live_frame` handlers. They do not change this format.
"""

from __future__ import annotations

import base64
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


def photo(path: str, camera: str) -> str:
    """A picture for the strip, and only for the strip.

    This frame exists because the photo must not travel in the model's
    answer: an answer goes wherever the turn goes, and `MEDIA:` would put
    a picture of the house on any platform that turn was routed to. See
    the snapshot spec §3.
    """
    return json.dumps({"type": "photo", "path": path, "camera": camera})


def error(message: str) -> str:
    """`message` is shown to the user, so it is Spanish and in her voice."""
    return json.dumps({"type": "error", "error": message})


# One access unit of H.264. A substream keyframe from these cameras is a
# few tens of KB; 4 MB is aiohttp's own default and generous enough that
# a real frame can never hit it. Bytes carry no path to validate, so this
# cap is what replaces `push_photo`'s spool check as the guard on a
# socket any process on this box can open.
MAX_LIVE_FRAME_BYTES = 4 * 1024 * 1024

# Why a view ended. There is deliberately no reason for "the gateway
# stopped": a process on its way down cannot promise to send anything, so
# the strip treats a socket that closes with a view open as a close in
# its own right (spec §4.2).
LIVE_REASONS = frozenset({"asked", "timeout", "lost"})


def live(camera: str, epoch: int, extradata: bytes, width: int, height: int) -> str:
    """Open a live view on the strip.

    `extradata` is the codec's parameter sets (SPS/PPS). It travels here
    because a decoder cannot start without them; sending packets alone is
    how a restream ends up as a black rectangle that reads as a bug in
    the drawing code. Empty is legal: many cameras send them in-band with
    every keyframe instead.
    """
    return json.dumps(
        {
            "type": "live",
            "camera": camera,
            "epoch": epoch,
            "codec": "h264",
            "extradata": base64.b64encode(extradata).decode("ascii"),
            "width": width,
            "height": height,
        }
    )


def live_end(epoch: int, reason: str) -> str:
    """Close a live view, and say why."""
    if reason not in LIVE_REASONS:
        raise ProtocolError(f"unknown live_end reason: {reason!r}")
    return json.dumps({"type": "live_end", "epoch": epoch, "reason": reason})


def live_frame(epoch: int, packet: bytes) -> bytes:
    """One access unit, stamped with the view it belongs to.

    The epoch exists because closing and the packets in flight race: you
    say "ya está", the gateway closes, and three frames of the previous
    view are still on the socket. Without a number to stamp them the
    strip paints them onto a band that has already shrunk.
    """
    if len(packet) > MAX_LIVE_FRAME_BYTES:
        raise ProtocolError(
            f"live frame is {len(packet)} bytes, over the {MAX_LIVE_FRAME_BYTES} cap"
        )
    return epoch.to_bytes(4, "big") + packet
