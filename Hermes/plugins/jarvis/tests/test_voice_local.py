import json
from pathlib import Path

import pytest

from Hermes.plugins.jarvis.voice_local import (
    PROTOCOL,
    VoiceProtocolError,
    decode_json,
    encode_pcm,
    validate_input_pcm,
)


def test_binary_vectors_match_the_frozen_fixture():
    fixture = json.loads(
        (Path(__file__).parents[4] / "widget/tests/fixtures/local_voice_v1/binary.json").read_text()
    )
    for vector in fixture["vectors"]:
        data = bytes.fromhex(vector["hex"])
        if vector["direction"] == "client":
            operation = lambda data=data: validate_input_pcm(data)
        else:
            operation = lambda data=data: encode_pcm(
                int.from_bytes(data[:4], "big"), data[4:]
            )
        if vector["valid"]:
            operation()
        else:
            with pytest.raises(VoiceProtocolError):
                operation()


def test_output_encoding_is_exactly_turn_prefixed_little_endian_pcm():
    assert encode_pcm(1, bytes.fromhex("0000ff7f0080ffff")).hex() == "000000010000ff7f0080ffff"


def test_json_decoder_rejects_duplicate_keys_and_nonfinite_numbers():
    with pytest.raises(VoiceProtocolError):
        decode_json('{"type":"hello","type":"hello"}')
    with pytest.raises(VoiceProtocolError):
        decode_json('{"type":NaN}')
    assert decode_json(
        '{"type":"hello","protocol":"jarvis.local-voice.v1","processing":"local-only"}'
    )["protocol"] == PROTOCOL
