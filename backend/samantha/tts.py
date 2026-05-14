"""TTS for Samantha — vllm-omni streaming primary, Piper local fallback.

Two backends sit behind a single contract:

  config.tts_backend == "vllm_omni"  (default)
      Streams 24 kHz mono int16 PCM chunks from a vllm-omni server's
      OpenAI-compatible /v1/audio/speech endpoint. Voice cloning is
      driven by `tts_remote_ref_audio` + `tts_remote_ref_text`
      (Qwen3-TTS Base task_type). TTFA ~40 ms warm.

  config.tts_backend == "piper"
      Local Piper synth. One-shot WAV, ~50-300 ms on CPU. Fallback
      target when the remote is unreachable; can be selected
      explicitly for offline/CPU-only environments.

Public API:

    stream(text)   → async generator yielding (chunk, backend_label).
                     For vllm_omni chunks are header-less PCM. For
                     piper the single yielded chunk is a complete WAV.
    synth(text)    → sync wrapper; collects the stream and returns
                     (wav_bytes, backend_label). The WAV header is
                     stamped with the right sample rate for the
                     backend that served (24000 for vllm_omni,
                     whatever Piper's voice config reports for piper).
    is_available() → True iff the configured backend has plausible
                     config to serve.

The /speak handler in api.py keeps the sync `synth()` for now;
Phase 2.2 will switch it to a StreamingResponse driven by `stream()`.
"""

from __future__ import annotations

import asyncio
import io
import wave
from pathlib import Path
from typing import TYPE_CHECKING, AsyncIterator

import httpx
from loguru import logger

from .config import config

if TYPE_CHECKING:
    from piper import PiperVoice


class VoiceMissingError(RuntimeError):
    """Raised when synth()/stream() can't find any usable backend."""


# vllm-omni Qwen3-TTS native rate. Piper's rate is read from its
# voice config (typically 22050) when wrapping its bytes back into WAV.
VLLM_OMNI_SAMPLE_RATE = 24000


# ──────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────


def is_available() -> bool:
    """Cheap, non-network probe of whether the configured backend can serve.

    Doesn't ping the remote. The /speak handler relies on the runtime
    fall-through inside stream()/synth() to handle real failures.
    """
    backend = (config.tts_backend or "piper").lower()
    if backend == "vllm_omni":
        return bool(config.tts_remote_url)
    return _piper_voice_available()


async def stream(text: str) -> AsyncIterator[tuple[bytes, str]]:
    """Yield (chunk_bytes, backend_label) tuples.

    For backend=vllm_omni each chunk is raw 24 kHz mono int16 PCM
    (header-less); multiple chunks arrive over the streamed response.

    For backend=piper a single tuple is yielded whose `chunk_bytes`
    is the complete Piper WAV (header included) — Piper does not
    produce in-flight chunks.

    On vllm_omni failure the function silently falls back to Piper.
    Empty / whitespace input yields nothing.
    """
    if not text or not text.strip():
        return
    clean = text.strip()

    backend = (config.tts_backend or "piper").lower()
    if backend == "vllm_omni":
        try:
            async for chunk in _stream_vllm_omni(clean):
                yield chunk, "vllm_omni"
            return
        except Exception as e:
            logger.warning(
                f"tts: vllm_omni failed ({e}); falling back to piper"
            )

    # Piper path. The synth is sync; run it in a thread so we don't
    # block the event loop.
    wav = await asyncio.to_thread(_synth_piper, clean)
    yield wav, "piper"


def synth(text: str) -> tuple[bytes, str]:
    """Synchronous wrapper around `stream()`.

    Returns (wav_bytes, backend_label). For vllm_omni the streamed PCM
    chunks are concatenated and wrapped in a 24 kHz mono int16 WAV
    header. For piper the single chunk is already a complete WAV and
    is passed through.

    Returns (b"", "empty") on blank input.

    Used by api.py /speak today; Phase 2.2 will replace the caller
    with a StreamingResponse driven by `stream()` directly.
    """
    if not text or not text.strip():
        return b"", "empty"

    # asyncio.run is safe here because api.py invokes synth via
    # asyncio.to_thread, so the calling thread has no running loop.
    return asyncio.run(_consolidate(text))


async def _consolidate(text: str) -> tuple[bytes, str]:
    """Collect the async stream into a single (wav_bytes, backend) tuple."""
    chunks: list[bytes] = []
    backend: str = ""
    async for chunk, label in stream(text):
        chunks.append(chunk)
        backend = label

    if backend == "piper":
        # Piper already produced a complete WAV — pass through.
        return (chunks[0] if chunks else b""), "piper"

    if backend == "vllm_omni":
        pcm = b"".join(chunks)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(VLLM_OMNI_SAMPLE_RATE)
            wf.writeframes(pcm)
        return buf.getvalue(), "vllm_omni"

    return b"", "empty"


# ──────────────────────────────────────────────────────────────────
# vllm-omni backend
# ──────────────────────────────────────────────────────────────────


async def _stream_vllm_omni(text: str) -> AsyncIterator[bytes]:
    """POST to /v1/audio/speech with stream=true; yield PCM chunks.

    Body shape matches the OpenAI Audio API extended for Qwen3-TTS:
        input, model, task_type="Base", language,
        ref_audio (file URI or http(s) URL), ref_text,
        instructions, stream=true, response_format="pcm".

    Raises RuntimeError on non-200; raises VoiceMissingError if the
    remote URL isn't configured.
    """
    if not config.tts_remote_url:
        raise VoiceMissingError("tts_remote_url not configured")

    body: dict = {
        "input": text,
        "model": config.tts_remote_model,
        "task_type": "Base",
        "language": config.tts_remote_language,
        "ref_audio": config.tts_remote_ref_audio,
        "ref_text": config.tts_remote_ref_text,
        "stream": True,
        "response_format": "pcm",
    }
    if config.tts_remote_instructions:
        body["instructions"] = config.tts_remote_instructions

    url = f"{config.tts_remote_url.rstrip('/')}/v1/audio/speech"

    # read=None disables the per-read timeout. Streaming responses
    # may sit idle between chunks; the default 5s read timeout would
    # spuriously kill long generations.
    timeout = httpx.Timeout(
        connect=config.tts_remote_timeout_s,
        read=None,
        write=config.tts_remote_timeout_s,
        pool=config.tts_remote_timeout_s,
    )

    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream("POST", url, json=body) as resp:
            if resp.status_code != 200:
                err = await resp.aread()
                snippet = err[:200].decode("utf-8", errors="replace")
                raise RuntimeError(
                    f"vllm-omni {resp.status_code}: {snippet}"
                )
            async for chunk in resp.aiter_bytes(chunk_size=4096):
                if chunk:
                    yield chunk


# ──────────────────────────────────────────────────────────────────
# Piper backend (local fallback)
# ──────────────────────────────────────────────────────────────────


# Resolved on first call. None until then; True if we tried and failed.
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
    """Synthesize via local Piper. Returns a complete WAV (header included).

    Piper's native sample rate is whatever the voice model carries
    (es_ES-sharvard-medium is 22050 Hz). The browser <audio> element
    handles arbitrary rates via the WAV header so we don't resample.
    """
    voice = _get_piper_voice()

    syn_config = None
    if config.tts_speaker_id is not None:
        from piper import SynthesisConfig

        syn_config = SynthesisConfig(speaker_id=config.tts_speaker_id)

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        voice.synthesize_wav(text, wf, syn_config=syn_config)
    return buf.getvalue()
