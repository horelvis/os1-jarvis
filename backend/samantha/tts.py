"""TTS for Samantha — CosyVoice 3 (zero-shot voice cloning).

Emits 24 kHz mono int16 PCM chunks via
/inference_zero_shot on the CosyVoice 3 server (4090, port 8093).
Sends the reference WAV + its transcript on every call so the model
gets prosodic conditioning. Honors personality v6 inline markers
(`[laughter]`, `<laughter>palabras</laughter>`, `[breath]`, `[sigh]`).

Public API:

    OUTPUT_SAMPLE_RATE: int = 24000 — the rate of every yielded chunk
    stream(text, client=None)
                   → async generator yielding (pcm_chunk, "cosyvoice").
                     PCM is raw int16 little-endian at 24 kHz mono.
                     Pass `client=new_client()` unless you are on the
                     process's single long-lived loop (see `_client`).
    new_client()   → an httpx.AsyncClient with the CosyVoice timeouts,
                     for callers that own their event loop.
    synth(text)    → sync wrapper; collects the stream and returns
                     (wav_bytes, "cosyvoice"). WAV header at 24 kHz.
                     Runs its own loop and its own client; /speak uses
                     stream().
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


# THE CONSTRAINT THIS FILE IS SHAPED AROUND: an httpx.AsyncClient may
# only be used on the event loop that created it. Its connection pool
# holds transports bound to that loop; issuing a request from a second
# loop fails (or, worse, fails intermittently and silently for the
# caller who swallows it).
#
# So there are two client policies here, and callers pick:
#   - no `client=` argument → the shared module-global pool below. Only
#     correct for a caller that lives on ONE long-lived loop for the
#     process's lifetime. That is exactly uvicorn/FastAPI, where the
#     shared pool is a deliberate optimisation (no TCP handshake per
#     /speak) and must stay.
#   - `client=new_client()` → a client the caller creates, uses and
#     closes on its own loop. Required for anything that runs on a
#     short-lived or per-call loop: `synth()`'s own `asyncio.run()`, and
#     the Hermes voice plugin, whose bridge spins up a fresh loop in a
#     worker thread for every clause.
_client: httpx.AsyncClient | None = None
# The loop `_client` was created on, or None if it was built outside a
# running loop. Used only to detect the misuse described above.
_client_loop: asyncio.AbstractEventLoop | None = None


def new_client() -> httpx.AsyncClient:
    """Build an AsyncClient with the configured CosyVoice timeouts.

    Call this from a loop you own, and close it on that same loop (the
    constraint above). It exists so callers that cannot use the shared
    pool don't have to duplicate the timeout policy.

    `read` is httpx's per-read-operation (inter-chunk) timeout, not a
    whole-body cap: a healthy stream that keeps emitting chunks never
    trips it, while a wedged server (CUDA hang) fails loudly instead
    of freezing the caller forever.
    """
    timeout = httpx.Timeout(
        connect=config.tts_cosyvoice_timeout_s,
        read=config.tts_cosyvoice_timeout_s,
        write=config.tts_cosyvoice_timeout_s,
        pool=config.tts_cosyvoice_timeout_s,
    )
    return httpx.AsyncClient(timeout=timeout)


def _running_loop() -> asyncio.AbstractEventLoop | None:
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None


def _get_client() -> httpx.AsyncClient:
    """Shared AsyncClient: one connection pool for all synthesis calls
    instead of a fresh client (and TCP handshake) per /speak.

    Safety net, not a strategy: if the cached client belongs to a
    different loop than the caller's, it is unusable here (see the
    constraint above), so it is dropped and rebuilt rather than handed
    out to fail. The stale client cannot be awaited closed — its loop is
    typically already gone — so it is left to GC. That leak is why this
    only ever fires as a warning: a caller off the uvicorn loop should
    be passing its own `client=`.
    """
    global _client, _client_loop
    loop = _running_loop()
    if _client is not None and _client_loop is not loop:
        logger.warning(
            "tts: shared HTTP client belongs to another event loop — rebuilding. "
            "A caller on its own loop should pass client=tts.new_client() instead."
        )
        _client = None
    if _client is None:
        _client = new_client()
        _client_loop = loop
    return _client


async def aclose() -> None:
    """Release the shared HTTP client. Called from api.py's lifespan."""
    global _client, _client_loop
    if _client is not None:
        await _client.aclose()
        _client = None
        _client_loop = None


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


