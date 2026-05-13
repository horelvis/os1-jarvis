"""Samantha FastAPI server.

Serves BOTH the static frontend (HTML/CSS/JS) and the API on a single
port. The frontend is loaded by Chromium in --kiosk mode at boot.

HTTP endpoints:
  - GET  /              → frontend (static/index.html)
  - GET  /static/*      → frontend assets (CSS, JS)
  - GET  /ping          → health check
  - POST /chat          → conversation (mock or real)
  - POST /transcribe    → audio → text (mock)
  - POST /speak         → text → audio (mock)

WebSocket:
  - /ws                 → streaming conversation + (placeholder) listen

Run with:
    python -m samantha.api

Or with hot reload during development:
    uvicorn samantha.api:app --host 127.0.0.1 --port 7777 --reload
"""

import asyncio
import io
import json
import math
import os
import random
import struct
import time
import wave
from pathlib import Path
from typing import TYPE_CHECKING, AsyncIterator

from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from loguru import logger

from . import __version__
from .config import config
from .mock_llm import generate_reply as mock_generate_reply, tokenize_for_streaming
from .profile import (
    complete_onboarding as _complete_onboarding,
    delete_profile as _delete_profile,
    get_profile as _get_profile,
    is_onboarded as _is_onboarded,
)
from .schemas import (
    ChatRequest,
    ChatResponse,
    PingResponse,
    ProfileCreateRequest,
    ProfileResponse,
    SpeakRequest,
    TranscribeResponse,
)

if TYPE_CHECKING:
    from .memory import Memory, MemoryChunk


# ============================================================
# Memory singleton (lazy)
# ============================================================

_memory: "Memory | None" = None
_memory_init_failed: bool = False


def get_memory() -> "Memory | None":
    """Lazily initialize the persistent memory store.

    Returns None if memory is disabled (config.memory_enabled=False) or
    if initialization fails — never raise into the request path.
    """
    global _memory, _memory_init_failed
    if not config.memory_enabled or _memory_init_failed:
        return None
    if _memory is None:
        try:
            from .memory import Memory

            persist = os.path.expanduser(config.memory_persist_dir)
            _memory = Memory(persist_dir=persist)
        except Exception as e:  # pragma: no cover — defensive
            logger.error(f"memory: failed to initialize, disabling: {e}")
            _memory_init_failed = True
            return None
    return _memory


def _collect_facts(mem: "Memory", *, user_id: str) -> list[dict]:
    """Gather the facts surfaced into the system prompt.

    Today: `name` and `onboarding_completed_at`. Future preference facts
    (favorite drink, conversational style, etc.) land here too — keep
    the list short so the prompt stays scannable for the LLM.
    """
    out: list[dict] = []
    for kind in ("name", "onboarding_completed_at"):
        f = mem.get_fact(kind, user_id=user_id)
        if f is not None:
            out.append(f)
    return out


# ============================================================
# Token streaming (dispatches on config.mode)
# ============================================================


async def _stream_tokens(
    message: str,
    *,
    facts: "list[dict] | None" = None,
    recall: "list[MemoryChunk] | None" = None,
    short_term: "list[MemoryChunk] | None" = None,
) -> AsyncIterator[str]:
    """Yield reply tokens, dispatching on `config.mode`.

    - "real": pulls a live stream from `real_llm` (llama-server, etc.),
      threading facts + recall + short-term into the system prompt
      (spec §9.6 layout).
    - "mock": tokenizes the canned reply and emits chunks with a small
      inter-token delay. Context kwargs are accepted-and-ignored — the
      mock LLM is keyword-based and doesn't read the system prompt.
    """
    if config.mode == "real":
        from .real_llm import stream_reply as real_stream_reply

        async for tok in real_stream_reply(
            message, facts=facts, recall=recall, short_term=short_term
        ):
            yield tok
        return

    # Mock path: brief "thinking" pause, then drip tokens.
    await asyncio.sleep(random.uniform(0.2, 0.6))
    reply = mock_generate_reply(message)
    for token in tokenize_for_streaming(reply):
        await asyncio.sleep(config.mock_streaming_delay_s)
        yield token


