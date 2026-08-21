# AGENTS.md — Samantha Project Specification (v3)

> **For Codex:** This is the single source of truth for the Samantha
> project. Read this entire document before making any changes. When in
> doubt about scope, architecture, or style, this document overrides your
> defaults. Update `PROGRESS.md` after completing each phase.
>
> **This is v3.** Previous versions used Tauri + Rust (v1) and Ubuntu
> Frame + WPE WebKit + snap (v2). v3 simplifies to Chromium in kiosk
> mode launched via systemd. See §12 for the full decision log.

---

## 0. TL;DR

Samantha is a **kiosk-style AI companion** inspired by the film *Her*.
She runs on a single mini-PC and interacts with one user via voice and
text through a fullscreen webview interface. Inference (LLM, TTS,
optionally STT) is local; ancillary rendering pieces (fonts, browser
STT) MAY use the network. Offline-only was a v1 principle that was
relaxed on 2026-05-13.

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

1. **Privacy with eyes open, not absolute.** TTS and STT inference stay
   local (Piper / vllm-omni + Qwen3-TTS / browser Web Speech). The LLM
   path is configurable: local llama-server (Qwen3-8B Q8) is supported,
   but the default since 2026-05-15 is **X.AI's Grok API** because A/B
   testing showed Qwen3-8B-Q8 produced visibly more verbose/theatrical
   replies than `grok-4-1-fast-non-reasoning` for the same prompt.
   Conversational content thus *does* leave the device when the API
   path is active. Ancillary network use (Google Fonts CDN, browser
   Web Speech) is still allowed. To restore "fully local LLM", unset
   `SAMANTHA_LLM_API_KEY` and point `SAMANTHA_LLM_SERVER_URL` at a
   local OpenAI-compatible server.

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
- ❌ A cloud-LLM wrapper (conversational inference stays local — Qwen via llama-server)
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

**Implications (v2 redesign, 2026-05-12):**
- The frontend lives in `frontend/` separate from `backend/`. Vite builds to
  `frontend/dist/`, which FastAPI's `StaticFiles` mounts at `/`.
- Phase 7 deployment now requires `cd frontend && npm install && npm run build`
  before starting the systemd services.

### 2.5 LLM Runtime + Model

**Decision (revised 2026-05-15):**
- **Default runtime:** X.AI Grok API (`https://api.x.ai`,
  OpenAI-compatible). Default model: `grok-4-1-fast-non-reasoning`.
- **Local fallback runtime:** llama.cpp via `llama-server`
  (OpenAI-compatible HTTP API) on the 4090 box at port 8000.
- **Local model (when used):** Qwen3-8B-Q8 GGUF (~8.5 GB).

**Rationale for the switch to Grok API:**
- A/B testing on 2026-05-15 with the v4 evocative system prompt:
  Qwen3-8B-Q8 → 200-word reply, three metaphors stacked, theatrical
  ("¿te sientes como si algo se hubiera roto en ti?"). Same prompt
  on `grok-4-1-fast-non-reasoning` → 110-word reply, one controlled
  metaphor, asks one concrete follow-up. The 8B model can't carry
  the nuance the personality spec asks for.
- Wall-clock latency comparable (~3s warm) — Grok isn't penalized.
- Cost: fractions of a cent per turn (~$0.2/M input + $0.5/M output).
  Negligible for personal use.

**Rationale for keeping the protocol agnostic:**
- The client (`backend/samantha/real_llm.py`) speaks plain
  OpenAI-compatible `/v1/chat/completions`. Adding a Bearer header
  when `llm_api_key` is set is the only difference vs local
  llama-server. Swapping to OpenAI / Anthropic / local-only is a
  config change, not a code change.

**Trade-off accepted explicitly:**
- Conversation content leaves the device when the API path is active.
  See §1 — privacy principle is "eyes open", not absolute. To restore
  full-local, see the override block in `config.py`.

**Rejected alternatives:**
- **vLLM (for LLM):** Faster on multi-stream GPU workloads but
  CUDA-only and shares VRAM with vllm-omni — fits awkwardly.
