# Phase 11 — Server-side Voice Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace browser-side STT/VAD/TTS choreography with a single `/voice` WebSocket endpoint that runs the full voice loop (mic → Silero VAD → Whisper STT → Grok LLM → CosyVoice TTS → audio out) inside the Python backend.

**Architecture:** A custom `voice_pipeline.py` defines four `FrameProcessor` subclasses wired into a Pipecat `Pipeline`; the `FastAPIWebsocketTransport` handles WebSocket I/O and runs Silero VAD internally. A new `/voice` WebSocket endpoint in `api.py` owns the single-client guard. The frontend replaces `useSpeechRecognition + useBargeIn + speak()` with a single `useVoiceSocket` hook that sends 48 kHz int16 PCM uplink and receives PCM + JSON downlink over the same connection.

**Tech Stack:** Python 3.12, FastAPI, pipecat-ai[silero]≥0.0.50, faster-whisper≥1.0.3, numpy, React 18 + TypeScript, AudioContext (ScriptProcessorNode), WebSocket binary frames.

## Global Constraints

- Python 3.12+; formatter `ruff format`; linter `ruff check` — run both before committing.
- All new Python code uses type hints on public functions.
- User-facing strings in Spanish (Spain); code/comments/commit messages in English.
- Frontend package manager is **pnpm** — never `npm install`.
- Frontend typecheck: `pnpm typecheck`; build: `pnpm build` (runs from `frontend/`).
- No new top-level directories.
- Every new backend endpoint needs at least one pytest test.
- `tts.ts` is NOT deleted in this plan — `OnboardingScreen.tsx` still uses it for HTTP-based TTS.
- Run `pytest backend/tests/ -v` before every commit that touches backend code.

---

## File Map

### Created
| File | Responsibility |
|---|---|
| `backend/samantha/context.py` | `_collect_facts()` + `gather_context()` — extracted from `api.py` to break the circular import |
| `backend/samantha/voice_pipeline.py` | `Resample48kTo16kProcessor`, `WhisperSTTProcessor`, `SamanthaLLMProcessor`, `CosyVoiceTTSProcessor`, `build_pipeline()` |
| `backend/tests/test_voice_pipeline.py` | Unit tests for pipeline processors and `/voice` endpoint |
| `frontend/src/net/useVoiceSocket.ts` | Voice loop hook: WebSocket + mic capture + PCM playback |

### Modified
| File | Change |
|---|---|
| `backend/pyproject.toml` | Move `faster-whisper`, `numpy` to main deps; add `pipecat-ai[silero]` to main deps |
| `backend/samantha/api.py` | Import `gather_context` from `context.py`; add `_active_voice_task` + `/voice` endpoint |
| `backend/tests/test_api.py` | Add `/voice` connection test |
| `frontend/src/screens/ConversationScreen.tsx` | Swap `useSpeechRecognition` + `useBargeIn` + `speak()` → `useVoiceSocket` |
| `frontend/src/net/audio-analyser.ts` | Export `setActiveAnalyser` (already exists) — wire it from `useVoiceSocket` |

### Removed
| File | Reason |
|---|---|
| `frontend/src/core/useBargeIn.ts` | Replaced by server-side VAD |

---

## Task 1: Dependencies — pipecat-ai, faster-whisper, numpy into main deps

**Files:**
- Modify: `backend/pyproject.toml`
- Test: `backend/tests/test_pipecat_imports.py` (new, smoke-only, deleted after Task 1)

**Interfaces:**
- Produces: `pipecat.processors.frame_processor.FrameProcessor`, `pipecat.frames.frames.AudioRawFrame`, `pipecat.pipeline.pipeline.Pipeline`, `pipecat.pipeline.task.PipelineTask`, `pipecat.audio.vad.silero.SileroVADAnalyzer`, `pipecat.transports.network.fastapi_websocket.FastAPIWebsocketTransport` — all importable.

- [ ] **Step 1: Update pyproject.toml**

Replace the `[project]` dependencies block and `real` optional block:

```toml
[project]
name = "samantha-backend"
version = "0.1.0"
description = "Samantha backend — FastAPI server (mock for development, real models in production)"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "pydantic>=2.9",
    "python-multipart>=0.0.20",
    "loguru>=0.7",
    "httpx>=0.27",
    "chromadb>=0.5.0",
    "fastembed>=0.5",
    "pipecat-ai[silero]>=0.0.50",
    "faster-whisper>=1.0.3",
    "numpy>=2.0",
]

[project.optional-dependencies]
real = [
    "sounddevice>=0.4.7",
]
dev = [
    "pytest>=8.0",
    "httpx>=0.27",
    "ruff>=0.6",
]
```

- [ ] **Step 2: Install**

```bash
cd backend && pip install -e ".[dev]"
```

Expected: no errors. If pipecat-ai 0.0.50 is not yet released, try `>=0.0.45`.

- [ ] **Step 3: Write the import smoke test**

Create `backend/tests/test_pipecat_imports.py`:

```python
"""Smoke test: verify pipecat import paths are correct for installed version."""


def test_core_frame_processor_imports():
    from pipecat.processors.frame_processor import FrameProcessor, FrameDirection  # noqa: F401
    from pipecat.frames.frames import AudioRawFrame, TextFrame, Frame  # noqa: F401
    from pipecat.pipeline.pipeline import Pipeline  # noqa: F401
    from pipecat.pipeline.task import PipelineTask  # noqa: F401
    assert True


def test_silero_vad_imports():
    from pipecat.audio.vad.silero import SileroVADAnalyzer  # noqa: F401
    assert True


def test_fastapi_transport_imports():
    from pipecat.transports.network.fastapi_websocket import (  # noqa: F401
        FastAPIWebsocketTransport,
        FastAPIWebsocketParams,
    )
    assert True


def test_faster_whisper_imports():
    from faster_whisper import WhisperModel  # noqa: F401
    assert True
```

