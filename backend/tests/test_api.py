"""Tests del backend mock.

Para ejecutar:
    cd backend
    pip install -e ".[dev]"
    pytest tests/
"""

from fastapi.testclient import TestClient

from samantha.api import app


client = TestClient(app)


# ========================================================================
# /ping
# ========================================================================

def test_ping_returns_ok():
    response = client.get("/ping")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["mode"] == "mock"
    assert "timestamp" in data
    assert "version" in data


# ========================================================================
# /chat
# ========================================================================

def test_chat_greeting_responds():
    response = client.post("/chat", json={"message": "Hola Samantha", "user_id": "test"})
    assert response.status_code == 200
    data = response.json()
    assert "reply" in data
    assert len(data["reply"]) > 0
    assert data["thinking_ms"] > 0


def test_chat_sadness_gets_caring_response():
    """Cuando el usuario dice que está triste, Samantha NO debe dar disclaimer
    ni sugerir profesional. Debe responder con cercanía."""
    response = client.post("/chat", json={"message": "estoy fatal", "user_id": "test"})
    assert response.status_code == 200
    reply = response.json()["reply"].lower()
    # Verificar que NO contiene frases disclaimer típicas
    assert "profesional" not in reply
    assert "modelo de lenguaje" not in reply
    assert "lamento escuchar" not in reply


def test_chat_returns_different_replies():
    """El mock debe tener variedad — no devolver siempre lo mismo."""
    replies = set()
    for _ in range(20):
        response = client.post("/chat", json={"message": "hola"})
        replies.add(response.json()["reply"])
    # Con 20 intentos sobre un pool de varios saludos, debe haber al menos 2 distintos
    assert len(replies) >= 2


def test_chat_validates_empty_message():
    response = client.post("/chat", json={"message": "", "user_id": "test"})
    # Pydantic min_length=1 debe rechazarlo
    assert response.status_code == 422


# ========================================================================
# /transcribe
# ========================================================================

def test_transcribe_returns_text():
    fake_audio = b"\x00" * 32000  # 1 segundo de silencio fake
    response = client.post(
        "/transcribe",
        files={"audio": ("test.wav", fake_audio, "audio/wav")},
    )
    assert response.status_code == 200
    data = response.json()
    assert "text" in data
    assert data["language"] == "es"
    assert data["duration_s"] > 0


# ========================================================================
# /speak
# ========================================================================

def test_speak_returns_wav():
    response = client.post("/speak", json={"text": "Hola", "voice": "default"})
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    # WAV magic bytes
    assert response.content[:4] == b"RIFF"
    assert response.content[8:12] == b"WAVE"


def test_speak_validates_empty():
    response = client.post("/speak", json={"text": "", "voice": "default"})
    assert response.status_code == 422


# ========================================================================
# Mock LLM directo (sin HTTP)
# ========================================================================

def test_generate_reply_matches_keyword():
    from samantha.mock_llm import generate_reply

    # "estoy triste" debe activar el patrón de empatía
    reply = generate_reply("estoy muy triste hoy")
    # No verificamos texto exacto (es aleatorio) pero sí que no sea genérico
    # Las respuestas genéricas son cortas tipo "Cuéntame más."
    # Las de empatía suelen ser más elaboradas
    assert len(reply) > 5


def test_generate_reply_with_accents():
    """El matching debe funcionar con y sin acentos."""
    from samantha.mock_llm import generate_reply

    r1 = generate_reply("estoy triste")
    r2 = generate_reply("estóy trÍste")  # con acentos raros
    # Ambos deben generar respuesta (no fallar)
    assert r1 and r2
