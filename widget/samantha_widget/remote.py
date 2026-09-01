"""JARVIS on a phone, inside the house's own network.

The phone is a peripheral of this process, not a platform: audio that
arrives here goes into the same `dispatch()` the desk microphone uses,
so it is the same session, the same memory and the same JARVIS. The
gateway never learns it exists.

What is behind this socket is an agent holding the `terminal` toolset,
so `remote_auth.Guard` is not a formality.
"""

from __future__ import annotations

import json
import os
import ssl
import sys
from pathlib import Path
from typing import Callable, Protocol

from aiohttp import WSMsgType, web

from .certs import ensure_certificate, lan_address
from .remote_audio import MAX_UTTERANCE_BYTES, resample_to_input
from .remote_auth import Guard, load_or_create_secret

PORT = int(os.getenv("SAMANTHA_WIDGET_REMOTE_PORT", "8443"))
HOSTNAME = os.getenv("SAMANTHA_WIDGET_REMOTE_NAME", "brain.local")
CERT_DIR = Path.home() / ".samantha" / "certs"


class Endpoint(Protocol):
    """Anywhere his voice can come out.

    Deliberately the same shape as `audio.Player`: one `write(pcm)`. That
    is what lets `Speaker` be pointed at a phone without knowing what a
    phone is.
    """

    name: str

    def write(self, pcm: bytes) -> None: ...

    def refuse(self) -> None: ...


class RemoteDesk:
    """Who is holding the turn.

    One at a time, and a second press is REFUSED rather than queued: a
    queued spoken order is answered a minute after it was asked, which
    reads as him being confused rather than busy.
    """

    def __init__(self, on_utterance: Callable[[bytes, Endpoint], None]) -> None:
        self._on_utterance = on_utterance
        self.current: Endpoint | None = None

    @property
    def busy(self) -> bool:
        return self.current is not None

    def claim(self, endpoint: Endpoint) -> bool:
        """True if this endpoint now holds the turn."""
        if self.current is not None and self.current is not endpoint:
            endpoint.refuse()
            return False
        self.current = endpoint
        return True

    def release(self, endpoint: Endpoint | None = None) -> None:
        """Give the turn back. A release from an endpoint that does not
        hold it is ignored — otherwise the second phone to press frees
        the first one's turn."""
        if endpoint is not None and self.current is not endpoint:
            return
        self.current = None

    def finish(self, pcm: bytes, endpoint: Endpoint) -> None:
        """The button was released: hand the utterance up with the
        endpoint that spoke, so the reply knows where to go."""
        self._on_utterance(pcm, endpoint)


class WebEndpoint:
    """One connected phone."""

    def __init__(self, ws: web.WebSocketResponse, name: str, loop) -> None:
        self._ws = ws
        self._loop = loop
        self.name = name

    def write(self, pcm: bytes) -> None:
        # Called from the Speaker on the asyncio loop already, but going
        # through call_soon_threadsafe costs nothing and makes this safe
        # from the audio thread too.
        self._loop.call_soon_threadsafe(
            lambda: self._loop.create_task(self._ws.send_bytes(pcm))
        )

    def refuse(self) -> None:
        self._loop.call_soon_threadsafe(
            lambda: self._loop.create_task(self._ws.send_json({"type": "busy"}))
        )


async def serve(desk: RemoteDesk, guard: Guard, loop) -> web.AppRunner:
    """Start the HTTPS server. Returns the runner so it can be stopped.

    Routes are registered here, one `app.router.add_*` line per route, so
    a later task can add its own (the static page, the plain-HTTP
    enrolment server) without touching what is already here.
    """
    app = web.Application()
    app.router.add_get("/ws", _handler(desk, guard, loop))
    ca, cert, key = ensure_certificate(CERT_DIR, HOSTNAME, lan_address())
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(cert), str(key))
    runner = web.AppRunner(app)
    await runner.setup()
    # One interface, never 0.0.0.0: this box has twelve Docker bridges,
    # and no container has any business reaching this socket.
    site = web.TCPSite(runner, lan_address(), PORT, ssl_context=context)
    await site.start()
    print(
        f"móvil: escuchando en https://{HOSTNAME}:{PORT} ({lan_address()}), CA en {ca}",
        file=sys.stderr,
        flush=True,
    )
    return runner


def _handler(desk: RemoteDesk, guard: Guard, loop):
    async def handle(request: web.Request) -> web.WebSocketResponse:
        if not guard.origin_ok(request.headers.get("Origin", "")):
            raise web.HTTPForbidden()
        if not guard.token_ok(request.query.get("t")):
            raise web.HTTPForbidden()
        ws = web.WebSocketResponse(heartbeat=20)
        await ws.prepare(request)
        endpoint = WebEndpoint(ws, request.remote or "phone", loop)
        buffer = bytearray()
        rate = 48000
        async for message in ws:
            if message.type == WSMsgType.TEXT:
                frame = json.loads(message.data)
                if frame.get("type") == "start":
                    rate = int(frame.get("rate", 48000))
                    buffer.clear()
                    if not desk.claim(endpoint):
                        continue
                elif frame.get("type") == "end" and desk.current is endpoint:
                    desk.finish(resample_to_input(bytes(buffer), rate), endpoint)
                    buffer.clear()
            elif message.type == WSMsgType.BINARY:
                if desk.current is endpoint and len(buffer) < MAX_UTTERANCE_BYTES:
                    buffer += message.data
        desk.release(endpoint)
        return ws

    return handle


__all__ = [
    "CERT_DIR",
    "HOSTNAME",
    "PORT",
    "Endpoint",
    "Guard",
    "RemoteDesk",
    "WebEndpoint",
    "load_or_create_secret",
    "serve",
]
