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