- **Ollama:** Wraps llama.cpp behind a daemon; extra surface area.
- **Qwen 3.6-27B local:** needs 16+ GB VRAM at Q4_K_M, fights
  vllm-omni for VRAM on the same 4090.
- **Llama 3.3-70B local:** needs ~40 GB VRAM — doesn't fit.
- **OpenAI / Anthropic API:** also valid; Grok picked for cost +
  available API key + reasonable Spanish quality.

### 2.6 STT/TTS

**Decision:**
- **STT:** faster-whisper Large v3 Turbo (~1.5GB model, runs on GPU
  when LLM is not actively generating)
- **TTS:** Piper with voice `es_ES-davefx-medium` (~40MB, CPU-only,
  ~200ms latency)

### 2.7 Memory: ChromaDB + SQLite ring + facts (v2)

**Decision:** ChromaDB at `~/.samantha/memory/chroma/` for long-term
semantic memory, paired with a SQLite ring buffer at
`~/.samantha/memory/state.db` for short-term (last N turns verbatim)
memory. Embedder: fastembed (ONNX runtime) with
`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`.

**Design principle:** **Samantha never forgets anything** (user
directive 2026-05-12). The store is append-only from the user's
perspective. `Memory.forget()` and `Memory.clear()` exist as admin/
test tools but are NOT wired to user input. Short-term ring eviction
removes from the buffer but the chunk remains in long-term forever.

**Structured facts** (`name`, `onboarding_completed_at`, future
preferences) are stored as `role: "fact"` chunks with `kind`/`value`
metadata. Excluded from conversational recall by default. Replaces
the `profile.json` concept — there is no parallel file. `profile.py`
is a thin facade over Memory that synthesizes a profile view from
the latest facts plus the 6 onboarding answer chunks.

**Why fastembed:** ChromaDB's default ONNX MiniLM is English-leaning
and Samantha is Spanish-first. fastembed runs the multilingual
MiniLM-L12-v2 model in-process (no extra daemon, no torch). Cost:
~130 MB deps + a one-time ~30s model download on first launch.

### 2.8 Audio I/O: browser Web Speech API for STT, Python for TTS

**Decision (revised 2026-05-13):** Microphone capture and speech
recognition happen in the **browser** via the Web Speech API
(`webkitSpeechRecognition`). TTS playback uses an HTMLAudioElement
with WAV bytes produced by Python (Piper) and served by /speak.

**Rationale (post-offline-relaxation):**
- Web Speech API is built into Chromium with native Spanish (`es-ES`)
  support and streams a transcript in real time. No model download,
  no Python audio stack, no per-OS audio quirks.
- Local Whisper (faster-whisper) remains an option for environments
  that genuinely need offline STT, but the offline kiosk requirement
  was relaxed on 2026-05-13 so the simpler path wins.
- TTS stays Python-side because Piper is local, deterministic, and
  the voice file (`es_ES-sharvard-medium`, ~73 MB) lives at
  `~/.samantha/voices/`.

**Implications:**
- Frontend calls `new webkitSpeechRecognition()` (AGENTS.md §6 marks
  this as the one approved browser-side audio API). The previous WS
  `listen` message path that delegated to Python is deprecated but
  still wired in `backend/samantha/api.py:_ws_handle_listen` for the
  mock fallback.
- Chromium kiosk needs `--use-fake-ui-for-media-stream` (or pre-granted
  mic permission via origin allowlist) so the kiosk illusion isn't
  broken by a permission prompt at first use.
- Audio playback (TTS) is an `<audio>` element fed by `/speak` (Piper).
  See §2.6 and `backend/samantha/tts.py`.

### 2.9 Language: Spanish (Spain)

**Decision:** All user-facing strings, voice synthesis, and prompts in
Spanish from Spain (peninsular).

**Code itself:**
- Code identifiers, comments, commit messages: **English**
- User-facing strings: **Spanish**
- Documentation: **English** (this file, READMEs)

### 2.10 Frontend Stack: React + Vite + TypeScript

**Decision:** React 18 + Vite + TypeScript in a separate `frontend/`
directory.

**Rationale:** The UI grew beyond what vanilla DOM manipulation
handles cleanly (4 screens with state, a wave canvas, a toggleable
history, a router). Component model + types + HMR pay back the
build-step cost quickly. The original vanilla-JS decision (§12,
2026-05) was correct for the original scope; that scope changed with
the v2 redesign.

