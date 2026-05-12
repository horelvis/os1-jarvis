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


# ========================================================================
# GET / + /static/* — frontend serving (Phase 3)
# ========================================================================


def test_index_serves_html():
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    body = response.text
    # The SPA must reference the modular CSS and JS extracted in Phase 3
    assert "/static/style.css" in body
    assert "/static/app.js" in body


def test_static_css_served():
    response = client.get("/static/style.css")
    assert response.status_code == 200
    assert "text/css" in response.headers["content-type"]


def test_static_js_modules_served():
    for name in ("app.js", "samantha-wave.js", "os1-loader.js", "ws-client.js"):
        response = client.get(f"/static/{name}")
        assert response.status_code == 200, f"{name} should be served"


# ========================================================================
# /ws — WebSocket streaming chat + listen (Phase 3)
# ========================================================================


def test_ws_chat_streams_tokens_then_done():
    """A `chat` message produces one or more `token` events, then `done`."""
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "chat", "message": "hola"})
        tokens: list[str] = []
        done_msg = None
        while True:
            msg = ws.receive_json()
            if msg["type"] == "token":
                tokens.append(msg["token"])
            elif msg["type"] == "done":
                done_msg = msg
                break
            else:
                raise AssertionError(f"unexpected message: {msg}")
        assert tokens, "expected at least one token"
        assert "".join(tokens).strip(), "tokens should join into a non-empty reply"
        assert done_msg["thinking_ms"] >= 0


def test_ws_listen_returns_transcription():
    """A `listen` turn returns a single `transcription` message."""
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "listen"})
        msg = ws.receive_json()
        assert msg["type"] == "transcription"
        assert isinstance(msg["text"], str)
        assert msg["text"]


def test_ws_rejects_unknown_type():
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "nope"})
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert "unknown_type" in msg["error"]


def test_ws_rejects_empty_chat_message():
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "chat", "message": "   "})
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert msg["error"] == "empty_message"


# ========================================================================
# real_llm — OpenAI-compat SSE client (Phase 4)
# ========================================================================


def test_real_llm_streams_sse_tokens():
    """Verify real_llm parses OpenAI-style SSE deltas into a token stream.

    Mocks the httpx client so the test doesn't require a running
    llama-server. Locks down the SSE parser contract.
    """
    import asyncio

    from samantha import real_llm

    sse_lines = [
        'data: {"choices":[{"delta":{"content":"Hola"}}]}',
        "",  # blank line between events, must be tolerated
        'data: {"choices":[{"delta":{"content":". "}}]}',
        'data: {"choices":[{"delta":{"content":"\\u00bfC\\u00f3mo va?"}}]}',
        "data: [DONE]",
    ]

    class _FakeResponse:
        status_code = 200

        async def aiter_lines(self):
            for line in sse_lines:
                yield line

        async def aread(self):
            return b""

    class _FakeStreamCtx:
        async def __aenter__(self):
            return _FakeResponse()

        async def __aexit__(self, exc_type, exc, tb):
            return None

    class _FakeClient:
        def stream(self, method, url, json=None):
            assert method == "POST"
            assert url.endswith("/v1/chat/completions")
            assert json["stream"] is True
            assert json["messages"][0]["role"] == "system"
            # User message is the raw input plus Qwen3's /no_think
            # control token (disables the reasoning block).
            assert json["messages"][1]["content"] == "hola\n/no_think"
            return _FakeStreamCtx()

        async def aclose(self):
            pass

    async def run():
        real_llm._client = _FakeClient()
        try:
            return [tok async for tok in real_llm.stream_reply("hola")]
        finally:
            real_llm._client = None

    tokens = asyncio.run(run())
    assert "".join(tokens) == "Hola. ¿Cómo va?"


def test_real_llm_falls_back_on_http_error():
    """If the LLM server returns non-200, we emit an in-character fallback
    instead of bubbling an exception to the UI."""
    import asyncio

    from samantha import real_llm

    class _FakeResponse:
        status_code = 503

        async def aiter_lines(self):
            if False:
                yield ""  # pragma: no cover

        async def aread(self):
            return b"upstream is down"

    class _FakeStreamCtx:
        async def __aenter__(self):
            return _FakeResponse()

        async def __aexit__(self, exc_type, exc, tb):
            return None

    class _FakeClient:
        def stream(self, *a, **kw):
            return _FakeStreamCtx()

        async def aclose(self):
            pass

    async def run():
        real_llm._client = _FakeClient()
        try:
            return [tok async for tok in real_llm.stream_reply("hola")]
        finally:
            real_llm._client = None

    tokens = asyncio.run(run())
    full = "".join(tokens)
    assert full, "should still yield something so the UI doesn't hang"
    # Fallback is in Samantha's voice (no "error 503" disclaimer)
    assert "perdido el hilo" in full.lower() or "vuelve a" in full.lower()


