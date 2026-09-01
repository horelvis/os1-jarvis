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
import time
from pathlib import Path
from typing import Callable, Protocol

from aiohttp import WSMsgType, web

from .certs import ensure_certificate, lan_address
from .enrol import mobileconfig, write_qr
from .remote_audio import MAX_UTTERANCE_BYTES, resample_to_input
from .remote_auth import Guard, load_or_create_secret

PORT = int(os.getenv("SAMANTHA_WIDGET_REMOTE_PORT", "8443"))
HOSTNAME = os.getenv("SAMANTHA_WIDGET_REMOTE_NAME", "brain.local")
CERT_DIR = Path.home() / ".samantha" / "certs"

# A held turn expires: a phone that presses and never releases — a
# vanished network, an app killed mid-utterance — must not lock out
# every other phone in the house forever. 30 s is MAX_UTTERANCE_BYTES'
# own ceiling (remote_audio.py); this is that plus slack.
HELD_TURN_SECONDS = 35.0

# How long a turn may be held once the button is released. The recording
# ceiling (HELD_TURN_SECONDS) stops applying at `finish` — a reply can
# legitimately take minutes, since he holds a terminal. This is the
# backstop under that: a turn producing no answer at all (the
# `📬 No home channel` first turn of a new session is exactly that
# shape) would otherwise hold the phone forever, and the next thing
# said in the room would play on it.
#
# The gateway's own error path is the FIRST recovery and normally fires
# well inside this; this only catches turns that end in silence.
ANSWERING_SECONDS = 600.0

# The plain-HTTP welcome page hands the shared secret to whoever asks —
# it is embedded, in cleartext, in the second link's href — with no
# check of its own; that is the cost of it being reachable before a
# phone has any reason yet to trust this box (see enrol.py). Serving it
# at all therefore has to be a WINDOW, not a standing service: 300 s is
# long enough to walk to a phone and scan the QR, and not a minute
# longer that the secret sits readable by anyone else on the wifi with
# a browser.
ENROLMENT_SECONDS = 300.0


class Enrolment:
    """Whether the plain-HTTP welcome page (and `/jarvis.mobileconfig`) may answer.

    Closed until something opens it — showing the QR on the strip,
    today (`SAMANTHA_WIDGET_SHOW_QR=1`) — and closed again on its own
    `ENROLMENT_SECONDS` later. `now` is a monotonic clock reading,
    injectable for tests, the same way `RemoteDesk.claim` is.
    """

    def __init__(self) -> None:
        self._opened_at: float | None = None

    def open_enrolment(self, now: float | None = None) -> None:
        self._opened_at = time.monotonic() if now is None else now

    def is_open(self, now: float | None = None) -> bool:
        if self._opened_at is None:
            return False
        if now is None:
            now = time.monotonic()
        return now - self._opened_at < ENROLMENT_SECONDS


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
        # Set whenever somebody holds the turn, RECORDING or ANSWERING —
        # `None` only while nobody does. Which ceiling applies to it is
        # `_allowance`: short while recording (a phone that presses and
        # never releases), long while answering (a reply that never
        # settles — see `finish`). Both expire; neither is unbounded,
        # because a turn producing no answer at all is a real, measured
        # shape (CLAUDE.md §5, the `📬 No home channel` first turn) and
        # must not hold a phone forever.
        self._claimed_at: float | None = None
        self._allowance: float = HELD_TURN_SECONDS

    @property
    def busy(self) -> bool:
        return self.current is not None

    def claim(self, endpoint: Endpoint, now: float | None = None) -> bool:
        """True if this endpoint now holds the turn.

        `now` is a monotonic clock reading, injectable for tests. A turn
        held longer than its current allowance — `HELD_TURN_SECONDS`
        while recording, `ANSWERING_SECONDS` while answering (see
        `finish`) — is stolen rather than defended: its holder cannot
        possibly still be in that phase.
        """
        if now is None:
            now = time.monotonic()
        if self.current is not None and self.current is not endpoint:
            expired = (
                self._claimed_at is not None
                and now - self._claimed_at >= self._allowance
            )
            if not expired:
                endpoint.refuse()
                return False
        self.current = endpoint
        self._claimed_at = now
        self._allowance = HELD_TURN_SECONDS
        return True

    def release(self, endpoint: Endpoint | None = None) -> None:
        """Give the turn back. A release from an endpoint that does not
        hold it is ignored — otherwise the second phone to press frees
        the first one's turn."""
        if endpoint is not None and self.current is not endpoint:
            return
        self.current = None
        self._claimed_at = None

    def finish(self, pcm: bytes, endpoint: Endpoint, now: float | None = None) -> None:
        """The button was released: hand the utterance up with the
        endpoint that spoke, so the reply knows where to go.

        This also SWITCHES the deadline rather than clearing it.
        `_claimed_at` while recording exists to catch a phone that
        presses and never releases; once `end` has arrived that risk is
        gone, and what remains is the reply, which may legitimately
        take minutes — he holds a terminal. Clearing the deadline
        entirely was the first version of this, and it traded one bug
        for another: a turn that ends in silence — no token at all, the
        gateway's own `📬 No home channel` first-turn quirk is exactly
        that shape — then held the phone with no way back except its
        own socket dropping. Re-stamping with `ANSWERING_SECONDS`
        keeps the short ceiling from firing mid-answer while still
        giving a silent turn a way out.
        """
        if now is None:
            now = time.monotonic()
        self._claimed_at = now
        self._allowance = ANSWERING_SECONDS
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


