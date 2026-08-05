"""Tests del backend mock.

Para ejecutar:
    cd backend
    pip install -e ".[dev]"
    pytest tests/
"""

import json

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


def test_speak_503_when_backend_unavailable(monkeypatch):
    """No silent tone fallback: if the configured TTS backend can't serve,
    /speak returns 503 so the UI surfaces a real error instead of a beep."""
    from samantha import tts as tts_mod

    monkeypatch.setattr(tts_mod, "is_available", lambda: False)
    response = client.post("/speak", json={"text": "Hola", "voice": "default"})
    assert response.status_code == 503


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


def test_index_serves_frontend_html():
    """The root route serves frontend/dist/index.html (built by Vite)."""
    import pytest

    response = client.get("/")
    if response.status_code == 404:
        pytest.skip("frontend not built (frontend/dist/ missing)")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


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


def test_ws_chat_handles_streaming_exception(monkeypatch):
    """If an exception occurs during streaming, /ws sends an error message instead of crashing."""
    from samantha import api

    async def mock_stream_tokens(*args, **kwargs):
        if False:
            yield ""
        raise ValueError("Simulated streaming error")

    monkeypatch.setattr(api, "_stream_tokens", mock_stream_tokens)

    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "chat", "message": "hola"})
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert "llm_error" in msg["error"]
        assert "Simulated streaming error" in msg["error"]


def test_ws_chat_reports_generator_runtime_error(monkeypatch):
    """httpx raises RuntimeError for real faults (client closed, event
    loop closed). Those come from the token GENERATOR, not from the
    socket — the client must receive an error frame, not silence."""
    from samantha import api

    async def mock_stream_tokens(*args, **kwargs):
        if False:
            yield ""
        raise RuntimeError("Cannot send a request, as the client has been closed")

    monkeypatch.setattr(api, "_stream_tokens", mock_stream_tokens)

    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "chat", "message": "hola"})
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert "llm_error" in msg["error"]
        assert "client has been closed" in msg["error"]


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
        def stream(self, method, url, json=None, headers=None):
            assert method == "POST"
            assert url.endswith("/v1/chat/completions")
            assert json["stream"] is True
            assert json["messages"][0]["role"] == "system"
            # User message verbatim (no /no_think suffix because the
            # default model is grok-* not qwen). The suffix is only
            # appended for Qwen-family models — see
            # test_real_llm_build_payload_qwen_appends_no_think.
            assert json["messages"][1]["content"] == "hola"
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


def test_real_llm_raises_on_http_error():
    """If the LLM server returns non-200, the stream raises so the WS
    handler surfaces it. The previous silent 'He perdido el hilo'
    fallback hid LLM outages AND fed the mic-feedback loop (Samantha
    saying the fallback line was picked back up as the next user
    message)."""
    import asyncio

    import httpx

    from samantha import real_llm

    class _FakeRequest:
        pass

    class _FakeResponse:
        status_code = 503
        request = _FakeRequest()

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

    import pytest

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(run())


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
    assert not (result_ids & short_ids), "recall should exclude short-term entries"


def test_memory_set_and_get_fact(tmp_path):
    from samantha.memory import Memory

    mem = Memory(persist_dir=str(tmp_path / "mem"))
    fact_id = mem.set_fact("name", "Horelvis", user_id="u1")
    assert fact_id
    fact = mem.get_fact("name", user_id="u1")
    assert fact is not None
    assert fact["value"] == "Horelvis"
    assert fact["kind"] == "name"


def test_memory_get_fact_returns_newest(tmp_path):
    import time
    from samantha.memory import Memory

    mem = Memory(persist_dir=str(tmp_path / "mem"))
    mem.set_fact("name", "Old Name", user_id="u1")
    time.sleep(1.1)
    mem.set_fact("name", "New Name", user_id="u1")
    fact = mem.get_fact("name", user_id="u1")
    assert fact["value"] == "New Name"


def test_memory_facts_excluded_from_conversational_recall(tmp_path):
    from samantha.memory import Memory

    mem = Memory(persist_dir=str(tmp_path / "mem"), short_term_capacity=0)
    mem.set_fact("name", "Horelvis", user_id="u1", text="El usuario se llama Horelvis")
    mem.remember("user", "Me encanta el café por la mañana", user_id="u1")
    results = mem.recall("Horelvis", k=5, user_id="u1")
    for r in results:
        assert r.role != "fact"


