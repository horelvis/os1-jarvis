"""Server-side voice loop — Pipecat-based pipeline for Phase 11.

Pipeline (assembled by build_pipeline):
  FastAPIWebsocketTransport.input()     ← 48 kHz int16 PCM binary WS frames
    → Resample48kTo16kProcessor         ← 48 k → 16 k
    → WhisperSTTProcessor               ← 16 kHz AudioRawFrame → UserTranscriptFrame
    → SamanthaLLMProcessor              ← UserTranscriptFrame → TextFrames + JSON
    → CosyVoiceTTSProcessor             ← TextFrames → AudioRawFrame 24 kHz
  FastAPIWebsocketTransport.output()   → 24 kHz binary WS frames + JSON WS text

The WebSocket carries:
  - Binary frames (ArrayBuffer) for PCM audio in both directions.
  - Text frames (JSON string) for control: transcript, token, error, barge_in.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, AsyncIterator

import numpy as np
from loguru import logger
from pipecat.frames.frames import AudioRawFrame, Frame, TextFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

if TYPE_CHECKING:
    from fastapi import WebSocket
    from pipecat.pipeline.task import PipelineTask

    from .memory import Memory

# ──────────────────────────────────────────────────────────────────────────
# Module-level aliases so tests can monkeypatch without touching real imports
# ──────────────────────────────────────────────────────────────────────────

from .context import gather_context
from .tts import stream as _tts_stream


async def _stream_reply_impl(
    message: str,
    *,
    facts=None,
    recall=None,
    short_term=None,
    user_id: str = "primary",
) -> AsyncIterator[str]:
    """Thin wrapper so tests can monkeypatch samantha.voice_pipeline._stream_reply_impl."""
    from .real_llm import stream_reply

    async for tok in stream_reply(
        message, facts=facts, recall=recall, short_term=short_term, user_id=user_id
    ):
        yield tok


# ──────────────────────────────────────────────────────────────────────────
# Custom frame types
# ──────────────────────────────────────────────────────────────────────────


@dataclass
class UserTranscriptFrame(Frame):
    """A confirmed user utterance, ready for the LLM."""

    text: str


@dataclass
class LLMDoneFrame(Frame):
    """Signals CosyVoiceTTSProcessor that all tokens for this turn have arrived."""


# ──────────────────────────────────────────────────────────────────────────
# Stage 1 — Resample 48 kHz → 16 kHz
# ──────────────────────────────────────────────────────────────────────────


class Resample48kTo16kProcessor(FrameProcessor):
    """Downsample 48 kHz int16 PCM to 16 kHz for Whisper.

    Uses linear interpolation (same method as the former Piper resampling path).
    Only transforms AudioRawFrame at 48 kHz; all other frames pass through.
    """

    SRC_RATE = 48_000
    DST_RATE = 16_000

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, AudioRawFrame) and frame.sample_rate == self.SRC_RATE:
            resampled = self._resample(frame.audio)
            await self.push_frame(
                AudioRawFrame(audio=resampled, sample_rate=self.DST_RATE, num_channels=1),
                direction,
            )
        else:
            await self.push_frame(frame, direction)

    def _resample(self, audio: bytes) -> bytes:
        src = np.frombuffer(audio, dtype=np.int16)
        ratio = self.DST_RATE / self.SRC_RATE
        dst_len = max(1, int(len(src) * ratio))
        dst = np.interp(
            np.linspace(0, len(src) - 1, dst_len),
            np.arange(len(src)),
            src,
        ).astype(np.int16)
        return dst.tobytes()


# ──────────────────────────────────────────────────────────────────────────
# Stage 2 — Whisper STT (faster-whisper)
# ──────────────────────────────────────────────────────────────────────────


class WhisperSTTProcessor(FrameProcessor):
    """Transcribe AudioRawFrame (16 kHz int16 mono) via faster-whisper.

    Lazy-loads the model on first frame so the process starts quickly.
    Emits UserTranscriptFrame when transcription is non-empty.
    """

    def __init__(
        self,
        model_size: str = "large-v3-turbo",
        language: str = "es",
        device: str = "cuda",
        compute_type: str = "float16",
    ) -> None:
        super().__init__()
        self._model_size = model_size
        self._language = language
        self._device = device
        self._compute_type = compute_type
        self._model = None  # lazy

    def _load(self) -> None:
        from faster_whisper import WhisperModel

        logger.info(f"stt: loading whisper {self._model_size} on {self._device}")
        self._model = WhisperModel(
            self._model_size,
            device=self._device,
            compute_type=self._compute_type,
        )
        logger.info("stt: whisper ready")

    def _transcribe(self, audio_bytes: bytes) -> str:
        if self._model is None:
            self._load()
        audio = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        segments, _ = self._model.transcribe(
            audio,
            language=self._language,
            beam_size=5,
            vad_filter=False,
        )
        return " ".join(s.text for s in segments).strip()

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, AudioRawFrame) and frame.sample_rate == 16_000:
            text = await asyncio.to_thread(self._transcribe, frame.audio)
            if text:
                logger.info(f"stt: {text!r}")
                await self.push_frame(UserTranscriptFrame(text=text), direction)
        else:
            await self.push_frame(frame, direction)


# ──────────────────────────────────────────────────────────────────────────
# Stage 3 — LLM
# ──────────────────────────────────────────────────────────────────────────


class SamanthaLLMProcessor(FrameProcessor):
    """On UserTranscriptFrame: gather context, stream reply tokens.

    Side-effects per turn:
      - Sends {"type":"transcript","text":"..."} JSON to browser.
      - Sends {"type":"token","text":"..."} JSON per token to browser.
      - Persists the full Samantha reply in memory.
    """

    def __init__(
        self,
        websocket: "WebSocket",
        mem: "Memory | None",
        user_id: str = "primary",
    ) -> None:
        super().__init__()
        self._ws = websocket
        self._mem = mem
        self._user_id = user_id

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, UserTranscriptFrame):
            await self._handle(frame.text)
        else:
            await self.push_frame(frame, direction)

    async def _handle(self, text: str) -> None:
        await self._ws.send_text(json.dumps({"type": "transcript", "text": text}))

        if self._mem is not None:
            facts, recall, short = await gather_context(self._mem, text, self._user_id)
        else:
            facts, recall, short = [], [], []

        reply_chunks: list[str] = []
        async for token in _stream_reply_impl(
            text,
            facts=facts,
            recall=recall,
            short_term=short,
            user_id=self._user_id,
        ):
            reply_chunks.append(token)
            await self._ws.send_text(json.dumps({"type": "token", "text": token}))
            await self.push_frame(TextFrame(text=token), FrameDirection.DOWNSTREAM)

        full_reply = "".join(reply_chunks)
        if self._mem is not None and full_reply:
            await asyncio.to_thread(
                self._mem.remember, "samantha", full_reply, user_id=self._user_id
            )

        await self.push_frame(LLMDoneFrame(), FrameDirection.DOWNSTREAM)


# ──────────────────────────────────────────────────────────────────────────
# Stage 4 — TTS (CosyVoice 3)
# ──────────────────────────────────────────────────────────────────────────


class CosyVoiceTTSProcessor(FrameProcessor):
    """Accumulate TextFrames, synthesize on LLMDoneFrame, emit AudioRawFrame.

    A barge_in asyncio.Event (shared with the /voice endpoint) can abort
    synthesis mid-stream: checked before each chunk, cleared on fire.
    """

    OUTPUT_RATE = 24_000

    def __init__(self, barge_in: asyncio.Event) -> None:
        super().__init__()
        self._barge_in = barge_in
        self._buffer: list[str] = []

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, TextFrame):
            self._buffer.append(frame.text)
        elif isinstance(frame, LLMDoneFrame):
            text = "".join(self._buffer).strip()
            self._buffer.clear()
            if text:
                await self._synthesize(text, direction)
        else:
            await self.push_frame(frame, direction)

    async def _synthesize(self, text: str, direction: FrameDirection) -> None:
        async for chunk, _ in _tts_stream(text):
            if self._barge_in.is_set():
                self._barge_in.clear()
                logger.info("tts: barge-in — synthesis stopped")
                return
            await self.push_frame(
                AudioRawFrame(audio=chunk, sample_rate=self.OUTPUT_RATE, num_channels=1),
                direction,
            )


# ──────────────────────────────────────────────────────────────────────────
# Pipeline factory
# ──────────────────────────────────────────────────────────────────────────


def build_pipeline(
    websocket: "WebSocket",
    mem: "Memory | None",
    user_id: str = "primary",
    barge_in: asyncio.Event | None = None,
) -> "PipelineTask":
    """Assemble and return a PipelineTask for one /voice client.

    The caller owns the task lifetime. Call task.run() to start and
    task.cancel() to stop (e.g., when a new client connects).
    """
    from pipecat.audio.vad.silero import SileroVADAnalyzer
    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.pipeline.task import PipelineTask
    from pipecat.transports.websocket.fastapi import (
        FastAPIWebsocketParams,
        FastAPIWebsocketTransport,
    )

    if barge_in is None:
        barge_in = asyncio.Event()

    transport = FastAPIWebsocketTransport(
        websocket,
        FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            add_wav_header=False,
            vad_enabled=True,
            vad_analyzer=SileroVADAnalyzer(),
            vad_audio_passthrough=False,
        ),
    )

    pipeline = Pipeline(
        [
            transport.input(),
            Resample48kTo16kProcessor(),
            WhisperSTTProcessor(),
            SamanthaLLMProcessor(websocket=websocket, mem=mem, user_id=user_id),
            CosyVoiceTTSProcessor(barge_in=barge_in),
            transport.output(),
        ]
    )

    return PipelineTask(pipeline)