def build_welcome_app(guard: Guard, enrolment: Enrolment, ca: Path) -> web.Application:
    """The plain-HTTP side: a welcome page and the CA profile it links to.

    Pulled out of `serve()` so it can be built and hit directly in a
    test — a real `aiohttp.test_utils.TestServer` around this app, no
    socket on the LAN, no certificate, no `serve()` at all — rather than
    only through the whole of `serve()`'s TCP binding.
    """
    welcome = web.Application()

    async def _welcome(request: web.Request) -> web.Response:
        if not enrolment.is_open():
            # A closed window looks like nothing is there — 404, not
            # 403, which would confirm to a scanning stranger that
            # something is listening on this port at all.
            raise web.HTTPNotFound()
        target = f"https://{HOSTNAME}:{PORT}/#{guard.secret}"
        return web.Response(
            content_type="text/html",
            text=(
                "<!doctype html><meta charset=utf-8>"
                "<meta name=viewport content='width=device-width,initial-scale=1'>"
                "<title>JARVIS</title>"
                "<style>body{font-family:-apple-system,sans-serif;margin:2rem;"
                "background:#141210;color:#d1684e}a{display:block;margin:1.5rem 0;"
                "padding:1rem;border:1px solid #d1684e;border-radius:.5rem;"
                "color:inherit;text-decoration:none;text-align:center}</style>"
                "<h1>JARVIS en casa</h1>"
                "<a href='/jarvis.mobileconfig'>1 · Instalar el certificado</a>"
                "<p>Después: Ajustes → General → Información → "
                "Ajustes de confianza de certificados → activar "
                "<b>JARVIS Home CA</b>.</p>"
                f"<a href='{target}'>2 · Abrir JARVIS</a>"
            ),
        )

    async def _ca(request: web.Request) -> web.Response:
        if not enrolment.is_open():
            raise web.HTTPNotFound()
        return web.Response(
            body=mobileconfig(ca),
            content_type="application/x-apple-aspen-config",
            # iOS decides "this is a configuration profile, offer to
            # install it" from the type AND the filename together —
            # the type alone is not enough. Measured live 2026-09-01:
            # served at /ca with no Content-Disposition, Safari fell
            # through to a plain download and "Perfil descargado" never
            # appeared in Settings. The route itself has to end in
            # `.mobileconfig` too (see the route below) — the header
            # alone was not enough either. `inline`, never `attachment`:
            # attachment is an explicit instruction to download, the
            # exact behaviour this fixes.
            headers={"Content-Disposition": 'inline; filename="jarvis.mobileconfig"'},
        )

    welcome.router.add_get("/", _welcome)
    # Not `/ca` — a route with no file extension, however the header
    # names it, still reads to iOS as "a download", not "a profile to
    # install". Do not "tidy" this back to `/ca`.
    welcome.router.add_get("/jarvis.mobileconfig", _ca)
    return welcome


