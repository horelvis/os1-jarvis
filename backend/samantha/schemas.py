"""Modelos de datos (Pydantic) que definen el contrato del API.

Estos schemas SON el contrato entre Tauri (Rust) y este backend (Python).
Si cambias algo aquí, hay que actualizar también `src-tauri/src/backend.rs`.
"""

from pydantic import BaseModel, Field


# ========================================================================
# /ping
# ========================================================================

class PingResponse(BaseModel):
    """Respuesta del endpoint de health check."""

    status: str = Field(description="'ok' si todo va bien")
    version: str = Field(description="Versión del backend")
    timestamp: int = Field(description="Unix timestamp en segundos")
    mode: str = Field(description="'mock' o 'real'")
    has_profile: bool = Field(
        default=False,
        description="True si Samantha ya conoce a esta persona",
    )


# ========================================================================
# /chat
# ========================================================================

class ChatRequest(BaseModel):
    """Mensaje del usuario hacia Samantha."""

    message: str = Field(
        min_length=1,
        max_length=8000,
        description="Lo que el usuario ha dicho/escrito",
    )
    user_id: str = Field(
        default="primary",
        description="Identificador del usuario. Por ahora siempre 'primary'.",
    )
    stream: bool = Field(
        default=False,
        description="Si True, devuelve Server-Sent Events token a token",
    )


class ChatResponse(BaseModel):
    """Respuesta de Samantha al mensaje del usuario."""

    reply: str = Field(description="Lo que Samantha ha respondido")
    thinking_ms: int = Field(description="Tiempo total que ha tardado en pensar+responder")
    model: str | None = Field(
        default=None,
        description="Modelo usado (None en modo mock)",
    )


# ========================================================================
# /transcribe — STT
# ========================================================================

class TranscribeResponse(BaseModel):
    """Resultado de transcribir un fragmento de audio a texto."""

    text: str = Field(description="Texto transcrito de la voz del usuario")
    language: str = Field(default="es", description="Idioma detectado (ISO 639-1)")
    duration_s: float = Field(description="Duración del audio en segundos")
    confidence: float | None = Field(
        default=None,
        description="Confianza del modelo, 0.0–1.0 (None si no disponible)",
    )


# ========================================================================
# /speak — TTS
# ========================================================================

class SpeakRequest(BaseModel):
    """Petición para sintetizar voz a partir de texto."""

    text: str = Field(min_length=1, max_length=4000)
    voice: str = Field(
        default="default",
        description="Identificador de voz. Por defecto la voz de Samantha.",
    )


# La respuesta de /speak es audio binario (audio/wav), no JSON.
# No necesita schema Pydantic.


# ========================================================================
# /profile — onboarding state synthesized from Memory
# ========================================================================


class ProfileAnswer(BaseModel):
    """Una de las 6 respuestas del onboarding."""

    q: str = Field(min_length=1, max_length=400)
    a: str | None = Field(default=None, max_length=2000)


class ProfileCreateRequest(BaseModel):
    """Cuerpo de POST /profile cuando completa el onboarding."""

    name: str = Field(min_length=1, max_length=80)
    answers: list[ProfileAnswer] = Field(min_length=6, max_length=6)


class ProfileResponse(BaseModel):
    """Vista de perfil sintetizada desde Memory."""

    name: str
    onboarding_completed_at: int
    answers: list[ProfileAnswer]


# ========================================================================
# Errores estándar
# ========================================================================

class ErrorResponse(BaseModel):
    """Respuesta de error estándar."""

    error: str = Field(description="Mensaje legible del error")
    code: str | None = Field(default=None, description="Código de error opcional")
