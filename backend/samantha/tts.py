"""TTS for Samantha — XTTS-v2 default, CosyVoice 3 for expressive, Piper local fallback.

All backends emit through a single contract: 24 kHz mono int16 PCM
chunks. Piper's native 22050 Hz output is resampled on the fly to
keep the wire format uniform — the frontend only has to know one
sample rate.

  config.tts_backend == "xtts"  (default)
      Streams PCM chunks from Coqui xtts-streaming-server (port
      8092 on the 4090) with our overlay that exposes
      temperature / top_p / repetition_penalty / speed. Voice
      cloning from `tts_xtts_ref_wav` (uploaded once, embeddings
      cached). Chosen over vllm-omni + Qwen3-TTS after A/B testing
      on 2026-05-15: same tone across requests, expressive at
      temperature 0.85.

  config.tts_backend == "cosyvoice"
      CosyVoice 3 zero-shot (port 8093 on the 4090) via
      inference_zero_shot. Sends the ref WAV + its transcript on
      every call so the LLM gets prosodic conditioning (cross_lingual
      strips it and sounds robotic). The ONLY backend that honors
      Samantha's inline expression markers from personality v6
      (`[laughter]`, `<laughter>palabras</laughter>`, `[breath]`,
      `[sigh]`). For every other backend `_strip_tts_markers()` wipes
      them upstream so they don't get read literally.

  config.tts_backend == "piper"
      Local Piper synth. One-shot WAV, ~50-300 ms on CPU. WAV header
      stripped, PCM resampled 22050 → 24000 with linear interp, and
      the whole thing yielded as a single chunk. Selectable
      explicitly for offline / CPU-only environments. No auto-
      fallback from xtts — see CLAUDE.md decision log.

Public API:

    OUTPUT_SAMPLE_RATE: int = 24000 — the rate of every yielded chunk
    stream(text)   → async generator yielding (pcm_chunk, backend).
                     PCM is raw int16 little-endian at 24 kHz mono.
    synth(text)    → sync wrapper; collects the stream and returns
                     (wav_bytes, backend). WAV header stamped at
                     24 kHz. Kept for the rare non-streaming caller.
    is_available() → True iff the configured backend has plausible
                     config to serve.
"""

from __future__ import annotations

import asyncio
import io
import re
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


# Uniform output rate. XTTS-v2 emits 24 kHz natively; Piper (22050)
# is resampled up to match before being yielded.
OUTPUT_SAMPLE_RATE = 24000


# Personality v6 lets Samantha emit inline CosyVoice 3 markers like
# `[laughter]` and `<laughter>de verdad</laughter>`. XTTS and Piper
# don't understand them — they'd read "corchete laughter corchete"
# letter by letter. Strip when not routing to a marker-aware backend.
# `[foo]` → removed entirely; `<tag>X</tag>` → keep X, drop the tags.
_BRACKET_MARKER_RE = re.compile(r"\[[a-z][a-z_-]*\]")
_TAG_MARKER_RE = re.compile(r"</?[a-z][a-z_-]*>")


def _strip_tts_markers(text: str) -> str:
    return _TAG_MARKER_RE.sub("", _BRACKET_MARKER_RE.sub("", text))


# ──────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────


def is_available() -> bool:
    """Cheap, non-network probe of whether the configured backend can serve.

    Doesn't ping the remote. The /speak handler relies on the runtime
    fall-through inside stream()/synth() to handle real failures.
    """
    backend = (config.tts_backend or "piper").lower()
    if backend == "xtts":
        return bool(config.tts_xtts_url) and Path(
            config.tts_xtts_ref_wav
        ).expanduser().is_file()
    if backend == "cosyvoice":
        return (
            bool(config.tts_cosyvoice_url)
            and Path(config.tts_cosyvoice_ref_wav).expanduser().is_file()
            and Path(
                config.tts_cosyvoice_ref_transcript_path
            ).expanduser().is_file()
        )
    return _piper_voice_available()


