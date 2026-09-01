"""The phone socket: who holds the turn, and what happens to the second
person who presses.

Three iPhones plus the desk can press at once. Queueing spoken orders
ages badly — he would answer something asked a minute ago — so a press
during a running turn is refused and the page says so.
"""

import asyncio

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from samantha_widget.remote import (
    ANSWERING_SECONDS,
    ENROLMENT_SECONDS,
    HELD_TURN_SECONDS,
    Enrolment,
    EnrolmentSite,
    RemoteDesk,
    _handler,
    build_welcome_app,
)
from samantha_widget.remote_audio import MAX_UTTERANCE_BYTES, MAX_UTTERANCE_SECONDS
from samantha_widget.remote_auth import Guard


class FakeEndpoint:
    def __init__(self, name: str) -> None:
        self.name = name
        self.written: list[bytes] = []
        self.refusals = 0

    def write(self, pcm: bytes) -> None:
        self.written.append(pcm)

    def refuse(self) -> None:
        self.refusals += 1


def test_the_first_to_press_holds_the_turn() -> None:
    desk = RemoteDesk(on_utterance=lambda pcm, endpoint: None)
    phone = FakeEndpoint("iphone-cocina")

    assert desk.claim(phone) is True
    assert desk.busy is True
    assert desk.current is phone


def test_the_second_to_press_is_refused_not_queued() -> None:
    desk = RemoteDesk(on_utterance=lambda pcm, endpoint: None)
    first, second = FakeEndpoint("a"), FakeEndpoint("b")
    desk.claim(first)

    assert desk.claim(second) is False
    assert desk.current is first
    assert second.written == []


def test_releasing_lets_the_next_one_in() -> None:
    desk = RemoteDesk(on_utterance=lambda pcm, endpoint: None)
    first, second = FakeEndpoint("a"), FakeEndpoint("b")
    desk.claim(first)
    desk.release()

    assert desk.busy is False
    assert desk.claim(second) is True


def test_the_utterance_is_delivered_with_the_endpoint_that_spoke() -> None:
    """The reply has to go back where the question came from, so the
    endpoint travels with the audio."""
    seen: list[tuple[bytes, object]] = []
    desk = RemoteDesk(on_utterance=lambda pcm, endpoint: seen.append((pcm, endpoint)))
    phone = FakeEndpoint("iphone-cocina")
    desk.claim(phone)

    desk.finish(b"\x01\x02" * 100, phone)

    assert seen == [(b"\x01\x02" * 100, phone)]


def test_a_release_by_a_phone_that_does_not_hold_the_turn_is_ignored() -> None:
    """Otherwise a second phone releasing frees the first one's turn."""
    desk = RemoteDesk(on_utterance=lambda pcm, endpoint: None)
    first, second = FakeEndpoint("a"), FakeEndpoint("b")
    desk.claim(first)

    desk.release(second)

    assert desk.current is first


def test_a_turn_held_under_the_ceiling_cannot_be_stolen() -> None:
    desk = RemoteDesk(on_utterance=lambda pcm, endpoint: None)
    first, second = FakeEndpoint("a"), FakeEndpoint("b")
    desk.claim(first, now=0.0)

    assert desk.claim(second, now=HELD_TURN_SECONDS - 1) is False
    assert desk.current is first
    assert second.refusals == 1


def test_a_turn_held_past_the_ceiling_is_stolen_not_refused() -> None:
    """A phone that pressed and vanished — a dead app, a dropped
    connection with no `end` frame — must not lock out the house
    forever. No sleeping: the clock is passed in."""
    desk = RemoteDesk(on_utterance=lambda pcm, endpoint: None)
    first, second = FakeEndpoint("a"), FakeEndpoint("b")
    desk.claim(first, now=0.0)

    assert desk.claim(second, now=HELD_TURN_SECONDS + 1) is True
    assert desk.current is second
    assert second.refusals == 0


def test_finishing_ends_the_deadline_so_a_long_reply_is_not_stolen() -> None:
    """The deadline is for the RECORDING phase only — a phone that
    pressed and never released. Once `end` arrived and `finish()` ran,
    the reply may legitimately take minutes (he holds a terminal), so a
    claim well past HELD_TURN_SECONDS after the press must still be
    refused, not allowed to steal the turn mid-answer."""
    desk = RemoteDesk(on_utterance=lambda pcm, endpoint: None)
    first, second = FakeEndpoint("a"), FakeEndpoint("b")
    desk.claim(first, now=0.0)
    desk.finish(b"\x01\x02" * 100, first, now=0.0)

    assert desk.claim(second, now=HELD_TURN_SECONDS + 1) is False
    assert desk.current is first
    assert second.refusals == 1


def test_enrolment_is_closed_until_opened() -> None:
    """Before anything opens it — at startup — the welcome page and
    /jarvis.mobileconfig must answer as if nothing were listening."""
    enrolment = Enrolment()

    assert enrolment.is_open(now=0.0) is False


def test_enrolment_opens_when_asked() -> None:
    enrolment = Enrolment()
    enrolment.open_enrolment(now=0.0)

    assert enrolment.is_open(now=1.0) is True


