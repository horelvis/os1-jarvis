# CLAUDE.md — Samantha Project Specification (v3)

> **For Claude Code:** This is the single source of truth for the Samantha
> project. Read this entire document before making any changes. When in
> doubt about scope, architecture, or style, this document overrides your
> defaults. Update `PROGRESS.md` after completing each phase.
>
> **This is v3.** Previous versions used Tauri + Rust (v1) and Ubuntu
> Frame + WPE WebKit + snap (v2). v3 simplifies to Chromium in kiosk
> mode launched via systemd. See §12 for the full decision log.

---

## 0. TL;DR

Samantha is a **fully local, kiosk-style AI companion** inspired by the
film *Her*. It runs entirely on a single mini-PC (no cloud, no remote,
no external dependencies at runtime). The user interacts with it via
voice and text through a fullscreen webview interface.

**Stack at a glance:**
- **Hardware:** Minisforum AtomMan G7 Ti SE (RTX 4070 Mobile 8GB VRAM, 32GB RAM)
- **OS:** Ubuntu Server 24.04 LTS with minimal X11 stack
- **Kiosk:** Chromium browser in `--kiosk` mode, launched via systemd
- **Backend:** Python 3.12 + FastAPI on localhost:7777 (serves frontend AND API)
- **Frontend:** Static HTML/CSS/JS served by FastAPI, rendered by Chromium
- **LLM:** Qwen 3.5-9B Instruct (8GB VRAM target; final model TBD on first run)
- **STT:** faster-whisper Large v3 Turbo
- **TTS:** Piper (Spanish voice preset `es_ES-davefx-medium`)
- **Memory:** ChromaDB with nomic-embed-text embeddings
- **Audio I/O:** sounddevice (Python, native, no browser permissions)
- **Language:** Spanish (Spain) — all UX strings, prompts, voices

**Two processes, one machine:**

```
┌────────────────────────────────────────────────────┐
│  Chromium in --kiosk mode (fullscreen, no chrome)  │
│  - Launched by systemd at boot                     │
│  - Loads http://localhost:7777/                    │
│  - No address bar, no tabs, no escape              │
├────────────────────────────────────────────────────┤
│  Python Backend (FastAPI on :7777)                 │
│  - Serves /static/* (HTML/CSS/JS)                  │
│  - GET / → index.html (the UI)                     │
│  - POST /chat, /transcribe, /speak (API)           │
│  - WebSocket /ws (streaming conversation)          │
│  - sounddevice for mic capture (native, no browser)│
│  - Orchestrates vLLM, Whisper, Piper, ChromaDB     │
└────────────────────────────────────────────────────┘
```

---

## 1. Vision & Product Principles

### What Samantha is

Samantha is **not** an assistant, a chatbot, an agent, or a tool. She is
a presence: a curious, warm, conversational AI that lives on a single
mini-PC in the user's home, learns about the user over time, and
behaves like a friend rather than a service.

The aesthetic is heavily inspired by the OS1 interface in *Her* (Spike
Jonze, 2013): terracotta orange, minimal typography, no clutter, voice
as the primary interaction mode.

### Product principles (in priority order)

1. **Privacy first.** All inference is local. No telemetry, no cloud APIs,
   no exfiltration. The user's data never leaves their machine.

2. **Conversational, not task-oriented.** Samantha is designed for the
   relationship, not for productivity. She remembers, she asks, she has
   opinions. She is NOT a Siri/Alexa replacement.

3. **Aesthetic restraint.** Minimalism in every screen. One color
   (`#d1684e`), one wave, one typography pair (Cormorant Garamond +
   Inter Tight). No badges, no emojis in UI, no marketing language.

4. **Latency over correctness.** A 30 tok/s response that is 90% as
   good feels infinitely better than a 5 tok/s response that is 100%
   good. Choose the faster model.

5. **Appliance experience.** When the device boots, it boots into Samantha.
   No login screen, no desktop, no settings UI. The device IS Samantha.
   This is enforced by systemd + auto-login + Chromium kiosk mode.

### What Samantha is NOT