async def stream(text: str) -> AsyncIterator[tuple[bytes, str]]:
    """Yield (pcm_chunk, backend_label) tuples.

    Every chunk is raw 24 kHz mono int16 little-endian PCM, no header.
    Multiple chunks for xtts (real streaming); a single chunk for
    piper (one-shot synth, resampled if needed).

    No silent cross-backend fallback. If the selected backend fails,
    the exception propagates so the caller surfaces a real error to
    the UI instead of swapping voices mid-utterance (which was the
    "voice changes mid-audio" bug). Empty input yields nothing.
    """
    if not text or not text.strip():
        return
    clean = text.strip()

    backend = (config.tts_backend or "xtts").lower()
    # CosyVoice 3 understands the personality v6 inline markers; every
    # other backend would read them literally.
    if backend != "cosyvoice":
        clean = _strip_tts_markers(clean).strip()
        if not clean:
            return
    if backend == "cosyvoice":
        async for chunk in _stream_cosyvoice(clean):
            yield chunk, "cosyvoice"
        return
    if backend == "xtts":
        async for chunk in _stream_xtts(clean):
            yield chunk, "xtts"
        return
    if backend == "piper":
        # Sync synth — run in a thread so the event loop isn't blocked.
        # _piper_to_pcm strips the WAV header and resamples to
        # OUTPUT_SAMPLE_RATE so the frontend only sees one wire format.
        pcm = await asyncio.to_thread(_piper_to_pcm, clean)
        yield pcm, "piper"
        return
    raise ValueError(f"unknown tts backend: {backend!r}")


