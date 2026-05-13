"""Standalone Qwen3-TTS HTTP server.

Designed to run on a machine with a real GPU (the 4090 box in our
case) while Samantha herself runs on a smaller mini-PC. The Samantha
backend hits this server's /speak when `tts_backend = qwen3_remote`.

Why a separate process:
- Keeps the heavy model (`qwen-tts` + torch + transformers, ~2 GB on
  disk, ~3 GB VRAM at fp16) off the mini-PC, which is already loading
  the Qwen LLM.
- Loads the voice once and reuses it. No per-request startup cost.
- Decouples deploy lifecycles. We can restart Samantha without
  re-loading the TTS model.

Config via environment:
  TTS_HOST          (default 0.0.0.0)
  TTS_PORT          (default 9000)
  TTS_MODEL_PATH    (default ~/.samantha/qwen3-tts/1.7B-CustomVoice)
  TTS_DEFAULT_SPEAKER  (default serena)
  TTS_DEFAULT_LANGUAGE (default spanish)
  TTS_DEFAULT_INSTRUCT (default empty — pass-through to Qwen3 style
                       prompt; e.g. "Whispering, very soft voice.")

Endpoints:
  GET  /ping         → {status, model, speaker, languages, speakers}
  POST /speak        → 24kHz mono 16-bit WAV.
                       Body: {"text": str, "speaker"?: str,
                              "language"?: str, "instruct"?: str}

Run:
  python -m server
or:
  uvicorn server:app --host 0.0.0.0 --port 9000
"""

from __future__ import annotations

import io
import os
import time
import wave
from pathlib import Path

import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from loguru import logger
from pydantic import BaseModel, Field


# ──────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────

HOST = os.environ.get("TTS_HOST", "0.0.0.0")
PORT = int(os.environ.get("TTS_PORT", "9000"))
MODEL_PATH = os.environ.get(
    "TTS_MODEL_PATH",
    str(Path.home() / ".samantha" / "qwen3-tts" / "1.7B-CustomVoice"),
)
DEFAULT_SPEAKER = os.environ.get("TTS_DEFAULT_SPEAKER", "serena")
DEFAULT_LANGUAGE = os.environ.get("TTS_DEFAULT_LANGUAGE", "spanish")
DEFAULT_INSTRUCT = os.environ.get("TTS_DEFAULT_INSTRUCT", "").strip() or None


# ──────────────────────────────────────────────────────────────────
# Model singleton (lazy)
# ──────────────────────────────────────────────────────────────────

_model = None


def get_model():
    """Lazy-load Qwen3-TTS. Cached for process lifetime."""
    global _model
    if _model is not None:
        return _model

    from qwen_tts import Qwen3TTSModel  # heavy import — kept lazy

    logger.info(f"loading Qwen3-TTS from {MODEL_PATH}")
    t0 = time.perf_counter()
    _model = Qwen3TTSModel.from_pretrained(MODEL_PATH)
    logger.info(f"Qwen3-TTS ready in {time.perf_counter() - t0:.1f}s")
    return _model


def _audio_to_wav(audio_chunks: list, sample_rate: int) -> bytes:
    """Concatenate float-32 chunks → 16-bit PCM WAV bytes."""
    wav_f32 = np.concatenate(audio_chunks).astype(np.float32)
    wav_i16 = np.clip(wav_f32 * 32767.0, -32768, 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(wav_i16.tobytes())
    return buf.getvalue()


# ──────────────────────────────────────────────────────────────────
# API
# ──────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Samantha TTS server (Qwen3-TTS)",
    description="Remote TTS for the Samantha kiosk. Single user, single voice.",
    version="0.1.0",
)


class SpeakRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    speaker: str | None = Field(
        default=None,
        description="One of the supported CustomVoice speaker IDs. "
        "Falls back to TTS_DEFAULT_SPEAKER if absent.",
    )
    language: str | None = Field(
        default=None,
        description="Language name (full name, e.g. 'spanish'). "
        "Falls back to TTS_DEFAULT_LANGUAGE.",
    )
    instruct: str | None = Field(
        default=None,
        description="Optional natural-language style instruction "
        "('Whispering, soft voice.') passed to Qwen3's controllable "
        "synthesis path.",
    )


@app.get("/ping")
async def ping() -> dict:
    """Health + capability probe. Loads the model on first hit so the
    first /speak isn't paying the cold-start tax."""
    model = get_model()
    return {
        "status": "ok",
        "model": MODEL_PATH,
        "default_speaker": DEFAULT_SPEAKER,
        "default_language": DEFAULT_LANGUAGE,
        "languages": model.get_supported_languages(),
        "speakers": model.get_supported_speakers(),
    }


@app.post("/speak")
async def speak(req: SpeakRequest) -> Response:
    """Synthesize `text` to a 24 kHz mono WAV."""
    model = get_model()
    speaker = req.speaker or DEFAULT_SPEAKER
    language = req.language or DEFAULT_LANGUAGE
    instruct = req.instruct if req.instruct is not None else DEFAULT_INSTRUCT

    t0 = time.perf_counter()
    try:
        audio_chunks, sr = model.generate_custom_voice(
            text=req.text,
            speaker=speaker,
            language=language,
            instruct=instruct,
        )
    except ValueError as e:
        # Speaker / language validation errors land here.
        raise HTTPException(status_code=422, detail=str(e)) from e
    except Exception as e:  # pragma: no cover — runtime safety net
        logger.exception("synth failed")
        raise HTTPException(status_code=500, detail=str(e)) from e

    wav_bytes = _audio_to_wav(audio_chunks, sr)
    duration_s = sum(c.shape[0] for c in audio_chunks) / sr
    elapsed = time.perf_counter() - t0
    rtf = elapsed / duration_s if duration_s > 0 else float("inf")
    logger.info(
        f"speak: {len(req.text)} chars → {duration_s:.2f}s audio "
        f"in {elapsed * 1000:.0f}ms (RTF={rtf:.2f}) speaker={speaker}"
    )

    return Response(
        content=wav_bytes,
        media_type="audio/wav",
        headers={
            "X-TTS-Backend": "qwen3",
            "X-TTS-Speaker": speaker,
            "X-TTS-RTF": f"{rtf:.2f}",
            "X-TTS-Audio-Duration-S": f"{duration_s:.2f}",
        },
    )


if __name__ == "__main__":
    import uvicorn

    logger.info(f"Samantha TTS server starting on {HOST}:{PORT}")
    logger.info(f"Model: {MODEL_PATH}")
    logger.info(f"Default speaker: {DEFAULT_SPEAKER} ({DEFAULT_LANGUAGE})")
    uvicorn.run(
        "server:app",
        host=HOST,
        port=PORT,
        log_level="info",
        reload=False,
    )