def test_enrolment_closes_again_on_its_own() -> None:
    """No sleeping: the clock is passed in, the same way RemoteDesk's
    ceilings are tested. The secret sits in that page's HTML in
    cleartext for exactly ENROLMENT_SECONDS, not for as long as the
    widget runs."""
    enrolment = Enrolment()
    enrolment.open_enrolment(now=0.0)

    assert enrolment.is_open(now=ENROLMENT_SECONDS + 1) is False


async def test_the_welcome_routes_404_while_the_window_is_closed(
    tmp_path,
) -> None:
    """A closed window has to look like nothing is there — 404, not
    403, which would confirm to a scanning stranger that something is
    listening on this port at all. Route names per the live acceptance
    fix of 2026-09-01: /jarvis.mobileconfig, not /ca — belt and braces
    for iOS profile delivery, which reads the path as well as the type
    (never demonstrated necessary: the download that was observed was
    Chrome's, and only Safari installs profiles on iOS at all).

    `ca` is never read on this path — the 404 fires before the handler
    would touch it — so a path that does not exist is fine here."""
    guard = Guard("secret", "https://brain.local:8443")
    enrolment = Enrolment()  # never opened
    app = build_welcome_app(guard, enrolment, tmp_path / "unused-ca.pem")

    async with TestClient(TestServer(app)) as client:
        assert (await client.get("/")).status == 404
        assert (await client.get("/jarvis.mobileconfig")).status == 404


async def test_the_profile_route_advertises_a_mobileconfig_filename(
    tmp_path,
) -> None:
    """iOS reads the type, the filename and the path together when it
    decides whether to offer to INSTALL a profile rather than download
    it, and profile delivery is not worth resting on the MIME type
    alone — so both extra signals are asserted here. Neither was ever
    shown to be required: the plain download observed on 2026-09-01 was
    **Chrome**, which does not install profiles on iOS at all, and `/ca`
    was never tried in Safari, which is the only browser that does."""
    ca = tmp_path / "ca.pem"
    ca.write_bytes(b"-----BEGIN CERTIFICATE-----\nAAAA\n-----END CERTIFICATE-----\n")
    guard = Guard("secret", "https://brain.local:8443")
    enrolment = Enrolment()
    enrolment.open_enrolment()  # real clock: the route checks it too
    app = build_welcome_app(guard, enrolment, ca)

    async with TestClient(TestServer(app)) as client:
        response = await client.get("/jarvis.mobileconfig")

        assert response.status == 200
        assert (
            response.headers["Content-Disposition"]
            == 'inline; filename="jarvis.mobileconfig"'
        )


def test_a_reply_that_never_settles_can_still_be_stolen_eventually() -> None:
    """`finish()` re-stamps the deadline rather than clearing it: a turn
    that ends in silence (the gateway's own `📬 No home channel` first
    turn is exactly that shape — CLAUDE.md §5) must not hold a phone
    forever with no way back except its own socket dropping."""
    desk = RemoteDesk(on_utterance=lambda pcm, endpoint: None)
    first, second = FakeEndpoint("a"), FakeEndpoint("b")
    desk.claim(first, now=0.0)
    desk.finish(b"\x01\x02" * 100, first, now=0.0)

    assert desk.claim(second, now=ANSWERING_SECONDS + 1) is True
    assert desk.current is second
    assert second.refusals == 0


def test_the_ceiling_and_the_held_turn_cannot_drift_apart() -> None:
    """The recording deadline exists to catch a phone that presses and
    never releases, so it has to sit just above the longest press the
    server will accept. While the ceiling was being applied to the
    48 kHz buffer, the longest press was really ~10 s and nothing said
    so."""
    assert HELD_TURN_SECONDS == MAX_UTTERANCE_SECONDS + 5.0


def test_releasing_sends_his_voice_home_too() -> None:
    """The claim and the sink are two halves of one thing. Only the
    claim used to come back."""
    homed = []
    desk = RemoteDesk(
        on_utterance=lambda pcm, endpoint: None,
        on_release=lambda: homed.append(True),
    )
    phone = FakeEndpoint("iphone-cocina")
    desk.claim(phone)

    desk.release(phone)

    assert homed == [True]


def test_a_claim_that_merely_EXPIRES_sends_his_voice_home() -> None:
    """The recovery path nobody calls. A phone that drops during a turn
    that produces no token at all is released by nothing — only the
    deadline ends it — and until this the sink went on pointing at that
    dead socket, so the NEXT reply, to anybody, was written into it and
    the desk stayed mute."""
    homed = []
    desk = RemoteDesk(
        on_utterance=lambda pcm, endpoint: None,
        on_release=lambda: homed.append(True),
    )
    gone, next_one = FakeEndpoint("gone"), FakeEndpoint("next")
    desk.claim(gone, now=0.0)

    assert desk.claim(next_one, now=ANSWERING_SECONDS + 1) is True
    assert homed == [True]


def test_a_release_that_frees_nothing_does_not_move_his_voice() -> None:
    homed = []
    desk = RemoteDesk(
        on_utterance=lambda pcm, endpoint: None,
        on_release=lambda: homed.append(True),
    )
    first, second = FakeEndpoint("a"), FakeEndpoint("b")
    desk.claim(first)

    desk.release(second)

    assert homed == []