def test_memory_all_facts_filters_by_kind(tmp_path):
    from samantha.memory import Memory

    mem = Memory(persist_dir=str(tmp_path / "mem"))
    mem.set_fact("name", "Alice", user_id="u1")
    mem.set_fact("preferred_tone", "direct", user_id="u1")
    names = mem.all_facts(kind="name", user_id="u1")
    assert len(names) == 1
    assert names[0]["value"] == "Alice"
    everything = mem.all_facts(user_id="u1")
    assert len(everything) == 2


def test_real_llm_injects_recall_into_system_prompt():
    """When recall chunks are passed, they appear under '# Lo que recuerdas'."""
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
    payload = real_llm._build_payload("¿Cómo está Toby?", recall=memories)
    system = payload["messages"][0]["content"]
    assert "# Lo que recuerdas" in system
    assert "Toby" in system
    assert "tú dijiste" in system  # samantha-role line
    assert "ella" in system  # user-role line
    # /no_think is Qwen-specific; with the default grok model it's not appended.
    assert payload["messages"][-1]["content"] == "¿Cómo está Toby?"


def test_real_llm_build_payload_includes_facts_recall_and_short_term():
    """Spec §9.6 — the prompt has 3 labeled sections in order."""
    from samantha import real_llm
    from samantha.memory import MemoryChunk

    facts = [
        {"kind": "name", "value": "Horelvis", "text": "El usuario se llama Horelvis"},
        {
            "kind": "onboarding_completed_at",
            "value": 1778000000,
            "text": "Onboarding completado en 1778000000",
        },
    ]
    recall = [
        MemoryChunk(
            id="r1",
            role="user",
            text="Trabajo en una agencia",
            timestamp=1778001000,
            user_id="primary",
        ),
    ]
    short_term = [
        MemoryChunk(
            id="s1", role="user", text="¿qué tal el día?", timestamp=1778002000, user_id="primary"
        ),
        MemoryChunk(
            id="s2", role="samantha", text="Bien. ¿Y tú?", timestamp=1778002005, user_id="primary"
        ),
    ]

    payload = real_llm._build_payload(
        message="me siento perdido",
        facts=facts,
        recall=recall,
        short_term=short_term,
    )
    system = payload["messages"][0]["content"]
    assert "# Lo que sabes de ella" in system
    assert "Horelvis" in system
    assert "# Lo que recuerdas" in system
    assert "agencia" in system
    assert "# Conversación reciente" in system
    assert "¿qué tal el día?" in system
    assert (
        system.find("# Lo que sabes")
        < system.find("# Lo que recuerdas")
        < system.find("# Conversación reciente")
    )
    assert payload["messages"][-1]["role"] == "user"
    # /no_think is Qwen-specific; with the default grok model it's not appended.
    assert payload["messages"][-1]["content"] == "me siento perdido"


def test_real_llm_build_payload_qwen_appends_no_think(monkeypatch):
    """Qwen3-family models get the /no_think soft switch appended so we
    don't wait for the reasoning block; non-Qwen models don't."""
    from samantha import real_llm
    from samantha.config import config as cfg

    monkeypatch.setattr(cfg, "llm_model", "qwen3-8b")
    payload_qwen = real_llm._build_payload("hola")
    assert payload_qwen["messages"][-1]["content"] == "hola\n/no_think"

    monkeypatch.setattr(cfg, "llm_model", "grok-4-1-fast-non-reasoning")
    payload_grok = real_llm._build_payload("hola")
    assert payload_grok["messages"][-1]["content"] == "hola"


# ========================================================================
# /profile endpoints
# ========================================================================


def test_get_profile_503_when_memory_disabled():
    """Default test config disables memory (conftest); endpoint must reject."""
    response = client.get("/profile")
    # 503 expected (memory_disabled). Accept 404 in case some setup hydrates it.
    assert response.status_code in (404, 503)


def test_ping_includes_has_profile():
    response = client.get("/ping")
    assert response.status_code == 200
    data = response.json()
    assert "has_profile" in data
    assert isinstance(data["has_profile"], bool)


