"""Turning what a browser hands us into what the pipeline speaks.

The pipeline is 16 kHz mono int16 everywhere — the VAD, Whisper, the
dumps. A browser gives whatever rate its device chose, usually 48 kHz. Getting
this wrong does not raise: it transcribes as confident nonsense, which is
the worst kind of failure this project has.
"""

import math
import struct

import pytest

from samantha_widget.remote_audio import (
    MAX_UTTERANCE_BYTES,
    MAX_UTTERANCE_SECONDS,
    max_bytes_at,
    resample_to_input,
)
from samantha_widget.vad import INPUT_RATE


def _tone(samples: int, rate: int, hz: float = 440.0) -> bytes:
    return b"".join(
        struct.pack("<h", int(8000 * math.sin(2 * math.pi * hz * i / rate)))
        for i in range(samples)
    )


def test_a_matching_rate_is_returned_untouched() -> None:
    pcm = _tone(1600, INPUT_RATE)

    assert resample_to_input(pcm, INPUT_RATE) == pcm


def test_48k_becomes_16k_and_keeps_its_duration() -> None:
    """One second in, one second out. A length bug here shortens or
    stretches speech, and Whisper transcribes the result without complaint."""
    pcm = _tone(48000, 48000)

    out = resample_to_input(pcm, 48000)

    assert len(out) // 2 == INPUT_RATE


def test_44100_is_handled_too() -> None:
    """48 kHz is usual, not guaranteed — the rate is the device's choice
    and must be read from the AudioContext, never assumed."""
    pcm = _tone(44100, 44100)

    out = resample_to_input(pcm, 44100)

    assert abs(len(out) // 2 - INPUT_RATE) <= 1


def test_the_output_is_still_int16() -> None:
    pcm = _tone(4800, 48000)

    out = resample_to_input(pcm, 48000)

    assert len(out) % 2 == 0
    values = struct.unpack(f"<{len(out) // 2}h", out)
    assert max(values) > 1000  # a tone survived, it is not silence


def test_an_odd_number_of_bytes_is_refused() -> None:
    """Half a sample means the stream is misframed; guessing would put a
    click into the audio and hide the real bug."""
    import pytest

    with pytest.raises(ValueError):
        resample_to_input(b"\x00\x00\x00", 48000)


def test_there_is_a_ceiling_on_one_utterance() -> None:
    """A held button — or a hostile client — must not be able to make the
    widget allocate without bound. Thirty seconds is the same cap
    `vad.py` puts on a spoken turn."""
    assert MAX_UTTERANCE_BYTES == 30 * INPUT_RATE * 2


def test_the_ceiling_is_scaled_to_the_rate_that_is_arriving() -> None:
    """`MAX_UTTERANCE_BYTES` is thirty seconds AT 16 kHz. A phone sends
    48, so measuring its buffer against that number cut every press at
    about ten seconds — a third of what every comment around it said."""
    assert max_bytes_at(INPUT_RATE) == MAX_UTTERANCE_BYTES
    assert max_bytes_at(48000) == 3 * MAX_UTTERANCE_BYTES
    assert max_bytes_at(44100) / 2 / 44100 == MAX_UTTERANCE_SECONDS


def test_an_impossible_rate_has_no_ceiling_to_offer() -> None:
    with pytest.raises(ValueError):
        max_bytes_at(0)
