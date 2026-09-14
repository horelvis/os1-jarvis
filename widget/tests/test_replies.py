"""Private reply destinations captured when a phone turn is admitted."""

import asyncio

import pytest

from jarvis_widget.replies import ReplyRoutes
from jarvis_widget.speech import Speaker


class Phone:
    def __init__(self, persona: str = "marta") -> None:
        self.persona = persona
        self.events: list[tuple[str, bytes | str] | tuple[str]] = []

    def write(self, pcm: bytes) -> None:
        self.events.append(("audio", pcm))

    def text(self, text: str) -> None:
        self.events.append(("text", text))

    def ficha(self, md, tipo, fuente, correcta, elegida) -> None:
        self.events.append(("ficha", md, tipo, fuente, correcta, elegida))

    def done(self) -> None:
        self.events.append(("done",))


class Room:
    def write(self, _pcm: bytes) -> None:
        pass

    def stop(self) -> None:
        pass


@pytest.fixture
async def routes(monkeypatch):
    from Hermes.plugins.jarvis_voice import tts

    async def stream(_clause, client=None):
        yield b"\x01\x02", "fake"

    monkeypatch.setattr(tts, "new_client", lambda: object())
    monkeypatch.setattr(tts, "stream", stream)
    released: list[Phone] = []
    speaker = Speaker(Room())
    speaker.start()
    yield ReplyRoutes(speaker, released.append), released
    for worker in speaker._workers:
        worker.cancel()
    await asyncio.gather(*speaker._workers, return_exceptions=True)


async def test_private_route_keeps_its_original_phone_until_delivery(routes) -> None:
    reply_routes, released = routes
    old, replacement = Phone(), Phone()
    reply = reply_routes.open(old.persona, old)

    assert reply is not None
    assert reply_routes.open(replacement.persona, replacement) is None
    reply.destination.text("Sólo para el teléfono original.")
    reply_routes._speaker.say("Una respuesta privada.", reply.destination)
    reply_routes.finish(reply)

    for _ in range(50):
        if old.events and old.events[-1] == ("done",):
            break
        await asyncio.sleep(0.01)

    assert [event[0] for event in old.events] == ["text", "audio", "done"]
    assert replacement.events == []
    assert released == [old]
    assert reply_routes.get(old.persona) is None


def test_disconnect_closes_the_old_private_sink_and_rejects_late_output(routes) -> None:
    reply_routes, released = routes
    phone = Phone()
    reply = reply_routes.open(phone.persona, phone)

    assert reply is not None
    reply_routes.disconnect(phone)
    reply.destination.text("Esto llega tarde.")
    reply.destination.write(b"\x01\x02")
    reply_routes.finish(reply)

    assert phone.events == [("done",)]
    assert released == [phone]
    assert reply_routes.get(phone.persona) is None


def test_reset_closes_each_private_route_once(routes) -> None:
    reply_routes, released = routes
    marta, lucia = Phone("marta"), Phone("lucia")
    assert reply_routes.open(marta.persona, marta) is not None
    assert reply_routes.open(lucia.persona, lucia) is not None

    reply_routes.reset()
    reply_routes.reset()

    assert marta.events == [("done",)]
    assert lucia.events == [("done",)]
    assert released == [marta, lucia]


def test_private_route_sends_the_teacher_card_only_to_its_phone(routes) -> None:
    reply_routes, _released = routes
    phone = Phone()
    reply = reply_routes.open("request-1", phone.persona, phone)

    assert reply is not None
    reply.destination.ficha("## Pregunta\n\n- a", "pregunta", "Cambridge", None, None)

    assert phone.events == [
        ("ficha", "## Pregunta\n\n- a", "pregunta", "Cambridge", None, None)
    ]


def test_room_route_has_no_phone_destination(routes) -> None:
    reply_routes, _released = routes

    reply = reply_routes.open("request-1", "casa", None)

    assert reply is not None
    assert reply.destination is None


def test_hermes_acceptance_replaces_the_client_nonce(routes) -> None:
    reply_routes, _released = routes
    reply = reply_routes.open("client-1", "casa", None)

    assert reply_routes.accept("client-1", "turn-1") is reply
    assert reply_routes.get("client-1") is None
    assert reply_routes.get("turn-1") is reply


def test_hermes_pcm_reaches_the_original_phone_never_the_room(routes) -> None:
    reply_routes, _released = routes
    phone, other = Phone("marta"), Phone("lucia")
    room: list[bytes] = []
    reply_routes.open("client-1", phone.persona, phone)
    reply_routes.open("client-2", other.persona, other)
    reply_routes.accept("client-1", "turn-1")
    reply_routes.accept("client-2", "turn-2")

    assert reply_routes.write_pcm("turn-1", b"\x01\x02", room.append)
    assert reply_routes.write_pcm("turn-2", b"\x03\x04", room.append)

    assert phone.events == [("audio", b"\x01\x02")]
    assert other.events == [("audio", b"\x03\x04")]
    assert room == []


@pytest.mark.parametrize("stop", ["interrupt", "disconnect"])
def test_late_hermes_pcm_cannot_escape_to_room_or_reconnected_phone(
    routes, stop
) -> None:
    reply_routes, _released = routes
    old, replacement = Phone(), Phone()
    room: list[bytes] = []
    reply_routes.open("client-1", old.persona, old)
    reply_routes.accept("client-1", "turn-1")
    getattr(reply_routes, stop)(old)
    reply_routes.open("client-2", replacement.persona, replacement)
    reply_routes.accept("client-2", "turn-2")

    assert not reply_routes.write_pcm("turn-1", b"\x01\x02", room.append)
    assert reply_routes.write_pcm("turn-2", b"\x03\x04", room.append)

    assert old.events == [("done",)]
    assert replacement.events == [("audio", b"\x03\x04")]
    assert room == []


def test_unknown_or_finished_pcm_does_not_default_to_room(routes) -> None:
    reply_routes, _released = routes
    room: list[bytes] = []
    reply = reply_routes.open("turn-1", "casa", None)
    assert reply is not None
    reply_routes.finish(reply)

    assert not reply_routes.write_pcm("unknown", b"\x01\x02", room.append)
    assert not reply_routes.write_pcm("turn-1", b"\x01\x02", room.append)
    assert room == []


def test_desktop_pcm_obeys_the_room_voice_switch(routes) -> None:
    reply_routes, _released = routes
    room: list[bytes] = []
    reply_routes.open("turn-1", "casa", None)

    assert not reply_routes.write_pcm("turn-1", b"\x01\x02", None)
    assert reply_routes.write_pcm("turn-1", b"\x03\x04", room.append)
    assert room == [b"\x03\x04"]


def test_muting_the_room_does_not_mute_a_private_phone(routes) -> None:
    reply_routes, _released = routes
    phone = Phone()
    reply_routes.open("turn-1", phone.persona, phone)

    assert reply_routes.write_pcm("turn-1", b"\x01\x02", None)
    assert phone.events == [("audio", b"\x01\x02")]