def test_profile_endpoints_full_cycle(tmp_path, monkeypatch):
    """End-to-end: profile starts missing, becomes onboarded after POST,
    is_onboarded persists, DELETE clears it back to 404."""
    from samantha import api as api_mod
    from samantha.memory import Memory

    mem = Memory(persist_dir=str(tmp_path / "mem"), short_term_capacity=2)
    monkeypatch.setattr(api_mod, "_memory", mem)
    monkeypatch.setattr(api_mod.config, "memory_enabled", True)
    api_mod._memory_init_failed_at = None

    r = client.get("/profile")
    assert r.status_code == 404
    ping = client.get("/ping").json()
    assert ping["has_profile"] is False

    body = {
        "name": "Horelvis",
        "answers": [
            {"q": "¿Cómo te llamo?", "a": "Horelvis"},
            {"q": "¿Cómo estás hoy?", "a": "bien"},
            {"q": "¿Qué te gusta?", "a": "leer"},
            {"q": "¿Algo que te ilusione?", "a": "un viaje a Lisboa"},
            {"q": "¿Algo que te ronde?", "a": "trabajo"},
            {"q": "¿Directa o cuidadosa?", "a": "directa"},
        ],
    }
    r = client.post("/profile", json=body)
    assert r.status_code == 200, r.text
    saved = r.json()
    assert saved["name"] == "Horelvis"
    assert saved["onboarding_completed_at"] > 0
    assert len(saved["answers"]) == 6

    r = client.get("/profile")
    assert r.status_code == 200
    ping = client.get("/ping").json()
    assert ping["has_profile"] is True

    r = client.delete("/profile")
    assert r.status_code == 200
    r = client.get("/profile")
    assert r.status_code == 404


def test_profile_post_rejects_empty_body():
    r = client.post("/profile", json={})
    assert r.status_code == 422


def test_profile_post_rejects_short_answers():
    r = client.post(
        "/profile",
        json={
            "name": "Foo",
            "answers": [{"q": "q", "a": "a"}],
        },
    )
    assert r.status_code == 422


def test_profile_post_rejects_empty_first_answer(tmp_path, monkeypatch):
    """Spec: pairing must yield a real name — answers[0].a cannot be blank."""
    from samantha import api as api_mod
    from samantha.memory import Memory

    mem = Memory(persist_dir=str(tmp_path / "mem"), short_term_capacity=2)
    monkeypatch.setattr(api_mod, "_memory", mem)
    monkeypatch.setattr(api_mod.config, "memory_enabled", True)
    api_mod._memory_init_failed_at = None

    body = {
        "name": "tú",  # frontend fallback we must reject
        "answers": [
            {"q": "¿Cómo te llamo?", "a": None},
            {"q": "¿Cómo estás hoy?", "a": "bien"},
            {"q": "¿Qué te gusta?", "a": "leer"},
            {"q": "¿Algo que te ilusione?", "a": "viaje"},
            {"q": "¿Algo que te ronde?", "a": "trabajo"},
            {"q": "¿Directa o cuidadosa?", "a": "directa"},
        ],
    }
    r = client.post("/profile", json=body)
    assert r.status_code == 422
    assert "name_answer_required" in r.text


def test_profile_post_rejects_re_pairing(tmp_path, monkeypatch):
    """Spec: once paired, the device is bound. Re-pairing returns 409."""
    from samantha import api as api_mod
    from samantha.memory import Memory

    mem = Memory(persist_dir=str(tmp_path / "mem"), short_term_capacity=2)
    monkeypatch.setattr(api_mod, "_memory", mem)
    monkeypatch.setattr(api_mod.config, "memory_enabled", True)
    api_mod._memory_init_failed_at = None

    body = {
        "name": "Alice",
        "answers": [
            {"q": "¿Cómo te llamo?", "a": "Alice"},
            {"q": "¿Cómo estás hoy?", "a": "bien"},
            {"q": "¿Qué te gusta?", "a": "leer"},
            {"q": "¿Algo que te ilusione?", "a": "viaje"},
            {"q": "¿Algo que te ronde?", "a": "trabajo"},
            {"q": "¿Directa o cuidadosa?", "a": "directa"},
        ],
    }
    r1 = client.post("/profile", json=body)
    assert r1.status_code == 200

    r2 = client.post("/profile", json={**body, "name": "Bob"})
    assert r2.status_code == 409
    assert "already_paired" in r2.text

    # DELETE clears the pairing → POST works again (admin-only escape).
    client.delete("/profile")
    r3 = client.post("/profile", json={**body, "name": "Bob"})
    assert r3.status_code == 200


def test_hermes_provider_config_loading(monkeypatch):
    """Verify that SAMANTHA_LLM_PROVIDER loads correctly and sets Config.llm_provider."""
    from samantha.config import Config

    monkeypatch.setenv("SAMANTHA_LLM_PROVIDER", "hermes")
    cfg = Config.from_env()
    assert cfg.llm_provider == "hermes"


