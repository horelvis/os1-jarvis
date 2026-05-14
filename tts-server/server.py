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
  TTS_PORT          (default 9876)
  TTS_MODE          (default custom_voice; voice_clone for ref-audio cloning)
  TTS_MODEL_PATH    (default depends on TTS_MODE — CustomVoice for
                    custom_voice, Base for voice_clone)
  TTS_DEFAULT_SPEAKER  (default serena; only used in custom_voice mode)
  TTS_DEFAULT_LANGUAGE (default Spanish — capitalized; lowercase drifts
                       toward English/Chinese phonemes on preset voices)
  TTS_DEFAULT_INSTRUCT (default: a Spanish-priming instruction. Override
                       for other styles, e.g. "Whispering, very soft voice.")
  TTS_REF_AUDIO     (voice_clone only — path to the reference WAV;
                    default ~/.samantha/voices/ref/samantha.wav)
  TTS_REF_TEXT_FILE (voice_clone only — path to the reference transcript;
                    default ~/.samantha/voices/ref/samantha.txt)
  TTS_DEVICE        (default cuda if torch.cuda.is_available() else cpu)
  TTS_DTYPE         (default float16 on cuda, float32 on cpu)

Endpoints:
  GET  /ping         → {status, mode, model, languages, ...}
  POST /speak        → 24kHz mono 16-bit WAV.
                       Body: {"text": str, "speaker"?: str,
                              "language"?: str, "instruct"?: str}
                       In voice_clone mode `speaker` and `instruct` are
                       ignored (the voice is fixed by the ref audio).

Run:
  python -m server
or:
  uvicorn server:app --host 0.0.0.0 --port 9876
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
PORT = int(os.environ.get("TTS_PORT", "9876"))

# Two operating modes:
#   custom_voice → preset speakers (serena, vivian, …). Fast to set up
#                  but every preset is trained on Chinese/English/JP/KR
#                  speech, so Spanish output carries a foreign accent.
#   voice_clone  → clone the voice from a reference WAV + transcript.
#                  Requires the Base model variant. Native Spanish is
#                  achievable by pointing TTS_REF_AUDIO at a clean
#                  native-speaker sample.
TTS_MODE = os.environ.get("TTS_MODE", "custom_voice").strip().lower()
if TTS_MODE not in ("custom_voice", "voice_clone"):
    raise ValueError(
        f"TTS_MODE must be 'custom_voice' or 'voice_clone', got {TTS_MODE!r}"
    )

# Default model dir flips with the mode. Voice cloning needs the Base
# variant; the preset-speaker path needs the CustomVoice variant.
_DEFAULT_MODEL_SUBDIR = (
    "1.7B-Base" if TTS_MODE == "voice_clone" else "1.7B-CustomVoice"
)
MODEL_PATH = os.environ.get(
    "TTS_MODEL_PATH",
    str(Path.home() / ".samantha" / "qwen3-tts" / _DEFAULT_MODEL_SUBDIR),
)

# Voice-cloning reference. Only meaningful when TTS_MODE=voice_clone.
TTS_REF_AUDIO = os.environ.get(
    "TTS_REF_AUDIO",
    str(Path.home() / ".samantha" / "voices" / "ref" / "samantha.wav"),
)
TTS_REF_TEXT_FILE = os.environ.get(
    "TTS_REF_TEXT_FILE",
    str(Path.home() / ".samantha" / "voices" / "ref" / "samantha.txt"),
)

DEFAULT_SPEAKER = os.environ.get("TTS_DEFAULT_SPEAKER", "serena")
# Capitalized language name — the model's tokenizer treats "Spanish"
# and "spanish" as different tokens, and the lowercase form drifts
# toward English/Chinese phonemes (see Qwen3-TTS discussion #230).
DEFAULT_LANGUAGE = os.environ.get("TTS_DEFAULT_LANGUAGE", "Spanish")
# Style instruction primes the model toward Spanish phonemes when the
# selected speaker (serena/vivian/etc.) isn't a native Spanish voice.
DEFAULT_INSTRUCT = (
    os.environ.get(
        "TTS_DEFAULT_INSTRUCT",
        "Voz femenina, español nativo de España. "
        "Tono conversacional y cálido.",
    ).strip()
    or None
)

# Device override. If unset, picks CUDA when available, else CPU.
DEVICE = os.environ.get("TTS_DEVICE", "").strip() or None
# Precision. fp16 is the sweet spot on Ada/Hopper (4090, A100): same
# perceived quality, ~2× faster, ~2× less VRAM. CPU runs in fp32 by
# default — fp16 on CPU is actually slower because of emulation.
DTYPE = os.environ.get("TTS_DTYPE", "").strip() or None


# ──────────────────────────────────────────────────────────────────
# Model singleton (lazy)
# ──────────────────────────────────────────────────────────────────

_model = None


def _resolve_device_dtype() -> tuple[str, "object"]:
    """Pick the right device + dtype.

    Without this the qwen-tts default initialization lands on CPU
    even when a CUDA device is available — and the user sees RTF
    ~2.5 on a 4090 instead of ~0.2.
    """
    import torch  # local import — only needed when actually loading

    if DEVICE:
        device = DEVICE
    else:
        device = "cuda" if torch.cuda.is_available() else "cpu"

    if DTYPE:
        dtype = getattr(torch, DTYPE)
    else:
        # fp16 on GPU, fp32 on CPU. Mixed precision on CPU is slower.
        dtype = torch.float16 if device.startswith("cuda") else torch.float32

    return device, dtype


