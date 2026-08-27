import base64
import json

import pytest

from Hermes.plugins.samantha_kiosk.protocol import (
    MAX_LIVE_FRAME_BYTES,
    ProtocolError,
    console,
    decode_client,
    done,
    error,
    live,
    live_end,
    live_frame,
    photo,
    silence,
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


def test_live_carries_the_codec_header_so_a_decoder_can_start():
    msg = json.loads(live("entrada", 7, b"\x00\x00\x01\x67sps", 704, 480))
    assert msg["type"] == "live"
    assert msg["camera"] == "entrada"
    assert msg["epoch"] == 7
    assert msg["codec"] == "h264"
    assert base64.b64decode(msg["extradata"]) == b"\x00\x00\x01\x67sps"
    assert (msg["width"], msg["height"]) == (704, 480)


def test_live_survives_a_camera_that_reports_no_extradata():
    # Many RTSP cameras send SPS/PPS in-band with every keyframe and leave
    # codec_context.extradata empty. That is not an error, and the frame
    # must still open the view.
    msg = json.loads(live("entrada", 1, b"", 704, 480))
    assert msg["extradata"] == ""


def test_live_end_says_why():
    msg = json.loads(live_end(7, "timeout"))
    assert msg == {"type": "live_end", "epoch": 7, "reason": "timeout"}


def test_live_end_refuses_a_reason_nobody_defined():
    with pytest.raises(ProtocolError):
        live_end(7, "because")


def test_live_frame_stamps_the_epoch_in_four_big_endian_bytes():
    payload = live_frame(7, b"\x00\x00\x01\x65payload")
    assert payload[:4] == (7).to_bytes(4, "big")
    assert payload[4:] == b"\x00\x00\x01\x65payload"


def test_live_frame_refuses_a_packet_over_the_cap():
    # The socket is an unauthenticated local listener; bytes need no path
    # validation, so the size cap is the guard that replaces it.
    with pytest.raises(ProtocolError):
        live_frame(7, b"\x00" * (MAX_LIVE_FRAME_BYTES + 1))


def test_console_lines_carry_no_end_marker_by_default():
    frame = json.loads(console("compilando"))
    assert frame == {"type": "console", "text": "compilando"}


def test_the_end_of_the_work_is_a_flag_and_needs_no_text():
    """The strip closes the console on this; the last line is separate.

    A run that dies mid-sentence still ends, so the fact that it ended
    cannot ride on what was written.
    """
    frame = json.loads(console("", done=True))
    assert frame == {"type": "console", "text": "", "done": True}


def test_a_run_starting_resets_the_console():
    frame = json.loads(console("", reset=True))
    assert frame == {"type": "console", "text": "", "reset": True}


def test_a_chat_frame_may_say_it_was_addressed_by_name():
    msg = decode_client(
        json.dumps({"type": "chat", "message": "hola", "user_id": "u", "wake": True})
    )
    assert msg["wake"] is True


def test_wake_must_be_a_boolean_if_present():
    with pytest.raises(ProtocolError):
        decode_client(
            json.dumps(
                {"type": "chat", "message": "hola", "user_id": "u", "wake": "yes"}
            )
        )


def test_an_older_strip_that_sends_no_wake_is_still_understood():
    # The widget is versioned separately: a gateway that requires `wake`
    # would stop talking to every strip built before this frame existed.
    msg = decode_client(json.dumps({"type": "chat", "message": "hola", "user_id": "u"}))
    assert "wake" not in msg


def test_silence_is_an_error_frame_with_nothing_to_say():
    # The wire shape matters more than the helper: every strip already
    # built settles on an empty `error` and says nothing, so this frame
    # needs no widget change to work.
    assert json.loads(silence()) == {"type": "error", "error": ""}