async def serve(
    desk: RemoteDesk, guard: Guard, enrolment: Enrolment, loop
) -> web.AppRunner:
    """Start the HTTPS server. Returns the runner so it can be stopped.

    Routes are registered here, one `app.router.add_*` line per route, so
    a later task can add its own (the static page, the plain-HTTP
    enrolment server) without touching what is already here.
    """
    app = web.Application()
    app.router.add_get("/ws", _handler(desk, guard, loop))

    static = Path(__file__).parent / "static"

    async def page(request: web.Request) -> web.FileResponse:
        return web.FileResponse(static / "movil.html")

    app.router.add_get("/", page)

    ca, cert, key = ensure_certificate(CERT_DIR, HOSTNAME, lan_address())
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(cert), str(key))
    # access_log=None, structurally: aiohttp's default access logger
    # formats %r — the whole request line, which here is
    # "GET /ws?t=<the shared secret>". It is silent today only because
    # the root logger sits at WARNING; any dependency or debug flag
    # raising that to INFO would put the secret in the journal,
    # including on the 403 path. Not worth being one config change away
    # from a leak.
    runner = web.AppRunner(app, access_log=None)
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

    # Plain HTTP, and only these two routes. The certificate cannot be
    # fetched over a connection that requires trusting it.
    welcome = build_welcome_app(guard, enrolment, ca)
    welcome_runner = web.AppRunner(welcome)
    await welcome_runner.setup()
    await web.TCPSite(welcome_runner, lan_address(), PORT + 1).start()

    qr = write_qr(
        f"http://{lan_address()}:{PORT + 1}/",
        Path.home() / ".samantha" / "enrol-qr.png",
    )
    print(
        f"móvil: alta en http://{lan_address()}:{PORT + 1}/ · QR {qr}",
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
        ws = web.WebSocketResponse(
            heartbeat=20,
            # permessage-deflate is aiohttp's default, and every browser
            # offers it. CLAUDE.md §12 (2026-08-27) already paid for
            # this exact bug on the gateway side: with deflate
            # negotiated, aiohttp refuses the FIRST compressed data
            # frame of a connection if a control frame reached it
            # first, and the 20 s heartbeat ping IS that control frame
            # for any phone idle between presses. The symptom last time
            # was a sentence vanishing on the wire with nothing in any
            # log. PCM barely compresses and these are LAN frames — do
            # not re-enable this.
            compress=False,
        )
        await ws.prepare(request)
        endpoint = WebEndpoint(ws, request.remote or "phone", loop)
        buffer = bytearray()
        rate = 48000
        try:
            async for message in ws:
                if message.type == WSMsgType.TEXT:
                    try:
                        frame = json.loads(message.data)
                    except ValueError:
                        continue
                    if frame.get("type") == "start":
                        rate = int(frame.get("rate", 48000))
                        buffer.clear()
                        if not desk.claim(endpoint, time.monotonic()):
                            continue
                    elif frame.get("type") == "end" and desk.current is endpoint:
                        desk.finish(
                            resample_to_input(bytes(buffer), rate),
                            endpoint,
                            time.monotonic(),
                        )
                        buffer.clear()
                elif message.type == WSMsgType.BINARY:
                    if desk.current is endpoint and len(buffer) < MAX_UTTERANCE_BYTES:
                        buffer += message.data
        finally:
            # Whatever happened — a malformed frame past the guard
            # above, a bad rate, resample_to_input raising on an
            # odd-length buffer, on_utterance raising, or the socket
            # just dying mid-utterance — the turn goes back. Without
            # this, `desk.current` points at a dead endpoint forever
            # and every phone in the house is told he is busy until
            # the widget restarts.
            desk.release(endpoint)
        return ws

    return handle


__all__ = [
    "CERT_DIR",
    "ENROLMENT_SECONDS",
    "HOSTNAME",
    "PORT",
    "Endpoint",
    "Enrolment",
    "Guard",
    "RemoteDesk",
    "WebEndpoint",
    "build_welcome_app",
    "load_or_create_secret",
    "serve",
]
