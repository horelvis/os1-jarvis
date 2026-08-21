"""Tests for voice_pipeline.py processors."""

from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import numpy as np


# ── helpers ──────────────────────────────────────────────────────────────


def make_silence(sample_rate: int, duration_s: float = 0.1) -> bytes:
    n = int(sample_rate * duration_s)
    return np.zeros(n, dtype=np.int16).tobytes()


def _run(coro):
    return asyncio.run(coro)


# ── Resample48kTo16kProcessor ─────────────────────────────────────────────


def test_resample_output_length():
    """1 second of silence at 48 kHz → 16 000 samples (× 2 bytes) at 16 kHz."""
    from pipecat.frames.frames import AudioRawFrame
    from pipecat.processors.frame_processor import FrameDirection

    from samantha.voice_pipeline import Resample48kTo16kProcessor

    proc = Resample48kTo16kProcessor()
    audio_in = make_silence(48_000, 1.0)
    frame_in = AudioRawFrame(audio=audio_in, sample_rate=48_000, num_channels=1)

    received: list = []

    async def run():
        async def fake_push(f, d):
            received.append(f)

        proc.push_frame = fake_push
        await proc.process_frame(frame_in, FrameDirection.DOWNSTREAM)

    _run(run())

    assert len(received) == 1
    out = received[0]
    assert out.sample_rate == 16_000
    assert len(out.audio) == 16_000 * 2  # 16 000 int16 samples


def test_resample_non_audio_frame_passes_through():
    """Non-AudioRawFrame must be forwarded unchanged."""
    from pipecat.frames.frames import TextFrame
    from pipecat.processors.frame_processor import FrameDirection

    from samantha.voice_pipeline import Resample48kTo16kProcessor

    proc = Resample48kTo16kProcessor()
    frame_in = TextFrame(text="hola")

    received = []

    async def run():
        async def fake_push(f, d):
            received.append(f)

        proc.push_frame = fake_push
        await proc.process_frame(frame_in, FrameDirection.DOWNSTREAM)

    _run(run())
    assert received == [frame_in]


# ── WhisperSTTProcessor ───────────────────────────────────────────────────


def test_whisper_stt_skips_non_audio():
    """Non-AudioRawFrame must be forwarded unchanged."""
    from pipecat.frames.frames import TextFrame
    from pipecat.processors.frame_processor import FrameDirection

    from samantha.voice_pipeline import WhisperSTTProcessor

    proc = WhisperSTTProcessor(model_size="tiny", language="es", device="cpu", compute_type="int8")

    received = []

    async def run():
        async def fake_push(f, d):
            received.append(f)

        proc.push_frame = fake_push
        frame_in = TextFrame(text="hello")
        await proc.process_frame(frame_in, FrameDirection.DOWNSTREAM)

    _run(run())
    assert len(received) == 1
    assert received[0].text == "hello"


def test_whisper_stt_emits_transcript_frame():
    """16 kHz AudioRawFrame → UserTranscriptFrame with transcribed text.

    We inject the fake model directly onto _model (bypassing _load and the
    faster_whisper import) to avoid pulling in ctranslate2 → torch which
    crashes on numpy ABI mismatch in the test process.
    """
    from pipecat.frames.frames import AudioRawFrame
    from pipecat.processors.frame_processor import FrameDirection

    from samantha.voice_pipeline import UserTranscriptFrame, WhisperSTTProcessor

    fake_segment = MagicMock()
    fake_segment.text = " hola mundo"
    fake_model = MagicMock()
    fake_model.transcribe.return_value = ([fake_segment], MagicMock())

    proc = WhisperSTTProcessor(model_size="tiny", language="es", device="cpu", compute_type="int8")
    proc._model = fake_model  # bypass lazy _load() — avoids importing ctranslate2/torch

    audio_16k = make_silence(16_000, 0.5)
    frame_in = AudioRawFrame(audio=audio_16k, sample_rate=16_000, num_channels=1)
    received = []

    async def run():
        async def fake_push(f, d):
            received.append(f)

        proc.push_frame = fake_push
        await proc.process_frame(frame_in, FrameDirection.DOWNSTREAM)

    _run(run())
    assert len(received) == 1
    assert isinstance(received[0], UserTranscriptFrame)
    assert received[0].text == "hola mundo"


# ── SamanthaLLMProcessor ─────────────────────────────────────────────────