- [ ] **Step 4: Run smoke test**

```bash
cd backend && pytest tests/test_pipecat_imports.py -v
```

Expected: all 4 PASS. If any import fails, check `pip show pipecat-ai` for the installed version and adjust import paths accordingly. Common alternative paths:
- `pipecat.audio.vad.silero` → `pipecat.vad.silero`
- `pipecat.transports.network.fastapi_websocket` → `pipecat.transports.websocket`

Fix import paths in the test until they pass, then note the correct paths — you'll use them in Tasks 3–5.

- [ ] **Step 5: Commit**

```bash
cd backend && ruff check . && ruff format .
git add pyproject.toml tests/test_pipecat_imports.py
git commit -m "feat(deps): add pipecat-ai[silero], faster-whisper, numpy to main deps"
```

---

## Task 2: Extract context helpers to `context.py`

`voice_pipeline.py` will import `gather_context`, but `api.py` also imports from `voice_pipeline.py`. Extracting to a shared module breaks the circular dependency.

**Files:**
- Create: `backend/samantha/context.py`
- Modify: `backend/samantha/api.py` (import from context.py, remove local definitions)
- Test: `backend/tests/test_api.py` (existing tests must still pass)

**Interfaces:**
- Produces:
  ```python
  # backend/samantha/context.py
  async def gather_context(
      mem: "Memory", message: str, user_id: str
  ) -> tuple[list[dict], list[MemoryChunk], list[MemoryChunk]]: ...
  ```
- Consumes: `Memory.get_fact()`, `Memory.recall()`, `Memory.short_term()`, `Memory.remember()`, `config.memory_top_k`

- [ ] **Step 1: Create `backend/samantha/context.py`**

```python
"""Context assembly helpers — shared between api.py and voice_pipeline.py.

Extracted from api.py to prevent a circular import when voice_pipeline
imports from both api (for gather_context) and samantha itself.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .memory import Memory, MemoryChunk


def _collect_facts(mem: "Memory", *, user_id: str) -> list[dict]:
    """Gather facts surfaced into the system prompt.

    Order: name → Big-Five traits → onboarding_completed_at.
    """
    from .profile import BIG5_FACT_KINDS

    kinds = ("name", *BIG5_FACT_KINDS, "onboarding_completed_at")
    out: list[dict] = []
    for kind in kinds:
        f = mem.get_fact(kind, user_id=user_id)
        if f is not None:
            out.append(f)
    return out


async def gather_context(
    mem: "Memory", message: str, user_id: str
) -> "tuple[list[dict], list[MemoryChunk], list[MemoryChunk]]":
    """Collect facts + recall + short-term and persist the user turn,
    off the event loop (embedding + ChromaDB + SQLite are sync/CPU-bound).

    Ordering matters: context FIRST, remember AFTER, so the ring never
    contains the current message when the LLM sees it.
    """
    from .config import config

    def _work() -> "tuple[list[dict], list[MemoryChunk], list[MemoryChunk]]":
        facts = _collect_facts(mem, user_id=user_id)
        recall = mem.recall(message, k=config.memory_top_k, user_id=user_id)
        short = mem.short_term(user_id=user_id)
        mem.remember("user", message, user_id=user_id)
        return facts, recall, short

    return await asyncio.to_thread(_work)
```

- [ ] **Step 2: Update `api.py` — replace local definitions with imports**

Find lines 114–160 in `backend/samantha/api.py` (the `_collect_facts` and `_gather_context` functions). Replace them with:

```python
from .context import gather_context as _gather_context  # noqa: F401 used in /ws handler
```

Also find every call to `_gather_context(` in api.py — they stay the same (the alias preserves the name).

Verify: `grep -n "_collect_facts\|_gather_context" backend/samantha/api.py` — should show only the import line and any call sites (which are unchanged).

- [ ] **Step 3: Run existing tests**

```bash
cd backend && pytest tests/test_api.py -v
```

Expected: all tests that were passing before still PASS. If any fail with `ImportError`, the extraction missed something — fix before continuing.

- [ ] **Step 4: Commit**

```bash
cd backend && ruff check . && ruff format .
git add samantha/context.py samantha/api.py
git commit -m "refactor: extract gather_context to context.py (prep for voice_pipeline)"
```

---

## Task 3: `Resample48kTo16kProcessor` + `WhisperSTTProcessor`

**Files:**
- Create: `backend/samantha/voice_pipeline.py`
- Create: `backend/tests/test_voice_pipeline.py`

**Interfaces:**
- Produces:
  ```python
  # Exported from voice_pipeline.py
  class Resample48kTo16kProcessor(FrameProcessor): ...
  class WhisperSTTProcessor(FrameProcessor): ...
  # Internal frame type used between processors
  @dataclass
  class UserTranscriptFrame(Frame):
      text: str
  ```
