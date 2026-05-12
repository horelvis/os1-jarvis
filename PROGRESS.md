# PROGRESS.md — Samantha Phase Log

> **For Claude Code:** Append to this file after completing each phase
> from CLAUDE.md §4. Newest entries at the top. Format:
>
> ```
> ## YYYY-MM-DD — Phase N: Title ✅
> Brief summary (2-3 lines).
> **Changed files:** list
> **Tests:** pass/fail count
> **Notes:** any caveats, follow-ups, or surprises
> ```

---

## 2026-05-12 — Phase 6: Persistent memory (ChromaDB) ✅ [out of order]

Done out of spec order (Phase 5 STT/TTS deferred) because the user
wanted to develop memory in parallel with their llama.cpp install.

Persistent semantic memory over user messages + Samantha replies, backed
by ChromaDB (SQLite + HNSW) at `~/.samantha/memory/`. Default embedder is
ChromaDB's ONNX MiniLM (will swap to multilingual sentence-transformers
once we see retrieval quality on real Spanish conversation).

Each turn now: (1) remember user msg → (2) recall top-k similar past
chunks → (3) inject into system prompt as "# Lo que recuerdas de esta
persona" → (4) stream reply → (5) remember reply. Both `/chat` and
`/ws chat` follow the same path.

**Design directive (user, mid-implementation):** *"Samantha nunca debe
olvidar nada."* The originally planned "olvida X" intent-detection
feature was REMOVED. `Memory.forget()` and `Memory.clear()` are kept
as admin/test tools but never triggered by user input. The system
prompt (v2) instructs Samantha to decline forget requests in character.

**Changed files:**
- `CLAUDE.md` §2.7 rewritten (sentence-transformers swap-path, no
  Ollama dep, never-forgets principle); §4 Phase 6 deliverables updated.
- `backend/samantha/memory.py` (new — Memory class: remember/recall/all/
  forget/clear/stats; MemoryChunk dataclass; chromadb lazy import).
- `backend/samantha/personality.py` (v1 → v2: added "no olvidas" clause
  + refusal example, `SYSTEM_PROMPT_VERSION = "v2-2026-05-12"`).
- `backend/samantha/real_llm.py` (`stream_reply()` / `generate_reply()`
  / `_build_payload()` accept `memories` kwarg; `_format_memories()`
  renders the system-prompt addendum).
- `backend/samantha/api.py` (`get_memory()` lazy singleton; `/chat` and
  `/ws chat` wire remember/recall/inject/remember).
- `backend/samantha/config.py` (`memory_enabled`, `memory_persist_dir`
  renamed from `chroma_persist_dir`, `memory_top_k`).
- `backend/pyproject.toml` (chromadb to main deps; sentence-transformers
  moved to [real] extras as upgrade path).
- `backend/tests/conftest.py` (new — sets `SAMANTHA_MEMORY_ENABLED=false`
  for the integration suite so chroma files don't land in the developer
  home; dedicated Memory tests use `tmp_path`).
- `backend/tests/test_api.py` (added 9 tests: remember+recall, user_id
  isolation, admin forget, persistence across reopens, empty store,
  clear, role validation, no-forget-intent-exposed, memory injection
  into system prompt).
- `docs/02-system-prompt-iterations.md` (v2 section added, marked as
  active; v1 kept for reference).

**Tests:** 29 / 29 passing.

**Notes:**
- First test run downloads ChromaDB's ONNX MiniLM (~80 MB). Subsequent
  runs use the cached model.
- Embedder is English-leaning. Spanish retrieval works (multilingual
  signal in pretraining) but is not optimal. Swap to
  `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` when
  real conversation data shows recall misses.
- Memory is enabled by default in production (mock and real modes both
  use it). To disable for local debugging: `SAMANTHA_MEMORY_ENABLED=false`.
- The `Memory.forget()` admin tool is unreachable from any HTTP/WS
  surface today. If we ever expose a "factory reset" or "new owner"
  flow, it'll be a separate admin endpoint that requires explicit
  intent, not a chat command.

---

## 2026-05-12 — Phase 4: Real LLM integration ✅

Wired Samantha to a real local LLM via an OpenAI-compatible HTTP API.
Chose **llama.cpp (`llama-server`)** as the runtime instead of vLLM —
single-user single-stream workload doesn't benefit from vLLM's batching
engine, and llama.cpp runs natively on Mac (Metal) AND Linux (CUDA),
unblocking Mac-side development. See decision log §12 in CLAUDE.md.