**Cost:** Node.js as a dev dependency. Production deploy needs
`npm install && npm run build` once during install. Runtime on the
kiosk still needs only Python + Chromium.

---

## 3. Project Structure (Authoritative)

```
samantha/
├── AGENTS.md                   ← This file. Read first.
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
│   ├── samantha-llamacpp.service   ← llama-server (Phase 4)
│   ├── samantha-hermes.service     ← Hermes-Agent gateway (Phase 9 / v3)
│   └── samantha-ui.service         ← Chromium kiosk launcher
│
└── docs/
    ├── 01-setup-ubuntu.md      ← Full setup guide for the mini-PC
    ├── 02-system-prompt-iterations.md
    └── 03-design-decisions.md
```

**Rules:**
- **MUST NOT** introduce Rust, Tauri, or snap packaging (all rejected in
  prior versions; see Decision Log §12)
- **MUST NOT** add new top-level directories without asking
- **MAY** add files within existing directories following conventions

---

## 4. Current Project Status

> Last updated by Codex: (initial v2)

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


#### Phase 3: Frontend integration ✅
Migrated the standalone mockup into a React + Vite application served by FastAPI. Wired all user input/output through real-time bidirectional WebSockets.

#### Phase 4: Real LLM integration ✅
Replaced `mock_llm.py` with `real_llm.py` that interacts with OpenAI-compatible completion endpoints (including local llama-server and remote Grok).

#### Phase 5: STT + TTS + audio capture ✅
Wired microphone and TTS audio streaming using Piper, XTTS-v2, and CosyVoice fallback paths.

#### Phase 6: Memory with ChromaDB ✅
Added ChromaDB semantic memory database. Facts are saved during onboarding and recalled semantically.

#### Phase 7: Kiosk deployment ✅
Auto-login and openbox launch on boot configured via systemd user services.

#### Phase 8: UI Redesign ✅
Immersive UI redesign using Zustand state management, 3D ribbon rendering with Three.js, and multi-mode wave visualizer.

#### Phase 9: Hermes-Agent Integration ✅
Hybrid integration of NousResearch `hermes-agent` API server daemon on port `8642` with session history mapping, header propagation (`X-Hermes-Session-Id`), and disabling `/no_think` Qwen switch to enable agéntico tool use.

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

# Run in real mode (requires llama-server on :8000)
SAMANTHA_MODE=real python -m samantha.api

# Run tests
pytest tests/ -v

# Format + lint
ruff check . && ruff format .
```

### Frontend (Vite + React + TS)

**Package manager: pnpm** (NOT npm). npm has had recurring supply-chain
issues and we want stricter dep isolation. pnpm ships with Node via
`corepack` — no extra install. Activate once on a new machine:

```bash
corepack enable
corepack prepare pnpm@latest --activate
```

Then in `frontend/`:

```bash
cd frontend

# One time
pnpm install
# pnpm blocks postinstall scripts by default. esbuild needs its
# postinstall to fetch its binary; the project's package.json already
# whitelists it under "pnpm.onlyBuiltDependencies". If pnpm prompts:
pnpm approve-builds esbuild

# Dev server with HMR on :5173, proxies API to :7777
pnpm dev

# Production build to frontend/dist/ (consumed by backend)
pnpm build

# Type checking only
pnpm typecheck
```

**Do NOT run `npm install` in `frontend/`** — it would regenerate
`package-lock.json` and pull deps without the pnpm isolation guarantees.

### Development workflow

```bash
# Backend hot reload — edit Python and uvicorn picks it up
cd backend && uvicorn samantha.api:app --host 127.0.0.1 --port 7777 --reload

# Frontend HMR — edit anything under frontend/src/ and the browser updates
cd frontend && npm run dev
# then open http://localhost:5173/ (NOT :7777 during dev — Vite proxies the API)
```

### Deployment (Phase 7, on the mini-PC)

```bash
# On Ubuntu Server 24.04 LTS, after running setup script:
# 1. Install dependencies
sudo apt install xorg openbox chromium-browser
sudo ubuntu-drivers autoinstall   # NVIDIA drivers