def synth(text: str) -> tuple[bytes, str]:
    """Synchronous wrapper around `stream()`.

    Returns (wav_bytes, backend_label). For xtts the streamed PCM
    chunks are concatenated and wrapped in a 24 kHz mono int16 WAV
    header. For piper the chunk is already PCM at 24 kHz (post-
    resampling) and gets wrapped the same way.

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
    """Collect the async stream into a single (wav_bytes, backend) tuple.

    Both backends yield PCM at OUTPUT_SAMPLE_RATE, so wrapping is
    uniform regardless of which served.
    """
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
# XTTS-v2 backend (Coqui xtts-streaming-server + our overlay)
# ──────────────────────────────────────────────────────────────────


_xtts_embeddings: dict | None = None


async def _xtts_clone_speaker() -> dict:
    """One-time upload of the reference WAV. Returns the speaker
    embedding + GPT conditioning latent that /tts_stream needs.

    Cached at module scope for the process lifetime. Restart the
    backend to pick up a changed ref WAV.
    """
    wav_path = Path(config.tts_xtts_ref_wav).expanduser()
    if not wav_path.is_file():
        raise VoiceMissingError(f"xtts ref wav not found: {wav_path}")

    url = f"{config.tts_xtts_url.rstrip('/')}/clone_speaker"
    logger.info(f"tts: cloning xtts speaker from {wav_path}")

    async with httpx.AsyncClient(timeout=config.tts_xtts_timeout_s) as client:
        with open(wav_path, "rb") as f:
            files = {"wav_file": (wav_path.name, f.read(), "audio/wav")}
        resp = await client.post(url, files=files)
        if resp.status_code != 200:
            raise RuntimeError(
                f"xtts /clone_speaker {resp.status_code}: "
                f"{resp.text[:200]}"
            )
        return resp.json()


async def _stream_xtts(text: str) -> AsyncIterator[bytes]:
    """POST text + cached embeddings to /tts_stream; yield raw PCM
    chunks (24 kHz mono int16, header-less).

    add_wav_header=False is critical — when true the server emits a
    WAV header with a placeholder data-length of 0 and most decoders
    refuse to play (the "silent file" bug we hit during the A/B
    smoke test).
    """
    global _xtts_embeddings
    if _xtts_embeddings is None:
        _xtts_embeddings = await _xtts_clone_speaker()

    body = {
        **_xtts_embeddings,
        "text": text,
        "language": config.tts_xtts_language,
        "add_wav_header": False,
        "stream_chunk_size": "20",
        "temperature": config.tts_xtts_temperature,
        "top_p": config.tts_xtts_top_p,
        "repetition_penalty": config.tts_xtts_repetition_penalty,
    }
    url = f"{config.tts_xtts_url.rstrip('/')}/tts_stream"
    timeout = httpx.Timeout(
        connect=config.tts_xtts_timeout_s,
        read=None,
        write=config.tts_xtts_timeout_s,
        pool=config.tts_xtts_timeout_s,
    )

    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream("POST", url, json=body) as resp:
            if resp.status_code != 200:
                err = await resp.aread()
                raise RuntimeError(
                    f"xtts {resp.status_code}: "
                    f"{err[:200].decode('utf-8', 'replace')}"
                )
            async for chunk in resp.aiter_bytes(chunk_size=4096):
                if chunk:
                    yield chunk


# ──────────────────────────────────────────────────────────────────
# CosyVoice 3 backend (zero-shot voice cloning + expressive markers)
# ──────────────────────────────────────────────────────────────────


# Cached at module scope for the process lifetime. Restart the
# backend to pick up an edited transcript or reference WAV.
_cosyvoice_ref_transcript: str | None = None
_cosyvoice_ref_wav_bytes: bytes | None = None


def _load_cosyvoice_refs() -> tuple[str, bytes, str]:
    """Lazy-load (and cache) the CosyVoice reference transcript +
    WAV bytes from disk. Returns (transcript, wav_bytes, wav_name).

    Raises VoiceMissingError if either file is missing — the route
    layer turns that into a fallback path, not a 500.
    """
    global _cosyvoice_ref_transcript, _cosyvoice_ref_wav_bytes

    wav_path = Path(config.tts_cosyvoice_ref_wav).expanduser()
    txt_path = Path(config.tts_cosyvoice_ref_transcript_path).expanduser()

    if _cosyvoice_ref_transcript is None:
        if not txt_path.is_file():
            raise VoiceMissingError(
                f"cosyvoice transcript not found: {txt_path}"
            )
        _cosyvoice_ref_transcript = txt_path.read_text(encoding="utf-8").strip()
        logger.info(
            f"tts: loaded cosyvoice transcript "
            f"({len(_cosyvoice_ref_transcript)} chars) from {txt_path}"
        )

    if _cosyvoice_ref_wav_bytes is None:
        if not wav_path.is_file():
            raise VoiceMissingError(
                f"cosyvoice ref wav not found: {wav_path}"
            )
        _cosyvoice_ref_wav_bytes = wav_path.read_bytes()
        logger.info(
            f"tts: cached cosyvoice ref wav "
            f"({len(_cosyvoice_ref_wav_bytes)} bytes) from {wav_path}"
        )

    return _cosyvoice_ref_transcript, _cosyvoice_ref_wav_bytes, wav_path.name


async def _stream_cosyvoice(text: str) -> AsyncIterator[bytes]:
    """POST tts_text + cached ref transcript + ref WAV to
    /inference_zero_shot; yield raw 24 kHz mono int16 PCM chunks.

    The server overlay (tts-server/cosyvoice/server.py) prepends
    `"You are a helpful assistant.<|endofprompt|>"` to prompt_text
    so we send plain Spanish here.

    Failure modes worth knowing:
      - tts_text much shorter than prompt_text → hifigan crashes
        with a kernel-size error and the server returns 200 + empty
        body (chunked stream that never yields). We detect this and
        raise a useful error.
      - Marker the tokenizer can't handle → same silent failure.
      - Stochastic timbre drift between calls (LLM sampling=25 in
        the model). Not addressable from the client; would need a
        seed parameter wired into the overlay.
    """
    transcript, wav_bytes, wav_name = _load_cosyvoice_refs()

    url = f"{config.tts_cosyvoice_url.rstrip('/')}/inference_zero_shot"
    timeout = httpx.Timeout(
        connect=config.tts_cosyvoice_timeout_s,
        read=None,
        write=config.tts_cosyvoice_timeout_s,
        pool=config.tts_cosyvoice_timeout_s,
    )
    # httpx multipart: (filename, content, content-type). For the
    # plain-text fields, filename=None makes httpx emit them as
    # regular form parts (no Content-Disposition filename).
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
                    f"cosyvoice {resp.status_code}: "
                    f"{err[:200].decode('utf-8', 'replace')}"
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
    (es_ES-sharvard-medium is 22050 Hz). _piper_to_pcm() below strips
    the header and resamples to OUTPUT_SAMPLE_RATE so the public
    stream() contract stays uniform.
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


def _piper_to_pcm(text: str) -> bytes:
    """Synth via Piper, strip the WAV header, and resample the PCM to
    OUTPUT_SAMPLE_RATE.

    Linear interpolation is good enough for a fallback (~50 ms of CPU
    on a typical sentence). When/if the fallback becomes a regular
    path, swap to scipy.signal.resample_poly for proper anti-aliasing.
    """
    import numpy as np

    wav_bytes = _synth_piper(text)
    with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
        src_rate = wf.getframerate()
        n_frames = wf.getnframes()
        pcm = wf.readframes(n_frames)

    if src_rate == OUTPUT_SAMPLE_RATE:
        return pcm

    src = np.frombuffer(pcm, dtype=np.int16)
    ratio = OUTPUT_SAMPLE_RATE / src_rate
    dst_len = int(len(src) * ratio)
    # linspace endpoints over [0, len-1] keep amplitude scaling neutral.
    dst = np.interp(
        np.linspace(0, len(src) - 1, dst_len),
        np.arange(len(src)),
        src,
    ).astype(np.int16)
    return dst.tobytes()