async def stream(
    text: str, *, client: httpx.AsyncClient | None = None
) -> AsyncIterator[tuple[bytes, str]]:
    """Yield (pcm_chunk, "cosyvoice") tuples.

    Every chunk is raw 24 kHz mono int16 little-endian PCM, no header.
    Empty input yields nothing. Exceptions propagate so the caller can
    surface a real error instead of silence.

    `client` selects the HTTP client policy — see the note above
    `_client`. Omit it only from a caller that lives on one long-lived
    event loop (uvicorn); pass `new_client()` from anywhere else,
    because an httpx.AsyncClient may only be used on the loop that
    created it.
    """
    if not text or not text.strip():
        return
    async for chunk in _stream_cosyvoice(text.strip(), client=client):
        yield chunk, "cosyvoice"


def synth(text: str) -> tuple[bytes, str]:
    """Synchronous wrapper around stream(). Returns (wav_bytes, backend).

    Used by the Hermes whole-file provider and by tests; /speak uses
    stream() via StreamingResponse so audio starts flowing before
    synthesis ends.
    """
    if not text or not text.strip():
        return b"", "empty"
    return asyncio.run(_consolidate(text))


async def _consolidate(text: str) -> tuple[bytes, str]:
    # synth() runs in its own short-lived asyncio.run() loop, so it owns
    # its client outright: created and closed here, on this loop. It
    # deliberately does NOT touch the shared pool — an AsyncClient may
    # only be used on the loop that created it, and this function used
    # to enforce that by closing the global on the way out, which meant
    # a whole-file call could yank the client out from under a /speak
    # request (or another thread) mid-stream. Owning one removes both
    # the loop mismatch and that race.
    async with new_client() as client:
        chunks: list[bytes] = []
        backend: str = ""
        async for chunk, label in stream(text, client=client):
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


async def _stream_cosyvoice(
    text: str, *, client: httpx.AsyncClient | None = None
) -> AsyncIterator[bytes]:
    """POST tts_text + ref transcript + ref WAV to /inference_zero_shot;
    yield raw 24 kHz mono int16 PCM chunks.

    The server overlay (tts-server/cosyvoice/server.py) prepends
    `"You are a helpful assistant.<|endofprompt|>"` to prompt_text
    so we send plain Spanish here.

    Failure modes, as measured against the live server on 2026-08-22
    (this replaces an earlier account that said short text crashes
    hifigan — it does not, for this server build):
      - tts_text much shorter than prompt_text → the server logs
        "... too short than prompt text ..., this may lead to bad
        performance" and returns audio anyway. Degraded quality, not a
        failure.
      - Isolated one-or-two-word utterances fail intermittently and
        content-specifically: 'No.' failed 2/6 calls and bare 'No' 1/6,
        while 'Sí.', 'Ya.' and 'No, claro.' never failed in 6 each, and
        nothing between 10 and 80 chars failed in 76 calls. The failure
        arrives as the server closing the connection mid-response ("peer
        closed connection without sending complete message body"), which
        httpx raises as RemoteProtocolError — it never reaches the
        empty-body check below.
      - 200 with an empty body: still guarded below, but not reproduced
        in that measurement. An unrecognized marker is the remaining
        suspect.
    """
    transcript, wav_bytes, wav_name = _load_cosyvoice_refs()

    # A voice prompt, when set, goes in front of the transcript with the
    # end-of-prompt marker. The server only prepends its own
    # "You are a helpful assistant." when the marker is ABSENT
    # (server.py::_ensure_eop_prefix), so supplying one replaces it
    # rather than fighting it.
    if config.tts_cosyvoice_voice_prompt:
        transcript = (
            f"{config.tts_cosyvoice_voice_prompt}<|endofprompt|>{transcript}"
        )

    url = f"{config.tts_cosyvoice_url.rstrip('/')}/inference_zero_shot"
    # httpx multipart: (filename, content, content-type). filename=None
    # for text fields makes httpx emit them as plain form parts.
    files = {
        "tts_text": (None, text),
        "prompt_text": (None, transcript),
        "prompt_wav": (wav_name, wav_bytes, "audio/wav"),
    }

    if client is None:
        client = _get_client()
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
                "cosyvoice returned 200 but no audio — cause unconfirmed; "
                "an unrecognized expression marker is the main suspect. "
                "NOT the old 'text shorter than the reference prompt' "
                "story: short text only degrades quality (the server says "
                "so and returns audio), and the real short-text failure is "
                "an intermittent mid-response disconnect that surfaces as "
                "httpx.RemoteProtocolError, not this. Check the server log."
            )
