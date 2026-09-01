"""What a browser sends, in the format the pipeline speaks.

Everything downstream — the VAD, Whisper, the dumps — is 16 kHz mono
int16. A browser hands over whatever rate its device picked, and the page
reads that rate off the `AudioContext` rather than assuming 48 kHz,
because it is the device's choice.

Linear interpolation rather than a windowed filter: the input is speech
being handed to Whisper, the ratio is a downsample by three, and the
aliasing that a proper filter would remove sits above what a 16 kHz
pipeline keeps anyway. If a measurement ever shows transcription
suffering, this is the place to put a real filter.
"""

from __future__ import annotations

import array

from .vad import INPUT_RATE

# The same ceiling `vad.py` puts on a spoken turn, for the same reason
# plus one: a held button, or a client that lies, must not be able to
# make this process allocate without bound.
MAX_UTTERANCE_BYTES = 30 * INPUT_RATE * 2


def resample_to_input(pcm: bytes, source_rate: int) -> bytes:
    """16 kHz mono int16, from mono int16 at `source_rate`."""
    if len(pcm) % 2:
        raise ValueError("PCM must be a whole number of int16 samples")
    if source_rate == INPUT_RATE:
        return pcm
    if source_rate <= 0:
        raise ValueError(f"impossible sample rate: {source_rate}")

    source = array.array("h")
    source.frombytes(pcm)
    count = len(source)
    if count == 0:
        return b""
    wanted = round(count * INPUT_RATE / source_rate)
    out = array.array("h", bytes(2 * wanted))
    step = (count - 1) / max(1, wanted - 1) if wanted > 1 else 0.0
    for i in range(wanted):
        position = i * step
        left = int(position)
        right = min(left + 1, count - 1)
        weight = position - left
        out[i] = int(source[left] * (1 - weight) + source[right] * weight)
    return out.tobytes()
