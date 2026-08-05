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
import json
import os
import random
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, AsyncIterator

from fastapi import (
    FastAPI,
    File,
    HTTPException,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
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
# Memory singleton (lazy, single-flight)
# ============================================================
# The kiosk polls /ping during boot, so first-init must be single-flight
# now that callers run in threads (asyncio.to_thread). Double-checked
# locking: cheap unlocked fast-path once _memory is set, lock only for
# the actual initialization window.

_memory: "Memory | None" = None
_memory_init_failed: bool = False
_memory_lock = threading.Lock()


def get_memory() -> "Memory | None":
    """Lazily initialize the persistent memory store.

    Returns None if memory is disabled (config.memory_enabled=False) or
    if initialization fails — never raise into the request path.
    """
    global _memory, _memory_init_failed
    # Fast path: already initialized (or permanently failed/disabled).
    if not config.memory_enabled or _memory_init_failed:
        return None
    if _memory is not None:
        return _memory
    # Slow path: first init. Serialize across threads so only one
    # fastembed ONNX session and one chroma open happen.
    with _memory_lock:
        # Re-check inside the lock — another thread may have won the race.
        if _memory_init_failed:
            return None
        if _memory is not None:
            return _memory
        try:
            from .memory import Memory

            persist = os.path.expanduser(config.memory_persist_dir)
            _memory = Memory(persist_dir=persist)
        except Exception as e:  # pragma: no cover — defensive
            logger.error(f"memory: failed to initialize, disabling: {e}")
            _memory_init_failed = True
            return None
    return _memory


from .context import gather_context as _gather_context  # noqa: E402

# ============================================================
# Token streaming (dispatches on config.mode)
# ============================================================


async def _stream_tokens(
    message: str,
    *,
    facts: "list[dict] | None" = None,
    recall: "list[MemoryChunk] | None" = None,
    short_term: "list[MemoryChunk] | None" = None,
    user_id: str = "primary",
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
            message, facts=facts, recall=recall, short_term=short_term, user_id=user_id
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

FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
INDEX_FILE = FRONTEND_DIST / "index.html"


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Startup is lazy (memory and HTTP clients init on first use);
    shutdown releases whatever got created: the shared LLM httpx
    client and the memory store (SQLite ring connection)."""
    global _memory
    yield
    from . import real_llm

    await real_llm.aclose()
    if _memory is not None:
        await asyncio.to_thread(_memory.close)
        _memory = None


app = FastAPI(
    title="Samantha Backend",
    version=__version__,
    description="Backend local para Samantha. Solo accesible desde localhost.",
    lifespan=_lifespan,
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


# Placeholder transcription used by /transcribe and the WS `listen`
# turn while we run in mock mode. Phase 5 replaces this with
# faster-whisper hitting the real microphone via sounddevice.
#
# Kept as a single, clearly-placeholder string so the user can tell
# at a glance that this is not their actual voice. The previous
# random pool of plausible-looking user phrases made the conversation
# look like Samantha was talking to herself.
FAKE_TRANSCRIPTS: list[str] = [
    "hola (mic en modo mock — Phase 5 cablea Whisper)",
]

# Mirror ChatRequest's max_length — the WS path must not accept
# unbounded input the HTTP path rejects.
MAX_WS_MESSAGE_CHARS = 8000


class _ClientGone(Exception):
    """A websocket SEND failed because the client disconnected.

    Distinguishes send-side RuntimeErrors (client vanished mid-reply)
    from generator-side RuntimeErrors (httpx client closed, event loop
    closed) — the latter are real LLM faults the client must hear about.
    """


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
    mem = await asyncio.to_thread(get_memory)
    has_profile = bool(mem and await asyncio.to_thread(_is_onboarded, mem))
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
    mem = await asyncio.to_thread(get_memory)
    if mem is None:
        raise HTTPException(status_code=503, detail="memory_disabled")
    profile = await asyncio.to_thread(_get_profile, mem)
    if profile is None:
        raise HTTPException(status_code=404, detail="not_onboarded")
    return ProfileResponse(**profile)


@app.post("/profile", response_model=ProfileResponse)
async def create_profile_endpoint(req: ProfileCreateRequest) -> ProfileResponse:
    """Complete onboarding: stores name + the 6 answers in Memory.

    Pairing is irreversible from the UI: once `is_onboarded` returns
    True the device is bound to its user. Re-pairing requires DELETE
    /profile from an admin terminal — Samantha herself cannot reach it.

    The first answer carries the name (per the onboarding flow). An
    empty / whitespace `answers[0].a` is rejected so we never persist
    a degenerate "tú" profile.
    """
    mem = await asyncio.to_thread(get_memory)
    if mem is None:
        raise HTTPException(status_code=503, detail="memory_disabled")
    if await asyncio.to_thread(_is_onboarded, mem):
        raise HTTPException(status_code=409, detail="already_paired")

    first_answer = (req.answers[0].a or "").strip() if req.answers else ""
    if not first_answer:
        raise HTTPException(status_code=422, detail="name_answer_required")
    name = (req.name or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="name_required")

    try:
        # 6 fastembed embeddings + ~13 Chroma writes — seconds of CPU.
        # Must not stall /ping, the WS, or /speak streaming.
        profile = await asyncio.to_thread(
            _complete_onboarding,
            mem,
            name=name,
            answers=[a.model_dump() for a in req.answers],
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return ProfileResponse(**profile)


@app.delete("/profile")
async def delete_profile_endpoint() -> dict:
    """ADMIN-only: clears name + onboarding_completed_at facts. The 6
    onboarding-answer chunks survive (Samantha never forgets)."""
    mem = await asyncio.to_thread(get_memory)
    if mem is None:
        raise HTTPException(status_code=503, detail="memory_disabled")
    deleted = await asyncio.to_thread(_delete_profile, mem)
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

    mem = await asyncio.to_thread(get_memory)
    facts: list[dict] = []
    recall: list = []
    short: list = []
    if mem is not None:
        facts, recall, short = await _gather_context(mem, req.message, req.user_id)

    if config.mode == "real":
        from .real_llm import generate_reply as real_generate_reply

        reply = await real_generate_reply(
            req.message, facts=facts, recall=recall, short_term=short, user_id=req.user_id
        )
    else:
        latency = random.uniform(config.mock_min_latency_s, config.mock_max_latency_s)
        await asyncio.sleep(latency)
        reply = mock_generate_reply(req.message)

    if mem is not None and reply:
        await asyncio.to_thread(mem.remember, "samantha", reply, user_id=req.user_id)

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
# /speak — TTS
# ========================================================================


@app.post("/speak")
async def speak(req: SpeakRequest) -> Response:
    """Synthesize speech via CosyVoice 3, streaming.

    Response is `audio/pcm` raw 24 kHz mono int16 little-endian,
    chunked. Headers carry mode + sample rate. The frontend uses
    Web Audio API to decode & play as chunks arrive.

    Returns 503 if the CosyVoice server config or ref files are
    missing — no silent fallback.
    """
    logger.info(f"speak: voice={req.voice} text='{req.text[:60]}'")

    if not req.text.strip():
        return Response(
            b"",
            media_type="audio/pcm",
            headers={"X-TTS-Mode": "empty"},
        )

    from . import tts

    if not tts.is_available():
        raise HTTPException(
            status_code=503,
            detail="cosyvoice not available — check ref WAV + transcript paths",
        )

    gen = tts.stream(req.text)
    # Prime the generator to discover the backend that serves — we
    # need its label for the X-TTS-Mode header, which has to be set
    # BEFORE the body starts streaming.
    try:
        first_chunk, mode_used = await gen.__anext__()
    except StopAsyncIteration:
        # stream() yielded nothing (e.g. whitespace-only input slipped
        # through the strip check); equivalent to "empty".
        return Response(
            b"",
            media_type="audio/pcm",
            headers={"X-TTS-Mode": "empty"},
        )

    async def body():
        yield first_chunk
        async for chunk, _label in gen:
            yield chunk

    return StreamingResponse(
        body(),
        media_type="audio/pcm",
        headers={
            "X-TTS-Mode": mode_used,
            "X-TTS-Sample-Rate": str(tts.OUTPUT_SAMPLE_RATE),
            # Hint to caches: each call is unique audio.
            "Cache-Control": "no-store",
        },
    )


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
    logger.info(f"ws chat: user_id={user_id} mode={config.mode} message='{message[:60]}'")

    mem = await asyncio.to_thread(get_memory)
    facts: list[dict] = []
    recall: list = []
    short: list = []
    if mem is not None:
        facts, recall, short = await _gather_context(mem, message, user_id)

    reply_chunks: list[str] = []
    try:
        async for token in _stream_tokens(
            message, facts=facts, recall=recall, short_term=short, user_id=user_id
        ):
            reply_chunks.append(token)
            try:
                await websocket.send_text(json.dumps({"type": "token", "token": token}))
            except (WebSocketDisconnect, RuntimeError) as e:
                # ONLY send failures mean "client gone". Anything the
                # generator raises falls through to the branches below.
                raise _ClientGone() from e
    except _ClientGone:
        # Don't try to talk to a dead socket; the endpoint loop closes.
        raise
    except WebSocketDisconnect:
        raise
    except Exception as e:
        logger.exception("Error in websocket chat stream")
        try:
            await websocket.send_text(
                json.dumps({"type": "error", "error": f"llm_error: {str(e)}"})
            )
        except Exception:
            logger.info("ws: client gone before error could be delivered")
        return

    if mem is not None and reply_chunks:
        full_reply = "".join(reply_chunks).strip()
        if full_reply:
            await asyncio.to_thread(mem.remember, "samantha", full_reply, user_id=user_id)

    elapsed_ms = int((time.perf_counter() - start) * 1000)
    await websocket.send_text(json.dumps({"type": "done", "thinking_ms": elapsed_ms}))


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
            try:
                raw = await websocket.receive_text()
            except KeyError:
                # Starlette's receive_text() KeyErrors on binary frames.
                await websocket.send_text(
                    json.dumps({"type": "error", "error": "binary_not_supported"})
                )
                continue
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_text(json.dumps({"type": "error", "error": "invalid_json"}))
                continue
            if not isinstance(msg, dict):
                await websocket.send_text(json.dumps({"type": "error", "error": "invalid_message"}))
                continue

            msg_type = msg.get("type")
            if msg_type == "chat":
                message = msg.get("message")
                message = message.strip() if isinstance(message, str) else ""
                if not message:
                    await websocket.send_text(
                        json.dumps({"type": "error", "error": "empty_message"})
                    )
                    continue
                if len(message) > MAX_WS_MESSAGE_CHARS:
                    await websocket.send_text(
                        json.dumps({"type": "error", "error": "message_too_long"})
                    )
                    continue
                user_id = msg.get("user_id")
                if not isinstance(user_id, str) or not user_id:
                    user_id = "primary"
                await _ws_stream_chat(websocket, message, user_id)
            elif msg_type == "listen":
                await _ws_handle_listen(websocket)
            else:
                await websocket.send_text(
                    json.dumps({"type": "error", "error": f"unknown_type:{msg_type}"})
                )
    except WebSocketDisconnect:
        logger.info("ws: client disconnected")
    except (_ClientGone, RuntimeError):
        # _ClientGone: token send failed mid-reply. Bare RuntimeError
        # here can only come from sends issued by this loop itself
        # (error frames / the `done` frame) on an already-closed socket.
        logger.info("ws: connection closed mid-send")


# ========================================================================
# Error handling
# ========================================================================


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception(f"Unhandled exception on {request.url.path}")
    # Deliberately generic: str(exc) can leak paths/keys to the client.
    # The full traceback is in the log.
    return JSONResponse(status_code=500, content={"detail": "internal_error"})


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
