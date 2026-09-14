"""The phone sees the same local transcription Hermes receives, privately."""

import ast
import asyncio
from pathlib import Path
import sys
import time
from types import SimpleNamespace
import uuid

from jarvis_widget.remote import WebEndpoint
from jarvis_widget.replies import PhoneOutput, ReplyRoutes
from jarvis_widget.stt import TranscriptionContext


async def test_transcript_is_sent_before_reply_text_and_done():
    sent = []

    class Socket:
        async def send_json(self, frame):
            sent.append(frame)

    endpoint = WebEndpoint(
        Socket(), "synthetic", "synthetic", asyncio.get_running_loop()
    )
    endpoint.transcript("Trabajo de Alfresco")
    endpoint.text("Respuesta")
    endpoint.done()
    await asyncio.sleep(0.01)
    assert sent == [
        {"type": "transcript", "text": "Trabajo de Alfresco"},
        {"type": "text", "text": "Respuesta"},
        {"type": "done"},
    ]


def test_closed_phone_never_receives_a_late_transcript():
    transcripts = []
    phone = SimpleNamespace(
        persona="synthetic", transcript=transcripts.append, done=lambda: None
    )
    output = PhoneOutput(phone, lambda: None)
    output.transcript("Primera pregunta")
    output.done()
    output.transcript("Pregunta antigua")
    assert transcripts == ["Primera pregunta"]


async def test_dispatch_uses_exactly_the_same_local_text_for_phone_and_hermes():
    events = []
    phrase = "El perfil que estoy buscando es de Alfresco."
    pcm = b"\x00\x01" * 100
    phone = SimpleNamespace(
        persona="synthetic",
        transcript=lambda text: events.append(("transcript", text)),
        done=lambda: None,
    )
    routes = ReplyRoutes(
        SimpleNamespace(finish=lambda destination: destination.done()), lambda _: None
    )

    context = TranscriptionContext()
    context.remember("synthetic", "Buscas un puesto de consultor Alfresco.")

    def transcribe(received, *, context):
        assert received == pcm
        assert "Alfresco" in context
        return phrase

    async def send_chat(text, **kwargs):
        assert kwargs["chat_id"] == "synthetic"
        events.append(("dispatch", text))

    namespace = {
        "asyncio": asyncio,
        "uuid": uuid,
        "sys": sys,
        "time": time,
        "INPUT_RATE": 16000,
        "_DUMP_DIR": False,
        "ULTIMO_HABLANTE": {},
        "remote_desk": SimpleNamespace(endpoint_for=lambda _: phone),
        "replies": routes,
        "transcription_context": context,
        "transcriber": SimpleNamespace(ready=True, transcribe=transcribe),
        "echo": SimpleNamespace(clean=lambda text, _: text),
        "machine": SimpleNamespace(error=lambda _: None),
        "_atendido_por_encuentro": lambda *_: False,
        "spoken_text": lambda text, *_: text,
        "wake": SimpleNamespace(named=False),
        "persona_de": lambda endpoint, *_: endpoint.persona,
        "client": SimpleNamespace(send_chat=send_chat),
    }
    source = Path(__file__).parents[1] / "jarvis_widget" / "__main__.py"
    definitions = [
        node
        for node in ast.walk(ast.parse(source.read_text()))
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "dispatch"
    ]
    assert len(definitions) == 1
    exec(
        compile(ast.Module(body=definitions, type_ignores=[]), str(source), "exec"),
        namespace,
    )
    await namespace["dispatch"](pcm, phone)
    assert events == [("transcript", phrase), ("dispatch", phrase)]