# 2. Install Samantha backend
cd backend && pip install -e .

# 3. Build the frontend (Node required at install time, not at runtime)
#    pnpm via corepack — never use npm here (see §5 / decision log).
corepack enable
corepack prepare pnpm@latest --activate
cd ../frontend && pnpm install && pnpm approve-builds esbuild --all && pnpm build && cd ..

# 4. Install systemd services
cp systemd/*.service ~/.config/systemd/user/
systemctl --user enable samantha-llamacpp.service
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

The full personality spec — core identity, linguistic style, forbidden
patterns, examples, system-prompt status — lives in
**[`docs/personality.md`](docs/personality.md)**.

It governs everything user-facing: chat replies, error messages,
button labels, even loading text. Read it before writing any
Samantha-facing string. Any reference to "§7" or "personality §7"
elsewhere in this document points to that file.

---

## 8. Agent Behavior Guidelines

> This section is for Codex specifically. How you should operate.

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
- Read AGENTS.md when starting a new session
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

### 2026-05-15 — LLM switched from local Qwen3-8B to Grok API

**Decision:** Default LLM path is now X.AI's Grok API
(`https://api.x.ai`, model `grok-4-1-fast-non-reasoning`). Local
llama-server (Qwen3-8B Q8) remains supported as a config override.

**Rationale:** A/B test on the v4 evocative system prompt
("Eres Samantha. No eres un asistente virtual…"). Same prompt, same
user input ("Hoy estoy un poco depre…"):
- Qwen3-8B-Q8: 200 words, three stacked metaphors, theatrical.
- grok-4-1-fast: 110 words, one controlled metaphor, asks one
  concrete follow-up. Latency comparable (~3 s warm).
- Cost: ~$0.2/M input + $0.5/M output → fractions of a cent per turn.

The 8B model can't carry the nuance this personality asks for; it
keeps "thinking out loud". Bigger local models (32B / 70B) wouldn't
fit alongside vllm-omni on a single 24 GB GPU.

**Cost:** Privacy principle (§1) explicitly relaxed — conversational
content leaves the device when an API key is set. Documented in §1
and §2.5. To restore full-local: unset `SAMANTHA_LLM_API_KEY` and
point `SAMANTHA_LLM_SERVER_URL` at the local llama-server.

**Implementation:** `backend/samantha/real_llm.py` adds Bearer auth
when `llm_api_key` is set; `/no_think` suffix only appended for
Qwen-family models. No other changes — the OpenAI-compatible
protocol meant zero refactor.

**Lessons:** Premature commitment to "everything local" wasn't free.
Held in v1/v2 against well-meaning but model-side reality (8B-class
dense models don't have enough capacity for nuanced dialog with this
prompt style). Buying a few cents/day of API beat months of prompt
engineering against an undersized model.

### 2026-05-13 — Offline-only requirement relaxed; STT moves to browser

**Decision:** "Zero network dependency at runtime" is no longer a
hard product principle. The kiosk runs with internet on by default;
LLM and TTS still execute locally, but ancillary pieces (fonts,
browser Web Speech API for STT) MAY hit the network.

**Rationale:** Building+shipping a fully local stack for every piece
(Whisper model ~1.5 GB, vendored fonts, etc.) was paying ongoing
operational cost for a property the actual deployment doesn't
require. Conversational *content* still never leaves the device via
us — the LLM is local. The privacy boundary moves from "no network
at all" to "no cloud LLM and no conversational data exfiltration".

**Cost:** §2.8 was rewritten — browser mic is now the default STT
path (was: Python via sounddevice). Local Whisper remains optional.
Chromium kiosk needs `--use-fake-ui-for-media-stream` so the first-
use permission prompt doesn't shatter the appliance feel.

**Lessons:** Hard offline is a real engineering commitment, not just
an architectural label. Removing the constraint cut hours of Whisper
+ model-download + audio-stack work that the actual product didn't
benefit from.

### 2026-05-13 — npm → pnpm (corepack)

**Decision:** Frontend package manager is **pnpm**, not npm. Activated
via `corepack` (ships with Node) so there's no extra install step
during deployment.

**Rationale:** npm has had a string of supply-chain incidents (worms
spreading via postinstall, typosquats, maintainer compromises). pnpm's
defaults are stricter:
- Content-addressable global store + isolated symlinked `node_modules`
  per project — lateral compromise across projects is much harder.
- Postinstall scripts are *blocked by default*; each must be explicitly
  approved via `pnpm.onlyBuiltDependencies` in package.json plus
  `pnpm approve-builds`. Today only `esbuild` is approved.
- Lockfile (`pnpm-lock.yaml`) is stricter and deterministic.

**Cost:** Developer flow changes `npm` → `pnpm` everywhere. No runtime
impact — production kiosk still runs only Python + Chromium against
the static `frontend/dist/`.

**Lessons:** The default package manager isn't always the right
default. For a single-user appliance with no untrusted contributors,
pnpm's stricter posture costs nothing and removes a real attack
surface.

### 2026-05-13 — Vanilla JS → React + Vite + TypeScript

**Decision:** Replace the vanilla-JS-no-build frontend with React +
Vite + TypeScript in a separate `frontend/` directory.
**Rationale:** v2 UI redesign expanded scope (Ambient screen added,
immersive Conversation with history toggle, traveling wave packet,
persistence layer). The "UI scope is small" rationale of the
original vanilla decision no longer applies.
**Cost:** Node.js required for dev and build. `node_modules/` adds
~100 MB to the dev environment. Production kiosk runs only Python +
Chromium.
**Lessons:** "Familiar tools first, exotic only when justified"
still holds — but "familiar" includes React for a four-screen
stateful UI, not just because it's the JS default.

### 2026-05-13 — Memory architecture: short/long-term + facts + fastembed

**Decision:** Restructure memory into three layers — short-term
(SQLite ring buffer for the last 20 turns), long-term (ChromaDB for
semantic recall), and structured facts (`role: "fact"` chunks in
long-term). Swap the embedder to
`paraphrase-multilingual-MiniLM-L12-v2` via fastembed (ONNX). No
parallel `profile.json` file.
**Rationale:** Pure-similarity recall has a continuity gap (the
previous turn isn't always similar to the new one). Short-term
solves that. Facts give structured access to name, onboarding
marker, future preferences without polluting conversational recall.
The multilingual embedder fixes weak Spanish recall.
**Cost:** +130 MB deps (fastembed + ONNX model). One-time model
download on first launch (~30 s).
**Alternatives rejected:**
- **Mem0** (NousResearch): 5 s/turn latency for fact extraction,
  English-leaning output. See `docs/superpowers/specs/mem0-spike/`.
- **Hermes-Agent** (NousResearch): full task-agent runtime, optimizes
  a problem we don't have in v2. Parked for v3 at
  `docs/superpowers/specs/2026-05-12-hermes-agent-spike-scope.md`.

### 2026-05-12 — vLLM → llama.cpp
**Decision:** Use llama.cpp (`llama-server`) as the LLM runtime instead
of vLLM. Model stays Qwen 3.5-9B Q4_K_M (GGUF).
**Rationale:** Samantha is single-user, single-stream — vLLM's batching
engine, Ollama's daemon layer, both optimize for problems we don't
have. vLLM is also CUDA-only, which blocks all Mac-side development.
llama.cpp runs natively on Mac (Metal) and Linux (CUDA) with the same
model file and the same OpenAI-compatible HTTP API, so the Python
client is runtime-agnostic.
**Cost:** None (Phase 4 not yet implemented when changed). Phase 7
systemd unit becomes `samantha-llamacpp.service` instead of
`samantha-vllm.service`. Pydeps lose `vllm`; gain only `httpx`.
**Lessons:** Pick the runtime that's cheapest to develop against;
optimize for production throughput only when there's a real workload.

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

### 2026-05 — Horizontal wave replaces orb
**Decision:** Samantha is represented by a horizontal animated line,
not a sphere/orb.
**Rationale:** User feedback during mockup iteration; the line feels
more "Her" than the orb.

---

## End of AGENTS.md

This document is the source of truth. When in doubt, re-read it before
asking the user. Update PROGRESS.md after each phase completion, not
this file (this file changes only when decisions change).