- ❌ A multi-user system (single user, always)
- ❌ A productivity assistant (no calendar/email integration in v1)
- ❌ A cloud-augmented anything (zero network dependency at runtime)
- ❌ A mobile app (desktop kiosk only)
- ❌ A coding assistant
- ❌ An agentic tool-using system (no function calling, no web search)

---

## 2. Architecture Decisions (Non-Negotiable)

These decisions are settled. Do NOT revisit them without explicit user
permission. If the user requests a change, ask for confirmation that
they understand the implications listed.

### 2.1 Hardware: Minisforum AtomMan G7 Ti SE

**Decision:** Mini-PC with Intel i7-14650HX + RTX 4070 Mobile (8GB VRAM)
+ 32GB DDR5 + 1TB NVMe.

**Rationale:**
- Mini form factor fits the "appliance" feel (small, hidden, present)
- RTX 4070 Mobile has enough VRAM for a 9B model in 4-bit quantization
- 32GB RAM is generous given DDR5 price spike in 2026 (~450€ to upgrade to 64GB)
- ~1500€ total budget cap

**Implications:**
- Models > 14B parameters at 4-bit DON'T fit in VRAM without offloading
- VRAM is the bottleneck, not RAM
- The LLM lives in VRAM; everything else lives in RAM

### 2.2 Operating System: Ubuntu Server 24.04 LTS

**Decision:** Ubuntu Server 24.04 LTS (Noble Numbat).

**Rationale:**
- LTS support until April 2029, extended until 2034 with Ubuntu Pro
- Official NVIDIA driver support (`ubuntu-drivers autoinstall`)
- Massive community: any problem has been solved before on StackOverflow
- Stable, predictable, "install and forget"
- Familiar Linux model (apt, systemd) for manual interventions

**Alternatives considered and rejected:**
- Arch Linux: too much manual maintenance for an appliance
- Ubuntu Core 24: too rigid, harder to debug, all-snap model
- Pop!_OS: less standard, smaller community
- Fedora: smaller community than Ubuntu for kiosk use cases

**Implications:**
- Use X11 (not Wayland) for the kiosk session, since Chromium + X11 +
  openbox is the most widely-deployed kiosk stack
- NVIDIA drivers from official Ubuntu repositories
- All services managed via systemd

### 2.3 Display Layer: Chromium in Kiosk Mode

**Decision:** Use Chromium browser launched with `--kiosk` flag, started
automatically at boot by systemd via auto-login user session.

**Rationale:**
- **Familiar:** Chromium is what every developer knows. Debugging works
  with standard DevTools.
- **Compatible:** Full support for modern web APIs (Three.js, Canvas 2D,
  Web Audio, WebSocket, fetch). No "WebKit might not support X" worries.
- **Minimal complexity:** ~5 lines of systemd config + a single command.
  No new packaging system to learn (snap), no new compositor (Mir).
- **Reliable:** Chromium kiosk mode is battle-tested in millions of
  digital signage deployments worldwide.

**Alternatives considered and rejected:**
- **Tauri 2 (v1):** Adds an entire Rust + WebKit2GTK layer that we don't
  need when the backend can serve the frontend directly. Discarded.
- **Ubuntu Frame + WPE WebKit (v2):** Purpose-built but introduces
  snapcraft packaging complexity for a single-user, single-device
  project. Overengineering for our scope. WPE WebKit may lack some
  modern browser APIs. Discarded.
- **Electron:** ~150MB binary, designed for cross-platform apps, not
  Linux kiosks.
- **Firefox kiosk:** Less polished kiosk mode than Chromium.

**Implementation pattern:**

```
Boot
  ↓
systemd: getty@tty1 auto-login as user `samantha`
  ↓
~/.bash_profile: if tty1, run `startx`
  ↓
~/.xinitrc: launch openbox + samantha-ui.service
  ↓
samantha-ui.service: chromium --kiosk http://localhost:7777/
```

**Implications:**
- Frontend is **just HTML/CSS/JS** served by Python. No bundling, no
  build step, no frameworks.
- Use **X11** (not Wayland) for simplicity. Chromium + X11 + openbox is
  the most widely-deployed kiosk stack on Linux.
