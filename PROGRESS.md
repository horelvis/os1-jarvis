# PROGRESS.md — Samantha Phase Log

## 2026-06-20 — Bugfix Sweep (2026-06-11 plan) ✅

23-task sweep fixing the daily-conversation path, backend robustness, frontend robustness, and deploy issues found in a full-project review.

**Fase 1 — Conversation core:**
- Task 1: Stop duplicating current user message in LLM context (collect → persist ordering).
- Task 2: Abort recognition before transcript reset so mic stays muted during TTS.
- Task 3: Abort TTS and recognizer on unmount; clear activeRef first.
- Task 4: Restart mic immediately on barge-in; keep interruption transcript via bargedInRef.
- Task 5: Drop empty reply bubble on chat failure; honest Samantha-voiced error copy.

**Fase 2 — Backend robustness:**
- Task 7: Generic exception handler returns JSONResponse(500) instead of re-raising.
- Task 8: Memory init and per-turn memory work moved off the event loop (asyncio.to_thread); ShortTermBuffer gains a threading.Lock.
- Task 9: WS loop survives malformed messages, binary frames, and mid-stream disconnects; MAX_WS_MESSAGE_CHARS cap.
- Task 10: SAMANTHA_MODE validated and normalized at startup; unknown values raise ValueError.
- Task 11: TTS read timeout applied to synthesis streams (wedged server no longer hangs /speak).
- Task 12: Hermes path gets facts + semantic recall injected into system prompt.

**Fase 3 — Frontend robustness:**
- Task 13: Global keyboard shortcuts ignored while typing in editable elements.
- Task 14: Serialize chat turns — concurrent sends clobbered WS handlers.
- Task 15: Surface microphone permission errors via isMicrophoneAvailable effect.
- Task 16: Kill switch skips VAD init (no mic stream, no CDN fetches) when barge-in disabled.
- Task 17: Dispose Three.js geometries and materials on OS1Loader unmount.
- Task 18: Strip debug logging, fix emoji residue (ZWJ + combining keycap), move @types dep.

**Fase 4 — Deploy & TTS server:**
- Task 19: Add missing samantha-backend.service and samantha-ui.service systemd units.
- Task 20: Move hermes API key out of committed unit file (rotate on kiosk box).
- Task 21: CosyVoice server — clip audio before int16 cast; pin upstream clone.
- Task 22: is_available() exhaustive dispatch; unified default fallback; purge stale docs across tts.py/config.py/api.py/memory.py/schemas.py.

**Changed files:** `backend/samantha/api.py`, `backend/samantha/config.py`, `backend/samantha/memory.py`, `backend/samantha/real_llm.py`, `backend/samantha/schemas.py`, `backend/samantha/short_term.py`, `backend/samantha/tts.py`, `backend/tests/test_api.py`, `backend/tests/test_short_term.py`, `backend/tests/test_tts.py`, `frontend/src/screens/ConversationScreen.tsx`, `frontend/src/core/useKeys.ts`, `frontend/src/core/useBargeIn.ts`, `frontend/src/core/store.ts`, `frontend/src/core/sanitize.ts`, `frontend/src/components/OS1Loader.tsx`, `frontend/package.json`, `tts-server/cosyvoice/server.py`, `tts-server/cosyvoice/Dockerfile`, `systemd/samantha-backend.service`, `systemd/samantha-ui.service`, `systemd/samantha-hermes.service`

**Tests:** 75 passed, 1 pre-existing failure (test_synth_produces_riff_wave — piper not installed on dev machine). Frontend: tsc clean, pnpm build succeeds.

**Notes:**
- The piper test failure is not new — `piper` module is not installed in the dev venv. On the kiosk box with piper installed it passes.
- Task 6 (Fase 1 smoke test) is manual — verify in the real kiosk environment.

---

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

## 2026-05-26 — Phase 10: Onboarding por Voz y Pulido de Interfaz (Her) ✅