def test_personality_system_prompt_loaded():
    """personality.SYSTEM_PROMPT must be present and in Samantha's voice."""
    from samantha.personality import SYSTEM_PROMPT, SYSTEM_PROMPT_VERSION

    assert isinstance(SYSTEM_PROMPT, str)
    assert len(SYSTEM_PROMPT) > 500
    assert "Samantha" in SYSTEM_PROMPT
    # Spanish-from-Spain markers (CLAUDE.md §7)
    assert "tuteas" in SYSTEM_PROMPT.lower() or "tutea" in SYSTEM_PROMPT.lower()
    # The prompt explicitly lists forbidden patterns so the model learns
    # to avoid them.
    assert "Como modelo de lenguaje" in SYSTEM_PROMPT
    assert SYSTEM_PROMPT_VERSION.startswith("v")


# ========================================================================
# memory — persistent semantic memory (Phase 6)
# ========================================================================


def test_memory_remember_and_recall(tmp_path):
    """Storing chunks and querying by semantic similarity returns the
    relevant ones near the top.

    short_term_capacity=0 isolates the long-term path so recall doesn't
    filter our chunks out as 'already-in-the-conversation-window'.
    """
    from samantha.memory import Memory

    mem = Memory(persist_dir=str(tmp_path / "mem"), short_term_capacity=0)
    mem.remember("user", "Me gusta tomarme un café por la mañana", user_id="u1")
    mem.remember("user", "Mi perro se llama Toby, es un labrador", user_id="u1")
    mem.remember("user", "Trabajo en una agencia de publicidad", user_id="u1")

    results = mem.recall("hablamos del café?", k=2, user_id="u1")
    assert len(results) >= 1
    # Top hit should be the coffee one — verify by content, since
    # distance values depend on the embedder.
    top_text = results[0].text.lower()
    assert "café" in top_text or "cafe" in top_text


def test_memory_isolates_by_user_id(tmp_path):
    from samantha.memory import Memory

    mem = Memory(persist_dir=str(tmp_path / "mem"), short_term_capacity=0)
    mem.remember("user", "Vivo en Madrid", user_id="alice")
    mem.remember("user", "Vivo en Barcelona", user_id="bob")

    a = mem.recall("dónde vives", k=5, user_id="alice")
    b = mem.recall("dónde vives", k=5, user_id="bob")

    assert any("Madrid" in c.text for c in a)
    assert all("Barcelona" not in c.text for c in a)
    assert any("Barcelona" in c.text for c in b)


def test_memory_admin_forget_deletes_similar_chunks(tmp_path):
    """ADMIN-only deletion path. NOT triggered by user input — Samantha
    never forgets in normal operation. This test just locks down that
    the admin tool still works for tests / future maintenance flows."""
    from samantha.memory import Memory

    mem = Memory(persist_dir=str(tmp_path / "mem"), short_term_capacity=0)
    mem.remember("user", "Tengo un perro labrador llamado Toby", user_id="u1")
    mem.remember("user", "Mi color favorito es el azul", user_id="u1")
    mem.remember("user", "Toby siempre me espera en la puerta", user_id="u1")

    deleted = mem.forget("el perro Toby", k=2, user_id="u1")
    assert len(deleted) >= 1

    remaining = mem.all(user_id="u1")
    assert any("azul" in c.text for c in remaining)


def test_memory_persists_across_reopen(tmp_path):
    """Closing and reopening the store keeps the chunks queryable."""
    from samantha.memory import Memory

    persist = str(tmp_path / "mem")

    mem1 = Memory(persist_dir=persist, short_term_capacity=0)
    mem1.remember("user", "Mi cumpleaños es el 12 de mayo", user_id="u1")
    del mem1  # drop the reference

    mem2 = Memory(persist_dir=persist, short_term_capacity=0)
    results = mem2.recall("cuándo nací", k=3, user_id="u1")
    assert len(results) >= 1
    assert "cumpleaños" in results[0].text.lower() or "12 de mayo" in results[0].text