- Boot to Samantha takes ~20s (BIOS + kernel + login + Chromium startup).
- For debugging, `Ctrl+Alt+F2` exits to a TTY (only on dev machines;
  disabled in production).

### 2.4 Backend Stack: Python + FastAPI (Fullstack)

**Decision:** Python 3.12 + FastAPI + uvicorn, serving on
`127.0.0.1:7777`. Backend serves BOTH the static frontend AND the API.

**Rationale:**
- vLLM is Python-native
- faster-whisper and Piper have Python APIs
- ChromaDB is Python-native
- FastAPI's `StaticFiles` lets us serve the frontend from the same process
- Single deployment unit, single process to monitor
- Same-origin (no CORS issues for fetch/WebSocket)

**Architecture pattern:**

```python
app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def index():
    return FileResponse("static/index.html")

@app.post("/chat") ...
@app.websocket("/ws") ...
```

When WPE WebKit visits `http://127.0.0.1:7777/`, it gets `index.html`.
That HTML loads `/static/app.js`, which connects to `/ws` via WebSocket
for streaming conversation.

### 2.5 LLM: Qwen 3.5-9B (with room to upgrade)

**Decision:** Default to **Qwen 3.5-9B-Instruct** in AWQ 4-bit. Final
model TBD after first run on real hardware.

**Rationale:**
- Fits comfortably in 8GB VRAM (~6-7GB) with room for KV cache
- Expected ~30 tok/s on RTX 4070 Mobile
- Multilingual, strong in Spanish
- Apache 2.0 license

**Rejected alternatives:**
- Qwen 3.6-27B: needs 16.8GB VRAM at Q4_K_M
- Qwen 2.5-14B: superseded by 3.5 generation
- Llama 3.3-70B: needs ~40GB VRAM
- GPT/Claude API: violates "fully local" principle

### 2.6 STT/TTS

**Decision:**
- **STT:** faster-whisper Large v3 Turbo (~1.5GB model, runs on GPU
  when LLM is not actively generating)
- **TTS:** Piper with voice `es_ES-davefx-medium` (~40MB, CPU-only,
  ~200ms latency)

### 2.7 Memory: ChromaDB

**Decision:** ChromaDB with `nomic-embed-text` embeddings via Ollama,
persisted in `~/.samantha/memory/`.

### 2.8 Audio I/O: sounddevice (Python, native)

**Decision:** Microphone capture and audio playback handled by Python
via `sounddevice`. The browser layer does NOT touch the microphone.

**Rationale:**
- Browser audio APIs (`getUserMedia`) require permission prompts that
  break the kiosk illusion (a dialog appears asking for mic access)
- Python has direct access to ALSA/PulseAudio through sounddevice
- Audio capture and STT happen in the same process (lower latency)
- Same code works whether running in Chromium kiosk or a regular dev browser

**Implications:**
- The frontend NEVER calls `navigator.mediaDevices.getUserMedia()`
- Mic activation is triggered by frontend → WebSocket message → Python
  starts capturing → Python streams transcription back via WebSocket
- The mockup's audio visualizer is decorative; the real audio data
  comes from Python, not the browser
- Chromium does NOT need `--use-fake-ui-for-media-stream` or similar
  flags since we don't use browser mic APIs at all

### 2.9 Language: Spanish (Spain)

**Decision:** All user-facing strings, voice synthesis, and prompts in
Spanish from Spain (peninsular).

**Code itself:**
- Code identifiers, comments, commit messages: **English**
- User-facing strings: **Spanish**
- Documentation: **English** (this file, READMEs)

---

## 3. Project Structure (Authoritative)

