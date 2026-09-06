"""The phone socket: who holds the turn, and what happens to the second
person who presses.

Three iPhones plus the desk can press at once. Queueing spoken orders
ages badly — he would answer something asked a minute ago — so a press
during a running turn is refused and the page says so.
"""

import asyncio

import pytest
from aiohttp import WSServerHandshakeError, web
from aiohttp.test_utils import TestClient, TestServer

from jarvis_widget.remote import (
    ANSWERING_SECONDS,
    ENROLMENT_SECONDS,
    HELD_TURN_SECONDS,
    Enrolment,
    EnrolmentSite,
    RemoteDesk,
    _handler,
    build_welcome_app,
)
from jarvis_widget.personas import CASA
from jarvis_widget.remote_audio import MAX_UTTERANCE_BYTES, MAX_UTTERANCE_SECONDS
from jarvis_widget.remote_auth import Guard, load_or_create_roster, save_roster


class FakeEndpoint:
    def __init__(self, name: str = "prueba", persona: str = CASA) -> None:
        self.name = name
        # Who this endpoint belongs to. Defaults to CASA, the same
        # fallback `personas.normalizar` gives an unattributable turn —
        # most of the tests below are about RemoteDesk's claim/release
        # bookkeeping and never look at this, only the ones that assert
        # identity (task 5) pass a real one.
        self.persona = persona
        self.written: list[bytes] = []
        self.refusals = 0

    def write(self, pcm: bytes) -> None:
        self.written.append(pcm)

    def refuse(self) -> None:
        self.refusals += 1


def test_an_endpoint_knows_whose_it_is() -> None:
    assert FakeEndpoint(persona="marta").persona == "marta"


def test_the_first_to_press_holds_the_turn() -> None:
    desk = RemoteDesk(on_utterance=lambda pcm, endpoint: None)
    phone = FakeEndpoint("iphone-cocina")

    assert desk.claim(phone) is True
    assert desk.busy is True
    assert desk.holders.get(CASA) is phone


def test_the_second_to_press_is_refused_not_queued() -> None:
    desk = RemoteDesk(on_utterance=lambda pcm, endpoint: None)
    first, second = FakeEndpoint("a"), FakeEndpoint("b")
    desk.claim(first)

    assert desk.claim(second) is False
    assert desk.holders.get(CASA) is first
    assert second.written == []


def test_releasing_lets_the_next_one_in() -> None:
    desk = RemoteDesk(on_utterance=lambda pcm, endpoint: None)
    first, second = FakeEndpoint("a"), FakeEndpoint("b")
    desk.claim(first)
    desk.release(first)

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

    assert desk.holders.get(CASA) is first


def test_a_turn_held_under_the_ceiling_cannot_be_stolen() -> None:
    desk = RemoteDesk(on_utterance=lambda pcm, endpoint: None)
    first, second = FakeEndpoint("a"), FakeEndpoint("b")
    desk.claim(first, now=0.0)

    assert desk.claim(second, now=HELD_TURN_SECONDS - 1) is False
    assert desk.holders.get(CASA) is first
    assert second.refusals == 1


def test_a_turn_held_past_the_ceiling_is_stolen_not_refused() -> None:
    """A phone that pressed and vanished — a dead app, a dropped
    connection with no `end` frame — must not lock out the house
    forever. No sleeping: the clock is passed in."""
    desk = RemoteDesk(on_utterance=lambda pcm, endpoint: None)
    first, second = FakeEndpoint("a"), FakeEndpoint("b")
    desk.claim(first, now=0.0)

    assert desk.claim(second, now=HELD_TURN_SECONDS + 1) is True
    assert desk.holders.get(CASA) is second
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
    assert desk.holders.get(CASA) is first
    assert second.refusals == 1


