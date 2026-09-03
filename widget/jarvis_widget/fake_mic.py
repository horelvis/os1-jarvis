"""A microphone made of synthesised speech.

This box has no microphone — its input jack captures digital silence —
so the last part of the voice turn could not be exercised at all. This
substitutes for the hardware and nothing else: it produces 16 kHz mono
int16 frames, 512 samples each, and hands them to the same `on_frame`
the real microphone calls.

Everything downstream is therefore real: Silero decides where the turn
starts and stops, Whisper transcribes it, the text goes up the WebSocket
to Hermes, and her reply comes back and is spoken. The only thing being
faked is the air.

The words are synthesised by CosyVoice — the same voice Samantha speaks
with — which is a slightly odd test in that she ends up transcribing
herself. It is also the most convenient source of clean Spanish speech
on this machine, and Whisper has no idea who is talking.
"""

from __future__ import annotations

import asyncio
from typing import Iterator

from .audio import OUTPUT_RATE
from .vad import FRAME_SAMPLES, INPUT_RATE

# Silence appended after the words so the VAD sees the turn END. Without
# it the utterance never closes and nothing is ever transcribed — the
# detector needs 0.7 s of quiet, and this leaves room to spare.
_TAIL_SECONDS = 1.5

# Silence BEFORE the words. The detector collects while unconfirmed and
# clears on the first quiet frame, so starting mid-syllable would work,
# but a real turn never begins that way.
_LEAD_SECONDS = 0.4


def _resample_to_16k(pcm24: bytes) -> bytes:
    """24 kHz mono int16 → 16 kHz mono int16.

    PyAV rather than a hand-rolled decimation: it is already installed
    (faster-whisper depends on it) and it filters properly. A naive
    linear interpolation aliases badly enough to change the words —
    an early version of this test turned "quieto" into "cuaito".
    """
    import av
    import numpy as np
    from av.audio.resampler import AudioResampler

    samples = np.frombuffer(pcm24, dtype=np.int16).reshape(1, -1)
    frame = av.AudioFrame.from_ndarray(samples, format="s16", layout="mono")
    frame.sample_rate = OUTPUT_RATE

    resampler = AudioResampler(format="s16", layout="mono", rate=INPUT_RATE)
    out = [f.to_ndarray().reshape(-1) for f in resampler.resample(frame)]
    # Flush whatever the resampler is still holding.
    out += [f.to_ndarray().reshape(-1) for f in resampler.resample(None)]
    if not out:
        return b""
    return np.concatenate(out).astype(np.int16).tobytes()


async def _synthesise(text: str) -> bytes:
    from Hermes.plugins.samantha_voice import tts

    client = tts.new_client()
    try:
        chunks = [chunk async for chunk, _backend in tts.stream(text, client=client)]
    finally:
        await client.aclose()
    return b"".join(chunks)


def frames_for(text: str) -> Iterator[bytes]:
    """Yield 512-sample 16 kHz frames of `text` spoken aloud."""
    pcm16 = _resample_to_16k(asyncio.run(_synthesise(text)))

    lead = b"\x00\x00" * int(_LEAD_SECONDS * INPUT_RATE)
    tail = b"\x00\x00" * int(_TAIL_SECONDS * INPUT_RATE)
    stream = lead + pcm16 + tail

    frame_bytes = FRAME_SAMPLES * 2
    for start in range(0, len(stream) - frame_bytes + 1, frame_bytes):
        yield stream[start : start + frame_bytes]