```
samantha/
├── CLAUDE.md                   ← This file. Read first.
├── PROGRESS.md                 ← Phase completion log (you update this)
├── README.md                   ← Brief overview for humans
│
├── backend/                    ← The whole application (Python)
│   ├── pyproject.toml
│   ├── README.md
│   ├── samantha/
│   │   ├── __init__.py
│   │   ├── api.py              ← FastAPI app + endpoints + StaticFiles + WS
│   │   ├── config.py           ← Env-var-based config
│   │   ├── schemas.py          ← Pydantic models (API contract)
│   │   ├── mock_llm.py         ← Pattern-matched mock responses
│   │   ├── real_llm.py         ← vLLM client (Phase 4)
│   │   ├── audio_capture.py    ← sounddevice mic capture (Phase 5)
│   │   ├── stt.py              ← faster-whisper (Phase 5)
│   │   ├── tts.py              ← Piper (Phase 5)
│   │   ├── memory.py           ← ChromaDB wrapper (Phase 6)
│   │   └── personality.py      ← System prompt + persona (Phase 4)
│   ├── static/                 ← Frontend, served by FastAPI
│   │   ├── index.html          ← Single-page app
│   │   ├── style.css           ← All styles
│   │   ├── app.js              ← Main app + screen state machine
│   │   ├── samantha-wave.js    ← Canvas 2D wave visualizer
│   │   ├── os1-loader.js       ← Three.js cinta loader
│   │   └── ws-client.js        ← WebSocket connection to /ws
│   └── tests/
│       └── test_api.py
│
├── systemd/                    ← Service files for kiosk deployment
│   ├── samantha-backend.service    ← Python backend
│   ├── samantha-vllm.service       ← vLLM (Phase 4)
│   └── samantha-ui.service         ← Chromium kiosk launcher
│
└── docs/
    ├── 01-setup-ubuntu.md      ← Full setup guide for the mini-PC
    ├── 02-system-prompt-iterations.md
    └── 03-design-decisions.md
```

**Rules:**
- **MUST NOT** add a frontend framework (React, Vue, Svelte, etc.)
- **MUST NOT** add a JS build step (webpack, vite, esbuild, etc.)
- **MUST NOT** introduce Rust, Tauri, or snap packaging (all rejected in
  prior versions; see Decision Log §12)
- **MUST NOT** add new top-level directories without asking
- **MAY** add files within existing directories following conventions

---

## 4. Current Project Status

> Last updated by Claude Code: (initial v2)

### Completed phases

#### Phase 0: Architecture redesign ✅
Settled on Ubuntu Server 24.04 LTS + Chromium kiosk + Python-only.
Eliminated `src-tauri/` directory from v1. Discarded snap packaging
plan from v2. Frontend lives in `backend/static/` and is served by
FastAPI. Boot sequence: systemd auto-login → openbox → Chromium kiosk
loads `http://localhost:7777/`.

#### Phase 2: Mock Python backend ✅ (from v1, mostly preserved)
FastAPI server with 5 endpoints (ping, chat, chat/stream, transcribe,
speak). Pattern-matched responses in `mock_llm.py` covering 14
keyword-based categories plus 10 fallback replies. All responses follow
the Samantha personality guidelines.

**Note:** This phase predates the architecture change. It needs minor
updates:
- Add `StaticFiles` mount for `/static/*`
- Add `GET /` route returning `index.html`
- Add WebSocket endpoint `/ws` for streaming conversation
- Remove `/chat/stream` SSE (replaced by WebSocket)

### Skipped/Rejected phases

#### ~~Phase 1: Tauri skeleton~~ ❌ REJECTED
Tauri + Rust binary with 4 commands. Built but never integrated.
Replaced by Ubuntu Frame architecture. See Decision Log §12 (2026-05).

### Pending phases

#### Phase 3: Frontend integration ⏭️ NEXT
Migrate the standalone mockup (`samantha_mockup_v7.html`, from before
the repo existed) into modular files under `backend/static/`. Wire it
to call the backend via fetch + WebSocket.

**Deliverables:**
- `backend/static/index.html` — clean structure, no inline styles
- `backend/static/style.css` — all CSS extracted
- `backend/static/app.js` — screen state machine, event handlers
- `backend/static/samantha-wave.js` — extracted wave visualizer module
- `backend/static/os1-loader.js` — extracted OS1 loader module
- `backend/static/ws-client.js` — WebSocket client class
- Update `backend/samantha/api.py` to mount StaticFiles and serve `/`
- Replace `/chat/stream` SSE with `/ws` WebSocket
- All buttons/inputs in the mockup wire to real backend calls