# ── one turn per person, not one turn for the whole house ────────────
#
# Until 2026-09-06 the desk held ONE turn, whoever it belonged to, and
# a second press by ANYONE heard "está ocupado". The user's decision is
# that different people hold genuinely parallel conversations; only a
# SECOND press by the SAME person is still refused — a queued spoken
# order answered a minute later reads as him being confused rather than
# busy. The shared engines (STT, the LLM, TTS) stay serialised
# elsewhere (task 10); this is only the claim.


def test_two_people_hold_turns_at_the_same_time() -> None:
    desk = RemoteDesk(on_utterance=lambda pcm, endpoint: None)
    marta = FakeEndpoint("iphone-marta", persona="marta")
    lucia = FakeEndpoint("iphone-lucia", persona="lucía")

    assert desk.claim(marta, now=0.0)
    assert desk.claim(lucia, now=0.0)
    assert marta.refusals == 0 and lucia.refusals == 0


def test_the_same_person_pressing_twice_is_still_refused() -> None:
    """Two phones logged in as the same person, or one phone pressed
    twice: a queued spoken order answered a minute later reads as him
    being confused, which is the reason this refusal exists."""
    desk = RemoteDesk(on_utterance=lambda pcm, endpoint: None)
    uno = FakeEndpoint("uno", persona="marta")
    otro = FakeEndpoint("otro", persona="marta")

    assert desk.claim(uno, now=0.0)
    assert not desk.claim(otro, now=0.0)
    assert otro.refusals == 1


def test_an_expired_claim_is_stolen_only_from_its_own_person() -> None:
    desk = RemoteDesk(on_utterance=lambda pcm, endpoint: None)
    uno = FakeEndpoint("uno", persona="marta")
    otro = FakeEndpoint("otro", persona="marta")
    desk.claim(uno, now=0.0)

    assert desk.claim(otro, now=HELD_TURN_SECONDS + 1)


def test_releasing_one_person_leaves_the_other_holding() -> None:
    liberadas: list[object] = []
    desk = RemoteDesk(
        on_utterance=lambda pcm, endpoint: None,
        on_release=lambda endpoint: liberadas.append(endpoint),
    )
    marta = FakeEndpoint("iphone-marta", persona="marta")
    lucia = FakeEndpoint("iphone-lucia", persona="lucía")
    desk.claim(marta, now=0.0)
    desk.claim(lucia, now=0.0)

    desk.release(marta)

    assert desk.busy_for("lucía")
    assert not desk.busy_for("marta")
    assert liberadas == [marta]


def test_endpoint_for_returns_the_holder_or_none() -> None:
    """Task 10's speaker asks this, rather than reading `_claims`
    itself, to decide where a reply's clauses go."""
    desk = RemoteDesk(on_utterance=lambda pcm, endpoint: None)
    marta = FakeEndpoint("iphone-marta", persona="marta")
    desk.claim(marta, now=0.0)

    assert desk.endpoint_for("marta") is marta
    assert desk.endpoint_for("lucía") is None


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
    guard = Guard({"casa": "secret"}, "https://brain.local:8443")
    enrolment = Enrolment()  # never opened
    app = build_welcome_app(guard, enrolment, tmp_path / "unused-ca.pem")

    async with TestClient(TestServer(app)) as client:
        assert (await client.get("/")).status == 404
        assert (await client.get("/jarvis.mobileconfig")).status == 404


async def test_the_welcome_page_carries_the_enrolling_persons_secret(
    tmp_path,
) -> None:
    """The page has nothing to choose (task-4-brief.md): whoever the
    window was opened FOR is who its link authenticates as, and nobody
    else's secret is anywhere in the page."""
    guard = Guard(
        {"casa": "casa-secreto", "marta": "marta-secreto"},
        "https://brain.local:8443",
    )
    enrolment = Enrolment()
    enrolment.abrir("marta")  # real clock: the route checks it too
    app = build_welcome_app(guard, enrolment, tmp_path / "unused-ca.pem")

    async with TestClient(TestServer(app)) as client:
        body = await (await client.get("/")).text()

    assert "#marta-secreto" in body
    assert "casa-secreto" not in body