- `WhisperSTTProcessor` emits `UserTranscriptFrame` (not pipecat's `TranscriptionFrame` — avoids version coupling).

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_voice_pipeline.py`:

```python
"""Tests for voice_pipeline.py processors."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import numpy as np
import pytest


# ── helpers ──────────────────────────────────────────────────────────────


def make_silence(sample_rate: int, duration_s: float = 0.1) -> bytes:
    n = int(sample_rate * duration_s)
    return np.zeros(n, dtype=np.int16).tobytes()


# ── Resample48kTo16kProcessor ─────────────────────────────────────────────


def test_resample_output_length():
    """1 second of silence at 48 kHz → 16 000 samples (× 2 bytes) at 16 kHz."""
    from pipecat.frames.frames import AudioRawFrame

    from samantha.voice_pipeline import Resample48kTo16kProcessor

    proc = Resample48kTo16kProcessor()
    audio_in = make_silence(48_000, 1.0)
    frame_in = AudioRawFrame(audio=audio_in, sample_rate=48_000, num_channels=1)

    received: list[AudioRawFrame] = []

    async def run():
        async def fake_push(f, d):
            received.append(f)

        proc.push_frame = fake_push
        from pipecat.processors.frame_processor import FrameDirection

        await proc.process_frame(frame_in, FrameDirection.DOWNSTREAM)

    asyncio.run(run())

    assert len(received) == 1
    out = received[0]
    assert out.sample_rate == 16_000
    assert len(out.audio) == 16_000 * 2  # 16 000 int16 samples


def test_resample_non_audio_frame_passes_through():
    """Non-AudioRawFrame must be forwarded unchanged."""
    from pipecat.frames.frames import TextFrame

    from samantha.voice_pipeline import Resample48kTo16kProcessor

    proc = Resample48kTo16kProcessor()
    frame_in = TextFrame(text="hola")

    received = []

    async def run():
        async def fake_push(f, d):
            received.append(f)

        proc.push_frame = fake_push
        from pipecat.processors.frame_processor import FrameDirection

        await proc.process_frame(frame_in, FrameDirection.DOWNSTREAM)

    asyncio.run(run())
    assert received == [frame_in]


# ── WhisperSTTProcessor ───────────────────────────────────────────────────


def test_whisper_stt_skips_non_audio():
    """Non-AudioRawFrame must be forwarded unchanged."""
    from pipecat.frames.frames import TextFrame

    from samantha.voice_pipeline import WhisperSTTProcessor

    proc = WhisperSTTProcessor.__new__(WhisperSTTProcessor)
    proc._language = "es"
    proc._model = None
    # Inject stub push_frame
    received = []

    async def run():
        from pipecat.processors.frame_processor import FrameDirection

        async def fake_push(f, d):
            received.append(f)

        proc.push_frame = fake_push
        frame_in = TextFrame(text="hello")
        await proc.process_frame(frame_in, FrameDirection.DOWNSTREAM)

    asyncio.run(run())
    assert len(received) == 1
    assert received[0].text == "hello"


def test_whisper_stt_emits_transcript_frame(monkeypatch):
    """16 kHz AudioRawFrame → UserTranscriptFrame with transcribed text."""
    from pipecat.frames.frames import AudioRawFrame
    from pipecat.processors.frame_processor import FrameDirection

    from samantha.voice_pipeline import UserTranscriptFrame, WhisperSTTProcessor

    # Mock WhisperModel
    fake_segment = MagicMock()
    fake_segment.text = " hola mundo"
    fake_model = MagicMock()
    fake_model.transcribe.return_value = ([fake_segment], MagicMock())

    with patch("faster_whisper.WhisperModel", return_value=fake_model):
        proc = WhisperSTTProcessor(model_size="tiny", language="es", device="cpu", compute_type="int8")

    audio_16k = make_silence(16_000, 0.5)
    frame_in = AudioRawFrame(audio=audio_16k, sample_rate=16_000, num_channels=1)
    received = []

    async def run():
        async def fake_push(f, d):
            received.append(f)

        proc.push_frame = fake_push
        await proc.process_frame(frame_in, FrameDirection.DOWNSTREAM)

    asyncio.run(run())
    assert len(received) == 1
    assert isinstance(received[0], UserTranscriptFrame)
    assert received[0].text == "hola mundo"
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
cd backend && pytest tests/test_voice_pipeline.py -v
```

Expected: `ModuleNotFoundError: No module named 'samantha.voice_pipeline'`

- [ ] **Step 3: Implement `Resample48kTo16kProcessor` and `WhisperSTTProcessor`**

Create `backend/samantha/voice_pipeline.py`:

```python
"""Server-side voice loop — Pipecat-based pipeline for Phase 11.

Pipeline (assembled by build_pipeline):
  FastAPIWebsocketTransport.input()     ← 48 kHz int16 PCM binary WS frames
    → Resample48kTo16kProcessor         ← 48 k → 16 k
    → WhisperSTTProcessor               ← 16 kHz → UserTranscriptFrame
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

    from .memory import Memory


# ──────────────────────────────────────────────────────────────────────────
# Custom frame type
# ──────────────────────────────────────────────────────────────────────────


@dataclass
class UserTranscriptFrame(Frame):
    """A confirmed user utterance, ready for the LLM."""

    text: str


# ──────────────────────────────────────────────────────────────────────────
# Stage 1 — Resample 48 kHz → 16 kHz
# ──────────────────────────────────────────────────────────────────────────


class Resample48kTo16kProcessor(FrameProcessor):
    """Downsample 48 kHz int16 PCM to 16 kHz for Whisper.

    Uses linear interpolation (same method as the former Piper path).
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
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
cd backend && pytest tests/test_voice_pipeline.py::test_resample_output_length tests/test_voice_pipeline.py::test_resample_non_audio_frame_passes_through tests/test_voice_pipeline.py::test_whisper_stt_skips_non_audio tests/test_voice_pipeline.py::test_whisper_stt_emits_transcript_frame -v
```

Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
cd backend && ruff check . && ruff format .
git add samantha/voice_pipeline.py tests/test_voice_pipeline.py tests/test_pipecat_imports.py
git commit -m "feat(voice): Resample48kTo16kProcessor + WhisperSTTProcessor"
```

---

## Task 4: `SamanthaLLMProcessor` + `CosyVoiceTTSProcessor`

**Files:**
- Modify: `backend/samantha/voice_pipeline.py` (add two classes)
- Modify: `backend/tests/test_voice_pipeline.py` (add tests)

**Interfaces:**
- Consumes (from Task 3): `UserTranscriptFrame`, `FrameProcessor`
- Consumes (existing): `samantha.context.gather_context`, `samantha.real_llm.stream_reply`, `samantha.tts.stream`
- Produces:
  ```python
  class SamanthaLLMProcessor(FrameProcessor):
      def __init__(self, websocket: WebSocket, mem: Memory | None, user_id: str = "primary") -> None: ...
  
  class CosyVoiceTTSProcessor(FrameProcessor):
      def __init__(self, barge_in: asyncio.Event) -> None: ...
  
  # Internal sentinel frame (TTS needs to know when all tokens arrived)
  @dataclass
  class LLMDoneFrame(Frame): ...
  ```

- [ ] **Step 1: Add tests to `test_voice_pipeline.py`**

Append to the file:

```python
# ── SamanthaLLMProcessor ─────────────────────────────────────────────────


def test_samantha_llm_emits_text_frames(monkeypatch):
    """UserTranscriptFrame → TextFrames (one per token) + LLMDoneFrame."""
    from unittest.mock import AsyncMock

    from pipecat.frames.frames import TextFrame
    from pipecat.processors.frame_processor import FrameDirection

    from samantha.voice_pipeline import LLMDoneFrame, SamanthaLLMProcessor, UserTranscriptFrame

    async def fake_stream_reply(msg, *, facts=None, recall=None, short_term=None, user_id="primary"):
        for tok in ["hola", " Horelvis"]:
            yield tok

    async def fake_gather(mem, message, user_id):
        return [], [], []

    monkeypatch.setattr("samantha.voice_pipeline.gather_context", fake_gather)
    monkeypatch.setattr("samantha.voice_pipeline._stream_reply", fake_stream_reply)

    ws = MagicMock()
    ws.send_text = AsyncMock()
    proc = SamanthaLLMProcessor(websocket=ws, mem=None, user_id="primary")

    pushed = []

    async def run():
        async def fake_push(f, d):
            pushed.append(f)

        proc.push_frame = fake_push
        await proc.process_frame(UserTranscriptFrame(text="hola"), FrameDirection.DOWNSTREAM)

    asyncio.run(run())

    text_frames = [f for f in pushed if isinstance(f, TextFrame)]
    assert [f.text for f in text_frames] == ["hola", " Horelvis"]
    assert any(isinstance(f, LLMDoneFrame) for f in pushed)

    # Browser must receive transcript JSON
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

    asyncio.run(run())

    audio_frames = [f for f in pushed if isinstance(f, AudioRawFrame)]
    assert len(audio_frames) == 1
    assert audio_frames[0].sample_rate == 24_000


def test_cosyvoice_tts_stops_on_barge_in(monkeypatch):
    """barge_in event set → TTS stops after the first chunk."""
    from pipecat.frames.frames import AudioRawFrame, TextFrame
    from pipecat.processors.frame_processor import FrameDirection

    from samantha.voice_pipeline import CosyVoiceTTSProcessor, LLMDoneFrame

    async def fake_tts_stream(text: str) -> AsyncIterator:
        yield b"\x00" * 4096, "cosyvoice"
        yield b"\x00" * 4096, "cosyvoice"  # second chunk must be suppressed

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

    asyncio.run(run())

    audio_frames = [f for f in pushed if isinstance(f, AudioRawFrame)]
    assert len(audio_frames) == 0
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
cd backend && pytest tests/test_voice_pipeline.py::test_samantha_llm_emits_text_frames tests/test_voice_pipeline.py::test_cosyvoice_tts_emits_audio_frames tests/test_voice_pipeline.py::test_cosyvoice_tts_stops_on_barge_in -v
```

Expected: `ImportError: cannot import name 'SamanthaLLMProcessor' from 'samantha.voice_pipeline'`

- [ ] **Step 3: Implement `SamanthaLLMProcessor` + `CosyVoiceTTSProcessor`**

Append to `backend/samantha/voice_pipeline.py` (after the WhisperSTTProcessor class):

```python
# ──────────────────────────────────────────────────────────────────────────
# Module-level aliases — monkeypatched in tests, real in production
# ──────────────────────────────────────────────────────────────────────────

from .context import gather_context
from .tts import stream as _tts_stream


async def _stream_reply(
    message: str,
    *,
    facts=None,
    recall=None,
    short_term=None,
    user_id: str = "primary",
) -> AsyncIterator[str]:
    """Thin wrapper so tests can monkeypatch samantha.voice_pipeline._stream_reply."""
    from .real_llm import stream_reply

    async for tok in stream_reply(
        message, facts=facts, recall=recall, short_term=short_term, user_id=user_id
    ):
        yield tok


# ──────────────────────────────────────────────────────────────────────────
# Sentinel frame
# ──────────────────────────────────────────────────────────────────────────


@dataclass
class LLMDoneFrame(Frame):
    """Signals CosyVoiceTTSProcessor that all tokens for this turn have arrived."""


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
        async for token in _stream_reply(
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
# Stage 4 — TTS
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
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
cd backend && pytest tests/test_voice_pipeline.py -v
```

Expected: all 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
cd backend && ruff check . && ruff format .
git add samantha/voice_pipeline.py tests/test_voice_pipeline.py
git commit -m "feat(voice): SamanthaLLMProcessor + CosyVoiceTTSProcessor"
```

---

## Task 5: `build_pipeline()` + `/voice` endpoint

**Files:**
- Modify: `backend/samantha/voice_pipeline.py` (add `build_pipeline`)
- Modify: `backend/samantha/api.py` (add `/voice` endpoint + `_active_voice_task`)
- Modify: `backend/tests/test_api.py` (add `/voice` connection test)

**Interfaces:**
- Produces:
  ```python
  # voice_pipeline.py
  def build_pipeline(
      websocket: WebSocket,
      mem: Memory | None,
      user_id: str = "primary",
      barge_in: asyncio.Event | None = None,
  ) -> PipelineTask: ...
  
  # api.py
  # GET /voice  (WebSocket)
  # Global: _active_voice_task: PipelineTask | None
  ```

- [ ] **Step 1: Add the `/voice` connection test to `test_api.py`**

Append to `backend/tests/test_api.py`:

```python
def test_voice_ws_accepts_and_closes():
    """GET /voice should accept a WebSocket connection without error."""
    from samantha import api as api_mod
    from samantha.voice_pipeline import build_pipeline
    from unittest.mock import AsyncMock, MagicMock, patch

    # build_pipeline returns a task whose run() ends immediately
    class _ImmediateTask:
        async def run(self):
            pass

        async def cancel(self):
            pass

    with patch.object(api_mod, "build_pipeline", return_value=_ImmediateTask()):
        client = TestClient(api_mod.app)
        # TestClient wraps WebSocket — just connecting and closing must not raise
        with client.websocket_connect("/voice"):
            pass


def test_voice_ws_single_client_displacement():
    """A second /voice connection must cancel the first task."""
    from samantha import api as api_mod
    from unittest.mock import AsyncMock, patch

    cancelled = []

    class _HangingTask:
        async def run(self):
            await asyncio.sleep(60)

        async def cancel(self):
            cancelled.append(True)

    class _ImmediateTask:
        async def run(self):
            pass

        async def cancel(self):
            pass

    tasks = [_HangingTask(), _ImmediateTask()]
    task_iter = iter(tasks)

    with patch.object(api_mod, "build_pipeline", side_effect=lambda *a, **kw: next(task_iter)):
        # Manually inject a "previous" task
        api_mod._active_voice_task = _HangingTask()
        client = TestClient(api_mod.app)
        with client.websocket_connect("/voice"):
            pass

    assert len(cancelled) >= 1
    api_mod._active_voice_task = None  # clean up
```

- [ ] **Step 2: Run test — expect FAIL**

```bash
cd backend && pytest tests/test_api.py::test_voice_ws_accepts_and_closes -v
```

Expected: `FAIL` with `404` or attribute error (endpoint not yet defined).

- [ ] **Step 3: Add `build_pipeline` to `voice_pipeline.py`**

Append to `backend/samantha/voice_pipeline.py`:

```python
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
    from pipecat.transports.network.fastapi_websocket import (
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
            vad_audio_passthrough=False,  # only emit frames when speech detected
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
```

- [ ] **Step 4: Add `/voice` endpoint to `api.py`**

Find the imports section near the top of `backend/samantha/api.py` and add:

```python
from .voice_pipeline import build_pipeline
```

Then find the last `@app.websocket` or `@app.post` definition and append the new endpoint after it:

```python
# Module-level — holds the single active /voice pipeline task.
# Kiosk is single-user: a new connection displaces the previous one.
_active_voice_task = None


@app.websocket("/voice")
async def voice_endpoint(websocket: WebSocket) -> None:
    """Server-side voice loop: VAD → Whisper STT → Grok LLM → CosyVoice TTS.

    Binary WebSocket frames carry 48 kHz int16 PCM uplink and 24 kHz
    int16 PCM downlink. JSON text frames carry control messages:
      browser → server: {"type": "barge_in"}
      server → browser: {"type": "transcript"|"token"|"error", ...}

    A new connection displaces the previous one (kiosk is single-user).
    """
    global _active_voice_task
    if _active_voice_task is not None:
        logger.info("voice: displacing previous connection")
        await _active_voice_task.cancel()
        _active_voice_task = None

    await websocket.accept()
    logger.info("voice: client connected")

    mem = await asyncio.to_thread(get_memory)
    task = build_pipeline(websocket, mem, user_id="primary")
    _active_voice_task = task
    try:
        await task.run()
    except Exception:
        logger.exception("voice: pipeline error")
    finally:
        _active_voice_task = None
        logger.info("voice: connection closed")
```

- [ ] **Step 5: Run all backend tests**

```bash
cd backend && pytest tests/ -v
```

Expected: all existing tests PASS + new voice tests PASS. If `test_voice_ws_accepts_and_closes` fails because `FastAPIWebsocketTransport` behaves differently in test context, patch `build_pipeline` in the test (already done in Step 1).

- [ ] **Step 6: Commit**

```bash
cd backend && ruff check . && ruff format .
git add samantha/voice_pipeline.py samantha/api.py tests/test_api.py
git commit -m "feat(voice): build_pipeline() + /voice WebSocket endpoint (single-client)"
```

---

## Task 6: Frontend `useVoiceSocket` hook

**Files:**
- Create: `frontend/src/net/useVoiceSocket.ts`

**Interfaces:**
- Produces:
  ```typescript
  interface VoiceState {
    connected: boolean;
    listening: boolean;
    speaking: boolean;
    error: string | null;
  }
  
  function useVoiceSocket(): {
    state: VoiceState;
    startListening: () => Promise<void>;
    stopListening: () => void;
    bargeIn: () => void;
  }
  ```
- Consumes: `useSamantha` (Zustand store) — `appendMessage`, `patchMessage`, `removeMessage`; `setActiveAnalyser` from `audio-analyser.ts`

- [ ] **Step 1: Create `frontend/src/net/useVoiceSocket.ts`**

```typescript
/**
 * useVoiceSocket — single hook for the server-side voice loop (Phase 11).
 *
 * Replaces: useSpeechRecognition + useBargeIn + speak() in ConversationScreen.
 *
 * WebSocket protocol (binary + JSON on the same /voice connection):
 *   Uplink:   ArrayBuffer — 48 kHz int16 PCM mono chunks from mic
 *             JSON string — {"type":"barge_in"}
 *   Downlink: ArrayBuffer — 24 kHz int16 PCM mono chunks (Samantha's voice)
 *             JSON string — {"type":"transcript"|"token"|"tts_done"|"error",...}
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { setActiveAnalyser } from "./audio-analyser";
import { useSamantha } from "../core/store";

// ─── types ────────────────────────────────────────────────────────────────

export interface VoiceState {
  connected: boolean;
  listening: boolean;
  speaking: boolean;
  error: string | null;
}

// ─── helpers ──────────────────────────────────────────────────────────────

function floatToInt16(float32: Float32Array): Int16Array {
  const out = new Int16Array(float32.length);
  for (let i = 0; i < float32.length; i++) {
    const clamped = Math.max(-1, Math.min(1, float32[i]));
    out[i] = clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff;
  }
  return out;
}

// ─── hook ─────────────────────────────────────────────────────────────────

export function useVoiceSocket() {
  const [state, setState] = useState<VoiceState>({
    connected: false,
    listening: false,
    speaking: false,
    error: null,
  });

  const wsRef = useRef<WebSocket | null>(null);
  const ctxRef = useRef<AudioContext | null>(null);
  const processorRef = useRef<ScriptProcessorNode | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const nextTimeRef = useRef<number>(0);
  const replyIdRef = useRef<string | null>(null);
  const replyAccumRef = useRef<string>("");

  const appendMessage = useSamantha((s) => s.appendMessage);
  const patchMessage = useSamantha((s) => s.patchMessage);
  const removeMessage = useSamantha((s) => s.removeMessage);

  // ── WebSocket lifecycle ─────────────────────────────────────────────────

  useEffect(() => {
    const protocol = window.location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${protocol}://${window.location.host}/voice`);
    ws.binaryType = "arraybuffer";
    wsRef.current = ws;

    ws.onopen = () => {
      setState((s) => ({ ...s, connected: true, error: null }));
    };

    ws.onclose = () => {
      setState((s) => ({
        ...s,
        connected: false,
        listening: false,
        speaking: false,
      }));
      setActiveAnalyser(null);
    };

    ws.onerror = () => {
      setState((s) => ({ ...s, error: "Conexión con el servidor perdida." }));
    };

    ws.onmessage = (event) => {
      if (event.data instanceof ArrayBuffer) {
        // PCM audio from Samantha — enqueue for gapless playback
        setState((s) => ({ ...s, speaking: true }));
        enqueuePCM(event.data);
      } else {
        handleControl(JSON.parse(event.data as string));
      }
    };

    return () => {
      ws.close();
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ── PCM playback ────────────────────────────────────────────────────────

  function getAudioContext(): AudioContext {
    if (!ctxRef.current || ctxRef.current.state === "closed") {
      const ctx = new AudioContext({ sampleRate: 24_000 });
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 256;
      analyserRef.current = analyser;
      analyser.connect(ctx.destination);
      setActiveAnalyser(analyser);
      ctxRef.current = ctx;
      nextTimeRef.current = ctx.currentTime;
    }
    return ctxRef.current;
  }

  function enqueuePCM(buffer: ArrayBuffer): void {
    const ctx = getAudioContext();
    const int16 = new Int16Array(buffer);
    const float32 = new Float32Array(int16.length);
    for (let i = 0; i < int16.length; i++) float32[i] = int16[i] / 32768;

    const audioBuffer = ctx.createBuffer(1, float32.length, 24_000);
    audioBuffer.copyToChannel(float32, 0);

    const source = ctx.createBufferSource();
    source.buffer = audioBuffer;
    source.connect(analyserRef.current!);

    const startAt = Math.max(ctx.currentTime, nextTimeRef.current);
    source.start(startAt);
    nextTimeRef.current = startAt + audioBuffer.duration;
    source.onended = () => {
      // If no more chunks are queued, mark speaking done
      if (Math.abs(nextTimeRef.current - ctx.currentTime) < 0.1) {
        setState((s) => ({ ...s, speaking: false }));
      }
    };
  }

  // ── Control frame dispatch ──────────────────────────────────────────────

  function handleControl(msg: Record<string, string>): void {
    if (msg.type === "transcript") {
      // User turn — add user bubble, open Samantha placeholder
      appendMessage({
        id: crypto.randomUUID(),
        role: "user",
        text: msg.text,
        timestamp: Date.now(),
      });
      const rid = crypto.randomUUID();
      replyIdRef.current = rid;
      replyAccumRef.current = "";
      appendMessage({ id: rid, role: "samantha", text: "", timestamp: Date.now() });
    } else if (msg.type === "token") {
      if (replyIdRef.current) {
        replyAccumRef.current += msg.text;
        patchMessage(replyIdRef.current, replyAccumRef.current);
      }
    } else if (msg.type === "error") {
      const rid = replyIdRef.current;
      if (rid) removeMessage(rid);
      replyIdRef.current = null;
      setState((s) => ({ ...s, error: msg.code ?? "Algo falló." }));
    }
  }

  // ── Mic capture ─────────────────────────────────────────────────────────

  const startListening = useCallback(async () => {
    if (state.listening) return;
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, sampleRate: 48_000 },
        video: false,
      });
    } catch {
      setState((s) => ({
        ...s,
        error: "No tengo permiso para el micrófono.",
      }));
      return;
    }
    streamRef.current = stream;

    // 48 kHz AudioContext for capture
    const captureCtx = new AudioContext({ sampleRate: 48_000 });
    const source = captureCtx.createMediaStreamSource(stream);
    // ScriptProcessorNode is deprecated but broadly supported in Chromium kiosk.
    // Buffer size 4096 @ 48 kHz = ~85 ms per chunk (acceptable latency).
    const proc = captureCtx.createScriptProcessor(4096, 1, 1);
    proc.onaudioprocess = (e) => {
      if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
      const float32 = e.inputBuffer.getChannelData(0);
      const int16 = floatToInt16(float32);
      wsRef.current.send(int16.buffer);
    };
    source.connect(proc);
    proc.connect(captureCtx.destination); // must be connected to receive events

    processorRef.current = proc;
    setState((s) => ({ ...s, listening: true, error: null }));
  }, [state.listening]);

  const stopListening = useCallback(() => {
    processorRef.current?.disconnect();
    processorRef.current = null;
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    setState((s) => ({ ...s, listening: false }));
  }, []);

  // ── Barge-in ────────────────────────────────────────────────────────────

  const bargeIn = useCallback(() => {
    wsRef.current?.send(JSON.stringify({ type: "barge_in" }));
    // Reset playback schedule so next audio starts immediately
    if (ctxRef.current) nextTimeRef.current = ctxRef.current.currentTime;
    setState((s) => ({ ...s, speaking: false }));
  }, []);

  return { state, startListening, stopListening, bargeIn };
}
```

- [ ] **Step 2: Typecheck**

```bash
cd frontend && pnpm typecheck
```

Expected: no errors related to `useVoiceSocket.ts`. If `appendMessage` / `patchMessage` / `removeMessage` don't exist on the Zustand store, check `frontend/src/core/store.ts` and use the actual method names — don't rename the methods in the store.

- [ ] **Step 3: Build**

```bash
cd frontend && pnpm build
```

Expected: build succeeds, `frontend/dist/` updated.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/net/useVoiceSocket.ts
git commit -m "feat(voice): useVoiceSocket hook — mic capture + PCM playback + JSON dispatch"
```

---

## Task 7: `ConversationScreen.tsx` swap + `audio-analyser.ts` + cleanup

Replace the browser-side voice choreography with `useVoiceSocket`. Remove `useBargeIn`.

**Files:**
- Modify: `frontend/src/screens/ConversationScreen.tsx`
- Modify: `frontend/src/net/audio-analyser.ts` (no change needed — `setActiveAnalyser` already exported; just verify)
- Delete: `frontend/src/core/useBargeIn.ts`

**Interfaces:**
- Consumes (from Task 6): `useVoiceSocket` → `state`, `startListening`, `stopListening`, `bargeIn`
- The text-input path (`sendMessage` via `/ws` WebSocket) remains unchanged.

- [ ] **Step 1: Verify `audio-analyser.ts` — no change required**

```bash
grep "export function setActiveAnalyser" frontend/src/net/audio-analyser.ts
```

Expected: one match. `useVoiceSocket` already calls `setActiveAnalyser(analyser)` when audio starts, so `Wave.tsx` will pick it up. No further change needed.

- [ ] **Step 2: Update `ConversationScreen.tsx` imports**

Remove these imports at the top of the file:

```typescript
import SpeechRecognition, { useSpeechRecognition } from "react-speech-recognition";
import { useBargeIn } from "../core/useBargeIn";
import { speak } from "../net/tts";
```

Add:

```typescript
import { useVoiceSocket } from "../net/useVoiceSocket";
```

- [ ] **Step 3: Replace hook usages in `ConversationScreen.tsx`**

Find the block that declares `useSpeechRecognition`, `useBargeIn`, `isSpeaking`, `speakAbortRef`, `bargedInRef`, and the effects that depend on them. Replace all of it with:

```typescript
const { state: voiceState, startListening, stopListening, bargeIn } = useVoiceSocket();
const { connected: voiceConnected, listening, speaking: isSpeaking, error: voiceError } = voiceState;

// Mirror voice errors into the status message shown to the user.
useEffect(() => {
  if (voiceError) setStatusMessage(voiceError);
}, [voiceError]);
```

Remove these now-unused state variables and refs:
- `const [conversationActive, setConversationActive] = useState(false);`
- `const [busy, setBusy] = useState(false);`
- `const busyRef = useRef(false);`
- `const speakAbortRef = useRef<AbortController | null>(null);`
- `const bargedInRef = useRef(false);`
- `const activeRef = useRef(false);`
- The `useEffect` that kept `activeRef.current` in sync with `conversationActive`
- The tail-echo guard `useEffect` that called `resetTranscript()`
- The `isMicrophoneAvailable` permission effect
- The `isSpeaking` + `setIsSpeaking` state

- [ ] **Step 4: Update `toggleConversation`**

Replace the existing `toggleConversation` function:

```typescript
const toggleConversation = () => {
  bump();
  setStatusMessage(null);
  if (!voiceConnected) {
    setStatusMessage("Sin conexión con el servidor de voz.");
    return;
  }
  if (listening) {
    stopListening();
  } else {
    void startListening();
  }
};
```

- [ ] **Step 5: Remove the Web Speech API debounce effect**

Delete the large `useEffect` block (around 20 lines) that watches `finalTranscript` and calls `sendMessage`. The voice pipeline handles transcription server-side; transcript arrives via the `useVoiceSocket` hook's JSON dispatch, not via the browser Speech API.

The text-input path (`onTextSubmit` → `sendMessage`) remains untouched.

- [ ] **Step 6: Remove Escape + barge-in from key handler**

In `useKeys`, replace the `Escape` handler — remove the `speakAbortRef.current?.abort()` line and replace it with `if (isSpeaking) bargeIn()`:

```typescript
useKeys({
  Escape: () => {
    if (isSpeaking) { bargeIn(); return; }
    if (showTextInput) setShowTextInput(false);
    else if (listening) stopListening();
    else route("ambient");
  },
  h: () => { bump(); setShowHistory((v) => !v); },
  H: () => { bump(); setShowHistory((v) => !v); },
  t: () => { bump(); setShowTextInput((v) => !v); },
  T: () => { bump(); setShowTextInput((v) => !v); },
});
```

- [ ] **Step 7: Remove Idle → Ambient SpeechRecognition call**

The idle effect calls `SpeechRecognition.stopListening()`. Replace with `stopListening()`:

```typescript
useEffect(() => {
  const tick = setInterval(() => {
    if (Date.now() - lastActivityRef.current > IDLE_TIMEOUT_MS) {
      stopListening();
      route("ambient");
    }
  }, 30_000);
  return () => clearInterval(tick);
}, [route, stopListening]);
```

- [ ] **Step 8: Update unmount cleanup**

Find the unmount `useEffect` that calls `SpeechRecognition.abortListening()`. Replace:

```typescript
useEffect(() => {
  mountedRef.current = true;
  return () => {
    mountedRef.current = false;
    stopListening();
  };
}, [stopListening]);
```

- [ ] **Step 9: Typecheck + build**

```bash
cd frontend && pnpm typecheck
```

Fix any remaining references to removed variables (e.g., `busy`, `setBusy`, `conversationActive`, `resetTranscript`, `finalTranscript`, `browserSupportsSpeechRecognition`, `isMicrophoneAvailable`). Each one either maps to `voiceState.listening` / `voiceState.speaking` / `voiceConnected`, or is simply deleted.

```bash
cd frontend && pnpm build
```

Expected: build succeeds.

- [ ] **Step 10: Delete `useBargeIn.ts`**

```bash
rm frontend/src/core/useBargeIn.ts
cd frontend && pnpm build
```

Expected: build still succeeds (no remaining imports).

- [ ] **Step 11: Commit**

```bash
git add frontend/src/screens/ConversationScreen.tsx
git rm frontend/src/core/useBargeIn.ts
git commit -m "feat(voice): wire useVoiceSocket in ConversationScreen; remove useBargeIn"
```

---

## Task 8: Final verification + PROGRESS.md

**Files:**
- Modify: `PROGRESS.md`

- [ ] **Step 1: Full backend test suite**

```bash
cd backend && pytest tests/ -v
```

Expected: all tests PASS. Note any skipped tests and confirm they were already skipped before this phase.

- [ ] **Step 2: Frontend build**

```bash
cd frontend && pnpm typecheck && pnpm build
```

Expected: zero type errors, build succeeds.

- [ ] **Step 3: Manual smoke checklist**

Start the backend in real mode and open Chromium to `http://localhost:7777/`:

```bash
cd backend && SAMANTHA_MODE=real uvicorn samantha.api:app --host 127.0.0.1 --port 7777 --reload
```

Check each item:

- [ ] **Mic tap** → wave switches to "listening" mode (wave pulse)
- [ ] **Speak** → transcript bubble appears in history
- [ ] **Samantha replies** → streaming tokens appear in Samantha bubble, wave switches to "speaking"
- [ ] **Audio plays** → Samantha's voice heard, analyser feeds Wave.tsx (wave reacts)
- [ ] **Barge-in** → press Esc mid-speech, audio stops, mic reopens
- [ ] **Second mic tap** → stops listening
- [ ] **Page reload** → `/voice` reconnects cleanly, previous task cancelled
- [ ] **Text input** (press T) → type a message, submit → still works via `/ws` path

If any check fails, diagnose before marking PROGRESS.md done.

- [ ] **Step 4: Update `PROGRESS.md`**

Add a new entry at the top of the "Completed phases" section:

```markdown
#### Phase 11: Server-side voice loop (Pipecat) ✅

Replaced browser-side STT/VAD/TTS with a single `/voice` WebSocket endpoint.

**Architecture:**
- `backend/samantha/voice_pipeline.py`: Four `FrameProcessor` subclasses —
  `Resample48kTo16kProcessor` (48k→16k), `WhisperSTTProcessor` (faster-whisper
  large-v3-turbo), `SamanthaLLMProcessor` (gather_context + stream_reply),
  `CosyVoiceTTSProcessor` (cosyvoice 3 synthesis). `build_pipeline()` wires them
  via Pipecat `Pipeline` + `FastAPIWebsocketTransport` with Silero VAD.
- `backend/samantha/api.py`: `/voice` WebSocket endpoint with single-client guard
  (`_active_voice_task` global).
- `backend/samantha/context.py`: `gather_context()` extracted from `api.py` to
  break circular import.
- `frontend/src/net/useVoiceSocket.ts`: Mic capture (ScriptProcessorNode @ 48 kHz)
  + PCM playback (AudioContext @ 24 kHz + analyser for Wave.tsx).
- `frontend/src/screens/ConversationScreen.tsx`: Replaced `useSpeechRecognition` +
  `useBargeIn` + `speak()` with `useVoiceSocket`.
- Deleted: `frontend/src/core/useBargeIn.ts`.
- Moved: `faster-whisper`, `numpy`, `pipecat-ai[silero]` to main deps.
```

- [ ] **Step 5: Commit and push**

```bash
cd backend && ruff check . && ruff format .
git add PROGRESS.md
git commit -m "docs: mark Phase 11 complete in PROGRESS.md"
git push origin development
```

---

## Self-Review

**1. Spec coverage:**

| Spec section | Task |
|---|---|
| `Resample48kTo16kProcessor` | Task 3 |
| `WhisperSTTService` | Task 3 |
| `SamanthaLLMService` → gather_context → stream_reply → JSON tokens | Task 4 |
| `CosyVoiceTTSService` + barge_in event | Task 4 |
| `build_pipeline()` + `FastAPIWebsocketTransport` + Silero VAD | Task 5 |
| `/voice` endpoint + single-client guard | Task 5 |
| `useVoiceSocket.ts` + AudioContext playback + analyser | Task 6 |
| `ConversationScreen.tsx` swap | Task 7 |
| `audio-analyser.ts` wire (setActiveAnalyser) | Task 6 |
| Remove `useBargeIn.ts` | Task 7 |
| `gather_context` extraction to `context.py` | Task 2 |
| pyproject.toml deps | Task 1 |
| `tts.ts` NOT deleted (OnboardingScreen still uses it) | noted in constraints |
| Test: resample, STT, LLM tokens, TTS audio, barge-in, single-client | Tasks 3, 4, 5 |
| PROGRESS.md | Task 8 |

**2. Placeholder scan:** All steps have concrete code. No "TBD" or "implement later".

**3. Type consistency:**
- `UserTranscriptFrame` defined in Task 3, used in Task 4 ✓
- `LLMDoneFrame` defined in Task 4, used in Task 4 (CosyVoiceTTSProcessor) ✓
- `gather_context` signature in Task 2 matches usage in Task 4 ✓
- `_stream_reply` wrapper in Task 4 matches monkeypatch in tests ✓
- `_tts_stream` alias in Task 4 matches monkeypatch in tests ✓
- `setActiveAnalyser` already exported from `audio-analyser.ts` ✓
- `appendMessage`, `patchMessage`, `removeMessage` — implementer must verify against actual store ✓