# ========================================================================
# APP SETUP
# ========================================================================

FRONTEND_DIST = (
    Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
)
INDEX_FILE = FRONTEND_DIST / "index.html"

app = FastAPI(
    title="Samantha Backend",
    version=__version__,
    description="Backend local para Samantha. Solo accesible desde localhost.",
)

# Frontend served from same origin → no CORS needed.
# Vite emits to frontend/dist/assets — only mount it if the build has
# run (test runs and pure-backend dev don't need it).
if (FRONTEND_DIST / "assets").exists():
    app.mount(
        "/assets",
        StaticFiles(directory=str(FRONTEND_DIST / "assets")),
        name="assets",
    )


# Placeholder transcriptions used by /transcribe and the WS `listen`
# turn. Phase 5 replaces this with faster-whisper.
FAKE_TRANSCRIPTS: list[str] = [
    "Hola Samantha, ¿qué tal?",
    "Cuéntame algo interesante.",
    "Estoy un poco cansado hoy.",
    "¿Te acuerdas de lo que hablamos ayer?",
    "Tengo una pregunta para ti.",
    "Me apetece charlar un rato.",
]


# ========================================================================
# GET / → frontend
# ========================================================================


@app.get("/")
async def index() -> FileResponse:
    """Serve the SPA. Chromium in kiosk mode lands here at boot."""
    return FileResponse(INDEX_FILE)


# ========================================================================
# /ping
# ========================================================================


@app.get("/ping", response_model=PingResponse)
async def ping() -> PingResponse:
    """Health check used by the kiosk to wait for the backend at boot.

    `has_profile` lets the frontend route between Onboarding (false) and
    Ambient (true) without a separate /profile probe at boot.
    """
    mem = get_memory()
    has_profile = bool(mem and _is_onboarded(mem))
    return PingResponse(
        status="ok",
        version=__version__,
        timestamp=int(time.time()),
        mode=config.mode,
        has_profile=has_profile,
    )


# ========================================================================
# /profile — onboarding state
# ========================================================================


@app.get("/profile", response_model=ProfileResponse)
async def get_profile_endpoint() -> ProfileResponse:
    """Return the synthesized profile, or 404 if onboarding hasn't completed."""
    mem = get_memory()
    if mem is None:
        raise HTTPException(status_code=503, detail="memory_disabled")
    profile = _get_profile(mem)
    if profile is None:
        raise HTTPException(status_code=404, detail="not_onboarded")
    return ProfileResponse(**profile)