async def test_the_welcome_page_mints_a_secret_for_a_new_person(
    tmp_path, monkeypatch
) -> None:
    """A person opened for the first time is not on the roster yet —
    the page mints their secret and persists it, rather than 500ing or
    falling back to somebody else's."""
    roster_path = tmp_path / "personas.json"
    save_roster({"casa": "casa-secreto"}, roster_path)
    monkeypatch.setenv("JARVIS_WIDGET_REMOTE_ROSTER", str(roster_path))
    guard = Guard({"casa": "casa-secreto"}, "https://brain.local:8443")
    enrolment = Enrolment()
    enrolment.abrir("nuevo")  # real clock: the route checks it too
    app = build_welcome_app(guard, enrolment, tmp_path / "unused-ca.pem")

    async with TestClient(TestServer(app)) as client:
        response = await client.get("/")
        assert response.status == 200

    assert "nuevo" in guard.secretos
    persisted = load_or_create_roster(roster_path)
    assert persisted["nuevo"] == guard.secretos["nuevo"]


async def test_a_failed_save_refuses_the_enrolment_and_does_not_adopt_it_in_memory(
    tmp_path, monkeypatch
) -> None:
    """The disk has to lead. Mutating `guard.secretos` before the write
    succeeds would let a failed save pass unnoticed here: the phone
    would enrol, work for the rest of THIS process, and simply stop
    working at the next widget restart, with nothing in the log at the
    moment it actually broke. A test that only checked the status code
    would pass against that broken shape — the second assertion below
    is the one that catches it."""
    import jarvis_widget.remote as remote_module

    def _falla(*_args, **_kwargs) -> None:
        raise OSError("disco lleno")

    monkeypatch.setattr(remote_module, "save_roster", _falla)

    guard = Guard({"casa": "casa-secreto"}, "https://brain.local:8443")
    enrolment = Enrolment()
    enrolment.abrir("nuevo")  # real clock: the route checks it too
    app = build_welcome_app(guard, enrolment, tmp_path / "unused-ca.pem")

    async with TestClient(TestServer(app)) as client:
        response = await client.get("/")

    assert response.status == 503
    assert "nuevo" not in guard.secretos


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
    guard = Guard({"casa": "secret"}, "https://brain.local:8443")
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
    assert desk.holders.get(CASA) is second
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
        on_release=lambda endpoint: homed.append(True),
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
        on_release=lambda endpoint: homed.append(True),
    )
    gone, next_one = FakeEndpoint("gone"), FakeEndpoint("next")
    desk.claim(gone, now=0.0)

    assert desk.claim(next_one, now=ANSWERING_SECONDS + 1) is True
    assert homed == [True]