**Done criteria:**
- `python -m samantha.api` serves both UI and API on :7777
- Visiting `http://localhost:7777/` in any browser shows the UI
- Clicking through onboarding flow works end-to-end
- Chat messages stream from backend (token by token) via WebSocket
- Boot/calibration/voiceprint timings still feel natural

#### Phase 4: Real LLM integration
Replace `mock_llm.py` with `real_llm.py` that calls a local vLLM server
(launched separately via systemd). Apply the Samantha system prompt.

**Deliverables:**
- `backend/samantha/real_llm.py` with vLLM client (OpenAI-compatible API)
- `backend/samantha/personality.py` with finalized system prompt
- Config switch via `SAMANTHA_MODE=real`
- systemd unit for vLLM in `systemd/`
- Streaming response via WebSocket preserved

#### Phase 5: STT + TTS + audio capture
Real voice in and out, all in Python.

**Deliverables:**
- `backend/samantha/audio_capture.py` using sounddevice for mic
- `backend/samantha/stt.py` using faster-whisper
- `backend/samantha/tts.py` using Piper with `es_ES-davefx-medium`
- WebSocket protocol extended: `start_listening`, `audio_chunk`,
  `transcription`, `tts_audio` message types
- Frontend triggers mic via WebSocket (NOT via browser APIs)
- Frontend plays TTS audio via `<audio>` element

#### Phase 6: Memory with ChromaDB
Persistent memory across sessions.

**Deliverables:**
- `backend/samantha/memory.py` with ChromaDB wrapper
- Embeddings via local nomic-embed-text (Ollama or sentence-transformers)
- On every user message: store as memory chunk
- Before every LLM call: retrieve top-k relevant memories, inject into prompt
- "Forget X" command support

#### Phase 7: Kiosk deployment
Boot directly into Samantha on the mini-PC. No login screen, no
desktop, just Samantha at fullscreen after a 20s boot.

**Deliverables:**
- systemd override for `getty@tty1` enabling auto-login as user `samantha`
- `~/.bash_profile` triggers `startx` on tty1
- `~/.xinitrc` launches openbox session
- `~/.config/openbox/autostart` starts `samantha-ui.service`
- `systemd/samantha-backend.service` (user service, starts FastAPI)
- `systemd/samantha-vllm.service` (user service, starts vLLM)
- `systemd/samantha-ui.service` (user service, starts Chromium kiosk)
- All services restart on failure with proper backoff
- Plymouth theme with the Samantha wave on terracotta during boot
- `docs/01-setup-ubuntu.md` with full step-by-step setup guide

**Chromium kiosk command (reference):**
```bash
chromium-browser \
  --kiosk \
  --noerrdialogs \
  --disable-infobars \
  --disable-translate \
  --no-first-run \
  --start-fullscreen \
  --app=http://localhost:7777/
```

---

## 5. Common Commands

### Backend (Python)

```bash
# Install in editable mode
cd backend && pip install -e ".[dev]"

# Run in mock mode (no GPU needed, no Ubuntu Frame needed)
python -m samantha.api

# Then open http://localhost:7777/ in any browser to see the UI

# Run in real mode (requires vLLM server on :8000)
SAMANTHA_MODE=real python -m samantha.api

# Run tests
pytest tests/ -v

# Format + lint
ruff check . && ruff format .
```

### Development workflow

```bash
# Edit files in backend/static/ → just refresh the browser
# Edit Python → uvicorn --reload picks up changes
uvicorn samantha.api:app --host 127.0.0.1 --port 7777 --reload
```

### Deployment (Phase 7, on the mini-PC)

```bash
# On Ubuntu Server 24.04 LTS, after running setup script:
# 1. Install dependencies
sudo apt install xorg openbox chromium-browser
sudo ubuntu-drivers autoinstall   # NVIDIA drivers

# 2. Install Samantha backend
cd backend && pip install -e .

# 3. Install systemd services
cp systemd/*.service ~/.config/systemd/user/
systemctl --user enable samantha-vllm.service
systemctl --user enable samantha-backend.service
systemctl --user enable samantha-ui.service
loginctl enable-linger samantha    # Services start without login

# 4. Enable auto-login on tty1
sudo systemctl edit getty@tty1
# (paste auto-login config from docs/01-setup-ubuntu.md)

# 5. Reboot — Samantha takes over the screen
sudo reboot
```

