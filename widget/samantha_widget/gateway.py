"""The client half of the kiosk WebSocket.

The server half is Hermes/plugins/samantha_kiosk/adapter.py, and the
frame format is pinned in its protocol.py — `chat` up, `token` /
`done` / `error` down. Nothing here invents a protocol; the whole point
of talking to the existing adapter is that there is nothing to invent.

Two details that are not obvious and are load-bearing:

- No `Origin` header. The adapter refuses a browser Origin that does
  not match its own port, and explicitly allows a client that sends
  none — "a future native shell", says the comment. That is us.
- `user_id` must be "primary". The adapter's allowlist defaults to
  exactly that id, and an unauthorized turn is dropped with a log line
  and NOTHING on the screen.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Callable

import websockets

DEFAULT_URI = "ws://127.0.0.1:7777/ws"
DEFAULT_USER_ID = "primary"

_SERVER_TYPES = {"token", "done", "error", "transcription"}

# Said out loud when the gateway is unreachable. Silence would leave the
# user talking to a wall — one of the few Spanish strings in this package.
_NO_GATEWAY = "No te oigo bien ahora mismo. Dame un momento."


class ProtocolError(ValueError):
    """Raised for anything the gateway should not have sent."""


def encode_chat(text: str, user_id: str = DEFAULT_USER_ID) -> str:
    return json.dumps({"type": "chat", "message": text, "user_id": user_id})


def decode_server(raw: str) -> dict[str, Any]:
    try:
        msg = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise ProtocolError(f"not JSON: {exc}") from exc
    if not isinstance(msg, dict):
        raise ProtocolError(f"expected an object, got {type(msg).__name__}")
    if msg.get("type") not in _SERVER_TYPES:
        raise ProtocolError(f"unknown type: {msg.get('type')!r}")
    return msg


class GatewayClient:
    def __init__(self, uri: str = DEFAULT_URI, user_id: str = DEFAULT_USER_ID) -> None:
        self.uri = uri
        self.user_id = user_id
        self.retry_seconds = 2.0
        self.on_token: Callable[[str], None] = lambda _t: None
        self.on_done: Callable[[int], None] = lambda _ms: None
        self.on_error: Callable[[str], None] = lambda _m: None
        self._ws: Any = None
        self._connected = asyncio.Event()

    async def wait_connected(self, timeout: float = 10.0) -> None:
        await asyncio.wait_for(self._connected.wait(), timeout=timeout)

    async def send_chat(self, text: str) -> None:
        if self._ws is None:
            self.on_error(_NO_GATEWAY)
            return
        await self._ws.send(encode_chat(text, self.user_id))

    async def run(self) -> None:
        """Connect, read, and reconnect forever. Cancel to stop."""
        while True:
            try:
                async with websockets.connect(self.uri) as ws:
                    self._ws = ws
                    self._connected.set()
                    async for raw in ws:
                        self._dispatch(raw)
            except asyncio.CancelledError:
                raise
            except Exception:
                # Every failure mode here — gateway down, gateway
                # restarting, socket dropped mid-turn — has the same
                # answer: wait and try again. A strip that gives up is
                # a strip that has to be restarted by hand.
                pass
            finally:
                self._ws = None
                self._connected.clear()
            await asyncio.sleep(self.retry_seconds)

    def _dispatch(self, raw: str) -> None:
        try:
            msg = decode_server(raw)
        except ProtocolError:
            return
        kind = msg["type"]
        if kind == "token":
            self.on_token(msg.get("token", ""))
        elif kind == "done":
            self.on_done(int(msg.get("thinking_ms", 0)))
        elif kind == "error":
            self.on_error(msg.get("error", ""))
