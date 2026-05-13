"""TTS for Samantha — backend-pluggable.

Two paths today:

  config.tts_backend == "qwen3_remote"
      POST text → http://{qwen3_tts_url}/speak.
      Returns WAV (24 kHz). Runs on a GPU box (4090) so the mini-PC
      doesn't have to fit a transformer TTS model in its 8 GB VRAM.
      On any network/HTTP failure we silently fall back to Piper.

  config.tts_backend == "piper"  (default, fallback)
      Local Piper synth using the model at
      `~/.samantha/voices/{tts_voice}.onnx`. Fast (~50 ms on CPU,
      no GPU needed). Single-speaker voices ignore tts_speaker_id;
      multi-speaker voices (sharvard M=0, F=1) honour it.

Both paths expose the same contract:

    synth(text)    → WAV bytes
    is_available() → bool

Callers (api.py /speak) don't care which backend served the WAV
beyond the X-TTS-Backend response header for observability.
"""

from __future__ import annotations

import io
import wave
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
from loguru import logger

from .config import config

if TYPE_CHECKING:
    from piper import PiperVoice


class VoiceMissingError(RuntimeError):
    """Raised when synth() can't find any usable backend."""


# ──────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────


def is_available() -> bool:
    """True iff at least one backend can serve a request.

    Doesn't actually probe the remote — that would block; just checks
    that the configured backend is plausible. The /speak handler
    handles real failures by falling back to the next backend.
    """
    backend = (config.tts_backend or "piper").lower()
    if backend == "qwen3_remote":
        # Remote URL must be set; we don't ping it here.
        return bool(config.qwen3_tts_url)
    # Piper requires the on-disk voice.
    return _piper_voice_available()


def synth(text: str) -> tuple[bytes, str]:
    """Synthesize `text`.

    Returns (wav_bytes, backend_used). `backend_used` is the actual
    backend that produced the audio — important when the requested
    backend silently fell back (e.g. qwen3_remote unreachable →
    piper). The /speak handler uses it for the X-TTS-Mode response
    header so observability doesn't lie.

    WAV is mono 16-bit PCM at the backend's native sample rate
    (22050 Hz for Piper, 24000 Hz for Qwen3-TTS). The frontend
    `<audio>` element plays both transparently.

    Raises VoiceMissingError if every configured backend fails.
    """
    if not text or not text.strip():
        return b"", "empty"

    backend = (config.tts_backend or "piper").lower()
    clean = text.strip()

    if backend == "qwen3_remote":
        try:
            return _synth_qwen3_remote(clean), "qwen3_remote"
        except Exception as e:
            logger.warning(
                f"tts: qwen3_remote failed ({e}); falling back to piper"
            )
            # Fall through to Piper below.

    return _synth_piper(clean), "piper"


# ──────────────────────────────────────────────────────────────────
# Qwen3 remote backend
# ──────────────────────────────────────────────────────────────────


def _synth_qwen3_remote(text: str) -> bytes:
    """POST text to the remote Qwen3-TTS server and return WAV bytes.

    The remote is expected to honour the contract from
    `tts-server/server.py`:
        POST /speak  {"text", "speaker"?, "language"?, "instruct"?}
        → audio/wav (24 kHz mono 16-bit PCM)
    """
    if not config.qwen3_tts_url:
        raise VoiceMissingError("qwen3_tts_url not configured")

    url = f"{config.qwen3_tts_url.rstrip('/')}/speak"
    payload: dict[str, str] = {"text": text}
    if config.qwen3_speaker:
        payload["speaker"] = config.qwen3_speaker
    if config.qwen3_language:
        payload["language"] = config.qwen3_language
    if config.qwen3_instruct:
        payload["instruct"] = config.qwen3_instruct

    # Synchronous httpx call — the /speak FastAPI handler is async and
    # wraps the synth in `asyncio.to_thread`, so this blocking call
    # doesn't tie up the event loop.
    with httpx.Client(timeout=config.qwen3_tts_timeout_s) as client:
        resp = client.post(url, json=payload)
    if resp.status_code != 200:
        raise RuntimeError(
            f"qwen3 remote returned {resp.status_code}: {resp.text[:200]}"
        )
    return resp.content


# ──────────────────────────────────────────────────────────────────
# Piper backend (local, fallback)
# ──────────────────────────────────────────────────────────────────


# Resolved on first call. None until then; False if we tried and failed.
_voice: "PiperVoice | None" = None
_voice_load_failed: bool = False


def _voice_paths() -> tuple[Path, Path]:
    base = Path(config.tts_voices_dir).expanduser()
    name = config.tts_voice
    return base / f"{name}.onnx", base / f"{name}.onnx.json"


def _piper_voice_available() -> bool:
    onnx, json_ = _voice_paths()
    return onnx.is_file() and json_.is_file()


def _get_piper_voice() -> "PiperVoice":
    """Lazy-load the Piper voice. Raises VoiceMissingError if absent."""
    global _voice, _voice_load_failed
    if _voice is not None:
        return _voice
    if _voice_load_failed:
        raise VoiceMissingError("piper voice previously failed to load")

    onnx, _json = _voice_paths()
    if not onnx.is_file():
        _voice_load_failed = True
        raise VoiceMissingError(f"piper voice model not found: {onnx}")

    # Lazy import — piper-tts pulls in onnxruntime (~80 MB) and we
    # don't want pure-mock test runs to pay that cost.
    from piper import PiperVoice

    logger.info(f"tts: loading piper voice {config.tts_voice} from {onnx}")
    _voice = PiperVoice.load(str(onnx))
    logger.info(
        f"tts: piper voice ready (sample_rate={_voice.config.sample_rate} Hz)"
    )
    return _voice


def _synth_piper(text: str) -> bytes:
    voice = _get_piper_voice()

    # Build SynthesisConfig only when needed — `None` lets piper use
    # the model's default speaker, which is the right behaviour for
    # single-speaker voices.
    syn_config = None
    if config.tts_speaker_id is not None:
        from piper import SynthesisConfig

        syn_config = SynthesisConfig(speaker_id=config.tts_speaker_id)

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        voice.synthesize_wav(text, wf, syn_config=syn_config)
    return buf.getvalue()
