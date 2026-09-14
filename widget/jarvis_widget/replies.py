"""Admission-time destinations for the legacy, conversation-tagged voice path.

Owned by the gateway loop. One outstanding reply per conversation prevents a
disconnect or a re-press from replacing its destination before settlement.
End-to-end request correlation remains a separate gateway protocol change.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from loguru import logger

_UNSET = object()


class PhoneOutput:
    """One turn's private sink, including an idempotent terminal notification."""

    def __init__(self, phone: object, on_done: Callable[[], None]) -> None:
        self.phone = phone
        self.persona = phone.persona
        self.closed = False
        self._on_done = on_done

    def write(self, pcm: bytes) -> None:
        if not self.closed:
            self.phone.write(pcm)

    def text(self, text: str) -> None:
        if not self.closed:
            self.phone.text(text)

    def transcript(self, text: str) -> None:
        """The local transcription belongs only to the original phone."""
        if not self.closed:
            self.phone.transcript(text)

    def ficha(
        self,
        md: str,
        tipo: str,
        fuente: str,
        correcta: str | None,
        elegida: str | None,
    ) -> None:
        if not self.closed:
            self.phone.ficha(md, tipo, fuente, correcta, elegida)

    def done(self) -> None:
        if self.closed:
            return
        self.closed = True
        try:
            self.phone.done()
        except Exception:
            logger.debug("Private reply terminal could not reach its endpoint")
        finally:
            self._on_done()


@dataclass(eq=False)
class Reply:
    request_id: str
    chat_id: str
    phone: object | None
    destination: PhoneOutput | None = None
    settled: bool = False

    @property
    def accepts_content(self) -> bool:
        return not self.settled and (
            self.destination is None or not self.destination.closed
        )


class ReplyRoutes:
    """Keep the original sink until both upstream and delivery have settled."""

    def __init__(self, speaker: object, release: Callable[[object], None]) -> None:
        self._speaker = speaker
        self._release = release
        self._replies: dict[str, Reply] = {}

    def open(
        self, request_id: str, chat_id: str | object, phone: object | None = _UNSET
    ) -> Reply | None:
        # The two-argument form was B1's public seam. Keeping it while the
        # widget and gateway upgrade together costs no alternate wire behavior.
        if phone is _UNSET:
            phone = chat_id
            chat_id = request_id
        assert isinstance(chat_id, str)
        if request_id in self._replies:
            return None
        reply = Reply(request_id, chat_id, phone)
        if phone is not None:
            reply.destination = PhoneOutput(phone, lambda: self._delivered(reply))
        self._replies[request_id] = reply
        return reply

    def get(self, request_id: str | None) -> Reply | None:
        return self._replies.get(request_id)

    def write_pcm(
        self,
        request_id: str,
        pcm: bytes,
        room_write: Callable[[bytes], None] | None,
    ) -> bool:
        """Deliver Hermes PCM to the same admission-time sink as its text.

        The widget connection relays phone turns too. A PCM capability on
        that connection does not make every reply a room reply. Unknown or
        closed private routes must never fall back to the room.
        """
        reply = self.get(request_id)
        if reply is None or not reply.accepts_content:
            logger.debug("Addressed PCM discarded: no active reply destination")
            return False
        if reply.destination is not None:
            reply.destination.write(pcm)
        elif room_write is not None:
            room_write(pcm)
        else:
            logger.debug("Room PCM discarded: room voice is muted")
            return False
        return True

    def accept(self, client_request_id: str, turn_id: str) -> Reply | None:
        """Replace the local nonce with Hermes' canonical turn id once."""
        reply = self._replies.get(client_request_id)
        if reply is None or turn_id in self._replies:
            return None
        del self._replies[client_request_id]
        reply.request_id = turn_id
        self._replies[turn_id] = reply
        return reply

    def finish(self, reply: Reply) -> None:
        if reply.settled:
            return
        reply.settled = True
        if reply.destination is None or reply.destination.closed:
            self._forget(reply)
        else:
            # The one Speaker worker consumes this after the last queued PCM.
            self._speaker.finish(reply.destination)

    def interrupt(self, phone: object) -> Reply | None:
        reply = next(
            (item for item in self._replies.values() if item.phone is phone), None
        )
        if reply is not None:
            # Silence queued/in-flight output without pretending to cancel Hermes.
            # The closed sink also rejects later text and PCM from the same turn.
            reply.destination.done()
        return reply

    def disconnect(self, phone: object) -> None:
        # Keep unresolved ownership: a reconnect must not inherit the old reply.
        self.interrupt(phone)

    def reset(self) -> None:
        for reply in list(self._replies.values()):
            if reply.destination is not None:
                reply.destination.done()
            self.finish(reply)

    def _delivered(self, reply: Reply) -> None:
        if reply.settled:
            self._forget(reply)
        if reply.phone is not None:
            self._release(reply.phone)

    def _forget(self, reply: Reply) -> None:
        if self._replies.get(reply.request_id) is reply:
            del self._replies[reply.request_id]