class FakeSite:
    def __init__(self) -> None:
        self.opened = 0

    def open_soon(self, seconds: float = ENROLMENT_SECONDS) -> None:
        self.opened += 1


def test_opening_the_window_raises_the_socket() -> None:
    """Not just the handlers: the socket itself. 404s bound accident —
    a phone that kept the link — and nothing else. Anyone on the wifi
    polling the port collected the secret the moment the window
    opened."""
    enrolment = Enrolment()
    site = FakeSite()
    enrolment.attach(site)

    enrolment.open_enrolment(now=0.0)

    assert site.opened == 1


def test_the_window_still_works_with_no_socket_attached() -> None:
    """Every test of the timing drives it without one, and the handlers
    ask `is_open` too."""
    enrolment = Enrolment()
    enrolment.open_enrolment(now=0.0)

    assert enrolment.is_open(now=1.0) is True


async def test_the_enrolment_socket_is_up_only_while_the_window_is() -> None:
    """A real socket, bound and unbound. The unbind is a timer rather
    than something the next request notices, because "no request
    arrives" is exactly the case that has to close the port."""
    app = web.Application()

    async def hello(request: web.Request) -> web.Response:
        return web.Response(text="ok")

    app.router.add_get("/", hello)
    runner = web.AppRunner(app)
    await runner.setup()
    site = EnrolmentSite(runner, "127.0.0.1", 0, asyncio.get_running_loop())
    try:
        assert site.bound is False

        await site.open(seconds=0.05)
        assert site.bound is True
        port = runner.addresses[0][1]
        _reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.close()
        await writer.wait_closed()

        await asyncio.sleep(0.3)
        assert site.bound is False
        with pytest.raises(OSError):
            await asyncio.open_connection("127.0.0.1", port)
    finally:
        await site.close()
        await runner.cleanup()


async def _socket(desk: RemoteDesk) -> tuple[TestClient, web.Application]:
    app = web.Application()
    app.router.add_get(
        "/ws", _handler(desk, Guard("s" * 32, "https://brain.local:8443"), None)
    )
    client = TestClient(TestServer(app))
    await client.start_server()
    return client, app


async def test_thirty_seconds_at_48k_is_thirty_seconds_not_ten() -> None:
    """`MAX_UTTERANCE_BYTES` is 30 s AT 16 kHz, and a phone sends 48 —
    so measuring the incoming buffer against it cut every press at
    about ten seconds while every comment around it said thirty. This
    sends twenty seconds of 48 kHz audio — comfortably past the point
    the 16 kHz number cut a press, comfortably inside the real one — and
    expects all of it through."""
    seen: list[bytes] = []
    desk = RemoteDesk(on_utterance=lambda pcm, endpoint: seen.append(pcm))
    client, _ = await _socket(desk)
    try:
        ws = await client.ws_connect("/ws?t=" + "s" * 32)
        await ws.send_json({"type": "start", "rate": 48000})
        for _ in range(20):
            await ws.send_bytes(b"\x01\x02" * 50_000)  # 100 kB each, 2 MB total
        await ws.send_json({"type": "end"})
        for _ in range(50):
            await asyncio.sleep(0.02)
            if seen:
                break
        await ws.close()
    finally:
        await client.close()

    assert seen, "the utterance never arrived"
    seconds = len(seen[0]) / 2 / 16000
    assert seconds > 15.0, f"cut at {seconds:.1f}s — the 16 kHz ceiling again"


async def test_the_ceiling_is_hit_at_the_real_thirty_seconds_and_says_so() -> None:
    """Hitting it used to be silent, so a long press became half a
    question with nothing to explain it. And the chunk that crosses the
    line is refused whole rather than appended and then noticed:
    `len(buffer) < ceiling` let one full chunk past the number it was
    defending.

    8 kHz keeps this cheap — the ceiling is the same thirty seconds
    either way, and thirty seconds at 8 kHz is 480 kB rather than the
    2.8 MB a phone's 48 would put through the loopback."""
    seen: list[bytes] = []
    desk = RemoteDesk(on_utterance=lambda pcm, endpoint: seen.append(pcm))
    client, _ = await _socket(desk)
    try:
        ws = await client.ws_connect("/ws?t=" + "s" * 32)
        await ws.send_json({"type": "start", "rate": 8000})
        for _ in range(9):  # 9 x 60 kB against a 480 kB ceiling
            await ws.send_bytes(b"\x01\x02" * 30_000)

        told = await asyncio.wait_for(ws.receive_json(), timeout=5)
        assert told == {"type": "truncated"}

        await ws.send_json({"type": "end"})
        for _ in range(200):
            await asyncio.sleep(0.02)
            if seen:
                break
        await ws.close()
    finally:
        await client.close()

    assert seen, "the utterance never arrived"
    # Exactly thirty seconds of 16 kHz audio: the buffer stopped AT the
    # ceiling, never one chunk past it.
    assert len(seen[0]) == MAX_UTTERANCE_BYTES