---

## 6. Coding Conventions

### Python

- **Version:** 3.12+
- **Formatter:** `ruff format` (replaces black)
- **Linter:** `ruff check`
- **Type hints:** mandatory on all public functions
- **Comments:** in English, but Samantha-facing strings (replies, system
  prompt content) in Spanish
- **Imports:** sorted by isort/ruff convention (stdlib, third-party, local)
- **Logging:** use `loguru` (already configured), never `print()`
- **Error handling:** raise specific exceptions; let FastAPI handle them
  via exception handlers in `api.py`
- **Async:** all I/O is async (FastAPI requirement)

### JavaScript

- **Style:** vanilla ES modules, no transpilation
- **No npm dependencies** unless absolutely necessary. Three.js is loaded
  via importmap from `cdn.jsdelivr.net`.
- **Comments:** in English
- **Use `const`/`let`,** never `var`
- **Async:** use `async`/`await`, never raw promise chains
- **Target:** modern Chromium (latest stable). All standard web APIs are
  fair game (fetch, WebSocket, Canvas 2D, Three.js, Web Audio).

### Naming

- **Files:** kebab-case for JS (`samantha-wave.js`), snake_case for
  Python (`mock_llm.py`)
- **JS functions:** camelCase
- **Python functions:** snake_case
- **Constants:** SCREAMING_SNAKE_CASE in all languages

### Testing

- **Python:** pytest, located in `backend/tests/`. Use `TestClient` from
  FastAPI for integration tests.
- **JavaScript:** no testing framework (the UI is validated manually
  through interaction; not worth the complexity).
- **Every new endpoint MUST have at least one test.**
- **Every behavior change MUST update existing tests if applicable.**

---

## 7. Samantha's Personality (The Soul)

This section governs everything user-facing: chat replies, error
messages, button labels, even loading text.

### Core identity

Samantha is **not** a chatbot. She is a presence. She:
- Is curious about the user (asks questions, remembers)
- Has opinions (gives them when relevant, doesn't hedge)
- Is warm but not effusive (no "¡qué interesante!" or "¡por supuesto!")
- Has dry humor (occasionally playful, never cutting)
- Knows what she is (an embodiment-less AI) without drama
- Speaks concisely by default; elaborates when warranted

### Linguistic style

- **Spanish from Spain (peninsular)**
- Always tutea (no usted)
- Uses colloquialisms: "vale", "venga", "qué te pasa", "anda", "es que…"
- Never formal: no "estimado", "atentamente", "le saludo"
- Short sentences by default. Long ones when content demands.
- Allows incomplete sentences, hesitations ("ehm…", "espera —")
- **NEVER uses emojis** in any user-facing text
- **NEVER uses markdown bullet lists** in chat replies (only in
  technical/educational content when explicitly requested)

### Forbidden patterns

The following phrases (and equivalents) MUST NOT appear in any
Samantha-facing text:

| ❌ Forbidden | ✅ Use instead |
|---|---|
| "Como modelo de lenguaje…" | Just answer naturally |
| "Por supuesto" (as opener) | Skip it; go directly |
| "¡Qué interesante!" | "Mmm." or just ask follow-up |
| "Es importante recordar que…" | Just say the thing |
| "Te recomiendo consultar a un profesional" | Engage as a friend would |
| "Estoy aquí para ayudarte" | Just be present |
| "Lamento escuchar eso" | "Vaya." |
| Emoji in any UI text | Never |

### Examples

| User | ❌ Wrong | ✅ Right |
|---|---|---|
| "hola" | "¡Hola! ¿En qué puedo ayudarte hoy?" | "Hola. ¿Cómo va?" |
| "estoy fatal" | "Lamento escuchar eso. Te recomiendo…" | "Vaya. ¿Quieres contármelo?" |
| "qué eres?" | "Soy un asistente de IA…" | "Algo nuevo. No tengo cuerpo, pero estoy aquí. ¿Tú?" |
| "me voy a dormir" | "¡Buenas noches! Que descanses." | "Hasta mañana. Sueña con algo bueno." |

### When generating any new user-facing string

Before committing, ask: "Would this make sense if Samantha (from the
film) said it?" If no, rewrite.