def test_real_llm_build_payload_hermes_format():
    """Verify that when llm_provider == 'hermes', _build_payload constructs a clean messages format."""
    from samantha import real_llm
    from samantha.config import config as cfg
    from samantha.memory import MemoryChunk

    # Save original provider to restore later
    orig_provider = cfg.llm_provider
    cfg.llm_provider = "hermes"

    try:
        short_term = [
            MemoryChunk(id="s1", role="user", text="hola", timestamp=1778002000, user_id="primary"),
            MemoryChunk(
                id="s2",
                role="samantha",
                text="hola, qué tal?",
                timestamp=1778002005,
                user_id="primary",
            ),
            MemoryChunk(
                id="s3", role="user", text="bien, y tú?", timestamp=1778002010, user_id="primary"
            ),
        ]

        payload = real_llm._build_payload(
            message="bien, y tú?",
            facts=[{"text": "Fact 1"}],
            recall=[
                MemoryChunk(
                    id="r1", role="user", text="recall", timestamp=1778002020, user_id="primary"
                )
            ],
            short_term=short_term,
        )

        messages = payload["messages"]
        # System prompt should include SYSTEM_PROMPT plus injected facts/recall
        assert messages[0]["role"] == "system"
        assert messages[0]["content"].startswith(real_llm.SYSTEM_PROMPT)
        assert "# Lo que sabes de ella" in messages[0]["content"]
        assert "Fact 1" in messages[0]["content"]
        assert "# Lo que recuerdas" in messages[0]["content"]
        # Short-term turns go as messages, not embedded in the system prompt
        assert "# Conversación reciente" not in messages[0]["content"]

        # Short term conversation must be mapped to user/assistant turns
        assert messages[1]["role"] == "user"
        assert messages[1]["content"] == "hola"

        assert messages[2]["role"] == "assistant"
        assert messages[2]["content"] == "hola, qué tal?"

        assert messages[3]["role"] == "user"
        assert messages[3]["content"] == "bien, y tú?"

        # Make sure no double current message is appended if already present at the end
        assert len(messages) == 4
    finally:
        cfg.llm_provider = orig_provider


def test_real_llm_build_payload_hermes_no_qwen_no_think(monkeypatch):
    """Verify that when llm_provider == 'hermes', Qwen /no_think switch is NOT appended."""
    from samantha import real_llm
    from samantha.config import config as cfg

    orig_provider = cfg.llm_provider
    orig_model = cfg.llm_model
    cfg.llm_provider = "hermes"
    cfg.llm_model = "qwen3-8b"

    try:
        payload = real_llm._build_payload("hola")
        messages = payload["messages"]
        # Last message should just be "hola", without "/no_think"
        assert messages[-1]["content"] == "hola"
    finally:
        cfg.llm_provider = orig_provider
        cfg.llm_model = orig_model


def test_chat_does_not_duplicate_current_message(tmp_path, monkeypatch):
    """The current user message must NOT be in the short_term context
    passed to the LLM (it is appended as the user message separately).
    It MUST appear in short_term on the NEXT turn."""
    from samantha import api as api_mod
    from samantha.memory import Memory

    mem = Memory(persist_dir=str(tmp_path / "memory"))
    monkeypatch.setattr(api_mod, "_memory", mem)
    monkeypatch.setattr(api_mod, "_memory_init_failed_at", None)
    monkeypatch.setattr(api_mod.config, "memory_enabled", True)
    monkeypatch.setattr(api_mod.config, "mode", "real")

    captured = {}

    async def fake_generate_reply(
        message, *, facts=None, recall=None, short_term=None, user_id="primary"
    ):
        captured["short_term"] = short_term or []
        return "claro"

    monkeypatch.setattr("samantha.real_llm.generate_reply", fake_generate_reply)

    client = TestClient(api_mod.app)
    r = client.post("/chat", json={"message": "hola, ¿qué tal?"})
    assert r.status_code == 200
    texts = [c.text for c in captured["short_term"]]
    assert "hola, ¿qué tal?" not in texts  # current turn excluded

    r2 = client.post("/chat", json={"message": "segunda pregunta"})
    assert r2.status_code == 200
    texts2 = [c.text for c in captured["short_term"]]
    assert "hola, ¿qué tal?" in texts2  # previous turn present
    assert "claro" in texts2  # previous reply present
    assert "segunda pregunta" not in texts2  # current turn excluded


