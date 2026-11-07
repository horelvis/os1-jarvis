"""Exercise the actual dispatch/reply closures without constructing a GTK window."""

import ast
import asyncio
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from jarvis_widget.__main__ import persona_de, spoken_text
from jarvis_widget.remote import RemoteDesk
from jarvis_widget.replies import ReplyRoutes
from jarvis_widget.speech import (
    Speaker,
    TurnChunkers,
    is_system_message,
    unwrap_delivery,
)
from jarvis_widget.wake import WakeWord


class Phone:
    def __init__(self, persona: str = "marta") -> None:
        self.persona = persona
        self.events = []
        self.ended = asyncio.Event()

    def write(self, pcm: bytes) -> None:
        self.events.append(("audio", pcm))

    def text(self, text: str) -> None:
        self.events.append(("text", text))

    def done(self) -> None:
        self.events.append(("done",))
        self.ended.set()

    def refuse(self) -> None:
        self.events.append(("busy",))


class Pipeline:
    def __init__(self) -> None:
        self.room = Phone("room")
        self.speaker = Speaker(self.room)
        self.chunkers = TurnChunkers()

        def release(phone: object) -> None:
            self.chunkers.drop(phone.persona)
            self.routes.disconnect(phone)

        self.desk = RemoteDesk(
            on_utterance=lambda *_: None,
            on_release=release,
            on_interrupt=lambda phone: self.routes.interrupt(phone),
        )
        self.routes = ReplyRoutes(self.speaker, self.desk.release)
        self.client = SimpleNamespace(send_chat=AsyncMock())
        self.transcriber = SimpleNamespace(ready=True, transcribe=lambda _: "Hola")
        self.env = {
            "asyncio": asyncio,
            "time": time,
            "sys": sys,
            "INPUT_RATE": 16000,
            "_DUMP_DIR": None,
            "remote_desk": self.desk,
            "replies": self.routes,
            "system_replies": set(),
            "transcriber": self.transcriber,
            "locutor": SimpleNamespace(vector=lambda _: None),
            "machine": SimpleNamespace(
                error=lambda _: None, token=lambda _: None, done=lambda: None
            ),
            "echo": SimpleNamespace(clean=lambda text, _: text),
            "_atendido_por_encuentro": lambda *_: False,
            "spoken_text": spoken_text,
            "wake": WakeWord(""),
            "huellas_actualizadas": lambda *_: None,
            "registro": None,
            "huellas_cache": {},
            "persona_de": persona_de,
            "ULTIMO_HABLANTE": {},
            "client": self.client,
            "chunkers": self.chunkers,
            "say": self.speaker.say,
            "is_system_message": is_system_message,
            "unwrap_delivery": unwrap_delivery,
            "_apply_error_to_wake_window": lambda *_: None,
        }
        # Compile the production closures themselves, rather than a test copy of
        # dispatch. Their GTK-free dependencies are supplied by this harness.
        source = Path(__file__).parents[1] / "jarvis_widget" / "__main__.py"
        tree = ast.parse(source.read_text())
        names = {"dispatch", "on_token", "on_done", "on_error", "on_disconnect"}
        nodes = [
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name in names
        ]
        assert {node.name for node in nodes} == names
        exec(
            compile(ast.Module(body=nodes, type_ignores=[]), str(source), "exec"),
            self.env,
        )

    def prepare(self, phone: Phone) -> None:
        assert self.desk.claim(phone)
        self.desk.finish(b"\x00\x00" * 100, phone)

    async def submit(self, phone: Phone) -> None:
        self.prepare(phone)
        await self.env["dispatch"](b"\x00\x00" * 100, phone)

    def answer(self, phone: Phone, text: str = "Esta respuesta es privada.") -> None:
        self.env["on_token"](text, phone.persona)
        self.env["on_done"](0, phone.persona)

    async def settled(self, phone: Phone) -> None:
        self.speaker.start()
        await asyncio.wait_for(phone.ended.wait(), 1)


@pytest.fixture
async def pipeline(monkeypatch):
    from Hermes.plugins.jarvis_voice import tts

    async def stream(clause, client=None):
        yield b"\x01\x02", "fake"

    monkeypatch.setattr(tts, "new_client", lambda: object())
    monkeypatch.setattr(tts, "stream", stream)
    instance = Pipeline()
    yield instance
    for worker in instance.speaker._workers:
        worker.cancel()
    await asyncio.gather(*instance.speaker._workers, return_exceptions=True)


@pytest.mark.parametrize(
    "exit_kind", ["empty", "echo", "welcome", "stt_error", "send_error"]
)
async def test_every_dispatch_exit_finishes_once(pipeline, exit_kind):
    phone = Phone()
    if exit_kind == "empty":
        pipeline.transcriber.transcribe = lambda _: ""
    elif exit_kind == "echo":
        pipeline.env["echo"].clean = lambda *_: ""
    elif exit_kind == "welcome":

        def welcome(text, vector, destination):
            pipeline.speaker.say("Hola, bienvenido.", destination)
            return True

        pipeline.env["_atendido_por_encuentro"] = welcome
    elif exit_kind == "stt_error":

        def fail(_):
            raise RuntimeError("fake transcription failure")

        pipeline.transcriber.transcribe = fail
    else:
        pipeline.client.send_chat.side_effect = RuntimeError("fake send failure")
    await pipeline.submit(phone)
    await pipeline.settled(phone)
    assert phone.events[-1] == ("done",)
    assert phone.events.count(("done",)) == 1
    assert not pipeline.desk.busy
    assert pipeline.routes.get(phone.persona) is None
    assert pipeline.room.events == []


