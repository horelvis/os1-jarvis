"""Piper-based TTS for Samantha (Phase 5).

Wraps `piper-tts` so the rest of the backend doesn't have to know
about it. Two things matter to callers:

  synth(text)        → bytes  (WAV, 22.05 kHz, mono, 16-bit PCM)
  is_available()     → bool   (True if the voice model is on disk)

Voice files (~60 MB ONNX + 5 KB JSON) live at
`~/.samantha/voices/es_ES-davefx-medium.{onnx,onnx.json}`. They are
NOT shipped in the repo — see docs/01-setup-ubuntu.md (TODO) for the
download command. If the model is missing, `is_available()` returns
False and `synth()` raises `VoiceMissingError`; the caller (api.py
`/speak`) falls back to the placeholder tone WAV so the UI never
hangs on a missing dependency.

The PiperVoice instance is loaded lazily at the first call. Holding
it as a module global is safe — single-process single-user backend
(CLAUDE.md §1) — and avoids a ~200 ms onnxruntime startup on every
synth.
"""

from __future__ import annotations

import io
import wave
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from .config import config

if TYPE_CHECKING:
    from piper import PiperVoice


# Resolved on first call. None until then; False if we tried and failed.
_voice: "PiperVoice | None" = None
_load_failed: bool = False


class VoiceMissingError(RuntimeError):
    """Raised when synth() is called and no voice model is on disk."""


def _voice_paths() -> tuple[Path, Path]:
    """Return (onnx, json) paths for the configured voice."""
    base = Path(config.tts_voices_dir).expanduser()
    name = config.tts_voice
    return base / f"{name}.onnx", base / f"{name}.onnx.json"


def is_available() -> bool:
    """True iff the configured voice model is on disk."""
    onnx, json_ = _voice_paths()
    return onnx.is_file() and json_.is_file()


def _get_voice() -> "PiperVoice":
    """Lazy-load the voice model. Raises VoiceMissingError if absent."""
    global _voice, _load_failed
    if _voice is not None:
        return _voice
    if _load_failed:
        raise VoiceMissingError("tts voice previously failed to load")

    onnx, _json = _voice_paths()
    if not onnx.is_file():
        _load_failed = True
        raise VoiceMissingError(f"voice model not found: {onnx}")

    # Lazy import — piper-tts pulls in onnxruntime (~80 MB) and we
    # don't want pure-mock test runs to pay that cost.
    from piper import PiperVoice

    logger.info(f"tts: loading piper voice {config.tts_voice} from {onnx}")
    _voice = PiperVoice.load(str(onnx))
    logger.info(
        f"tts: voice ready (sample_rate={_voice.config.sample_rate} Hz)"
    )
    return _voice


def synth(text: str) -> bytes:
    """Synthesize `text` to a WAV byte string.

    Output is mono 16-bit PCM at the voice's native sample rate
    (22050 Hz for the medium-quality voices we ship). Wrapped in a
    standard RIFF/WAVE header so the frontend `<audio>` element
    plays it directly.

    Multi-speaker voices (e.g. `es_ES-sharvard-medium` with
    M=0, F=1) consume `config.tts_speaker_id`. Set it to None for
    single-speaker voices like `es_ES-davefx-medium`.

    Raises:
      VoiceMissingError — if the model isn't on disk.
    """
    if not text or not text.strip():
        return b""
    voice = _get_voice()

    # Build SynthesisConfig only when needed — `None` lets piper use
    # the model's default speaker, which is the right behaviour for
    # single-speaker voices.
    syn_config = None
    if config.tts_speaker_id is not None:
        from piper import SynthesisConfig

        syn_config = SynthesisConfig(speaker_id=config.tts_speaker_id)

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        voice.synthesize_wav(text.strip(), wf, syn_config=syn_config)
    return buf.getvalue()