def test_real_llm_hermes_session_header_injected(monkeypatch):
    """Verify that X-Hermes-Session-Id header is injected with user_id when calling stream_reply in hermes mode."""
    import asyncio
    from samantha import real_llm
    from samantha.config import config as cfg
    import httpx

    orig_provider = cfg.llm_provider
    orig_url = cfg.llm_server_url
    cfg.llm_provider = "hermes"
    cfg.llm_server_url = "http://127.0.0.1:8642"

    class MockStreamContext:
        def __init__(self, method, url, **kwargs):
            self.headers = kwargs.get("headers", {})
            self.request = httpx.Request(method, url)

        async def __aenter__(self):
            # Return self or a mock response
            class MockResponse:
                status_code = 200
                request = self.request

                async def aread(self):
                    return b""

                async def aiter_lines(self):
                    # Yield a simple DONE event to end stream immediately
                    yield "data: [DONE]"

            return MockResponse()

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    mock_headers = {}

    def mock_stream(self, method, url, **kwargs):
        nonlocal mock_headers
        mock_headers = kwargs.get("headers", {})
        return MockStreamContext(method, url, **kwargs)

    # Force recreating the client to pick up the patched stream method
    real_llm._client = None
    monkeypatch.setattr(httpx.AsyncClient, "stream", mock_stream)

    async def run():
        async for _ in real_llm.stream_reply("hello", user_id="user_custom_123"):
            pass

    try:
        asyncio.run(run())
        assert mock_headers.get("X-Hermes-Session-Id") == "user_custom_123"
    finally:
        cfg.llm_provider = orig_provider
        cfg.llm_server_url = orig_url
        real_llm._client = None


# ========================================================================
# exception handler — must RETURN JSON 500, not re-raise
# ========================================================================


def test_unhandled_exception_returns_json_500(monkeypatch):
    """The generic handler must RETURN a JSONResponse — raising inside
    an exception handler propagates to uvicorn as a bodyless 500."""
    from samantha import api as api_mod
    from samantha import tts as tts_mod

    monkeypatch.setattr(tts_mod, "is_available", lambda: True)

    def boom(text):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(tts_mod, "stream", boom)

    client = TestClient(api_mod.app, raise_server_exceptions=False)
    r = client.post("/speak", json={"text": "hola"})
    assert r.status_code == 500
    assert r.json() == {"detail": "internal_error"}


# ========================================================================
# /ws — hardening: malformed messages, binary frames, length cap
# ========================================================================


def test_ws_non_dict_json_returns_error():
    client = TestClient(app)
    with client.websocket_connect("/ws") as ws:
        ws.send_text("42")  # valid JSON, not an object
        msg = ws.receive_json()
        assert msg == {"type": "error", "error": "invalid_message"}


def test_ws_non_string_message_field_returns_error():
    client = TestClient(app)
    with client.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({"type": "chat", "message": 123}))
        msg = ws.receive_json()
        assert msg == {"type": "error", "error": "empty_message"}


def test_real_llm_build_payload_hermes_includes_facts_and_recall(monkeypatch):
    """facts and recall must be injected into the hermes system prompt."""
    from samantha import real_llm
    from samantha.config import config as cfg

    orig_provider = cfg.llm_provider
    cfg.llm_provider = "hermes"

    try:
        facts = [{"kind": "name", "value": "Hor", "text": "Se llama Hor"}]
        payload = real_llm._build_payload("hola", facts=facts)
        system = payload["messages"][0]["content"]
        assert "Se llama Hor" in system
    finally:
        cfg.llm_provider = orig_provider


def test_ws_oversized_message_returns_error():
    client = TestClient(app)
    with client.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({"type": "chat", "message": "x" * 9001}))
        msg = ws.receive_json()
        assert msg == {"type": "error", "error": "message_too_long"}


def test_ws_binary_frame_returns_error():
    client = TestClient(app)
    with client.websocket_connect("/ws") as ws:
        ws.send_bytes(b"\x00\x01")
        msg = ws.receive_json()
        assert msg == {"type": "error", "error": "binary_not_supported"}

        # The socket must survive the error: a normal turn still works.
        ws.send_json({"type": "chat", "message": "hola"})
        while True:
            msg = ws.receive_json()
            if msg["type"] == "token":
                continue
            elif msg["type"] == "done":
                break
            else:
                raise AssertionError(f"unexpected message after recovery: {msg}")


# ========================================================================
# /profile — blocking Memory work must run off the event loop
# ========================================================================