The `real_llm` client uses `httpx.AsyncClient.stream()` to consume
OpenAI-style SSE deltas and yields token chunks as they arrive. The
WebSocket `/ws` and non-streaming `/chat` both dispatch on `config.mode`
via a unified `_stream_tokens()` async generator, so the on-wire protocol
is identical regardless of backend. If the LLM server is down, the
fallback reply is in Samantha's voice — the UI never sees a raw error.

`personality.SYSTEM_PROMPT` is embedded as a module constant (canonical
source-of-truth lives in `docs/02-system-prompt-iterations.md`, v1).

**Changed files:**
- `CLAUDE.md` updated (§2.5 vLLM→llama.cpp, §3 systemd filename,
  §4 Phase 4 deliverables, §5 commands, §12 decision log entry)
- `docs/02-system-prompt-iterations.md` (new — canonical prompt v1)
- `backend/samantha/personality.py` (new — embedded prompt + version)
- `backend/samantha/real_llm.py` (new — OpenAI-compat streaming client)
- `backend/samantha/config.py` (renamed `vllm_url` → `llm_server_url`,
  added `llm_request_timeout_s`, env var `SAMANTHA_LLM_SERVER_URL`)
- `backend/samantha/api.py` (unified `_stream_tokens()` dispatch by mode;
  `/chat` and `/ws` now branch on `config.mode` cleanly)
- `backend/pyproject.toml` (httpx moved to main deps; vllm removed from
  `[real]` extras since llama.cpp is a separate binary)
- `systemd/samantha-llamacpp.service` (new — runs `llama-server` with
  the model on :8000, restarts on failure, GPU offload via NGL=99)
- `backend/tests/test_api.py` (added 3 tests: SSE parsing, HTTP-error
  fallback, system-prompt presence + version)

**Tests:** 20 / 20 passing (`pytest tests/ -v`).

**Notes:**
- Run real mode locally:
  ```bash
  # 1. Install llama.cpp (brew install llama.cpp on Mac;
  #    apt/build-from-source on Linux).
  # 2. Download a GGUF model, e.g.:
  #    huggingface-cli download Qwen/Qwen3.5-9B-Instruct-GGUF \
  #      qwen3.5-9b-instruct-q4_k_m.gguf \
  #      --local-dir ~/.samantha/models
  # 3. Start llama-server:
  llama-server --model ~/.samantha/models/qwen3.5-9b-instruct-q4_k_m.gguf \
               --host 127.0.0.1 --port 8000 --jinja
  # 4. Start the backend in real mode:
  SAMANTHA_MODE=real python -m samantha.api
  ```
- The system prompt is v1 and untested against the actual model. Iterate
  by editing `docs/02-system-prompt-iterations.md` → sync to
  `personality.py`. Open questions are listed at the bottom of v1.
- The `llm_model` field in config is informational — llama-server runs
  whichever GGUF it was started with. The field becomes meaningful if
  you ever swap to vLLM (which uses it to select among loaded models).
- `httpx.AsyncClient` is created lazily on first call so the event loop
  owns it. `real_llm.aclose()` exists for clean shutdown but isn't wired
  into FastAPI's lifespan yet (no harm; the OS reclaims sockets on exit).

---

## 2026-05-12 — Phase 3: Frontend integration ✅

Migrated the `samantha_mockup_v7.html` mockup into modular files
under `backend/static/` and wired every interaction to the real
backend. FastAPI now serves both the SPA and the API on `:7777`.
The browser never touches the microphone (CLAUDE.md §2.8): the mic
button triggers a `listen` message over the new `/ws` WebSocket; the
backend returns a fake transcription (Phase 5 will swap in real STT).
Replaced `speechSynthesis` with fetch + `<audio>` playback of `/speak`.
Removed the obsolete `/chat/stream` SSE endpoint; streaming now flows
through `/ws` (token / done events).