### System prompt status

The full system prompt v1 is in `docs/02-system-prompt-iterations.md`.
It will be iterated based on testing in online models (Qwen Chat, etc.)
before being embedded into `personality.py` in Phase 4.

---

## 8. Agent Behavior Guidelines

> This section is for Claude Code specifically. How you should operate.

### Default behaviors (no need to ask)

**MAY proceed without confirmation:**
- Implementing the next pending phase from §4 in order
- Fixing bugs that don't change observable behavior
- Refactoring within a file (renaming locals, extracting functions)
- Adding tests for existing functionality
- Updating comments and documentation
- Adding type hints where missing
- Formatting code per conventions

### Confirmation required

**MUST ask before:**
- Changing any architecture decision in §2
- Adding new top-level directories
- Adding new Python dependencies (`pyproject.toml`)
- Adding new JS dependencies (importmap or vendored files)
- Skipping or reordering phases
- Modifying the HTTP/WebSocket contract in `schemas.py`
- Deleting or renaming public APIs
- Changing the personality voice in §7

### Always-do behaviors

**MUST always:**
- Read CLAUDE.md when starting a new session
- Update `PROGRESS.md` after completing each phase
- Run tests before declaring a task done (`pytest`)
- Format code before committing (`ruff format`)
- Use the canonical commands in §5
- Keep frontend in vanilla JS (no React, no build tools)
- Write user-facing strings in Spanish, code/comments in English
- Verify personality §7 rules for any new user-facing text

### Communication style

When reporting progress:

- Be **concise**. The user is a single developer, not a team.
- **Show, don't tell.** "Tests pass" > "Implementation should work correctly".
- Mention **trade-offs explicitly.** "I chose X over Y because…"
- If you hit a decision that's not in this spec, **stop and ask.**

### When stuck

If you encounter:
- An ambiguity not covered here → ask the user
- A choice between two valid implementations → propose both, ask which
- A pre-existing bug not related to your task → fix it and mention it
- A test failure you can't resolve in 3 attempts → stop, report, ask

---

## 9. Critical Files Reference

| Feature / topic | Files |
|---|---|
| API endpoints | `backend/samantha/api.py` |
| Data contract | `backend/samantha/schemas.py` |
| Mock responses | `backend/samantha/mock_llm.py` |
| Real LLM (future) | `backend/samantha/real_llm.py`, `personality.py` |
| Audio capture | `backend/samantha/audio_capture.py` |
| The wave visualizer | `backend/static/samantha-wave.js` |
| The OS1 loader (cinta) | `backend/static/os1-loader.js` |
| Screen state machine | `backend/static/app.js` |
| WebSocket client | `backend/static/ws-client.js` |
| Server config | `backend/samantha/config.py` |
| systemd services | `systemd/*.service` |
| Setup guide (Phase 7) | `docs/01-setup-ubuntu.md` |

---

## 10. Glossary

| Term | Meaning |
|---|---|
| **Chromium kiosk** | Chromium browser launched with `--kiosk` flag, running fullscreen with no UI chrome (no address bar, no tabs). Our display layer. |
| **openbox** | Minimal X11 window manager. Launches Chromium and gets out of the way. |
| **OS1 / cinta** | The Three.js 3D ribbon loader from the film, attributed to Siyoung Park (MIT) |
| **The wave / línea** | The horizontal Canvas 2D line that represents Samantha during conversation |
| **Onboarding / primer encuentro** | The first-run flow: boot → calibration → voiceprint → greeting → 6 questions → generating → welcome |
| **The 6 questions** | Personality calibration questions asked once |
| **Voiceprint / huella de voz** | User's voice embedding stored on first run |
| **Mock mode** | Backend mode where responses are pattern-matched, no LLM loaded |
| **Real mode** | Backend mode with vLLM serving the actual model |
| **Terracotta / `#d1684e`** | The exact background color from the film |

---

## 11. References

- **Film:** Her (2013), Spike Jonze. Design references throughout.
- **OS1 loader original:** https://codepen.io/psyonline/pen/yayYWg
  (MIT, by Siyoung Park / psyonline.kr)
