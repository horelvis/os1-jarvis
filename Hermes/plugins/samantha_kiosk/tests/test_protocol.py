import json

import pytest

from Hermes.plugins.samantha_kiosk.protocol import (
    ProtocolError,
    decode_client,
    done,
    error,
    photo,
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


def test_an_absurdly_long_message_is_rejected():
    # The socket is an unauthenticated local listener and whatever arrives
    # goes straight into a metered LLM; aiohttp's own frame default is 4 MB.
    raw = json.dumps({"type": "chat", "message": "a" * 4001, "user_id": "primary"})
    with pytest.raises(ProtocolError):
        decode_client(raw)


def test_a_long_but_plausible_message_is_accepted():
    raw = json.dumps({"type": "chat", "message": "a" * 4000, "user_id": "primary"})
    assert decode_client(raw)["message"]


def test_photo_frame_carries_the_path_and_the_camera():
    raw = photo("/tmp/vision/entrada-1000.jpg", "entrada")
    msg = json.loads(raw)
    assert msg == {
        "type": "photo",
        "path": "/tmp/vision/entrada-1000.jpg",
        "camera": "entrada",
    }


def test_photo_is_server_to_client_only():
    # A client must never be able to make the strip open a file.
    with pytest.raises(ProtocolError):
        decode_client(json.dumps({"type": "photo", "path": "/etc/shadow"}))