def test_samantha_llm_emits_text_frames(monkeypatch):
    """UserTranscriptFrame → TextFrames (one per token) + LLMDoneFrame."""
    from pipecat.frames.frames import TextFrame
    from pipecat.processors.frame_processor import FrameDirection

    from samantha.voice_pipeline import LLMDoneFrame, SamanthaLLMProcessor, UserTranscriptFrame

    async def fake_stream_reply(
        msg, *, facts=None, recall=None, short_term=None, user_id="primary"
    ):
        for tok in ["hola", " Horelvis"]:
            yield tok

    async def fake_gather(mem, message, user_id):
        return [], [], []

    monkeypatch.setattr("samantha.voice_pipeline.gather_context", fake_gather)
    monkeypatch.setattr("samantha.voice_pipeline._stream_reply_impl", fake_stream_reply)

    ws = MagicMock()
    ws.send_text = AsyncMock()
    proc = SamanthaLLMProcessor(websocket=ws, mem=None, user_id="primary")

    pushed = []

    async def run():
        async def fake_push(f, d):
            pushed.append(f)

        proc.push_frame = fake_push
        await proc.process_frame(UserTranscriptFrame(text="hola"), FrameDirection.DOWNSTREAM)

    _run(run())

    text_frames = [f for f in pushed if isinstance(f, TextFrame)]
    assert [f.text for f in text_frames] == ["hola", " Horelvis"]
    assert any(isinstance(f, LLMDoneFrame) for f in pushed)

    calls = [json.loads(c.args[0]) for c in ws.send_text.call_args_list]
    assert any(c.get("type") == "transcript" for c in calls)
    assert any(c.get("type") == "token" for c in calls)


# ── CosyVoiceTTSProcessor ─────────────────────────────────────────────────


def test_cosyvoice_tts_emits_audio_frames(monkeypatch):
    """TextFrames + LLMDoneFrame → AudioRawFrame (24 kHz) from tts.stream."""
    from pipecat.frames.frames import AudioRawFrame, TextFrame
    from pipecat.processors.frame_processor import FrameDirection

    from samantha.voice_pipeline import CosyVoiceTTSProcessor, LLMDoneFrame

    async def fake_tts_stream(text: str) -> AsyncIterator:
        yield b"\x00" * 4096, "cosyvoice"

    monkeypatch.setattr("samantha.voice_pipeline._tts_stream", fake_tts_stream)

    barge_in = asyncio.Event()
    proc = CosyVoiceTTSProcessor(barge_in=barge_in)
    pushed = []

    async def run():
        async def fake_push(f, d):
            pushed.append(f)

        proc.push_frame = fake_push
        await proc.process_frame(TextFrame(text="hola mundo"), FrameDirection.DOWNSTREAM)
        await proc.process_frame(LLMDoneFrame(), FrameDirection.DOWNSTREAM)

    _run(run())

    audio_frames = [f for f in pushed if isinstance(f, AudioRawFrame)]
    assert len(audio_frames) == 1
    assert audio_frames[0].sample_rate == 24_000


def test_cosyvoice_tts_stops_on_barge_in(monkeypatch):
    """barge_in event set → TTS stops after zero chunks."""
    from pipecat.frames.frames import AudioRawFrame, TextFrame
    from pipecat.processors.frame_processor import FrameDirection

    from samantha.voice_pipeline import CosyVoiceTTSProcessor, LLMDoneFrame

    async def fake_tts_stream(text: str) -> AsyncIterator:
        yield b"\x00" * 4096, "cosyvoice"
        yield b"\x00" * 4096, "cosyvoice"

    monkeypatch.setattr("samantha.voice_pipeline._tts_stream", fake_tts_stream)

    barge_in = asyncio.Event()
    barge_in.set()  # pre-signal: stop immediately
    proc = CosyVoiceTTSProcessor(barge_in=barge_in)
    pushed = []

    async def run():
        async def fake_push(f, d):
            pushed.append(f)

        proc.push_frame = fake_push
        await proc.process_frame(TextFrame(text="hola mundo"), FrameDirection.DOWNSTREAM)
        await proc.process_frame(LLMDoneFrame(), FrameDirection.DOWNSTREAM)

    _run(run())

    audio_frames = [f for f in pushed if isinstance(f, AudioRawFrame)]
    assert len(audio_frames) == 0