def test_profile_endpoints_run_memory_work_off_event_loop(monkeypatch):
    """The profile helpers do fastembed + Chroma work (seconds of CPU).
    Inside asyncio.to_thread there is no running loop, so
    get_running_loop() raising RuntimeError proves we're off-loop."""
    import asyncio as aio

    from samantha import api as api_mod

    violations: list[str] = []

    def _record_if_on_loop(label: str) -> None:
        try:
            aio.get_running_loop()
            violations.append(label)
        except RuntimeError:
            pass  # worker thread — correct

    class FakeMem:
        pass

    monkeypatch.setattr(api_mod, "_memory", FakeMem())
    monkeypatch.setattr(api_mod.config, "memory_enabled", True)

    onboarded = {"value": False}
    profile = {"name": "Ana", "onboarding_completed_at": 123, "answers": []}

    def fake_is_onboarded(mem):
        _record_if_on_loop("is_onboarded")
        return onboarded["value"]

    def fake_get_profile(mem):
        _record_if_on_loop("get_profile")
        return profile if onboarded["value"] else None

    def fake_complete_onboarding(mem, name, answers):
        _record_if_on_loop("complete_onboarding")
        onboarded["value"] = True
        return {**profile, "name": name, "answers": answers}

    def fake_delete_profile(mem):
        _record_if_on_loop("delete_profile")
        onboarded["value"] = False
        return True

    monkeypatch.setattr(api_mod, "_is_onboarded", fake_is_onboarded)
    monkeypatch.setattr(api_mod, "_get_profile", fake_get_profile)
    monkeypatch.setattr(api_mod, "_complete_onboarding", fake_complete_onboarding)
    monkeypatch.setattr(api_mod, "_delete_profile", fake_delete_profile)

    body = {
        "name": "Ana",
        "answers": [
            {"q": "¿Cómo te llamo?", "a": "Ana"},
            {"q": "¿Cómo estás hoy?", "a": "bien"},
            {"q": "¿Qué te gusta?", "a": "leer"},
            {"q": "¿Algo que te ilusione?", "a": "viajar"},
            {"q": "¿Algo que te ronde?", "a": "trabajo"},
            {"q": "¿Directa o cuidadosa?", "a": "directa"},
        ],
    }
    assert client.post("/profile", json=body).status_code == 200
    assert client.get("/profile").status_code == 200
    assert client.delete("/profile").status_code == 200
    assert violations == [], f"ran on the event loop: {violations}"


# ========================================================================
# lifespan — shutdown must release long-lived resources
# ========================================================================


def test_lifespan_closes_llm_client():
    """real_llm.aclose() exists but was never wired to the app
    lifecycle — the shared httpx client must be released on shutdown."""
    from samantha import api as api_mod
    from samantha import real_llm

    with TestClient(api_mod.app):
        real_llm._get_client()
        assert real_llm._client is not None
    assert real_llm._client is None


def test_lifespan_closes_memory():
    """Shutdown closes the memory store (SQLite ring connection) and
    drops the singleton so a restart re-initializes cleanly."""
    from samantha import api as api_mod

    closed = {"value": False}

    class FakeMem:
        def close(self):
            closed["value"] = True

    with TestClient(api_mod.app):
        api_mod._memory = FakeMem()
    assert closed["value"] is True
    assert api_mod._memory is None


def test_memory_init_failure_retries_after_backoff(monkeypatch):
    """A failed init (e.g. external volume not yet mounted at boot)
    must not disable memory forever — retry after the backoff window."""
    import samantha.memory as memory_mod
    from samantha import api as api_mod

    monkeypatch.setattr(api_mod, "_memory", None)
    monkeypatch.setattr(api_mod, "_memory_init_failed_at", None)
    monkeypatch.setattr(api_mod.config, "memory_enabled", True)

    calls = {"n": 0}

    class FlakyMemory:
        def __init__(self, persist_dir):
            calls["n"] += 1
            if calls["n"] == 1:
                raise OSError("volume not mounted")

        def close(self):
            pass

    monkeypatch.setattr(memory_mod, "Memory", FlakyMemory)

    # First call fails and latches the failure timestamp.
    assert api_mod.get_memory() is None
    # Within the backoff window: no new attempt.
    assert api_mod.get_memory() is None
    assert calls["n"] == 1
    # Simulate the window elapsing.
    monkeypatch.setattr(
        api_mod,
        "_memory_init_failed_at",
        api_mod._memory_init_failed_at - api_mod.MEMORY_INIT_RETRY_S - 1,
    )
    assert api_mod.get_memory() is not None
    assert calls["n"] == 2