Rediseño interactivo del onboarding a un flujo conversacional por voz. Samantha lee por voz las preguntas y el micrófono se abre automáticamente al finalizar su locución. Se pulieron botones y espaciados siguiendo la estética minimalista y orgánica de la película *Her*.

**Changed files:**
- [OnboardingScreen.tsx](file:///Volumes/Macintosh%20SSD%20-%20Daten/Users/horelvis/git/os1-samantha/frontend/src/screens/OnboardingScreen.tsx) (modificado)
- [components.css](file:///Volumes/Macintosh%20SSD%20-%20Daten/Users/horelvis/git/os1-samantha/frontend/src/styles/components.css) (modificado)

**Tests:** tsc --noEmit exitoso; 65 tests en pytest aprobados.

**Notes:** Se implementó degradación elegante a modo texto en caso de que el navegador no tenga soporte para SpeechRecognition o permisos bloqueados de micrófono.

---

## 2026-05-26 — Phase 9: Integración de Hermes-Agent ✅

Integración híbrida de NousResearch `hermes-agent` como cerebro agéntico secundario compatible con la API de OpenAI. Se estructuró el envío limpio del historial de conversación y se propagó el `user_id` para garantizar la continuidad de sesión y memoria del agente local.

**Changed files:**
- [config.py](file:///Volumes/Macintosh%20SSD%20-%20Daten/Users/horelvis/git/os1-samantha/backend/samantha/config.py) (modificado)
- [real_llm.py](file:///Volumes/Macintosh%20SSD%20-%20Daten/Users/horelvis/git/os1-samantha/backend/samantha/real_llm.py) (modificado)
- [api.py](file:///Volumes/Macintosh%20SSD%20-%20Daten/Users/horelvis/git/os1-samantha/backend/samantha/api.py) (modificado)
- [samantha-hermes.service](file:///Volumes/Macintosh%20SSD%20-%20Daten/Users/horelvis/git/os1-samantha/systemd/samantha-hermes.service) (nuevo)
- [test_api.py](file:///Volumes/Macintosh%20SSD%20-%20Daten/Users/horelvis/git/os1-samantha/backend/tests/test_api.py) (modificado)

**Tests:** 65 passed, 0 failed

**Notes:** La omisión de `/no_think` permite al agente de Hermes utilizar el bloque de razonamiento de Qwen para invocar herramientas, y la inyección de `X-Hermes-Session-Id` mapea correctamente el almacenamiento SQLite de Hermes.

---

## 2026-05-26 — Hermes-Agent Evaluation Spike ✅

Evaluación e informe de viabilidad técnica de NousResearch Hermes-Agent para sustentar las capacidades agénticas de Samantha v3. Se concluye con una recomendación de adopción híbrida, empleando Hermes como cerebro REST API local de herramientas y memoria mientras se conserva el backend actual en FastAPI para la gestión de audio en tiempo real y el frontend en React.

**Changed files:**
- [REPORT.md](file:///Volumes/Macintosh%20SSD%20-%20Daten/Users/horelvis/git/os1-samantha/docs/superpowers/specs/hermes-agent-spike/REPORT.md) (nuevo)

**Tests:** N/A (fase investigativa/documental)

**Notes:** La integración híbrida vía API OpenAI-compatible mantiene intacto nuestro frontend y simplifica de sobremanera la incorporación de MCP (correo/calendario).

---

## 2026-05-13 — Phase 8: UI v2 redesign ✅

Full redesign per `docs/superpowers/specs/2026-05-12-ui-redesign-design.md`
and `docs/superpowers/plans/2026-05-12-ui-redesign-v2.md`.

- **Frontend:** vanilla-JS in `backend/static/` deleted. New `frontend/`
  with React 18 + Vite 5 + TypeScript 5.5 strict. 4 screens (Boot,
  Onboarding, Ambient, Conversation immersive + history toggle). Design
  tokens system in `frontend/src/styles/tokens.css`. State managed by
  Zustand. Three.js OS1Loader ported to a `forwardRef` component with
  imperative handle.
- **Wave:** rewritten as a traveling wave packet — pulses propagate from
  the center outward with gaussian envelope and per-mode parameters
  (idle / listening / thinking / speaking) per spec §6. Stroke 0.6 px.
- **Memory:** extended with short-term (SQLite ring buffer, last 20
  turns, capacity-configurable), long-term (ChromaDB + fastembed
  multilingual ONNX embedder `paraphrase-multilingual-MiniLM-L12-v2`),
  and facts (`role: "fact"` chunks). `Memory.set_fact`, `get_fact`,
  `all_facts` added. `recall()` excludes short-term entries AND
  `role: "fact"` chunks.
- **Persistence:** no `profile.json`. `profile.py` thin facade over
  Memory. `/profile` endpoints (GET / POST / DELETE) routed through
  facts. `/ping` includes `has_profile: bool`.
- **Prompt assembly:** `real_llm._build_payload` accepts `facts`,
  `recall`, `short_term` kwargs (keyword-only). System prompt assembled
  per spec §9.6:
  `SYSTEM_PROMPT + # Lo que sabes de ella + # Lo que recuerdas + # Conversación reciente + user-turn`.
- **Backend serves frontend/dist:** `STATIC_DIR` removed,
  `FRONTEND_DIST = ../../frontend/dist`, `/assets` mount guarded on
  `dist/assets/` existing so backend-only test runs keep working.
- **CLAUDE.md updated:** §2.4 (frontend lives separately), §2.7 (3-layer
  memory architecture), §2.10 new (frontend stack), §3 (no-framework /
  no-build-step rules removed), §5 (npm commands + vite dev workflow),
  §7 (npm install && npm run build before systemd), §12 (two decision
  log entries: frontend pivot + memory redesign).

**Changed files (this redesign):**
- Backend new: `samantha/short_term.py`, `samantha/profile.py`,
  `tests/test_short_term.py`, `tests/test_profile.py`.
- Backend modified: `samantha/memory.py` (fastembed + short-term + facts),
  `samantha/real_llm.py` (three-layer prompt), `samantha/api.py`
  (/profile endpoints, _collect_facts, frontend/dist serving),
  `samantha/schemas.py` (ProfileAnswer / ProfileCreateRequest /
  ProfileResponse, PingResponse.has_profile),
  `samantha/config.py` (memory_short_term_capacity, memory_embedder_model),
  `pyproject.toml` (fastembed → main deps).
- Frontend new: 17 files under `frontend/`: package.json, tsconfig*,
  vite.config.ts, index.html, .gitignore, plus 12 `src/**` files
  (App.tsx, main.tsx, types.ts, store.ts, router.ts, useKeys.ts,
  profile.ts, tts.ts, wsClient.ts, mic.ts, Wave.tsx, OS1Loader.tsx,
  BootScreen.tsx, AmbientScreen.tsx, ConversationScreen.tsx,
  OnboardingScreen.tsx, tokens.css, base.css, components.css).
- Deleted: `backend/static/{index.html, style.css, app.js,
  samantha-wave.js, os1-loader.js, ws-client.js}`.

**Tests:** backend pytest 50 / 50 green. Frontend `npm run typecheck`
clean, `npm run build` succeeds (608KB bundle, Three.js dominant).
End-to-end smoke (mock mode): Boot → Onboarding → /profile POST →
Ambient → tap → Conversation → WS chat token stream works.

**Out of scope (deferred):**
- Samantha proactiva (initiative engine) → v3
- Agentic Samantha (emails, calendar, tools) → v3, scoped at
  `docs/superpowers/specs/2026-05-12-hermes-agent-spike-scope.md`
- Real STT (faster-whisper) + real TTS (Piper) → Phase 5 of v1 phase plan
- Memory browser UI → future

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
