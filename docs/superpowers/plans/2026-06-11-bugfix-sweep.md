# Bugfix Sweep + Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the bugs found in the 2026-06-11 full-project review, ordered so the daily-conversation path gets fixed first, then backend robustness, then frontend robustness, then deploy/TTS-server issues.

**Architecture:** No architectural changes — every task is a targeted fix inside the existing FastAPI backend (`backend/samantha/`), the React frontend (`frontend/src/`), the TTS server overlays (`tts-server/`), or the systemd units. Backend fixes follow TDD against `backend/tests/`. Frontend has no test framework by project convention (CLAUDE.md §6) — verification is `pnpm typecheck` + `pnpm build` + a manual smoke checklist at the end of each frontend phase.

**Tech Stack:** Python 3.12 / FastAPI / pytest / httpx; React 18 / TypeScript / Vite / pnpm; react-speech-recognition 4.x; systemd user units.

**Conventions that apply to every task:**
- Backend: run tests from `backend/` with `pytest tests/ -v`; format with `ruff format . && ruff check .` before committing.
- Frontend: run `pnpm typecheck` and `pnpm build` from `frontend/` before committing. Never `npm install` — pnpm only.
- Commit messages in English. User-facing strings in Spanish, in Samantha's voice (see `docs/personality.md`).
- Working dir is the repo root: `/Volumes/Macintosh SSD - Daten/Users/horelvis/git/os1-samantha`.

---

## Fase 1 — Conversation core (what hurts daily)

### Task 1: Backend — stop sending the current user message to the LLM twice

**Bug:** `api.py` calls `mem.remember("user", ...)` *before* reading the short-term ring, so the current message lands in the ring and `_build_payload` renders it inside the system prompt (`# Conversación reciente`, last line `ella: <message>`) AND appends it as the `user` message. The hermes branch dedupes this explicitly; the openai branch doesn't.

**Fix:** collect context first, persist after. The recall path is unaffected (the message isn't in the store yet, so it can't come back as a recall hit).

**Files:**
- Modify: `backend/samantha/api.py:311-315` (in `chat`) and `backend/samantha/api.py:461-465` (in `_ws_stream_chat`)
- Test: `backend/tests/test_api.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_api.py` (reuse the existing import style at the top of the file — `from samantha import api as api_mod`, `from samantha.memory import Memory`, `from fastapi.testclient import TestClient` are already imported or trivially available):

```python
def test_chat_does_not_duplicate_current_message(tmp_path, monkeypatch):
    """The current user message must NOT be in the short_term context
    passed to the LLM (it is appended as the user message separately).
    It MUST appear in short_term on the NEXT turn."""
    from samantha import api as api_mod
    from samantha.memory import Memory

    mem = Memory(persist_dir=str(tmp_path / "memory"))
    monkeypatch.setattr(api_mod, "_memory", mem)
    monkeypatch.setattr(api_mod, "_memory_init_failed", False)
    monkeypatch.setattr(api_mod.config, "memory_enabled", True)
    monkeypatch.setattr(api_mod.config, "mode", "real")

    captured = {}

    async def fake_generate_reply(message, *, facts=None, recall=None,
                                  short_term=None, user_id="primary"):
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
    assert "hola, ¿qué tal?" in texts2      # previous turn present
    assert "claro" in texts2                 # previous reply present
    assert "segunda pregunta" not in texts2  # current turn excluded
```

Note: `api.py` imports `generate_reply` *inside* the handler (`from .real_llm import generate_reply as real_generate_reply`), so patching the module attribute on `samantha.real_llm` is sufficient.

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && pytest tests/test_api.py::test_chat_does_not_duplicate_current_message -v`
Expected: FAIL on `assert "hola, ¿qué tal?" not in texts` (the message IS currently in short_term).

- [ ] **Step 3: Implement the fix in both handlers**

In `backend/samantha/api.py`, `chat()` — replace:

```python
    if mem is not None:
        mem.remember("user", req.message, user_id=req.user_id)
        facts = _collect_facts(mem, user_id=req.user_id)
        recall = mem.recall(req.message, k=config.memory_top_k, user_id=req.user_id)
        short = mem.short_term(user_id=req.user_id)
```

with:

```python
    if mem is not None:
        # Context first, persist after: the ring must NOT contain the
        # current message, because _build_payload appends it as the
        # user message — otherwise the LLM sees it twice.
        facts = _collect_facts(mem, user_id=req.user_id)
        recall = mem.recall(req.message, k=config.memory_top_k, user_id=req.user_id)
        short = mem.short_term(user_id=req.user_id)
        mem.remember("user", req.message, user_id=req.user_id)
```

And in `_ws_stream_chat()` — replace:

```python
    if mem is not None:
        mem.remember("user", message, user_id=user_id)
        facts = _collect_facts(mem, user_id=user_id)
        recall = mem.recall(message, k=config.memory_top_k, user_id=user_id)
        short = mem.short_term(user_id=user_id)
```

with:

```python
    if mem is not None:
        # Same ordering rationale as /chat: context first, persist after.
        facts = _collect_facts(mem, user_id=user_id)
        recall = mem.recall(message, k=config.memory_top_k, user_id=user_id)
        short = mem.short_term(user_id=user_id)
        mem.remember("user", message, user_id=user_id)