async def test_private_delivery_finishes_after_audio_and_only_once(pipeline):
    phone = Phone()
    await pipeline.submit(phone)
    pipeline.answer(phone)
    pipeline.env["on_done"](0, phone.persona)
    assert pipeline.desk.busy
    assert not phone.ended.is_set()
    await pipeline.settled(phone)
    assert [e[0] for e in phone.events] == ["text", "audio", "done"]
    assert not pipeline.desk.busy
    assert pipeline.room.events == []


async def test_disconnect_cannot_redirect_late_response_to_replacement_or_room(
    pipeline,
):
    old, new = Phone(), Phone()
    await pipeline.submit(old)
    pipeline.desk.release(old)
    await pipeline.submit(new)
    assert new.events == [("busy",)]
    pipeline.answer(old)
    assert old.events == [("done",)]
    assert new.events == [("busy",)]
    assert pipeline.room.events == []
    assert pipeline.client.send_chat.await_count == 1
    assert pipeline.routes.get(old.persona) is None


async def test_two_people_keep_their_own_destination_and_terminal(pipeline):
    first, second = Phone("marta"), Phone("lucia")
    await pipeline.submit(first)
    await pipeline.submit(second)
    pipeline.answer(second)
    pipeline.answer(first)
    await pipeline.settled(first)
    await pipeline.settled(second)
    for phone in (first, second):
        assert [e[0] for e in phone.events] == ["text", "audio", "done"]
    assert not pipeline.desk.busy
    assert pipeline.room.events == []


async def test_interruption_closes_once_and_suppresses_late_audio_and_text(pipeline):
    phone = Phone()
    await pipeline.submit(phone)
    pipeline.env["on_token"]("Esta respuesta es privada.", phone.persona)
    pipeline.desk.interrupt(phone)
    pipeline.answer(phone, "Esto ya no debe llegar.")
    await pipeline.settled(phone)
    assert phone.events == [("text", "Esta respuesta es privada."), ("done",)]
    assert pipeline.room.events == []


async def test_error_and_synthesis_failure_still_finish(pipeline, monkeypatch):
    from Hermes.plugins.jarvis_voice import tts

    async def fail(clause, client=None):
        raise RuntimeError("fake synthesis failure")
        yield  # pragma: no cover

    monkeypatch.setattr(tts, "stream", fail)
    phone = Phone()
    await pipeline.submit(phone)
    pipeline.env["on_error"]("No puedo responder ahora.", phone.persona)
    await pipeline.settled(phone)
    assert phone.events == [("done",)]
    assert not pipeline.desk.busy


async def test_muted_answer_and_no_token_done_both_close(pipeline):
    phone = Phone()
    pipeline.env["say"] = lambda *_: None
    await pipeline.submit(phone)
    pipeline.answer(phone)
    await pipeline.settled(phone)
    assert [e[0] for e in phone.events] == ["text", "done"]
    silent = Phone("lucia")
    await pipeline.submit(silent)
    pipeline.env["on_done"](0, silent.persona)
    await pipeline.settled(silent)
    assert silent.events == [("done",)]


async def test_gateway_disconnect_clears_claims_and_silences_queued_output(pipeline):
    phone = Phone()
    await pipeline.submit(phone)
    pipeline.env["on_token"]("Esta respuesta es privada.", phone.persona)
    pipeline.env["on_disconnect"]()
    pipeline.answer(phone)
    await pipeline.settled(phone)
    assert [e[0] for e in phone.events] == ["text", "done"]
    assert not pipeline.desk.busy
    assert pipeline.routes.get(phone.persona) is None
    assert pipeline.room.events == []


async def test_cancelled_dispatch_and_disconnected_transcription_do_not_send(
    pipeline, monkeypatch
):
    started, resume = asyncio.Event(), asyncio.Event()

    async def pause(fn):
        started.set()
        await resume.wait()
        return fn()

    monkeypatch.setattr(asyncio, "to_thread", pause)
    phone = Phone()
    pipeline.prepare(phone)
    task = asyncio.create_task(pipeline.env["dispatch"](b"\x00\x00", phone))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await pipeline.settled(phone)
    assert phone.events == [("done",)]
    pipeline.client.send_chat.assert_not_awaited()


async def test_system_done_does_not_release_a_pending_real_reply(pipeline):
    phone = Phone()
    await pipeline.submit(phone)
    pipeline.env["on_token"]("↪ Redirected current run", phone.persona)
    pipeline.env["on_done"](0, phone.persona)
    assert pipeline.desk.busy
    assert not phone.ended.is_set()
    pipeline.answer(phone)
    await pipeline.settled(phone)
    assert phone.events.count(("done",)) == 1


async def test_repeated_end_and_start_while_answering_cannot_dispatch_twice(pipeline):
    phone = Phone()
    dispatched = []
    pipeline.desk._on_utterance = lambda pcm, endpoint: dispatched.append(pcm)
    pipeline.prepare(phone)
    assert not pipeline.desk.claim(phone)
    pipeline.desk.finish(b"second", phone)
    assert len(dispatched) == 1


async def test_an_admitted_room_reply_stays_in_the_room(pipeline):
    await pipeline.env["dispatch"](b"\x00\x00", None)
    pipeline.env["on_token"]("Esta respuesta es para la sala.", "casa")
    pipeline.env["on_done"](0, "casa")
    assert pipeline.speaker._queue.get_nowait()[0] is None
    assert pipeline.routes.get("casa") is None


async def test_unknown_named_reply_is_not_an_unsolicited_room_reply(pipeline):
    pipeline.env["on_token"]("Private late answer", "unknown")
    pipeline.env["on_error"]("Private late error", "unknown")
    assert pipeline.speaker._queue.empty()
    pipeline.env["on_token"]("Este recordatorio es para la sala.", None)
    assert pipeline.speaker._queue.get_nowait()[0] is None
