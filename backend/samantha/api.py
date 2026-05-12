"""Servidor FastAPI principal de Samantha.

Endpoints:
  - GET  /ping        → health check
  - POST /chat        → conversación (mock o real)
  - POST /chat/stream → conversación con SSE (streaming)
  - POST /transcribe  → audio → texto (mock por ahora)
  - POST /speak       → texto → audio (mock por ahora)

Para arrancar:
    uvicorn samantha.api:app --host 127.0.0.1 --port 7777

O usar el helper:
    python -m samantha.api
"""

import asyncio
import io
import math
import random
import struct
import time
import wave

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from loguru import logger

from . import __version__
from .config import config
from .mock_llm import generate_reply, tokenize_for_streaming
from .schemas import (
    ChatRequest,
    ChatResponse,
    PingResponse,
    SpeakRequest,
    TranscribeResponse,
)


# ========================================================================
# APP SETUP
# ========================================================================

app = FastAPI(
    title="Samantha Backend",
    version=__version__,
    description="Backend local para Samantha. Solo accesible desde localhost.",
)

# CORS: Tauri webview puede tener origin "tauri://localhost" en producción
# y "http://localhost:1420" durante desarrollo. Permitimos ambos.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "tauri://localhost",
        "http://tauri.localhost",
        "http://localhost:1420",
        "http://127.0.0.1:1420",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ========================================================================
# /ping
# ========================================================================

@app.get("/ping", response_model=PingResponse)
async def ping() -> PingResponse:
    """Health check. Tauri lo llama al arrancar para esperar al backend."""
    return PingResponse(
        status="ok",
        version=__version__,
        timestamp=int(time.time()),
        mode=config.mode,
    )


# ========================================================================
# /chat (no streaming)
# ========================================================================

@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    """Endpoint principal de conversación.

    En mock, devuelve respuesta plausible tras latencia simulada.
    En real (futuro), llama a vLLM y devuelve la respuesta completa.
    """
    start = time.perf_counter()
    logger.info(f"chat: user_id={req.user_id} message='{req.message[:60]}'")

    # Simular latencia de "pensamiento" antes de responder
    latency = random.uniform(config.mock_min_latency_s, config.mock_max_latency_s)
    await asyncio.sleep(latency)

    reply = generate_reply(req.message)

    elapsed_ms = int((time.perf_counter() - start) * 1000)
    logger.info(f"chat: replied in {elapsed_ms}ms — '{reply[:60]}'")

    return ChatResponse(
        reply=reply,
        thinking_ms=elapsed_ms,
        model=None if config.mode == "mock" else config.llm_model,
    )


# ========================================================================
# /chat/stream — Server-Sent Events
# ========================================================================

@app.post("/chat/stream")
async def chat_stream(req: ChatRequest) -> StreamingResponse:
    """Variante streaming del /chat. Devuelve tokens en formato SSE.

    Formato de cada evento:
        data: {"token": "Hola "}\\n\\n

    Al finalizar:
        data: {"done": true, "thinking_ms": 1234}\\n\\n
    """
    start = time.perf_counter()
    logger.info(f"chat/stream: '{req.message[:60]}'")

    reply = generate_reply(req.message)
    tokens = tokenize_for_streaming(reply)

    async def event_generator():
        # Pequeña pausa inicial (como "pensando")
        await asyncio.sleep(random.uniform(0.2, 0.6))

        for token in tokens:
            await asyncio.sleep(config.mock_streaming_delay_s)
            # Escape simple para JSON
            safe = token.replace("\\", "\\\\").replace('"', '\\"')
            yield f'data: {{"token": "{safe}"}}\n\n'

        elapsed_ms = int((time.perf_counter() - start) * 1000)
        yield f'data: {{"done": true, "thinking_ms": {elapsed_ms}}}\n\n'

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # nginx no buffer (si algún día hay proxy)
        },
    )


# ========================================================================
# /transcribe — STT (mock)
# ========================================================================

@app.post("/transcribe", response_model=TranscribeResponse)
async def transcribe(audio: UploadFile = File(...)) -> TranscribeResponse:
    """Mock de transcripción de audio.

    En el real (faster-whisper), recibirá los bytes, los pasará al modelo
    y devolverá el texto detectado. Aquí simulamos.
    """
    contents = await audio.read()
    size = len(contents)
    logger.info(f"transcribe: received {size} bytes")

    # Simulación: latencia proporcional al tamaño (~50KB por segundo de audio)
    await asyncio.sleep(0.3 + size / 1_000_000)

    # Frases plausibles que podría haber dicho el usuario
    fake_transcripts = [
        "Hola Samantha, ¿qué tal?",
        "Cuéntame algo interesante.",
        "Estoy un poco cansado hoy.",
        "¿Te acuerdas de lo que hablamos ayer?",
        "Tengo una pregunta para ti.",
        "Me apetece charlar un rato.",
    ]

    fake_text = random.choice(fake_transcripts)

    return TranscribeResponse(
        text=fake_text,
        language="es",
        duration_s=size / 32000.0,  # estimación aprox a 16kHz 16-bit mono
        confidence=random.uniform(0.85, 0.98),
    )


# ========================================================================
# /speak — TTS (mock)
# ========================================================================

@app.post("/speak")
async def speak(req: SpeakRequest) -> Response:
    """Mock de síntesis de voz.

    Devuelve un WAV con un tono breve generado proceduralmente.
    En real (Piper), generará la voz real de Samantha.
    """
    logger.info(f"speak: voice={req.voice} text='{req.text[:60]}'")

    # Simular latencia de síntesis (~10ms por carácter)
    await asyncio.sleep(len(req.text) * 0.01)

    # Generar un WAV breve con un tono suave
    # En real: Piper devolvería el audio sintetizado
    wav_bytes = _generate_tone_wav(duration_s=0.4, freq=440)

    return Response(
        content=wav_bytes,
        media_type="audio/wav",
        headers={"X-Mock-Mode": "true"},
    )


def _generate_tone_wav(duration_s: float, freq: float = 440.0) -> bytes:
    """Genera un WAV mono 16-bit con un tono senoidal con fade in/out."""
    sample_rate = 16000
    n_samples = int(duration_s * sample_rate)
    fade_samples = int(0.05 * sample_rate)  # 50ms de fade

    samples = []
    for i in range(n_samples):
        # Envelope con fade in/out
        if i < fade_samples:
            envelope = i / fade_samples
        elif i > n_samples - fade_samples:
            envelope = (n_samples - i) / fade_samples
        else:
            envelope = 1.0
        # Onda senoidal con amplitud moderada
        value = envelope * 0.3 * math.sin(2 * math.pi * freq * i / sample_rate)
        samples.append(int(value * 32767))

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        wf.writeframes(struct.pack(f"<{n_samples}h", *samples))

    return buf.getvalue()


# ========================================================================
# Manejo de errores
# ========================================================================

@app.exception_handler(Exception)
async def generic_exception_handler(request, exc):
    logger.exception(f"Unhandled exception on {request.url.path}")
    raise HTTPException(status_code=500, detail=str(exc))


# ========================================================================
# Entry point para ejecución directa
# ========================================================================

if __name__ == "__main__":
    import uvicorn

    logger.info(
        f"Samantha backend starting on {config.host}:{config.port} "
        f"(mode={config.mode})"
    )

    uvicorn.run(
        "samantha.api:app",
        host=config.host,
        port=config.port,
        log_level=config.log_level.lower(),
        reload=False,  # Producción: no reload
    )
