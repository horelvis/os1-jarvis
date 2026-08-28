"""The client half of the jarvis WebSocket.

The server half is Hermes/plugins/jarvis/adapter.py, and the
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
import base64
import json
from typing import Any, Callable

import websockets
from loguru import logger

DEFAULT_URI = "ws://127.0.0.1:7777/ws"
DEFAULT_USER_ID = "primary"

_SERVER_TYPES = {
    "token",
    "done",
    "error",
    "transcription",
    "photo",
    "live",
    "live_end",
    "console",
    "asking",
}

# Said out loud when the gateway is unreachable. Silence would leave the
# user talking to a wall — one of the few Spanish strings in this package.
_NO_GATEWAY = "No te oigo bien ahora mismo. Dame un momento."


class ProtocolError(ValueError):
    """Raised for anything the gateway should not have sent."""


def decode_live_frame(raw: bytes) -> tuple[int, bytes]:
    """Split one binary frame into (epoch, packet). Raises ProtocolError."""
    if len(raw) < 4:
        raise ProtocolError(f"live frame is {len(raw)} bytes, needs at least 4")
    return int.from_bytes(raw[:4], "big"), bytes(raw[4:])


def encode_chat(
    text: str, user_id: str = DEFAULT_USER_ID, *, wake: bool = False
) -> str:
    frame: dict[str, Any] = {"type": "chat", "message": text, "user_id": user_id}
    if wake:
        # Addressed by name: the gateway must never divert this one to
        # the code assistant, whatever gate or question is pending.
        frame["wake"] = True
    return json.dumps(frame)


def decode_server(raw: str) -> dict[str, Any]:
    try:
        msg = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise ProtocolError(f"not JSON: {exc}") from exc
    if not isinstance(msg, dict):
        raise ProtocolError(f"expected an object, got {type(msg).__name__}")
    # A type we do not know is not an error. The gateway is versioned
    # separately from the strip and will ship frames this build has never
    # heard of (see _SERVER_TYPES); refusing them turned one unknown frame
    # into a dead turn. `_dispatch` handles what it recognises and drops
    # the rest.
    return msg


# What `websockets.connect` is asked for, and it is one keyword against
# a defect measured on the live machine on 2026-08-27.
#
# **`permessage-deflate` must be off.** With it negotiated, aiohttp —
# which is what the jarvis adapter is — refuses the FIRST compressed data
# frame of a connection when a control frame reached it first, and
# answers `CLOSE 1002 (protocol error)`. `websockets` sends a keepalive
# ping every 20 s by default, so any connection idle for 20 seconds has
# had its control frame: the next thing the user says is destroyed on
# the wire, the socket dies with it, and the strip reconnects into
# exactly the same state. Not a race — deterministic, and the strip is
# idle between turns by its nature.
#
# What it cost before it was found: the owner watched JARVIS not answer
# three times in nine minutes, and the only evidence on the box was an
# aiohttp access line closing the socket at the second of the send.
# Reproduced in milliseconds against a plain aiohttp server with no
# Hermes in it: ping-then-text fails with deflate at gaps of 0 s, 50 ms
# and 500 ms, passes with `compression=None`, and passes with deflate
# when a data frame went first. See `tests/test_gateway_deflate.py`.
#
# Nothing is lost by turning it off: these are small JSON frames over
# loopback. The keepalive stays — the ping is not what is broken.
CONNECT_OPTIONS: dict[str, Any] = {"compression": None}


class GatewayClient:
    def __init__(self, uri: str = DEFAULT_URI, user_id: str = DEFAULT_USER_ID) -> None:
        self.uri = uri
        self.user_id = user_id
        self.retry_seconds = 2.0
        # Per instance so a test can force the keepalive to fire in
        # milliseconds instead of the default twenty seconds.
        self.connect_options: dict[str, Any] = dict(CONNECT_OPTIONS)
        self.on_token: Callable[[str], None] = lambda _t: None
        self.on_done: Callable[[int], None] = lambda _ms: None
        self.on_error: Callable[[str], None] = lambda _m: None
        # A picture for the band above the wave. It is a frame of its
        # own and never a token: an answer travels wherever the turn is
        # routed, and a path in one would be read aloud.
        self.on_photo: Callable[[str, str], None] = lambda _p, _c: None
        # A live view: opened, fed packets, and closed. The picture never
        # travels as a token either — see on_photo above for why.
        self.on_live_open: Callable[[str, int, bytes, int, int], None] = (
            lambda _c, _e, _x, _w, _h: None
        )
        self.on_live_frame: Callable[[int, bytes], None] = lambda _e, _p: None
        self.on_live_end: Callable[[int, str], None] = lambda _e, _r: None
        # Lines for the strip's terminal. Not tokens: what a coding
        # assistant writes is shown, never spoken.
        self.on_console: Callable[[str], None] = lambda _t: None
        # The work is over: the console can put itself away. Separate
        # from `on_console` because an empty frame carries it — there is
        # nothing left to write, only the fact that there will not be.
        self.on_console_done: Callable[[], None] = lambda: None
        # A new run starts: empty it first, so its first line is at the
        # top of an empty box rather than under the last run's.
        self.on_console_reset: Callable[[], None] = lambda: None
        # Whether the code assistant is waiting for the user's answer.
        # Not part of a turn and not shown: it only decides whether an
        # unnamed sentence is still worth sending on. See `wake.hold`.
        self.on_asking: Callable[[bool], None] = lambda _open: None
        self._ws: Any = None
        self._connected = asyncio.Event()

    async def wait_connected(self, timeout: float = 10.0) -> None:
        await asyncio.wait_for(self._connected.wait(), timeout=timeout)

    async def send_chat(self, text: str, *, wake: bool = False) -> None:
        """Send one turn. Never raises: a lost send is a spoken failure.

        The socket can die between the last frame read and this write —
        that is what the deflate defect above did every time — and an
        exception here escapes into the task `__main__` spawned for the
        turn, which dies with no log and leaves the wave in `thinking`
        for as long as the strip is up. `on_error` settles the turn and
        says something out loud, which is the whole difference between a
        failure and a disappearance.
        """
        ws = self._ws
        if ws is None:
            self.on_error(_NO_GATEWAY)
            return
        try:
            await ws.send(encode_chat(text, self.user_id, wake=wake))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(f"pasarela: la frase no ha salido — {exc}")
            self.on_error(_NO_GATEWAY)

    async def run(self) -> None:
        """Connect, read, and reconnect forever. Cancel to stop.

        **Retrying forever is right; doing it in silence was not.** Every
        failure here — gateway down, gateway restarting, the socket
        dropped mid-turn, an exception raised out of `_dispatch` — has
        the same answer: wait and try again, because a strip that gives
        up is a strip somebody has to restart by hand. What is not the
        same is whether anybody is ever told, and until 2026-08-27 this
        was `except Exception: pass` with no log at any level.

        What that cost, measured on the live machine: the owner's
        sentence vanished three times in nine minutes, the widget
        journal showed `→ <the sentence>` and nothing after it, and the
        only evidence anywhere on the box was an aiohttp access line in
        the gateway's own log closing the socket at the same second. He
        watched JARVIS not answer, three times, with no way to know why.

        So: the first failure of a run of them is a `warning` naming the
        reason, every drop of a connection that HAD been established is
        a `warning`, and the reconnect says so — a reader can see
        "dropped at 11:25:18, back at 11:25:20". The attempts in between
        stay at `debug`, because a gateway that is simply down would
        otherwise write a line every `retry_seconds` for as long as it
        is down.
        """
        connected = False
        complained = False
        while True:
            why = ""
            try:
                async with websockets.connect(self.uri, **self.connect_options) as ws:
                    self._ws = ws
                    self._connected.set()
                    connected, complained = True, False
                    logger.info(f"pasarela: conectado a {self.uri}")
                    async for raw in ws:
                        self._dispatch(raw)
                # The `async for` ended without raising: the gateway
                # closed the socket on us. It is a drop like any other
                # and has to be reported like one — this is the branch
                # an `except` alone never sees.
                why = "la pasarela ha cerrado el socket"
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                why = f"{type(exc).__name__}: {exc}"
            finally:
                self._ws = None
                self._connected.clear()
            if connected:
                connected = False
                logger.warning(f"pasarela: conexión perdida — {why}")
            elif not complained:
                complained = True
                logger.warning(f"pasarela: no puedo conectar con {self.uri} — {why}")
            else:
                logger.debug(f"pasarela: sigo sin conectar — {why}")
            await asyncio.sleep(self.retry_seconds)

    def _dispatch(self, raw: str | bytes) -> None:
        # Branch BEFORE parsing. `websockets` yields str for text frames
        # and bytes for binary ones, and json.loads accepts bytes — so a
        # video frame would parse, fail as "not an object", and vanish
        # down the path that deliberately ignores unknown types.
        if isinstance(raw, (bytes, bytearray)):
            try:
                epoch, packet = decode_live_frame(bytes(raw))
            except ProtocolError:
                return
            self.on_live_frame(epoch, packet)
            return
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
        elif kind == "console":
            if msg.get("reset"):
                self.on_console_reset()
            text = msg.get("text")
            if isinstance(text, str) and text:
                self.on_console(text)
            if msg.get("done"):
                self.on_console_done()
        elif kind == "asking":
            self.on_asking(bool(msg.get("open")))
        elif kind == "photo":
            path = msg.get("path", "")
            if isinstance(path, str) and path:
                self.on_photo(path, str(msg.get("camera", "")))
        elif kind == "live":
            try:
                extradata = base64.b64decode(msg.get("extradata", "") or "")
            except (ValueError, TypeError):
                return
            self.on_live_open(
                str(msg.get("camera", "")),
                int(msg.get("epoch", 0)),
                extradata,
                int(msg.get("width", 0)),
                int(msg.get("height", 0)),
            )
        elif kind == "live_end":
            self.on_live_end(int(msg.get("epoch", 0)), str(msg.get("reason", "")))