```

- [ ] **Step 4: Run the new test + the full suite**

Run: `cd backend && pytest tests/ -v`
Expected: new test PASSES. If any existing test asserted the old ordering (current message present in short_term), update that test's expectation — the new ordering is the spec.

- [ ] **Step 5: Format and commit**

```bash
cd backend && ruff format . && ruff check .
git add backend/samantha/api.py backend/tests/test_api.py
git commit -m "fix(llm): stop duplicating current user message in LLM context"
```

---

### Task 2: Frontend — actually mute the mic during Samantha's turn

**Bug:** `ConversationScreen.tsx:241-245` calls `resetTranscript()` *before* `SpeechRecognition.stopListening()`. In react-speech-recognition 4.x, `resetTranscript()` → `disconnect("RESET")` → sets `pauseAfterDisconnect = false` and aborts; the abort flips `listening` to false synchronously, so the following `stopListening()` no-ops (its branch is guarded by `this.listening`). When the recognizer's async `onend` fires with `pauseAfterDisconnect === false` and `continuous === true`, the manager **restarts listening immediately**. Net effect: the mic listens to Samantha's own TTS for her whole turn.

**Fix:** abort FIRST (while `listening` is still true, so `pauseAfterDisconnect = true` sticks and `onend` does NOT restart), then reset the transcript (the hook-level reset clears local transcript state regardless of manager state).

**Files:**
- Modify: `frontend/src/screens/ConversationScreen.tsx:235-261` (debounce-commit effect)

- [ ] **Step 1: Verify the library internals the fix depends on**

Run:
```bash
grep -n "pauseAfterDisconnect\|case 'RESET'\|case 'ABORT'\|case 'STOP'\|abortListening\|this.listening = false" frontend/node_modules/react-speech-recognition/lib/RecognitionManager.js
```
Confirm: (a) `disconnect('RESET')` sets `pauseAfterDisconnect = false`; (b) `disconnect('ABORT')` sets `pauseAfterDisconnect = true`; (c) the disconnect switch is guarded by `this.listening`; (d) `abortListening` exists on the default export of `react-speech-recognition`. If any of these differ, STOP and re-derive the ordering before editing (the fix's whole premise is this state machine).

- [ ] **Step 2: Apply the fix**

In `frontend/src/screens/ConversationScreen.tsx`, inside the debounce effect, replace:

```ts
    const handle = setTimeout(() => {
      const text = finalTranscript.trim();
      console.info("[conv] debounce fired, committing:", JSON.stringify(text));
      resetTranscript();
      if (!text) return;
      // Mute the mic during chat + TTS so Samantha's voice doesn't
      // get re-recognized as user speech (the echo-loop trap).
      SpeechRecognition.stopListening();
```

with:

```ts
    const handle = setTimeout(() => {
      const text = finalTranscript.trim();
      // Abort BEFORE resetting: resetTranscript() aborts with
      // pauseAfterDisconnect=false, and in continuous mode the manager
      // auto-restarts on `onend` — the mic would stay open during
      // Samantha's TTS (the echo-loop trap). abortListening() while
      // still listening sets pauseAfterDisconnect=true, so the
      // recognizer stays down until we explicitly resume.
      if (text) void SpeechRecognition.abortListening();
      resetTranscript();
      if (!text) return;
```

(The old `SpeechRecognition.stopListening();` line below the comment is removed — the abort above replaces it.)

- [ ] **Step 3: Typecheck and build**

Run: `cd frontend && pnpm typecheck && pnpm build`
Expected: both succeed with no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/screens/ConversationScreen.tsx
git commit -m "fix(mic): abort recognition before transcript reset so mic stays muted during TTS"
```

---

### Task 3: Frontend — leaving the conversation aborts TTS and never reopens the mic

**Bug:** unmount cleanup (`ConversationScreen.tsx:131-134`) only calls `stopListening()`. Navigating to Ambient mid-turn (button or 5-min idle) leaves TTS playing, and when the in-flight `sendMessage` resolves, its `.then` restarts the recognizer because `activeRef.current` was never cleared.

**Files:**
- Modify: `frontend/src/screens/ConversationScreen.tsx:131-134`

- [ ] **Step 1: Apply the fix**

Replace:

```ts
  // Stop the singleton listener if we unmount mid-conversation.
  useEffect(() => {
    return () => { SpeechRecognition.stopListening(); };
  }, []);
```

with:

```ts
  // Unmounting mid-conversation must tear the whole turn down: clear
  // activeRef FIRST so the in-flight sendMessage .then can't restart
  // the (module-singleton) recognizer on another screen, silence any
  // playing TTS, and abort recognition (abort, not stop, so a
  // continuous session can't auto-restart on `onend`).
  useEffect(() => {
    return () => {
      activeRef.current = false;
      speakAbortRef.current?.abort();
      void SpeechRecognition.abortListening();
    };
  }, []);
```

- [ ] **Step 2: Typecheck, build, commit**

```bash
cd frontend && pnpm typecheck && pnpm build
git add frontend/src/screens/ConversationScreen.tsx
git commit -m "fix(conversation): abort TTS and recognizer teardown on unmount"
```

---

### Task 4: Frontend — barge-in reopens the mic immediately and keeps the interruption transcript

**Bug:** when the VAD fires, only the TTS is aborted. Recognition resumes in `sendMessage`'s `.then`, hundreds of ms later, so the words that triggered the interruption are lost; then the busy-flip wipe (`if (!busy) resetTranscript()`) deletes anything captured in between.

**Files:**
- Modify: `frontend/src/screens/ConversationScreen.tsx:90-95` (barge-in callback), `:114-116` (busy-flip wipe)

- [ ] **Step 1: Add a barge-in marker ref and restart recognition in the callback**

Below the existing `const speakAbortRef = useRef<AbortController | null>(null);` add:

```ts
  // Set when the VAD interrupts Samantha; tells the busy-flip wipe to
  // KEEP the transcript (it's the user's interruption, not echo).
  const bargedInRef = useRef(false);
```

Replace the barge-in hook call:

```ts
  useBargeIn(isSpeaking && bargeInEnabled, () => {
    if (speakAbortRef.current) {
      console.info("[conv] barge-in detected, aborting TTS");
      speakAbortRef.current.abort();
    }
  });
```

with:

```ts
  useBargeIn(isSpeaking && bargeInEnabled, () => {
    if (speakAbortRef.current) {
      speakAbortRef.current.abort();
      bargedInRef.current = true;
      // Reopen the mic NOW — waiting for speak() to settle loses the
      // first words of the interruption. startListening on an
      // already-listening manager is a no-op, so the later resume in
      // sendMessage's .then is harmless.
      if (activeRef.current) {
        void SpeechRecognition.startListening({
          continuous: true,
          language: "es-ES",
        });
      }
    }
  });
```

- [ ] **Step 2: Make the busy-flip wipe spare the interruption**

Replace:

```ts
  useEffect(() => {
    if (!busy) resetTranscript();
  }, [busy, resetTranscript]);
```

with:

```ts
  useEffect(() => {
    if (busy) return;
    if (bargedInRef.current) {
      // The transcript accumulating right now is the user's barge-in
      // utterance — keep it so the debounce commits it as the next
      // message instead of wiping it as presumed echo.
      bargedInRef.current = false;
      return;
    }
    resetTranscript();
  }, [busy, resetTranscript]);
```

- [ ] **Step 3: Typecheck, build, commit**

```bash
cd frontend && pnpm typecheck && pnpm build
git add frontend/src/screens/ConversationScreen.tsx
git commit -m "fix(barge-in): restart recognition on interrupt and keep its transcript"
```

---

### Task 5: Frontend — failed chat turns leave no empty bubble and show honest errors

**Bug:** `sendMessage` appends an empty Samantha placeholder before the WS call; on failure it stays in the transcript (renders as an empty bubble, blanks the main caption because it becomes `lastSamantha`). Errors are rendered through `micErrorMessage`, so an LLM failure shows as `Mic: llm_error...`, and `ws_not_connected` promises a retry that doesn't exist.

**Files:**
- Modify: `frontend/src/core/store.ts` (add `removeMessage`), `frontend/src/screens/ConversationScreen.tsx` (catch block + new error mapper)

- [ ] **Step 1: Add `removeMessage` to the store**

In `frontend/src/core/store.ts`, add to the interface after `patchMessage`:

```ts
  removeMessage: (id: string) => void;
```

and to the store implementation after `patchMessage`:

```ts
  removeMessage: (id) =>
    set((state) => ({
      transcript: state.transcript.filter((m) => m.id !== id),
    })),
```

- [ ] **Step 2: Add a chat-error mapper and use it in the catch**

In `ConversationScreen.tsx`, below `micErrorMessage`, add:

```ts
// Errors from the chat turn (WS / LLM), as Samantha would say them —
// distinct from mic errors, which come from speech recognition.
function chatErrorMessage(code: string): string {
  if (code === "ws_not_connected")
    return "He perdido la conexión con mi cabeza. Dame un momento y repítemelo.";
  if (code.startsWith("llm_error"))
    return "Se me ha ido el hilo. ¿Me lo dices otra vez?";
  return "Algo se me ha cruzado. Inténtalo de nuevo.";
}
```

Destructure the new store action next to the others (line ~53):

```ts
  const removeMessage = useSamantha((s) => s.removeMessage);
```

Replace the catch block in `sendMessage`:

```ts
    } catch (e) {
      console.warn("chat failed", e);
      setMicError(micErrorMessage(e instanceof Error ? e.message : "unknown"));
    } finally {
```

with:

```ts
    } catch (e) {
      console.warn("chat failed", e);
      removeMessage(replyId);
      setMicError(chatErrorMessage(e instanceof Error ? e.message : "unknown"));
    } finally {
```

Also add `setMicError(null);` as the first line inside `sendMessage` (right after `bump();`) so a stale error doesn't outlive the next successful turn. Remove the now-unused `"ws_not_connected"` case from `micErrorMessage` (chat errors no longer route through it).

- [ ] **Step 3: Typecheck, build, commit**

```bash
cd frontend && pnpm typecheck && pnpm build
git add frontend/src/core/store.ts frontend/src/screens/ConversationScreen.tsx
git commit -m "fix(conversation): drop empty reply bubble on chat failure, honest error copy"
```

---

### Task 6: Fase 1 manual smoke test (kiosk behavior)

No automated harness for this by design. With the backend running (`SAMANTHA_MODE=real`) and `pnpm dev`:

- [ ] Speak a message → console shows `listening: false` for the whole busy+TTS window (Task 2).
- [ ] Interrupt Samantha mid-sentence by voice → TTS stops, your interruption appears as the next user message without repeating yourself (Task 4).
- [ ] Click `← ambient` while she speaks → audio stops immediately, mic stays closed on Ambient (Task 3).
- [ ] Stop the backend, send a text message → no empty bubble, Samantha-voiced error shown; restart backend, next turn clears the error (Task 5).
- [ ] Check the backend log for one turn: the prompt context (`short_term=N` debug line) no longer includes the current message (Task 1).

---

## Fase 2 — Backend robustness

### Task 7: Fix the global exception handler (returns, not raises)

**Files:**
- Modify: `backend/samantha/api.py:548-551`
- Test: `backend/tests/test_api.py`

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run it — expect FAIL** (the current handler re-raises; the response body is not the JSON above).

Run: `cd backend && pytest tests/test_api.py::test_unhandled_exception_returns_json_500 -v`

- [ ] **Step 3: Fix the handler**

In `backend/samantha/api.py`, add imports: `Request` to the `fastapi` import line, `JSONResponse` to the `fastapi.responses` import line. Replace:

```python
@app.exception_handler(Exception)
async def generic_exception_handler(request, exc):
    logger.exception(f"Unhandled exception on {request.url.path}")
    raise HTTPException(status_code=500, detail=str(exc))
```

with:

```python
@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception(f"Unhandled exception on {request.url.path}")
    # Deliberately generic: str(exc) can leak paths/keys to the client.
    # The full traceback is in the log.
    return JSONResponse(status_code=500, content={"detail": "internal_error"})
```

- [ ] **Step 4: Run the full suite, format, commit**

```bash
cd backend && pytest tests/ -v && ruff format . && ruff check .
git add backend/samantha/api.py backend/tests/test_api.py
git commit -m "fix(api): generic exception handler returns JSON 500 instead of re-raising"
```

---

### Task 8: Move memory work off the event loop + make the SQLite ring thread-safe

**Bug:** `Memory()` construction (fastembed ONNX load, first-run ~130 MB download) and every `remember/recall/short_term` call are synchronous CPU/IO executed directly in async handlers — they freeze `/ping`, the WS, and `/speak` streaming. Moving them to a thread requires the shared `sqlite3` connection in `ShortTermBuffer` (opened with `check_same_thread=False`, no lock) to be locked.

**Files:**
- Modify: `backend/samantha/short_term.py`, `backend/samantha/api.py`
- Test: `backend/tests/test_short_term.py`

- [ ] **Step 1: Write the failing thread-safety test**

Append to `backend/tests/test_short_term.py` (match the existing import of `ShortTermBuffer` at the top of that file):

```python
def test_concurrent_appends_from_threads(tmp_path):
    import threading

    buf = ShortTermBuffer(tmp_path / "state.db", capacity=50)
    errors: list[Exception] = []

    def worker(i: int) -> None:
        try:
            for j in range(25):
                buf.append("user", f"msg-{i}-{j}")
        except Exception as e:  # noqa: BLE001 — collecting for assertion
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    assert len(buf.list()) == 50  # capacity respected under concurrency
```

- [ ] **Step 2: Run it** — it may pass or fail intermittently (race). Run it a few times: `cd backend && pytest tests/test_short_term.py::test_concurrent_appends_from_threads -v -x --count=1`. Even if it passes, proceed — the lock is correctness, not test-appeasement.

- [ ] **Step 3: Add the lock to `ShortTermBuffer`**

In `backend/samantha/short_term.py`: add `import threading` to the imports. In `__init__`, after `self.capacity = capacity`, add:

```python
        # The connection is shared across threads (api.py calls us via
        # asyncio.to_thread); sqlite3 objects are not thread-safe even
        # with check_same_thread=False, so serialize all access.
        self._lock = threading.Lock()
```

Then wrap every connection use:
- `append_with_id`: change `with self._conn:` to `with self._lock, self._conn:`
- `list`: wrap the `cur = self._conn.execute(...)` + `fetchall` in `with self._lock:` (fetch inside the lock)
- `ids`: same, `with self._lock:` around execute + fetch
- `clear`: change `with self._conn:` to `with self._lock, self._conn:`
- `close`: wrap in `with self._lock:`

- [ ] **Step 4: Push memory work to a thread in `api.py`**

Add this helper above `_stream_tokens`:

```python
async def _gather_context(
    mem: "Memory", message: str, user_id: str
) -> "tuple[list[dict], list[MemoryChunk], list[MemoryChunk]]":
    """Collect facts + recall + short-term and persist the user turn,
    off the event loop (embedding + ChromaDB + SQLite are all sync and
    CPU-bound; running them inline stalls /ping and TTS streaming).

    Ordering matters: context FIRST, remember AFTER, so the ring never
    contains the current message (see Task-1 of the 2026-06-11 plan).
    """

    def _work() -> "tuple[list[dict], list[MemoryChunk], list[MemoryChunk]]":
        facts = _collect_facts(mem, user_id=user_id)
        recall = mem.recall(message, k=config.memory_top_k, user_id=user_id)
        short = mem.short_term(user_id=user_id)
        mem.remember("user", message, user_id=user_id)
        return facts, recall, short

    return await asyncio.to_thread(_work)
```

In `chat()` replace the whole `if mem is not None:` context block (as rewritten in Task 1) with:

```python
    if mem is not None:
        facts, recall, short = await _gather_context(mem, req.message, req.user_id)
```

and the reply persistence:

```python
    if mem is not None and reply:
        await asyncio.to_thread(mem.remember, "samantha", reply, user_id=req.user_id)
```

In `_ws_stream_chat()` make the same two substitutions (`message`/`user_id` variables; the reply persistence wraps `mem.remember("samantha", full_reply, user_id=user_id)`).

In `ping()`, `chat()`, `_ws_stream_chat()`, and the three `/profile` endpoints, replace `mem = get_memory()` with `mem = await asyncio.to_thread(get_memory)` — first call constructs `Memory` (model load / download) and must not run on the loop. Also in `ping()`, wrap the onboarding probe: `has_profile = bool(mem and await asyncio.to_thread(_is_onboarded, mem))`.

- [ ] **Step 5: Run the full suite, format, commit**

```bash
cd backend && pytest tests/ -v && ruff format . && ruff check .
git add backend/samantha/api.py backend/samantha/short_term.py backend/tests/test_short_term.py
git commit -m "fix(api): run memory init and per-turn memory work off the event loop"
```

---

### Task 9: Harden the WebSocket loop (malformed messages, binary frames, disconnect mid-stream, length cap)

**Files:**
- Modify: `backend/samantha/api.py` (`websocket_endpoint`, `_ws_stream_chat`)
- Test: `backend/tests/test_api.py`

- [ ] **Step 1: Write the failing tests**

```python
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
```

(`app` and `json` are already imported in `test_api.py`; adjust to the file's local conventions if it uses `api_mod.app`.)

- [ ] **Step 2: Run them — all four FAIL** (each currently crashes the WS with an uncaught exception instead of replying).

Run: `cd backend && pytest tests/test_api.py -k "test_ws_non_dict or test_ws_non_string or test_ws_oversized or test_ws_binary" -v`

- [ ] **Step 3: Rewrite the WS loop**

Add near the top of `api.py` (next to other module constants):

```python
# Mirror ChatRequest's max_length — the WS path must not accept
# unbounded input the HTTP path rejects.
MAX_WS_MESSAGE_CHARS = 8000
```

Replace the body of `websocket_endpoint` (keep the docstring):

```python
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
                await websocket.send_text(
                    json.dumps({"type": "error", "error": "invalid_message"})
                )
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
    except RuntimeError:
        # send on an already-closed socket (client vanished mid-reply)
        logger.info("ws: connection closed mid-send")
```

In `_ws_stream_chat`, replace the streaming try/except:

```python
    try:
        async for token in _stream_tokens(message, facts=facts, recall=recall, short_term=short, user_id=user_id):
            reply_chunks.append(token)
            await websocket.send_text(json.dumps({"type": "token", "token": token}))
    except Exception as e:
        logger.exception("Error in websocket chat stream")
        await websocket.send_text(json.dumps({"type": "error", "error": f"llm_error: {str(e)}"}))
        return
```

with:

```python
    try:
        async for token in _stream_tokens(
            message, facts=facts, recall=recall, short_term=short, user_id=user_id
        ):
            reply_chunks.append(token)
            await websocket.send_text(json.dumps({"type": "token", "token": token}))
    except (WebSocketDisconnect, RuntimeError):
        # Client went away mid-reply — not an LLM error; don't try to
        # talk to a dead socket. The endpoint loop handles the close.
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
```

- [ ] **Step 4: Run the full suite, format, commit**

```bash
cd backend && pytest tests/ -v && ruff format . && ruff check .
git add backend/samantha/api.py backend/tests/test_api.py
git commit -m "fix(ws): survive malformed messages, binary frames, and mid-stream disconnects"
```

---

### Task 10: Reject unknown `SAMANTHA_MODE` values loudly

**Bug:** anything other than the exact string `"real"` silently selects mock mode (operator explicitly never wants mock by accident).

**Files:**
- Modify: `backend/samantha/config.py`
- Test: `backend/tests/test_api.py` (or a new `backend/tests/test_config.py` if one doesn't exist — check first)

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from samantha.config import Config


def test_config_mode_is_normalized():
    assert Config(mode="REAL").mode == "real"
    assert Config(mode=" Mock ").mode == "mock"


def test_config_rejects_unknown_mode():
    with pytest.raises(ValueError, match="SAMANTHA_MODE"):
        Config(mode="reall")
```

- [ ] **Step 2: Run — FAIL** (`Config(mode="REAL").mode == "REAL"` today).

- [ ] **Step 3: Add `__post_init__` to `Config`**

In `backend/samantha/config.py`, inside the dataclass (after the field declarations, before `from_env`):

```python
    def __post_init__(self) -> None:
        normalized = self.mode.strip().lower()
        if normalized not in ("mock", "real"):
            raise ValueError(
                f"SAMANTHA_MODE must be 'mock' or 'real', got {self.mode!r} "
                "— refusing to start with an ambiguous mode (a typo here "
                "would silently serve canned mock replies)."
            )
        self.mode = normalized
```

- [ ] **Step 4: Run the full suite, format, commit**

```bash
cd backend && pytest tests/ -v && ruff format . && ruff check .
git add backend/samantha/config.py backend/tests/
git commit -m "fix(config): validate and normalize SAMANTHA_MODE at startup"
```

---

### Task 11: Bound TTS reads (no more infinite hang on a wedged GPU server)

**Bug:** both streaming backends use `httpx.Timeout(..., read=None, ...)` so the configured 60 s knobs never bound synthesis reads; a wedged CosyVoice/XTTS hangs `/speak` forever.

**Files:**
- Modify: `backend/samantha/tts.py:251-256` (XTTS) and `backend/samantha/tts.py:334-339` (CosyVoice)

- [ ] **Step 1: Apply the change (no new test — `test_tts.py` covers the call path; this is a timeout-value change whose failure mode can't be unit-tested without a wedge simulator)**

XTTS block — replace:

```python
    timeout = httpx.Timeout(
        connect=config.tts_xtts_timeout_s,
        read=None,
        write=config.tts_xtts_timeout_s,
        pool=config.tts_xtts_timeout_s,
    )
```

with:

```python
    # `read` is httpx's per-read-operation (inter-chunk) timeout, not a
    # whole-body cap: a healthy stream that keeps emitting chunks never
    # trips it, while a wedged server (CUDA hang) fails loudly instead
    # of freezing /speak forever.
    timeout = httpx.Timeout(
        connect=config.tts_xtts_timeout_s,
        read=config.tts_xtts_timeout_s,
        write=config.tts_xtts_timeout_s,
        pool=config.tts_xtts_timeout_s,
    )
```

CosyVoice block — same substitution with `config.tts_cosyvoice_timeout_s` (and the same comment).

- [ ] **Step 2: Run the suite, format, commit**

```bash
cd backend && pytest tests/ -v && ruff format . && ruff check .
git add backend/samantha/tts.py
git commit -m "fix(tts): apply read timeout to synthesis streams (wedged server no longer hangs /speak)"
```

---

### Task 12: Hermes path gets facts + recall in its system prompt

**Bug:** in hermes mode `_build_payload` sends only `SYSTEM_PROMPT` + short-term history — the user's name, Big-Five facts, and semantic recall computed by `api.py` are silently discarded.

**Files:**
- Modify: `backend/samantha/real_llm.py:131-151`
- Test: `backend/tests/test_api.py`

- [ ] **Step 1: Write the failing test**

```python
def test_real_llm_build_payload_hermes_includes_facts_and_recall(monkeypatch):
    from samantha.config import config as cfg

    monkeypatch.setattr(cfg, "llm_provider", "hermes")
    facts = [{"kind": "name", "value": "Hor", "text": "Se llama Hor"}]
    payload = real_llm._build_payload("hola", facts=facts)
    system = payload["messages"][0]["content"]
    assert "Se llama Hor" in system
```

(Match the import style of the neighbouring hermes tests at `test_api.py:815+`.)

- [ ] **Step 2: Run — FAIL.**

- [ ] **Step 3: Implement**

In `real_llm.py`, replace the hermes branch of `_build_payload`:

```python
    if config.llm_provider == "hermes":
        messages = []
        messages.append({"role": "system", "content": SYSTEM_PROMPT})

        has_current_message = False
        if short_term:
            for c in short_term:
                role = "assistant" if c.role == "samantha" else "user"
                messages.append({"role": role, "content": c.text})
                if role == "user" and c.text.strip() == message.strip():
                    has_current_message = True

        if not has_current_message or (messages and messages[-1]["role"] != "user"):
            if not messages or messages[-1]["content"].strip() != message.strip() or messages[-1]["role"] != "user":
                messages.append({"role": "user", "content": message})

        return {
            "model": config.llm_model,
            "messages": messages,
            "stream": True,
        }
```

with:

```python
    if config.llm_provider == "hermes":
        # Hermes keeps its own session history server-side, but facts
        # and semantic recall live only in OUR memory — without them
        # the agent never learns the user's name. Short-term turns go
        # as real chat messages (hermes wants clean history), the rest
        # rides the system prompt like the openai path.
        system = SYSTEM_PROMPT
        if facts:
            system += _format_facts(facts)
        if recall:
            system += _format_recall(recall)

        messages: list[dict] = [{"role": "system", "content": system}]
        if short_term:
            for c in short_term:
                role = "assistant" if c.role == "samantha" else "user"
                messages.append({"role": role, "content": c.text})

        # The ring no longer contains the current message (api.py
        # persists AFTER collecting context), but guard anyway so a
        # direct caller passing it can't double-send.
        last = messages[-1]
        if last["role"] != "user" or last["content"].strip() != message.strip():
            messages.append({"role": "user", "content": message})

        return {
            "model": config.llm_model,
            "messages": messages,
            "stream": True,
        }
```

- [ ] **Step 4: Run the full suite** — the pre-existing hermes payload tests (`test_real_llm_build_payload_hermes_format` etc.) exercise the dedup guard; if one asserts the exact old append-condition behavior, update it to the simplified guard's semantics (same observable outcomes: current message appears exactly once, as the final user message).

```bash
cd backend && pytest tests/ -v && ruff format . && ruff check .
git add backend/samantha/real_llm.py backend/tests/test_api.py
git commit -m "fix(hermes): include facts and semantic recall in hermes system prompt"
```

---

## Fase 3 — Frontend robustness & quality

### Task 13: Keyboard shortcuts must not fire while typing

**Files:**
- Modify: `frontend/src/core/useKeys.ts:12-16`

- [ ] **Step 1: Apply**

Replace:

```ts
    const onKey = (e: KeyboardEvent) => {
      const handler = handlersRef.current[e.key];
      if (handler) handler(e);
    };
```

with:

```ts
    const onKey = (e: KeyboardEvent) => {
      // Typing "hasta" in the text input must not toggle history/text
      // panels — only Escape passes through from editable elements.
      const t = e.target;
      const isEditable =
        t instanceof HTMLInputElement ||
        t instanceof HTMLTextAreaElement ||
        (t instanceof HTMLElement && t.isContentEditable);
      if (isEditable && e.key !== "Escape") return;
      const handler = handlersRef.current[e.key];
      if (handler) handler(e);
    };
```

- [ ] **Step 2: Typecheck, build, commit**

```bash
cd frontend && pnpm typecheck && pnpm build
git add frontend/src/core/useKeys.ts
git commit -m "fix(keys): ignore global shortcuts while typing in editable elements"
```

---

### Task 14: One turn at a time (no concurrent chat() calls clobbering WS handlers)

**Bug:** `WSClient` keeps one handler per message type; a text submit while a voice turn is in flight overwrites the first turn's handlers — cross-contaminated replies and a `busy` flag that can stick `true` forever. Minimal correct fix for a single-user kiosk: never start a second turn (YAGNI on request-id routing).

**Files:**
- Modify: `frontend/src/screens/ConversationScreen.tsx` (`sendMessage`, busy ref management)

- [ ] **Step 1: Guard `sendMessage` and manage `busyRef` synchronously**

Replace the start of `sendMessage`:

```ts
  const sendMessage = async (msg: string) => {
    bump();
    const trimmed = msg.trim();
    if (!trimmed) return;
```

with:

```ts
  const sendMessage = async (msg: string) => {
    bump();
    const trimmed = msg.trim();
    if (!trimmed) return;
    // One turn at a time: WSClient keeps ONE handler per message type,
    // so a second concurrent chat() would steal the first turn's
    // token/done/error handlers. The ref (not state) makes the guard
    // race-free for same-tick double submits.
    if (busyRef.current) return;
    busyRef.current = true;
```

In the `finally` block add `busyRef.current = false;` before `setBusy(false);`. Then delete the now-redundant syncing effect:

```ts
  useEffect(() => { busyRef.current = busy; }, [busy]);
```

(`setMicError(null)` from Task 5 stays as the first statement after the guard passes, not before it.)

- [ ] **Step 2: Typecheck, build, commit**

```bash
cd frontend && pnpm typecheck && pnpm build
git add frontend/src/screens/ConversationScreen.tsx
git commit -m "fix(conversation): serialize chat turns — concurrent sends clobbered WS handlers"
```

---

### Task 15: Surface microphone-permission failures

**Bug:** the library only reports permission problems via `isMicrophoneAvailable`, which nobody reads; on denial the mic button pulses and nothing happens, silently. The `try/catch` around `startListening` can't catch anything (async function, sync prefix doesn't throw).

**Files:**
- Modify: `frontend/src/screens/ConversationScreen.tsx`

- [ ] **Step 1: Apply**

Destructure the flag (add to the existing `useSpeechRecognition()` destructuring):

```ts
  const {
    interimTranscript,
    finalTranscript,
    listening,
    resetTranscript,
    browserSupportsSpeechRecognition,
    isMicrophoneAvailable,
  } = useSpeechRecognition();
```

Add an effect (next to the other effects):

```ts
  // react-speech-recognition reports permission problems only through
  // this flag — startListening() swallows its own failures.
  useEffect(() => {
    if (isMicrophoneAvailable) return;
    setMicError(micErrorMessage("not-allowed"));
    setConversationActive(false);
  }, [isMicrophoneAvailable]);
```

Remove the dead `try/catch` in `toggleConversation` (keep the body of the `try`):

```ts
    } else {
      setConversationActive(true);
      void SpeechRecognition.startListening({
        continuous: true,
        language: "es-ES",
      });
    }
```

- [ ] **Step 2: Typecheck, build, commit**

```bash
cd frontend && pnpm typecheck && pnpm build
git add frontend/src/screens/ConversationScreen.tsx
git commit -m "fix(mic): surface microphone permission errors to the user"
```

---

### Task 16: Don't create the VAD (mic stream + CDN downloads) when barge-in is disabled

**Files:**
- Modify: `frontend/src/core/useBargeIn.ts`, `frontend/src/screens/ConversationScreen.tsx` (call site)

- [ ] **Step 1: Add an `enabled` parameter to the hook**

In `useBargeIn.ts`, change the signature:

```ts
export function useBargeIn(
  active: boolean,
  onSpeechStart: () => void,
  enabled: boolean = true,
): void {
```

and gate the init effect (first lines of the existing `useEffect`):

```ts
  useEffect(() => {
    // Kill switch (`sam.bargeIn = 0`): skip entirely — no extra
    // getUserMedia stream, no ONNX/WASM downloads from jsDelivr.
    if (!enabled) return;
    let cancelled = false;
```

and change its dependency array from `[]` to `[enabled]`.

- [ ] **Step 2: Pass the flag at the call site**

In `ConversationScreen.tsx`, change the hook call (as written in Task 4) to pass the third argument:

```ts
  useBargeIn(
    isSpeaking && bargeInEnabled,
    () => {
      if (speakAbortRef.current) {
        speakAbortRef.current.abort();
        bargedInRef.current = true;
        if (activeRef.current) {
          void SpeechRecognition.startListening({
            continuous: true,
            language: "es-ES",
          });
        }
      }
    },
    bargeInEnabled,
  );
```

- [ ] **Step 3: Typecheck, build, commit**

```bash
cd frontend && pnpm typecheck && pnpm build
git add frontend/src/core/useBargeIn.ts frontend/src/screens/ConversationScreen.tsx
git commit -m "fix(barge-in): kill switch skips VAD init (no mic stream, no CDN fetches)"
```

---

### Task 17: Dispose Three.js resources in the OS1 loader

**Files:**
- Modify: `frontend/src/components/OS1Loader.tsx:172-181` (effect cleanup)

- [ ] **Step 1: Read the current cleanup** (`frontend/src/components/OS1Loader.tsx` lines ~160-203) to locate the `return () => { ... renderer.dispose(); ... }` block and the `scene` variable name in scope.

- [ ] **Step 2: Add scene traversal before `renderer.dispose()`**

Insert into the cleanup, before `renderer.dispose()`:

```ts
      // TubeGeometry + 11 planes + 12 materials leak GPU memory per
      // mount (StrictMode double-mounts; every boot remount stacks).
      scene.traverse((obj) => {
        const mesh = obj as THREE.Mesh;
        if (mesh.isMesh) {
          mesh.geometry.dispose();
          const mat = mesh.material;
          if (Array.isArray(mat)) mat.forEach((m) => m.dispose());
          else mat.dispose();
        }
      });
```

(Adapt the cast style to the file's existing THREE typing conventions — if it imports `* as THREE`, `obj instanceof THREE.Mesh` is cleaner than the cast.)

- [ ] **Step 3: Typecheck, build, commit**

```bash
cd frontend && pnpm typecheck && pnpm build
git add frontend/src/components/OS1Loader.tsx
git commit -m "fix(loader): dispose Three.js geometries and materials on unmount"
```

---

### Task 18: Frontend noise cleanup (debug logs, dep placement, emoji residue)

**Files:**
- Modify: `frontend/src/screens/ConversationScreen.tsx`, `frontend/package.json`, `frontend/src/core/sanitize.ts`

- [ ] **Step 1: Remove shipped debug logging in `ConversationScreen.tsx`**
  - Delete the whole interim-transcript logging effect (the `useEffect` whose body is the `console.info("[conv] listening:", ...)` call, currently lines ~224-229).
  - Delete `console.info` calls inside the debounce commit and `toggleConversation` (`"[conv] debounce fired..."`, `"[conv] toggle clicked..."`, `"[conv] start listening..."`, `"[conv] stop listening"`, `"[conv] sendMessage done..."`). Keep every `console.warn`/`console.error`.

- [ ] **Step 2: Move `@types/react-speech-recognition` from `dependencies` to `devDependencies`** in `frontend/package.json`, then run `cd frontend && pnpm install` to update `pnpm-lock.yaml`.

- [ ] **Step 3: Fix ZWJ/keycap residue in `sanitize.ts`** — read `frontend/src/core/sanitize.ts` (23 lines) and add `‍` (zero-width joiner) and `⃣` (combining keycap) to the strip pattern's character class, with a comment:

```ts
// ‍: ZWJ left behind by stripped emoji sequences (👩‍🚀);
// ⃣: combining keycap left behind by 1️⃣-style sequences.
```

- [ ] **Step 4: Typecheck, build, commit**

```bash
cd frontend && pnpm typecheck && pnpm build
git add frontend/src/screens/ConversationScreen.tsx frontend/package.json frontend/pnpm-lock.yaml frontend/src/core/sanitize.ts
git commit -m "chore(frontend): strip debug logging, fix emoji residue, dep placement"
```

> NOT in scope (requires explicit user confirmation per CLAUDE.md §8 — public API removal): deleting the deprecated `listen`/`transcription` WS protocol (`wsClient.listen()`, `api.py:_ws_handle_listen`, `PingResponse` type, `/chat`+`/transcribe` Vite proxies, store `name`/`resetTranscript`). Propose separately.

---

## Fase 4 — Deploy & TTS server

### Task 19: Create the missing systemd units (backend + kiosk UI)

**Bug:** CLAUDE.md §3/§5 reference `samantha-backend.service` and `samantha-ui.service`; neither exists in `systemd/` — the documented deploy fails.

**Files:**
- Read first: `systemd/samantha-llamacpp.service`, `systemd/samantha-hermes.service` (mirror their path/venv/env conventions exactly — they encode where the repo and venv live on the kiosk box)
- Create: `systemd/samantha-backend.service`, `systemd/samantha-ui.service`

- [ ] **Step 1: Read both existing units** and note: venv path style, `WorkingDirectory`, `%h` usage, `[Install] WantedBy`.

- [ ] **Step 2: Create `systemd/samantha-backend.service`** (adjust paths to match Step 1's conventions):

```ini
# Samantha FastAPI backend (serves UI + API on :7777).
# Override env (e.g. SAMANTHA_LLM_API_KEY) via:
#   systemctl --user edit samantha-backend
[Unit]
Description=Samantha backend (FastAPI on :7777)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
Environment=SAMANTHA_MODE=real
WorkingDirectory=%h/git/os1-samantha/backend
ExecStart=%h/git/os1-samantha/backend/.venv/bin/python -m samantha.api
Restart=on-failure
RestartSec=3

[Install]
WantedBy=default.target
```

- [ ] **Step 3: Create `systemd/samantha-ui.service`**:

```ini
# Chromium kiosk pointed at the backend. Waits for /ping so the user
# never sees a connection-refused page at boot.
[Unit]
Description=Samantha UI (Chromium kiosk)
After=samantha-backend.service
Wants=samantha-backend.service

[Service]
Type=simple
Environment=DISPLAY=:0
ExecStartPre=/bin/sh -c 'until curl -fsS http://127.0.0.1:7777/ping >/dev/null 2>&1; do sleep 1; done'
ExecStart=/usr/bin/chromium-browser \
  --kiosk \
  --noerrdialogs \
  --disable-infobars \
  --no-first-run \
  --use-fake-ui-for-media-stream \
  --app=http://localhost:7777/
Restart=on-failure
RestartSec=3

[Install]
WantedBy=default.target
```

- [ ] **Step 4: Validate syntax**

Run: `systemd-analyze verify systemd/samantha-backend.service systemd/samantha-ui.service 2>&1 | grep -v "Unknown lvalue" || true`
(macOS has no systemd — if `systemd-analyze` is unavailable locally, skip and note in the commit that validation happens on the kiosk box.)

- [ ] **Step 5: Commit**

```bash
git add systemd/samantha-backend.service systemd/samantha-ui.service
git commit -m "feat(deploy): add missing samantha-backend and samantha-ui systemd units"
```

---

### Task 20: Get the hermes API key out of git

**Bug:** `systemd/samantha-hermes.service:24` commits a live key (`Environment=API_SERVER_KEY=<redacted — set via systemctl --user edit samantha-hermes>`). It's localhost-only, but the unit's own header says overrides belong in drop-ins. The committed value is burned (git history) — it must be rotated, not just moved.

**Files:**
- Modify: `systemd/samantha-hermes.service`

- [ ] **Step 1: Remove the key line** and replace with a pointer comment:

```ini
# API_SERVER_KEY intentionally NOT set here — the unit is committed to
# git. Set the real key in a local drop-in on the kiosk box:
#   systemctl --user edit samantha-hermes
#   [Service]
#   Environment=API_SERVER_KEY=<new key>
```

- [ ] **Step 2: Check whether the backend also carries this key** — `grep -rn "samantha-api-secret-key" backend/ systemd/ docs/` — and remove/parameterize any other occurrence the same way (env var, not literal).

- [ ] **Step 3: Commit, then flag rotation to the user**

```bash
git add systemd/samantha-hermes.service
git commit -m "fix(security): move hermes API key out of committed unit file"
```

Tell the user explicitly: generate a NEW key on the kiosk box (the old one is in git history forever) and set it via the drop-in on both the hermes service and wherever the backend reads it.

---

### Task 21: CosyVoice server — clip before int16 cast; pin upstream clone

**Files:**
- Modify: `tts-server/cosyvoice/server.py:50-53`, `tts-server/cosyvoice/Dockerfile:24`

- [ ] **Step 1: Fix the int16 wraparound**

In `tts-server/cosyvoice/server.py`, `generate_data` — replace:

```python
        tts_audio = (i['tts_speech'].numpy() * (2 ** 15)).astype(np.int16).tobytes()
```

with:

```python
        # Clip before casting: a sample at/above 1.0 would wrap to
        # -32768 (audible click). Matches the XTTS overlay's handling.
        tts_audio = (np.clip(i['tts_speech'].numpy(), -1.0, 1.0) * 32767).astype(np.int16).tobytes()
```

(Verify `numpy` is imported as `np` in that file; it is used at line 50 already.)

- [ ] **Step 2: Pin the upstream clone**

Get the currently-deployed commit: `git ls-remote https://github.com/FunAudioLLM/CosyVoice.git HEAD` (or, better, `docker exec <cosyvoice-container> git -C /opt/CosyVoice rev-parse HEAD` on the 4090 box if reachable — that pins what's actually running). In `tts-server/cosyvoice/Dockerfile`, replace:

```dockerfile
RUN git clone --recursive https://github.com/FunAudioLLM/CosyVoice.git
```

with (substituting the real hash):

```dockerfile
# Pinned: our server.py overlay (docker-compose mounts it over
# runtime/python/fastapi/server.py) tracks THIS revision's internals.
# Bump deliberately, re-testing the overlay against upstream changes.
ARG COSYVOICE_COMMIT=<hash-from-step-above>
RUN git clone --recursive https://github.com/FunAudioLLM/CosyVoice.git \
    && cd CosyVoice && git checkout --recurse-submodules "$COSYVOICE_COMMIT"
```

- [ ] **Step 3: Commit** (no rebuild required now — the running image predates this; the pin protects the *next* rebuild)

```bash
git add tts-server/cosyvoice/server.py tts-server/cosyvoice/Dockerfile
git commit -m "fix(cosyvoice): clip audio before int16 cast; pin upstream clone"
```

Note for deploy day: rebuilding the container picks up the clip fix; until then the wraparound click remains (rare — requires near-clipping output).

---

### Task 22: TTS backend selector consistency + doc rot purge

**Files:**
- Modify: `backend/samantha/tts.py`, `backend/samantha/config.py`, `backend/samantha/api.py`, `backend/samantha/memory.py`, `backend/samantha/schemas.py`
- Test: `backend/tests/test_tts.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_tts.py` (match its existing import style):

```python
def test_unknown_tts_backend_reports_unavailable(monkeypatch):
    """An unimplemented backend (e.g. the documented-but-never-built
    'vllm_omni') must gate at is_available() → /speak 503, not fall
    through to the Piper check and then 500 in stream()."""
    from samantha import tts as tts_mod

    monkeypatch.setattr(tts_mod.config, "tts_backend", "vllm_omni")
    assert tts_mod.is_available() is False
```

- [ ] **Step 2: Run — FAIL** (today it falls through to `_piper_voice_available()`, True on any dev box with the voice installed).

- [ ] **Step 3: Fix the selector in `tts.py`**

In `is_available()` (line ~97) and `stream()` (line ~125), unify the fallback — both currently differ (`or "piper"` vs `or "cosyvoice"`). In BOTH places use:

```python
    backend = (config.tts_backend or "").strip().lower() or "cosyvoice"
```

In `is_available()`, make the dispatch exhaustive — unknown names return False with a loud log instead of falling through to the Piper check:

```python
    if backend == "cosyvoice":
        ...  # existing check
    if backend == "xtts":
        ...  # existing check
    if backend == "piper":
        return _piper_voice_available()
    logger.error(f"tts: unknown backend {backend!r} — check SAMANTHA_TTS_BACKEND")
    return False
```

(Adapt to the function's actual structure when editing; the invariant is: only the three implemented names can return True.)

- [ ] **Step 4: Purge the lies in docstrings/comments** (each actively misleads):
  - `backend/samantha/tts.py:8-16` — first docstring block is labeled `"cosyvoice"` but describes XTTS; relabel it `"xtts"`.
  - `backend/samantha/tts.py` `synth()` (~line 150) — docstring says "Used by api.py /speak today"; it isn't (only tests). Rewrite: "Test-only convenience; /speak uses stream()."
  - `backend/samantha/api.py:376-378` — `/speak` docstring lists `vllm_omni ... Default`; rewrite the backend list to `cosyvoice (default) / xtts / piper`.
  - `backend/samantha/config.py:85-86` — drop the `"vllm_omni"` bullet (not implemented), or mark it explicitly `(NOT implemented — selecting it 503s)`.
  - `backend/samantha/config.py:75` — "Picked as default 2026-05-15" on XTTS contradicts `tts_backend: str = "cosyvoice"`; update to note CosyVoice became default (commit `1df4ea8`).
  - `backend/samantha/config.py:92-94` — "degrades to a tone WAV" is false (no tone fallback; /speak 503s); fix.
  - `backend/samantha/memory.py:25-28` — docstring says default ONNX MiniLM-L6 with a TODO to swap; code already uses fastembed multilingual; fix.
  - `backend/samantha/schemas.py:3-4` — "contrato entre Tauri (Rust) y este backend" → "contrato entre el frontend (React) y este backend".

- [ ] **Step 5: Run the full suite, format, commit**

```bash
cd backend && pytest tests/ -v && ruff format . && ruff check .
git add backend/samantha/ backend/tests/test_tts.py
git commit -m "fix(tts): exhaustive backend dispatch, unified fallback; purge stale docs"
```

---

### Task 23: Final verification pass

- [ ] **Step 1: Full backend suite from clean**: `cd backend && pytest tests/ -v` — all green.
- [ ] **Step 2: Lint**: `cd backend && ruff check .` — clean.
- [ ] **Step 3: Frontend**: `cd frontend && pnpm typecheck && pnpm build` — clean.
- [ ] **Step 4: Re-run the Fase 1 manual smoke checklist (Task 6)** against the built frontend served by the backend (`http://localhost:7777/`), not the Vite dev server.
- [ ] **Step 5: Update `PROGRESS.md`** with a "2026-06-11 bugfix sweep" entry summarizing the fixes (CLAUDE.md requires PROGRESS.md updates for completed work).
- [ ] **Step 6: Commit**: `git add PROGRESS.md && git commit -m "docs: log 2026-06-11 bugfix sweep in PROGRESS"`

---

## Fase 5 — Feature backlog (each is its own future plan — do NOT implement here)

Recorded so the roadmap lives next to the fixes. Ordered by leverage:

1. **Server-side voice loop via Pipecat** — already scoped and paused (see memory: decisions locked, design at §1; resume at §2). Replaces the fragile browser mic/TTS choreography that Fase 1 patches (Silero VAD, barge-in, smart turn detection server-side). Highest leverage: makes Tasks 2/3/4's whole problem class disappear.
2. **Iniciativa propia** — Samantha opens conversation after idle, referencing a past memory ("hace una semana me contaste…"). The most "Her" missing piece. Needs: idle scheduler in backend + a "she speaks first" WS message + recall sampling policy.
3. **Consolidación nocturna de memoria** — cron job summarizing the day into high-level chunks + extracting new facts (preferences, people). Append-only respected.
4. **Estado emocional persistente** — mood fact that evolves across sessions, modulates the system prompt and CosyVoice expression markers per reply.
5. **Wake word local** ("Samantha") — openWakeWord/Porcupine on Ambient screen to enter conversation hands-free.
6. **Backup/export de memoria** — tar of `~/.samantha/` via admin command. "Never forgets" without backups is one disk failure from forgetting everything.
7. **Modo noche** — dim UI + softer/slower voice by hour.
8. **Panel admin local** (`/admin`, localhost-only) — facts, memory browser, logs, service health without SSH.

Pending user confirmation (public-API removals, CLAUDE.md §8): delete deprecated `listen`/`transcription` WS path, `PingResponse` frontend type, store dead state (`name`, `resetTranscript`), stale Vite proxies.

## Known findings deliberately NOT in this plan (low priority / admin-only)

Logged so they aren't re-discovered: `Memory.clear()` doesn't clear the short-term ring (admin/test tool only); `profile.py` answer recovery depends on a ±5 s timestamp window (store answer chunk ids as a fact when touching profile next); `real_llm.aclose()` never wired to FastAPI shutdown; malformed numeric env vars crash config import without naming the variable; `get_fact()` fetches all historical facts per call (linear with device age); CosyVoice server leaks one temp ref-WAV per aborted stream; docker healthchecks assume `curl` exists in the images (verify once with `docker exec ... which curl`); `Wave.tsx` re-reads `getBoundingClientRect` per frame and caches `dpr` once; Ambient clock can lag up to 59 s.