@app.post("/profile", response_model=ProfileResponse)
async def create_profile_endpoint(req: ProfileCreateRequest) -> ProfileResponse:
    """Complete onboarding: stores name + the 6 answers in Memory."""
    mem = get_memory()
    if mem is None:
        raise HTTPException(status_code=503, detail="memory_disabled")
    try:
        profile = _complete_onboarding(
            mem,
            name=req.name,
            answers=[a.model_dump() for a in req.answers],
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return ProfileResponse(**profile)


@app.delete("/profile")
async def delete_profile_endpoint() -> dict:
    """ADMIN-only: clears name + onboarding_completed_at facts. The 6
    onboarding-answer chunks survive (Samantha never forgets)."""
    mem = get_memory()
    if mem is None:
        raise HTTPException(status_code=503, detail="memory_disabled")
    deleted = _delete_profile(mem)
    return {"deleted": deleted}


# ========================================================================
# /chat
# ========================================================================


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    """Non-streaming chat endpoint. The frontend uses /ws for streaming;
    /chat is retained for tests and one-shot integrations.

    Per spec §9.6 the system prompt is assembled from three layers:
      facts        — name, onboarding date, future preferences
      recall       — top-k semantically-similar past chunks
      short_term   — the last N turns verbatim
    Samantha never forgets — there is no "forget" path; "olvida X" goes
    to the LLM like any other message and she declines in character.
    """
    start = time.perf_counter()
    logger.info(f"chat: user_id={req.user_id} message='{req.message[:60]}'")

    mem = get_memory()
    facts: list[dict] = []
    recall: list = []
    short: list = []
    if mem is not None:
        mem.remember("user", req.message, user_id=req.user_id)
        facts = _collect_facts(mem, user_id=req.user_id)
        recall = mem.recall(
            req.message, k=config.memory_top_k, user_id=req.user_id
        )
        short = mem.short_term(user_id=req.user_id)

    if config.mode == "real":
        from .real_llm import generate_reply as real_generate_reply

        reply = await real_generate_reply(
            req.message, facts=facts, recall=recall, short_term=short
        )
    else:
        latency = random.uniform(config.mock_min_latency_s, config.mock_max_latency_s)
        await asyncio.sleep(latency)
        reply = mock_generate_reply(req.message)

    if mem is not None and reply:
        mem.remember("samantha", reply, user_id=req.user_id)

    elapsed_ms = int((time.perf_counter() - start) * 1000)
    logger.info(f"chat: replied in {elapsed_ms}ms — '{reply[:60]}'")

    return ChatResponse(
        reply=reply,
        thinking_ms=elapsed_ms,
        model=None if config.mode == "mock" else config.llm_model,
    )


# ========================================================================
# /transcribe — STT (mock)
# ========================================================================


@app.post("/transcribe", response_model=TranscribeResponse)
async def transcribe(audio: UploadFile = File(...)) -> TranscribeResponse:
    """Mock transcription. Phase 5 swaps in faster-whisper."""
    contents = await audio.read()
    size = len(contents)
    logger.info(f"transcribe: received {size} bytes")

    # Simulate latency proportional to audio size (~50KB/s of audio)
    await asyncio.sleep(0.3 + size / 1_000_000)

    fake_text = random.choice(FAKE_TRANSCRIPTS)

    return TranscribeResponse(
        text=fake_text,
        language="es",
        duration_s=size / 32000.0,
        confidence=random.uniform(0.85, 0.98),
    )


# ========================================================================
# /speak — TTS (mock)
# ========================================================================


@app.post("/speak")
async def speak(req: SpeakRequest) -> Response:
    """Mock TTS. Returns a WAV whose duration scales with text length so
    the frontend wave can animate for a realistic amount of time. Phase 5
    swaps this for Piper, where audio length is naturally text-proportional.
    """
    logger.info(f"speak: voice={req.voice} text='{req.text[:60]}'")

    # Simulate synthesis latency (~10ms per character)
    await asyncio.sleep(len(req.text) * 0.01)

    # Estimated playback duration: ~13 chars/sec is typical Spanish TTS.
    # Clamp so short replies still get a tail, long ones don't drag forever.
    duration_s = max(0.6, min(7.0, len(req.text) / 13.0))
    wav_bytes = _generate_tone_wav(duration_s=duration_s, freq=440)

    return Response(
        content=wav_bytes,
        media_type="audio/wav",
        headers={"X-Mock-Mode": "true"},
    )


def _generate_tone_wav(duration_s: float, freq: float = 440.0) -> bytes:
    """Build a mono 16-bit WAV.

    The waveform is a soft fade-in/out tone for the first ~250 ms (just
    enough to confirm audio is playing), then silence for the rest. This
    keeps `audio.ended` firing at `duration_s` so the frontend can drive
    state transitions on it, without subjecting the listener to a multi-
    second pitch.
    """
    sample_rate = 16000
    n_samples = int(duration_s * sample_rate)
    tone_samples = min(n_samples, int(0.25 * sample_rate))
    fade_samples = int(0.05 * sample_rate)
    amplitude = 0.12  # quieter than before; mock cue, not a beep

    samples = [0] * n_samples
    for i in range(tone_samples):
        if i < fade_samples:
            envelope = i / fade_samples
        elif i > tone_samples - fade_samples:
            envelope = (tone_samples - i) / fade_samples
        else:
            envelope = 1.0
        value = envelope * amplitude * math.sin(2 * math.pi * freq * i / sample_rate)
        samples[i] = int(value * 32767)

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(struct.pack(f"<{n_samples}h", *samples))

    return buf.getvalue()


# ========================================================================
# /ws — WebSocket: streaming chat + listen placeholder
# ========================================================================


async def _ws_stream_chat(websocket: WebSocket, message: str, user_id: str) -> None:
    """Stream a reply over the WebSocket, token by token.

    Mirrors the /chat handler's three-layer context assembly
    (facts + recall + short_term per spec §9.6). The on-wire protocol
    stays identical between mock and real because `_stream_tokens`
    dispatches on `config.mode`. Samantha never forgets.
    """
    start = time.perf_counter()
    logger.info(
        f"ws chat: user_id={user_id} mode={config.mode} "
        f"message='{message[:60]}'"
    )

    mem = get_memory()
    facts: list[dict] = []
    recall: list = []
    short: list = []
    if mem is not None:
        mem.remember("user", message, user_id=user_id)
        facts = _collect_facts(mem, user_id=user_id)
        recall = mem.recall(
            message, k=config.memory_top_k, user_id=user_id
        )
        short = mem.short_term(user_id=user_id)

    reply_chunks: list[str] = []
    async for token in _stream_tokens(
        message, facts=facts, recall=recall, short_term=short
    ):
        reply_chunks.append(token)
        await websocket.send_text(
            json.dumps({"type": "token", "token": token})
        )

    if mem is not None and reply_chunks:
        full_reply = "".join(reply_chunks).strip()
        if full_reply:
            mem.remember("samantha", full_reply, user_id=user_id)

    elapsed_ms = int((time.perf_counter() - start) * 1000)
    await websocket.send_text(
        json.dumps({"type": "done", "thinking_ms": elapsed_ms})
    )


async def _ws_handle_listen(websocket: WebSocket) -> None:
    """Placeholder for the future audio-driven listen turn (Phase 5).

    For now: simulate a short capture, then send back a fake transcription.
    The frontend's mic button drives this; it never opens the browser mic.
    """
    await asyncio.sleep(random.uniform(0.8, 1.6))
    text = random.choice(FAKE_TRANSCRIPTS)
    logger.info(f"ws listen: returning fake transcription '{text}'")
    await websocket.send_text(json.dumps({"type": "transcription", "text": text}))


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """Single bidirectional channel for the conversation UI.

    Client → Server messages:
      {"type": "chat",   "message": str, "user_id": str}
      {"type": "listen"}

    Server → Client messages:
      {"type": "token", "token": str}
      {"type": "done", "thinking_ms": int}
      {"type": "transcription", "text": str}
      {"type": "error", "error": str}
    """
    await websocket.accept()
    logger.info("ws: client connected")
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_text(json.dumps({"type": "error", "error": "invalid_json"}))
                continue

            msg_type = msg.get("type")
            if msg_type == "chat":
                message = (msg.get("message") or "").strip()
                if not message:
                    await websocket.send_text(
                        json.dumps({"type": "error", "error": "empty_message"})
                    )
                    continue
                user_id = msg.get("user_id", "primary")
                await _ws_stream_chat(websocket, message, user_id)
            elif msg_type == "listen":
                await _ws_handle_listen(websocket)
            else:
                await websocket.send_text(
                    json.dumps({"type": "error", "error": f"unknown_type:{msg_type}"})
                )
    except WebSocketDisconnect:
        logger.info("ws: client disconnected")


# ========================================================================
# Error handling
# ========================================================================


@app.exception_handler(Exception)
async def generic_exception_handler(request, exc):
    logger.exception(f"Unhandled exception on {request.url.path}")
    raise HTTPException(status_code=500, detail=str(exc))


# ========================================================================
# Entry point
# ========================================================================

if __name__ == "__main__":
    import uvicorn

    logger.info(f"Samantha backend starting on {config.host}:{config.port} (mode={config.mode})")

    uvicorn.run(
        "samantha.api:app",
        host=config.host,
        port=config.port,
        log_level=config.log_level.lower(),
        reload=False,
    )