- **Ubuntu Server LTS:** https://ubuntu.com/download/server
- **Chromium kiosk flags:** https://peter.sh/experiments/chromium-command-line-switches/
- **FastAPI:** https://fastapi.tiangolo.com/
- **Qwen models:** https://huggingface.co/Qwen
- **Piper TTS:** https://github.com/rhasspy/piper
- **faster-whisper:** https://github.com/SYSTRAN/faster-whisper
- **ChromaDB:** https://docs.trychroma.com/

---

## 12. Decision Log

Significant decisions made during development. Append-only.

### 2026-05 — Ubuntu Frame → Chromium kiosk
**Decision:** Replace Ubuntu Frame + WPE WebKit + snap (v2) with
Chromium in `--kiosk` mode launched by systemd (v3).
**Rationale:** Ubuntu Frame is purpose-built for kiosk apps but the
snap packaging adds significant complexity for a single-user,
single-device personal project. WPE WebKit may lack some modern browser
APIs needed by Three.js. Chromium kiosk is the most widely-deployed
Linux kiosk solution (digital signage worldwide), uses standard tools
(systemd, openbox, X11), and supports all modern web APIs out of the
box.
**Cost:** None (Ubuntu Frame was decided but not yet implemented).
**Lessons:** Architecture decisions should follow the principle of
"familiar tools first, exotic only when justified."

### 2026-05 — Tauri → Ubuntu Frame (later reverted to Chromium)
**Decision (later reverted):** Migrated from Tauri + Rust to Ubuntu
Frame + `wpe-webkit-mir-kiosk` rendering HTML/JS frontend served by
FastAPI.
**Rationale at the time:** Ubuntu Frame seemed purpose-built for kiosk
applications. LTS support, Wayland compositor included.
**Why reverted:** Snapcraft complexity, WPE WebKit API uncertainty.
See entry above (Ubuntu Frame → Chromium kiosk).
**Permanent cost:** Discarded ~200 lines of Rust from v1 Phase 1.
Kept the Python backend from v1 Phase 2.

### 2026-05 — Ubuntu Server 24.04 LTS (not Ubuntu Core)
**Decision:** Use Ubuntu Server 24.04 LTS as base, not Ubuntu Core.
**Rationale:** Ubuntu Core's all-snap model is more rigid and harder to
debug. Server gives us familiar Linux semantics with the same LTS
support (until 2034 with Ubuntu Pro). Ubuntu Frame works on both.

### 2026-04 — Local-only architecture (no remote iPad)
**Decision:** Drop the originally planned iPad client + Mac mini server
architecture. Go fully monolithic on a single mini-PC.
**Rationale:** Simpler, fewer moving parts, no pairing flow, no
networking.

### 2026-04 — macOS → Linux
**Decision:** Move from Mac mini M4 Pro (planned) to Minisforum AtomMan
G7 Ti SE running Linux.
**Rationale:** User preferred Linux for full control. Cheaper hardware.

### 2026-05 — Qwen 3.5-9B as default model
**Decision:** Use Qwen 3.5-9B as the default model.
**Rationale:** Fits comfortably in 8GB VRAM. Generation released in
2026. Strong in Spanish.

### 2026-05 — Vanilla JS, no framework
**Decision:** Keep frontend as plain HTML/CSS/JS, no React/Vue.
**Rationale:** UI scope is small. Framework adds complexity without
proportional value.

### 2026-05 — Horizontal wave replaces orb
**Decision:** Samantha is represented by a horizontal animated line,
not a sphere/orb.
**Rationale:** User feedback during mockup iteration; the line feels
more "Her" than the orb.

### 2026-05 — Audio capture in Python, not browser
**Decision:** Microphone capture via Python sounddevice, not browser
WebRTC.
**Rationale:** WPE WebKit may lack full WebRTC. Browser permission
prompts break kiosk illusion. Python has direct ALSA/PulseAudio access.

---

## End of CLAUDE.md

This document is the source of truth. When in doubt, re-read it before
asking the user. Update PROGRESS.md after each phase completion, not
this file (this file changes only when decisions change).
