import json

import pytest

from Hermes.plugins.samantha_kiosk.protocol import (
    ProtocolError,
    decode_client,
    done,
    error,
    token,
)


def test_decodes_a_chat_message():
    raw = '{"type": "chat", "message": "hola", "user_id": "primary"}'
    assert decode_client(raw) == {
        "type": "chat",
        "message": "hola",
        "user_id": "primary",
    }


def test_rejects_unknown_type():
    with pytest.raises(ProtocolError):
        decode_client('{"type": "shutdown"}')


def test_rejects_malformed_json():
    with pytest.raises(ProtocolError):
        decode_client("not json at all")


def test_rejects_chat_without_a_message():
    with pytest.raises(ProtocolError):
        decode_client('{"type": "chat", "user_id": "primary"}')


def test_rejects_a_blank_message():
    # An empty turn would reach the model as an empty prompt.
    with pytest.raises(ProtocolError):
        decode_client('{"type": "chat", "message": "   ", "user_id": "x"}')


def test_rejects_chat_without_user_id():
    with pytest.raises(ProtocolError):
        decode_client('{"type": "chat", "message": "hola"}')


def test_rejects_chat_with_non_string_user_id():
    with pytest.raises(ProtocolError):
        decode_client('{"type": "chat", "message": "hola", "user_id": 42}')


def test_rejects_chat_with_blank_user_id():
    with pytest.raises(ProtocolError):
        decode_client('{"type": "chat", "message": "hola", "user_id": "   "}')


def test_rejects_json_that_is_not_an_object():
    with pytest.raises(ProtocolError):
        decode_client("[1, 2, 3]")


def test_listen_needs_no_fields():
    assert decode_client('{"type": "listen"}') == {"type": "listen"}


def test_encoders_match_the_frontend_contract():
    # frontend/src/core/types.ts:41-45 — field names are load-bearing.
    assert json.loads(token("hola")) == {"type": "token", "token": "hola"}
    assert json.loads(done(1200)) == {"type": "done", "thinking_ms": 1200}
    assert json.loads(error("se me ha ido el hilo")) == {
        "type": "error",
        "error": "se me ha ido el hilo",
    }
