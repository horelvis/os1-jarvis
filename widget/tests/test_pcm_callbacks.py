"""Exercise the actual nested delivery callbacks without starting GTK/audio.

The callbacks are compiled from __main__, not duplicated in the fixture. The
room and phone sinks are recording fakes; routing and message filters are real.
"""

import ast
from pathlib import Path
from types import SimpleNamespace
import time

from jarvis_widget.replies import ReplyRoutes
from jarvis_widget.speech import (
    TurnChunkers,
    is_system_message,
    limit_reply_for_speech,
    unwrap_delivery,
)
from jarvis_widget.stt import TranscriptionContext


def callbacks():
    events = []
    released = []
    room = []
    phone = SimpleNamespace(
        persona="synthetic",
        text=lambda text: events.append(("text", text)),
        write=lambda pcm: events.append(("audio", pcm)),
        done=lambda: events.append(("done",)),
    )
    speaker = SimpleNamespace(finish=lambda destination: destination.done())
    routes = ReplyRoutes(speaker, released.append)
    namespace = {
        "replies": routes,
        "transcription_context": TranscriptionContext(),
        "pcm_turns": set(),
        "system_replies": set(),
        "chunkers": TurnChunkers(),
        "wave": SimpleNamespace(switches=SimpleNamespace(voice_on=True)),
        "player": SimpleNamespace(write=room.append),
        "machine": SimpleNamespace(token=lambda _: None, done=lambda: None),
        "echo": SimpleNamespace(spoke=lambda *_: None),
        "wake": SimpleNamespace(answered=lambda _: None),
        "say": lambda *_: None,
        "is_system_message": is_system_message,
        "limit_reply_for_speech": limit_reply_for_speech,
        "unwrap_delivery": unwrap_delivery,
        "time": time,
    }
    source = Path(__file__).parents[1] / "jarvis_widget" / "__main__.py"
    names = {"on_pcm_start", "on_pcm", "on_token", "on_done"}
    definitions = [
        node
        for node in ast.walk(ast.parse(source.read_text()))
        if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    assert len(definitions) == len(names)
    exec(
        compile(ast.Module(body=definitions, type_ignores=[]), str(source), "exec"),
        namespace,
    )
    return namespace, routes, phone, events, released, room


def test_three_phone_turns_including_laughter_deliver_audio_and_terminal():
    cb, routes, phone, events, released, room = callbacks()
    replies = ["Buenas tardes.", "<laughter>Un chiste.</laughter>", "Hasta luego."]
    for index, text in enumerate(replies):
        turn = f"turn-{index}"
        routes.open(turn, phone.persona, phone)
        cb["on_pcm_start"](turn)
        cb["on_token"](text, phone.persona, turn)
        cb["on_pcm"](turn, b"\x01\x02")
        cb["on_done"](0, phone.persona, turn)
        assert routes.get(turn) is None
        assert events[-3:] == [("text", text), ("audio", b"\x01\x02"), ("done",)]
    assert "Un chiste." in cb["transcription_context"].snapshot(phone.persona)
    assert cb["transcription_context"].snapshot("another-person") == ""
    assert released == [phone, phone, phone]
    assert room == []


def test_filtered_system_text_cannot_swallow_an_admitted_phone_terminal():
    cb, routes, phone, events, released, room = callbacks()
    routes.open("turn-1", phone.persona, phone)
    cb["on_token"]("⚠️ A synthetic system notice", phone.persona, "turn-1")
    cb["on_done"](0, phone.persona, "turn-1")
    assert events == [("done",)]
    cb["on_done"](0, phone.persona, "turn-1")
    assert events == [("done",)]
    assert released == [phone]
    assert routes.get("turn-1") is None
    assert room == []


def test_laughter_expression_is_speech_not_a_system_symbol():
    for text in [
        "<laughter>Un chiste.</laughter>",
        "  <laughter>Ja.",
        "[laughter] Ja.",
    ]:
        assert not is_system_message(text)
    assert is_system_message("⚠️ System notice")
    assert is_system_message("<internal>not an allowed voice marker</internal>")