def test_a_release_that_frees_nothing_does_not_move_his_voice() -> None:
    homed = []
    desk = RemoteDesk(
        on_utterance=lambda pcm, endpoint: None,
        on_release=lambda endpoint: homed.append(True),
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


async def _socket(
    desk: RemoteDesk, guard: Guard | None = None, registro=None
) -> tuple[TestClient, web.Application]:
    """The one way any test here stands up a live `/ws` socket.

    Defaults reproduce the two byte-ceiling tests' original fixture
    exactly (a single `casa` secret, no register), so passing neither
    argument changes nothing for them. A test that needs a real person
    behind the socket — the wire-level `enrolled` test below — passes
    its own `guard` and `registro` instead of standing up a second app.
    """
    if guard is None:
        guard = Guard({"casa": "s" * 32}, "https://brain.local:8443")
    app = web.Application()
    app.router.add_get("/ws", _handler(desk, guard, registro, None))
    client = TestClient(TestServer(app))
    await client.start_server()
    return client, app


async def test_the_socket_refuses_an_unknown_token() -> None:
    """A stranger's token must stay a refusal, never fall through to
    `casa` — `casa` is what an unattributable DESK turn is, which is a
    different thing from a wrong secret offered by a client."""
    desk = RemoteDesk(on_utterance=lambda pcm, endpoint: None)
    app = web.Application()
    app.router.add_get(
        "/ws",
        _handler(
            desk, Guard({"casa": "s" * 32}, "https://brain.local:8443"), None, None
        ),
    )
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        with pytest.raises(WSServerHandshakeError):
            await client.ws_connect("/ws?t=" + "x" * 32)
    finally:
        await client.close()


async def test_the_connection_carries_the_person_whose_secret_it_used() -> None:
    """The endpoint the handler builds knows whose it is from the
    roster lookup made when the socket was opened — never from
    anything the client itself says. A phone offering `marta`'s secret
    must produce an endpoint whose `persona` is `marta`, not `casa` and
    not whatever the client might claim."""
    seen: list[object] = []
    desk = RemoteDesk(on_utterance=lambda pcm, endpoint: seen.append(endpoint))
    marta_secreto = "m" * 32
    guard = Guard(
        {"casa": "c" * 32, "marta": marta_secreto},
        "https://brain.local:8443",
    )
    app = web.Application()
    app.router.add_get("/ws", _handler(desk, guard, None, None))
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        ws = await client.ws_connect("/ws?t=" + marta_secreto)
        await ws.send_json({"type": "start", "rate": 8000})
        await ws.send_bytes(b"\x01\x02")
        await ws.send_json({"type": "end"})
        for _ in range(50):
            await asyncio.sleep(0.02)
            if seen:
                break
        await ws.close()
    finally:
        await client.close()

    assert seen, "the utterance never arrived"
    assert seen[0].persona == "marta"


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
        # The handshake's own "enrolled" frame arrives first, ahead of
        # anything this test sends — consumed and ignored here, since
        # whose phone this is is a different task's assertion.
        await asyncio.wait_for(ws.receive_json(), timeout=5)
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


def test_the_enrolment_window_can_be_moved_without_touching_code(monkeypatch) -> None:
    """The user, 2026-09-01: five minutes is short if you are not already
    standing at the machine.

    It stays short by default, because the number is not arbitrary — it
    is how long the shared secret sits readable to anyone on the wifi
    with a browser. But which minute that is belongs to whoever owns the
    house, not to this file.
    """
    import importlib

    from jarvis_widget import remote

    monkeypatch.setenv("JARVIS_WIDGET_ENROLMENT_SECONDS", "900")
    reloaded = importlib.reload(remote)
    try:
        assert reloaded.ENROLMENT_SECONDS == 900.0
    finally:
        monkeypatch.delenv("JARVIS_WIDGET_ENROLMENT_SECONDS")
        importlib.reload(remote)

    assert remote.ENROLMENT_SECONDS == 300.0


def test_opening_a_window_writes_that_persons_qr() -> None:
    """The QR is per-person now: two people opening the window in turn
    must not get the same image, or the second phone enrols as the
    first — which the box would then be unable to tell apart, since the
    token IS the identity."""
    from jarvis_widget.remote import Enrolment

    escritos: list[str] = []
    enrolment = Enrolment()
    enrolment.attach_qr(escritos.append)

    enrolment.abrir("Nata", now=0.0)
    enrolment.abrir("Orelvis", now=1.0)

    assert len(escritos) == 2
    assert escritos[0] != escritos[1]


def test_a_window_with_no_qr_writer_still_opens() -> None:
    """`attach_qr` is optional the way `attach` already is: the unit
    tests that only drive the clock must not need a CA on disk."""
    from jarvis_widget.remote import Enrolment

    enrolment = Enrolment()
    enrolment.abrir("Nata", now=0.0)

    assert enrolment.persona(now=1.0) == "nata"


def test_the_qr_is_not_rewritten_when_writing_it_fails() -> None:
    """An unwritable QR must not take the window down with it: the
    welcome page is still a way in, and a raised exception here would
    reach `tools/enrolar.py`'s file watcher, which has nowhere to put
    one."""
    from jarvis_widget.remote import Enrolment

    def explota(_payload: str) -> None:
        raise OSError("disco lleno")

    enrolment = Enrolment()
    enrolment.attach_qr(explota)

    enrolment.abrir("Nata", now=0.0)

    assert enrolment.persona(now=1.0) == "nata"


def test_a_failed_qr_write_does_not_leave_the_previous_persons_qr_readable(
    tmp_path,
) -> None:
    """Marta is enrolled Tuesday; her QR lands at the one fixed path
    `_mostrar_qr` always shows. If `hijo`'s enrolment on Friday fails to
    write a new one — a full disk, a dangling symlink, all failures
    `save_roster`/`write_qr` already handle elsewhere as ordinary — the
    strip must not go on showing Marta's PNG on `hijo`'s window: that is
    her live credential, and his phone would connect as her.

    `Enrolment.abrir` is fixed to delete whatever is at the QR path
    BEFORE attempting the write, so a failure below leaves nothing
    rather than something wrong — the file the band would show simply
    is not there any more."""
    from jarvis_widget.remote import Enrolment

    qr_path = tmp_path / "enrol-qr.png"
    qr_path.write_bytes(b"la credencial en vivo de marta")

    def explota(_payload: str) -> None:
        raise OSError("disco lleno")

    enrolment = Enrolment()
    enrolment.attach_qr(explota, qr_path)

    enrolment.abrir("hijo", now=0.0)

    assert not qr_path.exists()


def test_a_qr_that_cannot_be_deleted_does_not_open_the_window() -> None:
    """The delete that clears the previous person's QR sits outside
    `missing_ok`'s reach: a `PermissionError` or a read-only mount makes
    `unlink` raise rather than silently no-op. Going on to open the
    window regardless would risk showing the very failure this ordering
    exists to prevent — a stale, live QR for someone else, on this
    person's window, undeleted because the delete itself failed. So this
    must refuse the window rather than gamble on what is still on disk:
    neither the QR writer nor `open_enrolment` may run."""
    from jarvis_widget.remote import Enrolment

    class NoBorrable:
        def unlink(self, missing_ok: bool = False) -> None:
            raise PermissionError("solo lectura")

    escritos: list[str] = []
    enrolment = Enrolment()
    enrolment.attach_qr(escritos.append, NoBorrable())

    enrolment.abrir("hijo", now=0.0)

    assert escritos == []
    assert enrolment.persona(now=0.0) is None
    assert not enrolment.is_open(now=0.0)


def test_the_journal_says_which_of_two_failures_happened(tmp_path) -> None:
    """A `save_roster` failure means no credential exists at all for this
    person; a `write_qr` failure means one exists on disk while the
    strip has nothing to show. Different next steps for whoever reads
    the journal, so the log line must say which one happened rather than
    one generic message for both."""
    import io

    from loguru import logger

    from jarvis_widget.remote import Enrolment, QrWriteError, RosterWriteError

    sink = io.StringIO()
    handler = logger.add(sink, level="DEBUG")
    try:
        no_credential = Enrolment()

        def sin_credencial(_persona: str) -> None:
            raise RosterWriteError("disco lleno")

        no_credential.attach_qr(sin_credencial, tmp_path / "a.png")
        no_credential.abrir("hijo", now=0.0)

        credential_exists = Enrolment()

        def sin_dibujar(_persona: str) -> None:
            raise QrWriteError("disco lleno")

        credential_exists.attach_qr(sin_dibujar, tmp_path / "b.png")
        credential_exists.abrir("hijo", now=0.0)
    finally:
        logger.remove(handler)

    logged = sink.getvalue()
    assert "no existe credencial" in logged
    assert "ya existe pero" in logged


def test_the_display_name_comes_from_the_register(tmp_path) -> None:
    """`persona_for` answers with an id; a person reads a name. The
    contract's whole purpose is somebody enrolling four phones in a row
    being able to tell which one they just did, so "orelvis" where the
    house says "Orelvis" is a worse answer than it looks."""
    import numpy as np

    from jarvis_widget.casa import Registro
    from jarvis_widget.remote import nombre_para

    registro = Registro(tmp_path / "casa.json")
    registro.emparejar("Orelvis", [np.array([1.0, 0.0, 0.0], dtype=np.float32)])

    assert nombre_para(registro, "orelvis") == "Orelvis"


def test_an_unknown_id_falls_back_to_itself(tmp_path) -> None:
    from jarvis_widget.casa import Registro
    from jarvis_widget.remote import nombre_para

    registro = Registro(tmp_path / "casa.json")

    assert nombre_para(registro, "nata") == "nata"


def test_a_register_that_cannot_be_read_does_not_break_the_handshake(tmp_path) -> None:
    """This runs inside a socket handler. `casa.Registro` reads from
    disk on every call by its own contract, so an unreadable file must
    degrade to the id, never raise into a connection that was otherwise
    fine."""
    from jarvis_widget.remote import nombre_para

    class Roto:
        def personas(self):
            raise OSError("ilegible")

    assert nombre_para(Roto(), "nata") == "nata"


async def test_the_enrolled_frame_names_the_phone_before_anything_else(
    tmp_path,
) -> None:
    """The wire contract, not `nombre_para` in isolation: a real socket,
    through the real `_handler`, must say whose phone this is — by
    DISPLAY name, not the id `persona_for` resolves to — before any
    other frame. The ordering matters because the iPhone app is being
    written against it; the exact value matters because a typo in the
    key, the wrong value, or sending the id instead of the name would
    otherwise still pass the whole suite (`nombre_para`'s own tests
    never touch a socket at all)."""
    import numpy as np

    from jarvis_widget.casa import Registro

    registro = Registro(tmp_path / "casa.json")
    registro.emparejar("Orelvis", [np.array([1.0, 0.0, 0.0], dtype=np.float32)])

    secreto = "o" * 32
    guard = Guard({"orelvis": secreto}, "https://brain.local:8443")
    desk = RemoteDesk(on_utterance=lambda pcm, endpoint: None)
    client, _ = await _socket(desk, guard=guard, registro=registro)
    try:
        ws = await client.ws_connect("/ws?t=" + secreto)
        first = await asyncio.wait_for(ws.receive_json(), timeout=5)
        assert first == {"type": "enrolled", "name": "Orelvis"}
    finally:
        await client.close()


def test_the_envelope_points_at_the_address_not_the_name(monkeypatch) -> None:
    """The owner's decision, 2026-09-06, after a real iPhone reported it
    could not reach the box at all.

    `brain.local` depends on mDNS resolving on the phone, and that is a
    second thing to go wrong on top of everything else — on THIS box the
    name resolves to a Docker bridge, never to the LAN. The leaf's SAN
    carries `DNS:brain.local, IP Address:<lan>`, so either verifies; the
    address removes a dependency, at the price the owner accepted: a
    DHCP change means re-enrolling.
    """
    from jarvis_widget.remote import host_del_sobre

    monkeypatch.delenv("JARVIS_WIDGET_ENVELOPE_HOST", raising=False)
    assert host_del_sobre(lambda: "192.168.1.40") == "192.168.1.40"


def test_the_envelope_host_can_be_overridden(monkeypatch) -> None:
    """One switch for the envelope alone. `JARVIS_WIDGET_REMOTE_NAME`
    cannot do this job: it moves the certificate's CN and SAN with it,
    so there was no way to serve a name and hand out an address."""
    from jarvis_widget.remote import host_del_sobre

    monkeypatch.setenv("JARVIS_WIDGET_ENVELOPE_HOST", "brain.local")
    assert host_del_sobre(lambda: "192.168.1.40") == "brain.local"
