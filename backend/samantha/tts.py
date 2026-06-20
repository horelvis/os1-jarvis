"""TTS for Samantha — CosyVoice 3 (zero-shot voice cloning).

Emits 24 kHz mono int16 PCM chunks via
/inference_zero_shot on the CosyVoice 3 server (4090, port 8093).
Sends the reference WAV + its transcript on every call so the model
gets prosodic conditioning. Honors personality v6 inline markers
(`[laughter]`, `<laughter>palabras</laughter>`, `[breath]`, `[sigh]`).

Public API:

    OUTPUT_SAMPLE_RATE: int = 24000 — the rate of every yielded chunk
    stream(text)   → async generator yielding (pcm_chunk, "cosyvoice").
                     PCM is raw int16 little-endian at 24 kHz mono.
    synth(text)    → sync wrapper; collects the stream and returns
                     (wav_bytes, "cosyvoice"). WAV header at 24 kHz.
                     Test-only convenience; /speak uses stream().
    is_available() → True iff the ref WAV and transcript are on disk.
"""

from __future__ import annotations

import asyncio
import io
import wave
from pathlib import Path
from typing import AsyncIterator

import httpx
from loguru import logger

from .config import config


class VoiceMissingError(RuntimeError):
    """Raised when the CosyVoice reference files are not on disk."""


OUTPUT_SAMPLE_RATE = 24000


# ──────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────


def is_available() -> bool:
    """Cheap, non-network probe: ref WAV + transcript exist on disk."""
    return (
        bool(config.tts_cosyvoice_url)
        and Path(config.tts_cosyvoice_ref_wav).expanduser().is_file()
        and Path(config.tts_cosyvoice_ref_transcript_path).expanduser().is_file()
    )


async def stream(text: str) -> AsyncIterator[tuple[bytes, str]]:
    """Yield (pcm_chunk, "cosyvoice") tuples.

    Every chunk is raw 24 kHz mono int16 little-endian PCM, no header.
    Empty input yields nothing. Exceptions propagate so the caller can
    surface a real error instead of silence.
    """
    if not text or not text.strip():
        return
    async for chunk in _stream_cosyvoice(text.strip()):
        yield chunk, "cosyvoice"


def synth(text: str) -> tuple[bytes, str]:
    """Synchronous wrapper around stream(). Returns (wav_bytes, backend).

    Test-only convenience; /speak uses stream() via StreamingResponse
    so audio starts flowing before synthesis ends.
    """
    if not text or not text.strip():
        return b"", "empty"
    return asyncio.run(_consolidate(text))


async def _consolidate(text: str) -> tuple[bytes, str]:
    chunks: list[bytes] = []
    backend: str = ""
    async for chunk, label in stream(text):
        chunks.append(chunk)
        backend = label

    if not backend:
        return b"", "empty"

    pcm = b"".join(chunks)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(OUTPUT_SAMPLE_RATE)
        wf.writeframes(pcm)
    return buf.getvalue(), backend


# ──────────────────────────────────────────────────────────────────
# CosyVoice 3 backend
# ──────────────────────────────────────────────────────────────────

_cosyvoice_ref_transcript: str | None = None
_cosyvoice_ref_wav_bytes: bytes | None = None


def _load_cosyvoice_refs() -> tuple[str, bytes, str]:
    """Lazy-load (and cache) the reference transcript + WAV bytes.

    Returns (transcript, wav_bytes, wav_name).
    Raises VoiceMissingError if either file is missing.
    """
    global _cosyvoice_ref_transcript, _cosyvoice_ref_wav_bytes

    wav_path = Path(config.tts_cosyvoice_ref_wav).expanduser()
    txt_path = Path(config.tts_cosyvoice_ref_transcript_path).expanduser()

    if _cosyvoice_ref_transcript is None:
        if not txt_path.is_file():
            raise VoiceMissingError(f"cosyvoice transcript not found: {txt_path}")
        _cosyvoice_ref_transcript = txt_path.read_text(encoding="utf-8").strip()
        logger.info(
            f"tts: loaded cosyvoice transcript "
            f"({len(_cosyvoice_ref_transcript)} chars) from {txt_path}"
        )

    if _cosyvoice_ref_wav_bytes is None:
        if not wav_path.is_file():
            raise VoiceMissingError(f"cosyvoice ref wav not found: {wav_path}")
        _cosyvoice_ref_wav_bytes = wav_path.read_bytes()
        logger.info(
            f"tts: cached cosyvoice ref wav ({len(_cosyvoice_ref_wav_bytes)} bytes) from {wav_path}"
        )

    return _cosyvoice_ref_transcript, _cosyvoice_ref_wav_bytes, wav_path.name


async def _stream_cosyvoice(text: str) -> AsyncIterator[bytes]:
    """POST tts_text + ref transcript + ref WAV to /inference_zero_shot;
    yield raw 24 kHz mono int16 PCM chunks.

    The server overlay (tts-server/cosyvoice/server.py) prepends
    `"You are a helpful assistant.<|endofprompt|>"` to prompt_text
    so we send plain Spanish here.

    Failure modes:
      - tts_text much shorter than prompt_text → hifigan crashes with a
        kernel-size error; server returns 200 + empty body. Detected and
        raised as a useful error.
      - Unrecognized marker → same silent 200+empty failure.
    """
    transcript, wav_bytes, wav_name = _load_cosyvoice_refs()

    url = f"{config.tts_cosyvoice_url.rstrip('/')}/inference_zero_shot"
    # `read` is httpx's per-read-operation (inter-chunk) timeout, not a
    # whole-body cap: a healthy stream that keeps emitting chunks never
    # trips it, while a wedged server (CUDA hang) fails loudly instead
    # of freezing /speak forever.
    timeout = httpx.Timeout(
        connect=config.tts_cosyvoice_timeout_s,
        read=config.tts_cosyvoice_timeout_s,
        write=config.tts_cosyvoice_timeout_s,
        pool=config.tts_cosyvoice_timeout_s,
    )
    # httpx multipart: (filename, content, content-type). filename=None
    # for text fields makes httpx emit them as plain form parts.
    files = {
        "tts_text": (None, text),
        "prompt_text": (None, transcript),
        "prompt_wav": (wav_name, wav_bytes, "audio/wav"),
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream("POST", url, files=files) as resp:
            if resp.status_code != 200:
                err = await resp.aread()
                raise RuntimeError(
                    f"cosyvoice {resp.status_code}: {err[:200].decode('utf-8', 'replace')}"
                )
            got_any = False
            async for chunk in resp.aiter_bytes(chunk_size=4096):
                if chunk:
                    got_any = True
                    yield chunk
            if not got_any:
                raise RuntimeError(
                    "cosyvoice returned 200 but no audio — most likely "
                    "tts_text shorter than prompt_text (hifigan kernel "
                    "size 4), or an unrecognized expression marker"
                )