def get_model():
    """Lazy-load Qwen3-TTS. Cached for process lifetime.

    The qwen-tts `Qwen3TTSModel.from_pretrained` forwards **kwargs
    straight to `AutoModel.from_pretrained`, so we pass HuggingFace's
    canonical `device_map` + `torch_dtype` here. Without explicit
    kwargs the model lands on CPU even on a 4090 (RTF ~2.5 instead
    of ~0.2).
    """
    global _model
    if _model is not None:
        return _model

    from qwen_tts import Qwen3TTSModel  # heavy import — kept lazy

    device, dtype = _resolve_device_dtype()
    logger.info(
        f"loading Qwen3-TTS from {MODEL_PATH} (device_map={device}, dtype={dtype})"
    )
    t0 = time.perf_counter()
    # Note: transformers 4.57+ renamed `torch_dtype` → `dtype` in
    # from_pretrained. Both still work but `torch_dtype` emits a
    # DeprecationWarning. Use the new name.
    _model = Qwen3TTSModel.from_pretrained(
        MODEL_PATH,
        device_map=device,
        dtype=dtype,
    )
    logger.info(f"Qwen3-TTS ready in {time.perf_counter() - t0:.1f}s")
    return _model


_ref_text: str | None = None


def _get_ref_text() -> str:
    """Load + cache the reference transcript (voice_clone mode only)."""
    global _ref_text
    if _ref_text is None:
        path = Path(TTS_REF_TEXT_FILE)
        if not path.is_file():
            raise FileNotFoundError(
                f"voice-clone ref text not found: {path}. "
                "Set TTS_REF_TEXT_FILE or write the transcript to the "
                "default path."
            )
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            raise ValueError(f"voice-clone ref text at {path} is empty")
        _ref_text = text
    return _ref_text


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
    out: dict = {
        "status": "ok",
        "mode": TTS_MODE,
        "model": MODEL_PATH,
        "default_language": DEFAULT_LANGUAGE,
        "languages": model.get_supported_languages(),
    }
    if TTS_MODE == "custom_voice":
        out["default_speaker"] = DEFAULT_SPEAKER
        try:
            out["speakers"] = model.get_supported_speakers()
        except Exception:  # Base model exposes no preset speakers.
            out["speakers"] = []
    else:
        out["ref_audio"] = TTS_REF_AUDIO
        out["ref_text_file"] = TTS_REF_TEXT_FILE
        try:
            out["ref_text_preview"] = _get_ref_text()[:120]
        except Exception as e:
            out["ref_text_preview"] = f"(error: {e})"
    return out


@app.post("/speak")
async def speak(req: SpeakRequest) -> Response:
    """Synthesize `text` to a 24 kHz mono WAV.

    In `custom_voice` mode the request's speaker/instruct steer the
    output. In `voice_clone` mode those fields are ignored — the voice
    is fixed by TTS_REF_AUDIO + TTS_REF_TEXT_FILE.
    """
    model = get_model()
    language = req.language or DEFAULT_LANGUAGE

    t0 = time.perf_counter()
    try:
        if TTS_MODE == "voice_clone":
            ref_audio = Path(TTS_REF_AUDIO)
            if not ref_audio.is_file():
                raise FileNotFoundError(
                    f"voice-clone ref audio not found: {ref_audio}. "
                    "Set TTS_REF_AUDIO or put a WAV at the default path."
                )
            audio_chunks, sr = model.generate_voice_clone(
                text=req.text,
                language=language,
                ref_audio=str(ref_audio),
                ref_text=_get_ref_text(),
            )
            backend_label = "qwen3_clone"
            speaker_label = "cloned"
        else:
            speaker_label = req.speaker or DEFAULT_SPEAKER
            instruct = (
                req.instruct if req.instruct is not None else DEFAULT_INSTRUCT
            )
            audio_chunks, sr = model.generate_custom_voice(
                text=req.text,
                speaker=speaker_label,
                language=language,
                instruct=instruct,
            )
            backend_label = "qwen3"
    except ValueError as e:
        # Speaker / language validation errors land here.
        raise HTTPException(status_code=422, detail=str(e)) from e
    except FileNotFoundError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    except Exception as e:  # pragma: no cover — runtime safety net
        logger.exception("synth failed")
        raise HTTPException(status_code=500, detail=str(e)) from e

    wav_bytes = _audio_to_wav(audio_chunks, sr)
    duration_s = sum(c.shape[0] for c in audio_chunks) / sr
    elapsed = time.perf_counter() - t0
    rtf = elapsed / duration_s if duration_s > 0 else float("inf")
    logger.info(
        f"speak: {len(req.text)} chars → {duration_s:.2f}s audio "
        f"in {elapsed * 1000:.0f}ms (RTF={rtf:.2f}) "
        f"mode={TTS_MODE} speaker={speaker_label}"
    )

    return Response(
        content=wav_bytes,
        media_type="audio/wav",
        headers={
            "X-TTS-Backend": backend_label,
            "X-TTS-Speaker": speaker_label,
            "X-TTS-RTF": f"{rtf:.2f}",
            "X-TTS-Audio-Duration-S": f"{duration_s:.2f}",
        },
    )


if __name__ == "__main__":
    import uvicorn

    logger.info(f"Samantha TTS server starting on {HOST}:{PORT}")
    logger.info(f"Mode: {TTS_MODE}")
    logger.info(f"Model: {MODEL_PATH}")
    if TTS_MODE == "voice_clone":
        logger.info(f"Ref audio: {TTS_REF_AUDIO}")
        logger.info(f"Ref text file: {TTS_REF_TEXT_FILE}")
    else:
        logger.info(f"Default speaker: {DEFAULT_SPEAKER} ({DEFAULT_LANGUAGE})")
    uvicorn.run(
        "server:app",
        host=HOST,
        port=PORT,
        log_level="info",
        reload=False,
    )