**Changed files:**
- `backend/static/index.html` (rewritten — was the Tauri skeleton)
- `backend/static/style.css` (new — full extraction)
- `backend/static/app.js` (new — screen state machine + event wiring)
- `backend/static/samantha-wave.js` (new — wave + audio-viz factories)
- `backend/static/os1-loader.js` (new — Three.js ribbon)
- `backend/static/ws-client.js` (new — WebSocket client with reconnect)
- `backend/samantha/api.py` (refactored — StaticFiles, GET /, /ws, no SSE/CORS)
- `backend/tests/test_api.py` (added 7 tests: index, static assets, /ws)

**Tests:** 17 / 17 passing (`pytest tests/ -v`).

**Notes:**
- CORS middleware for Tauri origins removed (same-origin now).
- `/chat` (non-streaming) kept for tests; the UI uses `/ws`.
- TTS still plays the 0.4s tone WAV (Phase 5 swaps Piper in). Onboarding
  timings stay natural because they're driven by independent setTimeouts,
  not by audio `ended` events.
- Three.js loaded via importmap from `cdn.jsdelivr.net` (CLAUDE.md §6),
  fonts via Google Fonts. Both authorized; vendoring is a future concern.
- WS auto-reconnects with backoff so the kiosk recovers from backend restarts.
- Frontend never calls `getUserMedia` / `speechSynthesis` / `webkitSpeechRecognition`
  — all routed through the backend per CLAUDE.md §2.8.

---

## 2026-05 — Phase 0: Architecture redesign (v3) ✅

Final architecture settled on Ubuntu Server 24.04 LTS + Chromium kiosk
mode + Python-only backend serving frontend on `localhost:7777`.
Eliminated all snap/Ubuntu Frame complexity from the v2 plan. The
Python backend serves both the static HTML/CSS/JS and the API on a
single port. Browser communication via fetch + WebSocket.

**Changed files:**
- `CLAUDE.md` updated to v3 (sections §2.2, §2.3, §2.8, §3, §4, §5,
  §6, §8, §9, §10, §11, §12 updated)
- `PROGRESS.md` updated (this file)
- Project structure unchanged from v2 (still no `src-tauri/`,
  no `snap/`)

**Tests:** N/A (architectural change, no new code)

**Notes:**
- This is the THIRD architecture iteration. v1 was Tauri + Rust
  (rejected). v2 was Ubuntu Frame + WPE WebKit + snap (rejected).
- The principle behind v3: "familiar tools first, exotic only when
  justified." Chromium kiosk is the most widely-deployed Linux kiosk
  solution.
- Hardware decision unchanged: Minisforum AtomMan G7 Ti SE
- LLM, STT, TTS, memory decisions unchanged

---

## ~~2026-05 — Phase 0: Architecture redesign (v2)~~ ❌ REVERTED

Briefly settled on Ubuntu Frame + WPE WebKit + snap. Reverted before
implementation due to snapcraft complexity and WPE WebKit API concerns.

---

## ~~2026-05 — Phase 1: Tauri skeleton~~ ❌ REJECTED

Originally built in v1 of the architecture. Replaced by web-based
kiosk approach. Code removed.

**Why rejected:** Tauri adds a Rust + WebKit2GTK layer that's
unnecessary when the backend can serve the frontend directly to a
browser in kiosk mode.

---

## 2026-05 — Phase 2: Mock Python backend ✅

FastAPI server with 5 endpoints (ping, chat, chat/stream, transcribe,
speak). Pattern-matched responses in `mock_llm.py` covering 14
keyword-based categories plus 10 fallback replies. All responses follow
the Samantha personality guidelines (no disclaimers, concise, warm).

**Changed files:**
- `backend/pyproject.toml` (new)
- `backend/samantha/__init__.py` (new)
- `backend/samantha/config.py` (new)
- `backend/samantha/schemas.py` (new)
- `backend/samantha/mock_llm.py` (new)
- `backend/samantha/api.py` (new)
- `backend/tests/test_api.py` (new)
- `backend/README.md` (new)

**Tests:** 10 / 10 passing.

**Notes:**
- Predates Phase 0 redesigns; needs minor updates in Phase 3:
  - Add `StaticFiles` mount for `/static/*`
  - Add `GET /` route returning `index.html`
  - Add WebSocket endpoint `/ws` for streaming
  - Remove `/chat/stream` SSE (replaced by WebSocket in Phase 3)
- Simulated latency (0.4–1.8s) intentional to match real LLM speeds
- `/transcribe` returns hardcoded fake transcriptions for mock mode
- `/speak` returns a synthesized tone WAV (placeholder for Piper output)

---