def test_memory_empty_store_returns_empty(tmp_path):
    from samantha.memory import Memory

    mem = Memory(persist_dir=str(tmp_path / "mem"))
    assert mem.recall("cualquier cosa") == []
    assert mem.all() == []
    assert mem.stats()["total_chunks"] == 0


def test_memory_clear_removes_user_chunks(tmp_path):
    from samantha.memory import Memory

    mem = Memory(persist_dir=str(tmp_path / "mem"))
    for i in range(5):
        mem.remember("user", f"Fact number {i}", user_id="u1")
    assert len(mem.all(user_id="u1")) == 5

    deleted = mem.clear(user_id="u1")
    assert deleted == 5
    assert mem.all(user_id="u1") == []


def test_memory_rejects_invalid_role(tmp_path):
    from samantha.memory import Memory

    mem = Memory(persist_dir=str(tmp_path / "mem"))
    import pytest

    with pytest.raises(ValueError):
        mem.remember("robot", "hola")


def test_memory_module_does_not_expose_forget_intent():
    """Per user directive: Samantha never forgets. The user-facing intent
    detector must not exist as a public hook anymore."""
    from samantha import memory as memory_mod

    assert not hasattr(memory_mod, "detect_forget_intent")
    assert not hasattr(memory_mod, "_FORGET_PATTERNS")


def test_memory_uses_fastembed_multilingual_by_default(tmp_path):
    """The embedder swap to fastembed multilingual is the default.

    short_term_capacity=0 isolates the long-term semantic path so the
    test validates the embedder rather than the recall/short-term
    interaction (covered separately).
    """
    from samantha.memory import Memory
    mem = Memory(persist_dir=str(tmp_path / "mem"), short_term_capacity=0)
    mem.remember("user", "Mi mascota se llama Toby, es un labrador.", user_id="u1")
    mem.remember("user", "Mi color favorito es el azul cobalto.", user_id="u1")
    mem.remember("user", "Trabajo en una agencia de publicidad.", user_id="u1")
    results = mem.recall("¿qué mascota tiene?", k=2, user_id="u1")
    assert results, "expected at least one result"
    top_text = results[0].text.lower()
    assert "toby" in top_text or "labrador" in top_text or "mascota" in top_text


def test_memory_remember_writes_to_short_term(tmp_path):
    from samantha.memory import Memory
    mem = Memory(persist_dir=str(tmp_path / "mem"), short_term_capacity=3)
    mem.remember("user", "uno", user_id="u1")
    mem.remember("samantha", "dos", user_id="u1")
    short = mem.short_term(user_id="u1")
    assert [e.text for e in short] == ["uno", "dos"]
    assert short[0].role == "user"
    assert short[1].role == "samantha"


def test_memory_recall_excludes_short_term_entries(tmp_path):
    from samantha.memory import Memory
    mem = Memory(persist_dir=str(tmp_path / "mem"), short_term_capacity=10)
    mem.remember("user", "hablamos del café por la mañana", user_id="u1")
    short_ids = {e.id for e in mem.short_term(user_id="u1")}
    results = mem.recall("café por la mañana", k=5, user_id="u1")
    result_ids = {r.id for r in results}
    assert not (result_ids & short_ids), \
        "recall should exclude short-term entries"


def test_real_llm_injects_memories_into_system_prompt():
    """When memories are passed, they appear as a system-prompt addendum."""
    from samantha import real_llm
    from samantha.memory import MemoryChunk

    memories = [
        MemoryChunk(
            id="x1",
            role="user",
            text="Tengo un perro llamado Toby",
            timestamp=1700000000,
            user_id="primary",
        ),
        MemoryChunk(
            id="x2",
            role="samantha",
            text="Vale, lo apunto.",
            timestamp=1700000010,
            user_id="primary",
        ),
    ]
    payload = real_llm._build_payload("¿Cómo está Toby?", memories=memories)
    system = payload["messages"][0]["content"]
    assert "Lo que recuerdas" in system
    assert "Toby" in system
    assert "tú dijiste" in system  # samantha-role line
    assert "ella" in system  # user-role line
