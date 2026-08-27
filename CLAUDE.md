# CLAUDE.md — JARVIS Project Specification (v4)

> **For Claude Code:** This is the single source of truth for this
> project. Read this entire document before making any changes. When in
> doubt about scope, architecture, or style, this document overrides your
> defaults. Update `PROGRESS.md` after completing each phase.
>
> **He is called JARVIS.** Until 2026-08-23 he was Samantha, and the
> package names, environment variables and systemd units still carry that
> name — `samantha_widget`, `samantha_kiosk`, `SAMANTHA_*`. Renaming them
> is not worth the churn. In prose he is JARVIS; in code, samantha.
>
> **This is v4.** v1 was Tauri + Rust, v2 Ubuntu Frame + WPE WebKit +
> snap, v3 Chromium in kiosk mode. v4 has no browser at all: a GTK4
> strip on the desktop, talking to a Hermes Agent gateway. Every one of
> those transitions is in §12.
>
> **Sections still carrying v3 assumptions are marked.** §0 is the
> shortest true description of what runs; where a later section
> contradicts it, §0 wins and the contradiction is a bug to report.

---

## 0. TL;DR

> **Rewritten 2026-08-23.** Everything below had drifted from the code:
> it described an 8 GB laptop GPU, a Chromium kiosk, FastAPI serving the
> UI and Piper as the voice. None of that had been true for a while. The
> decisions that caused the drift are in §12; this section is now what
> actually runs.

JARVIS — until 2026-08-23, Samantha — is an **AI presence that lives on
the desktop**: a strip along the bottom edge of the screen that listens
all the time, speaks in a cloned voice, watches the house's cameras, and
can act on it. Not a window you open. Something that is there.

**Stack at a glance:**
- **Hardware:** one box with an RTX 4090 (24 GB VRAM). VRAM is the
  budget everything competes for — see the note below.
- **OS:** Ubuntu with GNOME on X11 (`DISPLAY=:1`). Wayland out of scope.
- **Surface:** `widget/` — a GTK4 strip, no browser, no webview.
  Transparent, borderless, always above, drawn with GSK.
- **Brain:** Hermes Agent gateway on `:7777` (plugin `samantha_kiosk`),
  which gives JARVIS tools: memory, reminders, session recall.
- **LLM:** local `llama-server` with Qwen3.8-27B (GGUF), or X.AI's Grok
  API — a config switch. §2.5 and §12 carry the trade.
- **STT:** faster-whisper `large-v3-turbo`, on the GPU, in-process.
- **VAD:** Silero v5 over onnxruntime, CPU, always listening.
- **TTS:** CosyVoice 3 zero-shot on `:8093`, JARVIS' cloned voice.
- **Ears:** he answers to his name (§2.8). Everything else in the room
  is heard and dropped.
- **Vision:** YOLOv9 over onnxruntime against the house's RTSP cameras,
  borrowed from BarnDoor. Since 2026-08-24 it runs **inside the
  gateway**, as the plugin `samantha_vision` — one thread per named
  camera. The widget no longer opens a camera. Since 2026-08-25 he can
  also be **asked** (`mirar`), and the still he takes appears above the
  strip and nowhere else (§12). Since 2026-08-26 asking to see a camera
  gives the **moving** picture at 900x480, and a still only when a still
  is what was asked for.
- **Memory:** Hermes' own (`memories/USER.md`, `state.db`). ChromaDB
  (§2.7) still exists in `backend/` but the gateway path never uses it.
- **Language:** Spanish (Spain) — every user-facing string, prompt and
  voice.

**The processes, one machine:**

```
┌──────────────────────────────────────────────────────────┐
│  widget  (one Python process, GTK4 main loop)            │
│    the strip · Silero · Whisper · playback               │
│    speaks CosyVoice directly; never waits for audio      │
└───────────────┬─────────────────────────┬────────────────┘
      ws://127.0.0.1:7777/ws     http://127.0.0.1:8093
                │                         │
┌───────────────▼──────────────┐  ┌───────▼────────────────┐
│  Hermes gateway              │  │  CosyVoice 3 (Docker)  │
│   + samantha_kiosk (surface) │  └────────────────────────┘
│   + samantha_voice (TTS)     │
│   + samantha_vision (cameras)│
│   memory · cron · sessions   │       llama-server :8000
└───────────────┬──────────────┘       (Qwen3.8-27B, local)
                └──────────────────────────────┘
```

**The VRAM budget is the real constraint.** CosyVoice holds ~5.5 GB and
Whisper ~2.5 GB, so a 27B model at Q4_K_M does not fit alongside them
and spills onto the CPU. Measured 2026-08-23: 13.7 tok/s that way,
against 35 tok/s when the model fits. §1's "latency over correctness"
is what decides the quantisation.

**What is still here but unused:** `backend/` (FastAPI, `/chat`,
`/speak`, ChromaDB) and `frontend/` (React, Vite, the OS1 ribbon). The
widget replaced both. They stay until the widget has convinced; that was
an explicit condition, and the removal is plan 3.

---

## 1. Vision & Product Principles

### What he is

Samantha is **not** an assistant, a chatbot, an agent, or a tool. She is
a presence: a curious, warm, conversational AI that lives on a single
mini-PC in the user's home, learns about the user over time, and
behaves like a friend rather than a service.

The aesthetic is heavily inspired by the OS1 interface in *Her* (Spike
Jonze, 2013): terracotta orange, minimal typography, no clutter, voice
as the primary interaction mode.

### Product principles (in priority order)

1. **Privacy with eyes open, not absolute.** Every piece of inference
   runs on this box: the LLM (Qwen3.8-27B on llama-server), the voice
   (CosyVoice), the ears (Silero + Whisper) and the eyes (YOLO). Since
   2026-08-23 **nothing said in the room leaves it by default.**

   It is a default, not a property. Pointing the config at X.AI's Grok
   API is one line, and then the conversation — and a description of
   whatever the cameras see — goes to a third party. That switch was the
   default between 2026-05-15 and 2026-08-23, for reasons §12 records
   and a 27B model on a 4090 made obsolete.

   **Two leaks worth knowing about**, because both are silent:
   - **Hermes' `tts.provider` defaults to `edge`** — Microsoft's. If the
     `tts:` section of the Hermes config is missing, his words are
     synthesised in the cloud and it looks like it works. The config is
     git-ignored, so this must be re-applied on every box.
   - Cron/reminders resolve their own model, separately from the
     gateway. Pinning one and not the other splits the path.

2. **Conversational first, and able to act.** Samantha is designed for
   the relationship. She remembers, she asks, she has opinions. She is
   NOT a Siri/Alexa replacement — but since 2026-08-23 she *can* do
   things in the house: control it, remember, remind, look something up
   when the conversation needs it.

   Since 2026-08-23 she also **sees**: the house's cameras, through
   YOLO, close enough to notice somebody outside. Seeing obeys the same
   rule as acting — she mentions what she noticed, in her words, and
   never reports a detection.

   The order in that sentence is the principle. Acting serves the
   conversation, never replaces it. She does not announce her tools, does
   not narrate steps, does not offer menus of what she can do. If a
   request would make her sound like a task runner, she talks instead.
   The test: someone watching should not be able to tell where the
   conversation ended and the task began.

   Revised on 2026-08-23 — this principle used to end at "not for
   productivity", and §12 has the reasoning.

3. **Aesthetic restraint.** Minimalism in every screen. One color
   (`#d1684e`), one wave, one typography pair (Cormorant Garamond +
   Inter Tight). No badges, no emojis in UI, no marketing language.

4. **Latency over correctness.** A 30 tok/s response that is 90% as
   good feels infinitely better than a 5 tok/s response that is 100%
   good. Choose the faster model.

5. **Present, not launched.** He is not an application somebody opens.
   The strip is along the bottom edge of the screen from login, listening,
   with no window to focus, no icon to click and no settings UI. A systemd
   user service starts him; the desktop underneath stays the user's.

   Revised on 2026-08-23. This principle used to read "Appliance
   experience — when the device boots, it boots into Samantha… enforced
   by systemd + auto-login + Chromium kiosk mode". The appliance model
   went with the kiosk (§2.3, §12): the box is a desktop the user also
   works on, and taking the whole screen was the wrong trade.

### What he is NOT

- ❌ A multi-user system (single user, always)
- ❌ A cloud-LLM wrapper (conversational inference stays local — Qwen via llama-server)
- ❌ A mobile app (this desktop only)
- ❌ A coding assistant
- ❌ **A visible agent.** She uses tools; she never performs using them.
  No "ejecutando 3 de 5", no tool names out loud, no progress reports, no
  listing her own capabilities. A task that cannot be done without
  narrating it is a task she declines, in her own words.

**Removed 2026-08-23** (see §12): "❌ A productivity assistant" and
"❌ An agentic tool-using system (no function calling, no web search)".
Both were contradicted by Phase 9, which integrated Hermes *for* agentic
tool use, and the contradiction was resolved in favour of acting.

---

## 2. Architecture Decisions (Non-Negotiable)

These decisions are settled. Do NOT revisit them without explicit user
permission. If the user requests a change, ask for confirmation that
they understand the implications listed.

### 2.1 Hardware: one box, one RTX 4090

**Decision:** he runs on the machine that was already here — a desktop
with an RTX 4090 (24 GB VRAM).

**Revised 2026-08-23.** This section used to specify a Minisforum AtomMan
G7 Ti SE (RTX 4070 Mobile, 8 GB VRAM) bought for the purpose. That plan
belonged to the appliance model; when he became a widget on a desktop
the user already owned, the mini-PC stopped being the target.

**Implications, and they are the ones that shape everything else:**
- **VRAM is the budget three things compete for.** CosyVoice holds
  ~5.5 GB and Whisper ~2.5 GB, so the model gets what is left — about
  16 GB. That number, not model quality, picks the quantisation.
- A 27B at Q4_K_M does not fit alongside them and spills onto the CPU:
  13.7 tok/s measured, against 57 tok/s when it fits (§12, 2026-08-23).
- Everything is on one machine. There is no second box, no network hop,
  and every service in §0's diagram is on loopback.

### 2.2 Operating System: Ubuntu with GNOME on X11

**Decision:** Ubuntu with a full GNOME desktop, running **X11**
(`DISPLAY=:1`). Wayland is out of scope.

**Revised 2026-08-23.** This used to read "Ubuntu Server 24.04 LTS",
with no desktop, because the kiosk needed none. A widget needs a desktop
to sit on top of. X11 survived the change for a harder reason than
inertia: placing a window at an exact pixel and keeping it above others
is done through EWMH — `XSendEvent` of a `_NET_WM_STATE` ClientMessage
plus `XMoveResizeWindow`, via ctypes against libX11, no extra
dependency. GTK4 exposes no `set_keep_above` and no `move`, and
`gtk4-layer-shell`, the modern answer, is Wayland-only. Wayland would
mean either a compositor-specific protocol or losing the placement.

**Why Ubuntu, unchanged from the original decision:**
- LTS support until April 2029, extended until 2034 with Ubuntu Pro
- Official NVIDIA driver support (`ubuntu-drivers autoinstall`)
- Massive community: any problem has been solved before on StackOverflow
- Stable, predictable, "install and forget"
- Familiar Linux model (apt, systemd) for manual interventions

**Alternatives considered and rejected:**
- Arch Linux: too much manual maintenance
- Ubuntu Core 24: too rigid, harder to debug, all-snap model
- Pop!_OS: less standard, smaller community
- Fedora: smaller community than Ubuntu

**Implications:**
- **X11, not Wayland** — see the Decision above; this is now a hard
  constraint of the placement code, not a preference.
- NVIDIA drivers from official Ubuntu repositories
- All services managed via systemd **user** units (`systemctl --user`),
  since they need the user's session and its display

### 2.3 Display Layer: a GTK4 strip on the desktop

**Decision (2026-08-22, implemented 2026-08-23):** the surface is
`widget/` — a GTK4 window along the bottom edge of the screen.
Borderless, transparent, always above, drawn with GSK on the frame
clock, started by a systemd **user** service. **No browser and no
webview anywhere in the running system.**

**This replaced the Chromium kiosk**, which was v3's answer and is now
gone from the running system. §12 carries the decision and its cost; the
short version is that the kiosk owned the whole screen on a machine the
user also works on, and a presence that has to be exclusive is not a
presence but an application.

**Rationale:**
- **A strip is not a window.** It has no title bar, no focus, nothing to
  click. That is the product principle of §1.5 made literal, and no
  browser can be made to look like it without fighting the browser.
  (One exception since 2026-08-25: a photo he was asked for answers a
  press, to enlarge or dismiss it. Only the picture itself does, and
  only while it is up — a few seconds, and then there is nothing to
  click again.)
- **Native drawing.** GSK composites on the GPU. The wave animates on
  the frame clock, at no measurable cost.
- **One process.** The strip, the VAD, transcription and playback are
  threads in a single Python program, so the wave reacts to the state
  of the turn without a protocol between them. (Vision was one of them
  until 2026-08-24, when it moved into the gateway — see §12.)
- **Weight.** Measured against the alternative: ~389 MB resident, almost
  all of it Whisper, against Electron's baseline for the same job.

**Alternatives considered and rejected:**
- **Electron** — reconsidered on 2026-08-23 precisely because Hermes
  Desktop is Electron and already exists. Rejected again on the numbers;
  §12 has the table.
- **Keeping the Chromium kiosk** — see §12.
- **`gtk4-layer-shell`** — the modern way to place a panel, and
  Wayland-only. On X11 the placement is EWMH by hand (§2.2).

**Implementation, and the two things that bite:**

```
systemd --user: samantha-widget.service
  ↓
python -m samantha_widget      (venv with --system-site-packages)
  ↓
GTK4 window  →  EWMH: _NET_WM_STATE above + skip taskbar, XMoveResizeWindow
```

- **Cairo does not work on this machine.** PyGObject needs `gi._gi_cairo`
  from the system package `python3-gi-cairo`, which is not installed —
  and `python3-cairo`, which IS installed, makes that misleading. The
  failure is a `TypeError` raised inside the draw callback, where GTK
  swallows it: the strip appears, never draws, and logs nothing. Use
  `Gsk.PathBuilder` + `Gtk.Snapshot.append_stroke` (GTK 4.14+).
- **`_NET_WM_STATE` carries only two properties per message.** A third is
  dropped in silence. Send them in pairs and check with `xprop`.
- GNOME places the strip at x=66, width 1854, not 0/1920: the dock
  reserves those pixels. Taking them needs
  `_NET_WM_WINDOW_TYPE_DOCK`, which also gives up keyboard focus. Left
  as is, deliberately.
- Nothing about the appearance is provable by a test. Capture the screen
  (`ffmpeg -f x11grab`) — and confirm with `xwininfo -name` that you
  photographed the strip and not a lock screen.

### 2.4 Backend Stack: Python + FastAPI (Fullstack) — SUPERSEDED

> **Superseded 2026-08-23, kept for the history.** No FastAPI server
> runs. `127.0.0.1:7777` is now the **Hermes gateway**, not uvicorn, and
> nothing serves a frontend because there is no browser to serve it to.
>
> **`backend/` is not entirely dead, and the distinction matters:**
> `samantha.tts` is imported by the widget **as a library** to reach
> CosyVoice. That is the whole reason `PYTHONPATH` includes `backend/`
> when the widget runs. The FastAPI app, `/chat`, `/speak`, the
> WebSocket and ChromaDB are what is unused. Removing them is plan 3.
>
> Everything below describes v3 and is retained so the transition is
> legible.

> **Decision:** Python 3.12 + FastAPI + uvicorn, serving on
> `127.0.0.1:7777`. Backend serves BOTH the static frontend AND the API.
>
> **Rationale:**
> - vLLM is Python-native
> - faster-whisper and Piper have Python APIs
> - ChromaDB is Python-native
> - FastAPI's `StaticFiles` lets us serve the frontend from the same process
> - Single deployment unit, single process to monitor
> - Same-origin (no CORS issues for fetch/WebSocket)
>
> **Architecture pattern:**
>
> ```python
> app = FastAPI()
> app.mount("/static", StaticFiles(directory="static"), name="static")
>
> @app.get("/")
> async def index():
>     return FileResponse("static/index.html")
>
> @app.post("/chat") ...
> @app.websocket("/ws") ...
> ```
>
> When WPE WebKit visits `http://127.0.0.1:7777/`, it gets `index.html`.
> That HTML loads `/static/app.js`, which connects to `/ws` via WebSocket
> for streaming conversation.
>
> **Implications (v2 redesign, 2026-05-12):**
> - The frontend lives in `frontend/` separate from `backend/`. Vite builds to
>   `frontend/dist/`, which FastAPI's `StaticFiles` mounts at `/`.
> - Phase 7 deployment now requires `cd frontend && npm install && npm run build`
>   before starting the systemd services.

### 2.5 LLM Runtime + Model

**Decision (revised 2026-08-23 — the LLM came home):**
- **Default runtime:** llama.cpp `llama-server` on this box, `:8000`.
- **Default model:** **Qwen3.8-27B, UD-Q3_K_XL** GGUF. 20.8 GB, 57 tok/s.
- **Remote fallback:** X.AI Grok API (`https://api.x.ai`,
  OpenAI-compatible), `grok-4-1-fast-non-reasoning`. One config switch;
  §1.1 for what it costs.

**Why Q3 and not the usual Q4_K_M** — the only number that mattered:

| | VRAM | speed |
|---|---|---|
| Q4_K_M, llama.cpp b9115 | 22.3 GB | 13.7 tok/s |
| UD-Q3_K_XL, b10603 | 20.8 GB | **57.4 tok/s** |

Four times faster on less memory. Two causes, both needed: the smaller
quant fits **entirely** on the GPU next to CosyVoice and Whisper instead
of spilling layers onto the CPU, and b10603 is ~1500 builds of
optimisation ahead. §1.4 asks for 30 tok/s; this is the decision that
delivers it. Everything resident at once: 23.3 GB of 24.5.

**Three things that each cost a round, now in `samantha-config.yaml`:**
- **`enable_thinking: false`.** Qwen3.8 reasons by default and puts
  everything into `reasoning_content`; `content` comes back empty and the
  strip sits in "thinking" without ever speaking.
- **Provider and model are separate fields.** `model.default:
  custom:local` sends the literal string "custom:local" as a model name
  and the turn dies with a 404.
- **64K context is a hard floor.** Hermes refuses less and kills the
  turn, so `llama-server` must be started to match.

**The old default, for the record:**

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

**Decision (TTS revised 2026-08; STT unchanged in kind, moved in place):**
- **STT:** faster-whisper `large-v3-turbo`, in-process inside the widget,
  on the GPU. ~2.5 GB of VRAM resident, 81 s to load the first time and
  ~1 s afterwards; 0.23 s to transcribe 3.5 s of speech.
- **TTS:** **CosyVoice 3** zero-shot, in Docker on `:8093`, cloning his
  voice from one reference clip plus its transcript in `voices/`.
  24 kHz int16, synthesised clause by clause so he starts speaking
  before the sentence is finished. ~5.5 GB of VRAM.

**Piper was the v3 choice** (`es_ES-davefx-medium`, CPU, ~200 ms) and
lost on identity, not on latency: a preset voice is somebody else's.
XTTS-v2 was tried in between. `backend/samantha/tts.py` still dispatches
across all three; CosyVoice is the default and the only one used.

**A second lever, easy to miss:** CosyVoice takes a system prompt before
`<|endofprompt|>` that conditions *delivery* — pace, poise — not words.
The server injected a fixed "You are a helpful assistant." for months,
which is a personality too, just nobody's. Set it with
`SAMANTHA_TTS_COSYVOICE_VOICE_PROMPT`.

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

### 2.8 Audio I/O: everything in the widget, nothing in a browser

**Decision (revised 2026-08-23):** the widget owns the microphone and
the speakers, through PortAudio (`sounddevice`). There is no browser, so
there is no Web Speech API.

- **Always listening, and answering to his name since 2026-08-26.**
  Silero v5 VAD over onnxruntime, on the CPU, decides where an utterance
  starts and stops; `wake.py` then decides whether it was addressed to
  him. The 2026-08-22 decision below said "no wake word, no shortcut"
  and the user reversed it — a room he is in can now be talked in
  without talking to him. `SAMANTHA_WIDGET_WAKE_WORD` empty restores the
  old behaviour exactly. Two things that cost a measurement each:
  **Whisper does not hear "Jarvis"** (five spellings in one morning, so
  matching is a similarity ratio, not a comparison), and **the name was
  being discarded before Whisper saw it** — the detector cleared its
  buffer on every quiet frame, so the first syllable of a turn never
  survived. It keeps half a second of run-up now, and without that the
  wake word does not work at all.
- **Two switches on the strip** (2026-08-26): his ears and his voice,
  drawn at the right end of the wave. They exist because the obvious
  alternative does not work — "deja de escucharme" has to be heard to be
  obeyed, and "cállate" has to be heard over his own voice.
- **Transcription** is faster-whisper in the same process (§2.6).
- **Playback** is raw PCM from CosyVoice, written to the output stream
  clause by clause, strictly sequentially — synthesising clauses
  concurrently interleaves their chunks and garbles the speech.
- **The microphone is gated while he speaks**, or he hears himself.

**Two things that cost days, both silent:**
- **PortAudio's `callback=` mode segfaults under GTK.** No traceback, and
  it surfaces inside whatever unrelated `import` happens to be running.
  Read blocking from a thread of our own. `SAMANTHA_WIDGET_NO_MIC=1`
  exists because isolating the microphone is what found this.
- **A venv with `--system-site-packages` also sees `~/.local/lib`**, and
  a different numpy / anyio / websockets there gets loaded instead.
  Always run with `PYTHONNOUSERSITE=1`; `pip list --local` is the only
  honest view of what the venv holds.

**Status (2026-08-25):** verified against a human voice. A USB
microphone (`UACDemoV1.0`, `hw:2,0`) arrived; PipeWire's `default`
source routes to it, measured at RMS 0.0066 / peak 0.075 against the
0.0000 exactly — digital silence — that the onboard input used to give.
Five turns spoken and answered, transcriptions clean.
`SAMANTHA_WIDGET_FAKE_MIC` remains how the path is exercised with
nobody in the room.

> **The v3 decision, superseded, kept for the history.** Microphone
> capture and speech recognition happened in the **browser** via the Web
> Speech API (`webkitSpeechRecognition`); TTS playback used an
> HTMLAudioElement fed by `/speak`.

> **Rationale (post-offline-relaxation):**
> - Web Speech API is built into Chromium with native Spanish (`es-ES`)
>   support and streams a transcript in real time. No model download,
>   no Python audio stack, no per-OS audio quirks.
> - Local Whisper (faster-whisper) remains an option for environments
>   that genuinely need offline STT, but the offline kiosk requirement
>   was relaxed on 2026-05-13 so the simpler path wins.
> - TTS stays Python-side because Piper is local, deterministic, and
>   the voice file (`es_ES-sharvard-medium`, ~73 MB) lives at
>   `~/.samantha/voices/`.
>
> **Implications:**
> - Frontend calls `new webkitSpeechRecognition()` (CLAUDE.md §6 marks
>   this as the one approved browser-side audio API). The previous WS
>   `listen` message path that delegated to Python is deprecated but
>   still wired in `backend/samantha/api.py:_ws_handle_listen` for the
>   mock fallback.
> - Chromium kiosk needs `--use-fake-ui-for-media-stream` (or pre-granted
>   mic permission via origin allowlist) so the kiosk illusion isn't
>   broken by a permission prompt at first use.
> - Audio playback (TTS) is an `<audio>` element fed by `/speak` (Piper).
>   See §2.6 and `backend/samantha/tts.py`.

### 2.9 Language: Spanish (Spain)

**Decision:** All user-facing strings, voice synthesis, and prompts in
Spanish from Spain (peninsular).

**Code itself:**
- Code identifiers, comments, commit messages: **English**
- User-facing strings: **Spanish**
- Documentation: **English** (this file, READMEs)

### 2.10 Frontend Stack: React + Vite + TypeScript — SUPERSEDED

> **Superseded 2026-08-23, kept for the history.** `frontend/` still
> exists and nothing runs it. The four screens, the Zustand store and the
> Three.js OS1 ribbon were the kiosk's UI; the widget draws its own in
> GSK (§2.3). It stays until the widget has convinced — an explicit
> condition of the 2026-08-22 decision — and its removal is plan 3.
>
> **Node, pnpm and the whole build step are therefore not needed to run
> him.** They are needed only to build something nothing loads.

> **Decision:** React 18 + Vite + TypeScript in a separate `frontend/`
> directory.
>
> **Rationale:** The UI grew beyond what vanilla DOM manipulation
> handles cleanly (4 screens with state, a wave canvas, a toggleable
> history, a router). Component model + types + HMR pay back the
> build-step cost quickly. The original vanilla-JS decision (§12,
> 2026-05) was correct for the original scope; that scope changed with
> the v2 redesign.
>
> **Cost:** Node.js as a dev dependency. Production deploy needs
> `npm install && npm run build` once during install. Runtime on the
> kiosk still needs only Python + Chromium.

---

## 3. Project Structure (Authoritative)

```
os1-samantha/
├── CLAUDE.md               ← This file. Read first.
├── PROGRESS.md             ← The log, newest first (you append to this)
├── README.md               ← The short version, for humans
│
├── widget/                 ← HIM. The GTK4 strip and everything it does.
│   ├── pyproject.toml
│   ├── README.md           ← the venv, the models, the switches. Read it.
│   ├── samantha_widget/
│   │   ├── __main__.py     ← the process: threads and wiring
│   │   ├── window.py       ← the GTK4 window
│   │   ├── ewmh.py         ← above + placed, by ClientMessage (§2.2)
│   │   ├── geometry.py     ← where the strip goes
│   │   ├── theme.py        ← the colour, the shadow that must be killed
│   │   ├── wave.py         ← drawing, in GSK, on the frame clock
│   │   ├── wave_model.py   ← the wave as pure state, no GTK, testable
│   │   ├── bars_model.py   ← the equaliser, likewise
│   │   ├── vad.py          ← Silero: where an utterance starts and stops
│   │   ├── stt.py          ← faster-whisper, and the politeness it invents
│   │   ├── speech.py       ← splitting a reply into speakable clauses
│   │   ├── audio.py        ← PortAudio in and out, blocking, our thread
│   │   ├── gateway.py      ← the WebSocket to Hermes
│   │   ├── turn.py         ← the state machine of one turn
│   │   ├── photo.py        ← the band as pure state: size, batch, fade
│   │   ├── photo_area.py   ← the band drawn, and the click on it
│   │   └── fake_mic.py     ← speak INTO him, on a box with no microphone
│   ├── tools/              ← probes: render_wave, probe_gateway, probe_agentic
│   └── tests/
│
├── Hermes/                 ← the brain, pinned in-repo
│   ├── jarvis-soul.md      ← the persona (and see the warning in §7)
│   ├── samantha-config.yaml← model, provider, TTS. NOT the secrets.
│   ├── apply-config.sh
│   └── plugins/
│       ├── samantha_kiosk/  ← the surface he speaks through
│       ├── samantha_voice/  ← CosyVoice, from inside the gateway
│       └── samantha_vision/ ← the cameras: YOLO, the quiet rules, the
│                              alert, and `mirar`. Its own README.
│
├── tts-server/             ← CosyVoice 3 in Docker, on :8093
├── voices/                 ← the reference clip his voice is cloned from
├── systemd/                ← user units: widget, hermes, hermes-serve,
│                             llamacpp (+ backend/ui, dead with the kiosk)
├── docs/                   ← personality.md, designs, plans, decisions
│
├── backend/                ← FastAPI + ChromaDB. Only `samantha.tts` is
│                             still imported, as a library (§2.4).
└── frontend/               ← React + Vite. Nothing runs it (§2.10).
```

**Rules:**
- **MUST NOT** introduce Rust, Tauri, snap packaging, or a browser /
  webview of any kind (all rejected; see Decision Log §12)
- **MUST NOT** add new top-level directories without asking
- **MUST NOT** add code to `backend/` or `frontend/` — they are on their
  way out (plan 3). New work goes in `widget/`.
- **MAY** add files within existing directories following conventions

---

## 4. Current Project Status

> Rewritten 2026-08-23. The phase numbering below belongs to the kiosk
> era and stops being useful at Phase 9; what came after is dated
> instead. `PROGRESS.md` is the authority and carries what each day cost.

### Where he is now

**Working:** the strip, always on top and placed; the full voice turn
(VAD → Whisper → gateway → CosyVoice → playback); vision on the house's
named cameras, from inside the gateway — two configured, one of them
currently off; the persona; reminders that reach him unprompted;
the LLM local on this box at 57 tok/s.

**Delegating code runs through the BRIDGE by default, since 2026-08-27.**
§12 records the decision; this is the section that says what runs.
`samantha_code` follows the A2A bridge's firehose on :9910 unless
`plugins.entries.samantha-code.settings.bridge` is emptied, which selects
the v1 tee-file follower instead. What bridge mode buys is the console
showing milestones rather than raw lines, and three moments reaching the
user by voice — the assistant's own `AskUserQuestion`, a gate before
anything irreversible, and a closing checkpoint. The answer is routed by
the kiosk adapter straight to the bridge and never through the local
model, which fills its own tools with `args={}`. **So a box with no
`samantha-code-a2a.service` on it is in bridge mode too**: it reconnects
forever, at a 30 s ceiling, and says so in the journal the first time and
on every drop after.

**Not working / not done:**
- ~~**He has never heard a human voice.**~~ **He has, since 2026-08-25.**
  A USB microphone (`UACDemoV1.0`, `hw:2,0`) is plugged in, PipeWire's
  `default` source routes to it, and the local override that kept the
  microphone shut — `samantha-widget.service.d/no-mic.conf` — is gone.
  Five spoken turns, transcribed clean, answered out loud. That was the
  last task of widget plan 2 and it is done. `SAMANTHA_WIDGET_FAKE_MIC`
  stays: it is still how the path is exercised without a human present.
- **He can be asked to look — and that is the whole of what "asking"
  means.** Since 2026-08-25 the `mirar` tool answers "enséñame la
  entrada" with a sentence, and the photo appears above the strip for
  fifteen seconds. He does not see that photo: the model is text-only
  and is told only what YOLO labelled, so any visual detail beyond
  those eight labels is invented — and measured live, he invents it
  ("puerta cerrada, el porche vacío" against a tool that said only
  "no hay nadie"). He also calls `mirar` with **no** camera 5 times out
  of 5, even when one was named, so a question about one camera comes
  back as a survey of all of them. **Corrected 2026-08-26:** the "no
  camera 5 times out of 5" was measured through `mirar`, whose handler
  reads the whole argument dict. `ver_en_vivo` named that parameter
  `camara` and crashed on it instead — `'dict' object has no attribute
  'casefold'` — which is why the live view answered "la imagen en
  directo no me llega ahora mismo" and sounded like a camera fault.
- **"Who came this morning" still has no answer.** There is no
  detections table and no `revisar`; they are plan 2 of the vision
  spec.
- ~~**Nor is there live video.**~~ **There is, since 2026-08-26.**
  "Enséñame la entrada" puts the camera on the strip, moving, at
  900x480, until he is told to put it away, the picture is clicked, or
  two minutes pass. Measured against the house: ~1.2 s from the camera's
  burned-in clock to the screen, 11.7% CPU for the widget and 38.5% for
  the gateway, and the ceiling closing at 120.0 s exactly after 1200
  packets. The "considered and dropped" this line used to carry was
  reversed by the plan of 2026-08-25 and finished the day after.
- **Two of the three ways out are proven, the third is not.** The
  ceiling was measured; the spoken "ya está" and the click on the
  picture were not, because there is no way to send this window a click
  (no `xdotool`) and driving two sentences into one session is not
  something the fake microphone can do. Both want a human in the room.
- **Plan 3 is unwritten:** removing the kiosk, `backend/` and
  `frontend/`. Deliberately parked until the widget convinces.
- **The Hermes config is git-ignored**, so `tts:` must be re-applied by
  hand on any new box. Without it his words are synthesised by Edge TTS
  — which means they leave for Microsoft. `Hermes/apply-config.sh`.

### Completed phases (kiosk era, 1–9)

Phases 0–9 built the Chromium kiosk: FastAPI backend, React frontend,
llama.cpp, STT/TTS, ChromaDB memory, systemd deployment, the UI redesign
and the Hermes-Agent integration. All ✅, all superseded as a *surface*
by the widget — the LLM, TTS and Hermes work carried straight over.
`PROGRESS.md` has each one.

### Since (dated, not numbered)

- **2026-08-22** — decision: the widget replaces the kiosk (§12).
- **2026-08-23** — widget plan 1: the strip ✅
- **2026-08-23** — widget plan 2: the voice turn ⏸ blocked on a microphone
- **2026-08-23** — he may act: reminders that arrive unprompted ✅
- **2026-08-23** — JARVIS: the persona, the cloned voice ✅
- **2026-08-23** — vision: the cameras speak ✅
- **2026-08-23** — the LLM comes home: Qwen3.8-27B local, 57 tok/s ✅
- **2026-08-24** — vision moves into the gateway: the `samantha_vision`
  plugin, cameras plural and named ✅
- **2026-08-25** — the photo on demand: `mirar`, and a band above the
  strip that grows for it ✅ (the detections table: plan 2)
- **2026-08-26** — he delegates coding: the A2A bridge, the SDK behind
  it, and `terminal` as the fallback path ✅
- **2026-08-27** — the console shows milestones, and he asks: the three
  moments, and the answer routed by the adapter ✅

---

## 5. Common Commands

### The widget (this is the application)

```bash
cd widget

# One time. --system-site-packages is required: PyGObject and the GTK4
# typelib are system packages, not pip ones.
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -e ".[dev]"
# That flag also makes pip treat system packages as satisfying a
# requirement, so an install can be a silent no-op. Force what matters:
#   .venv/bin/pip install --ignore-installed -e ".[dev]"
# and check with `pip list --local`, the only honest view of the venv.

# Run him. PYTHONPATH reaches samantha.tts (CosyVoice) and Hermes'
# markers.py; PYTHONNOUSERSITE keeps ~/.local out of the way (§2.8).
DISPLAY=:1 PYTHONNOUSERSITE=1 \
  PYTHONPATH=$PWD/../backend:$PWD/.. \
  .venv/bin/python -m samantha_widget

# Tests + lint
.venv/bin/python -m pytest -v
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

`widget/README.md` documents every environment switch — freezing the
wave for a screenshot, running with no microphone, speaking INTO him,
dumping utterances to WAV. Read it before the first run. The cameras are
not among them any more — they are in
`Hermes/plugins/samantha_vision/README.md`.

### The services around him

```bash
# Install / refresh the user units
cp systemd/*.service ~/.config/systemd/user/
systemctl --user daemon-reload

systemctl --user enable --now samantha-llamacpp.service   # the LLM, :8000
systemctl --user enable --now samantha-hermes.service     # the gateway, :7777
systemctl --user enable --now samantha-widget.service     # him
loginctl enable-linger $USER    # so they survive without a login

journalctl --user -u samantha-widget.service -f
```

CosyVoice runs in Docker from `tts-server/cosyvoice/` and listens on
`:8093`. He answers without it, and is mute.

**After changing the persona** (`Hermes/jarvis-soul.md`) send `/new` then
`/approve` through the strip. Restarting the gateway is NOT enough — see
§7 and the warning there; this has cost an afternoon once already.

### When he hears you and says nothing

Measured 2026-08-26, and neither half is in the code: the strip printed
`→ Jarvis, ¿qué tiempo…`, the gateway logged nothing at all, and no
reply ever came. Two causes, both silent, both operational:

- **A run is stuck.** Hermes was still inside an earlier turn — one
  where the model called `tool_call` with `terminal` and got
  `'terminal' is not a deferrable tool` — and iterations are unbounded
  (`iteration 1/9223372036854775807`). Everything said afterwards is
  folded into that run (`↪ Redirected current run`) instead of being
  answered. **`/stop` clears it**, and the diagnosis is that any command
  answers `⏳ Agent is running`.
- **A new session eats its first turn.** With no home channel set, the
  first turn of a session comes back as `📬 No home channel is set for
  Samantha_Kiosk`, which the strip correctly discards as a system
  message — so the question that triggered it is simply gone. Fixed for
  good with `/sethome` (done 2026-08-26, `Home channel set to Kiosk`),
  which must be re-applied on any new box or after `state.db` is lost.

To tell "the gateway is stuck" from "the strip cannot reach it", stop
the strip first — a second connection replaces the first, so a probe
racing a running widget proves nothing:

```bash
systemctl --user stop samantha-widget.service
cd widget && PYTHONNOUSERSITE=1 ./.venv/bin/python tools/probe_gateway.py "¿Qué hora es?"
```

### Verifying anything visual

```bash
ffmpeg -y -f x11grab -video_size 1920x1080 -i :1 -frames:v 1 /tmp/strip.png
xwininfo -name "Samantha"          # did you photograph the strip, or the lock screen?
# The title is "Samantha" — window.py:36 sets it, and no code anywhere
# calls the window "samantha-widget"; that is only the unit's name. This
# line asked for the wrong one, so it answered "No window with name ...
# exists!" with the strip on screen and running (2026-08-25).
```

Nothing about his appearance is provable from a test, and a screenshot of
a locked session is a convincing picture of the wrong thing.

**A press CAN be sent, since 2026-08-26.** `widget/tools/click.py` drives
the pointer through XTEST by ctypes, the way `ewmh.py` reaches libX11 —
`libXtst` is installed even though `xdotool` is not. Anywhere this file
says a keystroke or a click cannot be delivered to the strip (§2.3, the
`SAMANTHA_WIDGET_STATE` note above), that is now only true of the
keyboard.

```bash
DISPLAY=:1 widget/.venv/bin/python widget/tools/click.py 1309 1032
```

### Legacy: backend and frontend

Neither runs (§2.4, §2.10). `backend/` still holds `samantha.tts`, which
the widget imports, so its tests are worth keeping green:

```bash
cd backend && ./.venv/bin/python -m pytest tests/ -q
```

The frontend build (`pnpm install && pnpm build`, never `npm`) produces
`frontend/dist/`, which nothing loads any more.

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

### JavaScript — no longer part of the running system

> There is no browser (§2.3), so none of this governs anything that
> runs. It applies only if you touch `frontend/`, which you should not
> (§3). **The UI language is Python + GTK4**, under the Python rules
> above, with one addition: `gi.require_version()` must run before the
> import it guards, so those imports cannot be at the top of the file and
> carry `# noqa: E402`. E402 is off in ruff's default set and is enabled
> explicitly in `widget/pyproject.toml` — otherwise ruff flags the noqa
> itself as unused.

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

## 7. The Personality (The Soul)

The full personality spec — core identity, linguistic style, forbidden
patterns, examples, system-prompt status — lives in
**[`docs/personality.md`](docs/personality.md)**.

It governs everything user-facing: chat replies, error messages, even
loading text. Read it before writing any string he might say. Any
reference to "§7" or "personality §7" elsewhere points to that file.

**Where the persona actually lives, and the trap in it.**
`Hermes/jarvis-soul.md` is the identity, and it is delivered through the
platform's `platform_hint` — **not** through `SOUL.md`. Hermes reads
`SOUL.md` only when `load_soul_identity=True`, which is passed by
`cron/scheduler.py` and nothing else, so a conversation through the strip
never sees it.

**The system prompt is fixed when the SESSION is born.** Editing the
persona file, the hint or the memory does not touch a session that
already exists, and restarting the gateway does not either — the session
lives in `state.db` and resumes exactly as it was. Send **`/new`, then
`/approve`** through the strip after any persona change. Hermes Desktop
appears to obey instantly only because it opens a session of its own,
and that discrepancy is the clue if you ever see it again.

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
- Keep new UI work in `widget/` (GTK4 + GSK) — not in `frontend/`, not in a browser
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
| The process: threads and wiring | `widget/samantha_widget/__main__.py` |
| One turn, as a state machine | `widget/samantha_widget/turn.py` |
| The window: borderless, above, and how it grows | `widget/samantha_widget/{window,ewmh,geometry}.py` |
| The photo band (drawing / pure model) | `widget/samantha_widget/{photo_area,photo}.py` |
| The wave (drawing / pure model) | `widget/samantha_widget/{wave,wave_model,bars_model}.py` |
| Colour, and the shadow to kill | `widget/samantha_widget/theme.py` |
| Listening: VAD and transcription | `widget/samantha_widget/{vad,stt}.py` |
| Speaking: clauses and playback | `widget/samantha_widget/{speech,audio}.py` |
| The link to the brain | `widget/samantha_widget/gateway.py` |
| Vision, and what is worth saying | `Hermes/plugins/samantha_vision/{vision,cameras}.py` |
| Being asked to look, and the JPEG it leaves | `Hermes/plugins/samantha_vision/{tool,snapshot}.py` |
| The `photo` frame, and the path it refuses | `Hermes/plugins/samantha_kiosk/{protocol,adapter}.py` |
| A sighting becomes a turn, not a sentence | `Hermes/plugins/samantha_vision/alert.py` |
| The cameras, and where the password goes | `Hermes/plugins/samantha_vision/README.md` |
| Whether he was being spoken to | `widget/samantha_widget/wake.py` |
| The two switches (drawing / pure model) | `widget/samantha_widget/{wave,switches}.py` |
| The live view: session, tools, decoding | `Hermes/plugins/samantha_vision/{live,live_tool}.py`, `widget/samantha_widget/live_decode.py` |
| Testing without a microphone | `widget/samantha_widget/fake_mic.py` |
| The surface Hermes speaks through | `Hermes/plugins/samantha_kiosk/` |
| His identity | `Hermes/jarvis-soul.md` (and §7 — sessions!) |
| Model, provider, TTS provider | `Hermes/samantha-config.yaml` |
| CosyVoice, and the voice prompt | `tts-server/cosyvoice/server.py`, `backend/samantha/tts.py` |
| The reference clip | `voices/` |
| Services | `systemd/*.service` |
| Design, plans, decisions | `docs/superpowers/` |

---

## 10. Glossary

| Term | Meaning |
|---|---|
| **The strip / la tira** | The GTK4 window along the bottom edge of the screen. Our display layer, and him. |
| **The gateway** | The Hermes Agent daemon on `:7777`. His brain, memory and tools. Not to be confused with `hermes serve` (`:8642`), which is what Hermes Desktop connects to. |
| **The turn** | One exchange, from the VAD deciding somebody is talking to the last clause of his reply being played. |
| **EWMH** | The X11 convention for telling a window manager to keep a window above others and put it at an exact pixel. GTK4 has no API for either (§2.2). |
| **Chromium kiosk** | v3's display layer, replaced 2026-08-23 (§2.3, §12). Mentioned only in history. |
| **openbox** | The minimal X11 window manager the kiosk used. Gone with it; the desktop is GNOME. |
| **OS1 / cinta** | The Three.js 3D ribbon loader from the film, attributed to Siyoung Park (MIT). In `frontend/`, unused. |
| **The wave / línea** | The line that represents him on the strip, drawn in GSK. Four states: idle, listening, thinking, speaking. |
| **The band / la banda** | The strip's second half, above the wave and zero pixels tall until a photo arrives. It grows the window rather than opening one. |
| **Onboarding / primer encuentro** | The first-run flow: boot → calibration → voiceprint → greeting → 6 questions → generating → welcome |
| **The 6 questions** | Personality calibration questions asked once |
| **Voiceprint / huella de voz** | User's voice embedding stored on first run |
| **Mock mode / Real mode** | Modes of the unused FastAPI backend (§2.4). Nothing in the running system has modes. |
| **Terracotta / `#d1684e`** | The exact colour from the film. It moved from the strip's background into the line itself when the strip went transparent. |

---

## 11. References

- **Film:** Her (2013), Spike Jonze. Design references throughout.
- **OS1 loader original:** https://codepen.io/psyonline/pen/yayYWg
  (MIT, by Siyoung Park / psyonline.kr)
- **GTK4 / GSK snapshot API:** https://docs.gtk.org/gtk4/class.Snapshot.html
- **EWMH spec (`_NET_WM_STATE`, §7.5):** https://specifications.freedesktop.org/wm-spec/latest/
- **Hermes Agent:** https://github.com/NousResearch/hermes-agent
- **CosyVoice:** https://github.com/FunAudioLLM/CosyVoice
- **Silero VAD:** https://github.com/snakers4/silero-vad
- **faster-whisper:** https://github.com/SYSTRAN/faster-whisper
- **llama.cpp:** https://github.com/ggml-org/llama.cpp
- **Qwen models:** https://huggingface.co/Qwen
- **Piper TTS:** https://github.com/rhasspy/piper (v3's voice, superseded)
- **FastAPI:** https://fastapi.tiangolo.com/ (unused backend)
- **ChromaDB:** https://docs.trychroma.com/ (unused backend)

---

## 12. Decision Log

Significant decisions made during development. Append-only.

### 2026-08-27 — The console gets milestones, and JARVIS can be asked

**Decision:** the A2A bridge becomes the default way he delegates
coding on this box. `samantha_code` follows the bridge's SSE firehose
and turns it into two things: milestones on the strip's console
(«Leyendo el proyecto…», «Editando vad.py», «Tests: 12 pasan, 2
fallan») instead of raw stream lines, and three moments that leave the
loop and reach the user by voice — the assistant's own
`AskUserQuestion`, a gate before anything irreversible, and a closing
checkpoint. `terminal` and the skills it drives (§12, 2026-08-26,
"terminal stops being forbidden") stay as the fallback for a box with
no bridge on it —
`plugins.entries.samantha-code.settings.bridge: ""` is the switch.

**The gate partially reverses "he can run ANY command on this box"**
(§12, 2026-08-26, same entry), at the user's request.
`SAMANTHA_CODE_GATES` defaults to `git push, rm -r, rm -f, sudo`;
nothing else asks. A gate nobody answers **denies after 300 s**; a
checkpoint nobody answers **closes after 600 s** and says so; a held
question has **no timeout at all** — it is exempted from the run's own
900 s silence watchdog, because the user thinking is not the run going
quiet.

**The answer bypasses the model, deliberately.** The probe of
2026-08-27 (`docs/superpowers/specs/2026-08-27-askuserquestion-probe.md`)
found there is no result-injection path — `can_use_tool` only rewrites
a tool's *input*, and an answer is necessarily a *result* — so what
steers a held `AskUserQuestion` is a `PreToolUse` deny carrying the
user's words as its reason. The kiosk adapter therefore diverts the
next spoken sentence straight to the bridge while a question is
pending, never through the model: the local model fills its own tools
with `args={}`, measured six times against the plugin this design
replaces (§12, 2026-08-26, "terminal stops being forbidden").

Full design: `docs/superpowers/specs/2026-08-27-samantha-code-v2-design.md`.

**Cost, stated plainly:** a strip that routes an answer back has
nothing to say about it — `error("")` settles the wave silently, using
a guard (`if message:`) that has existed since the first turn
implementation, rather than a new frame an older strip would not know.
And a box without `samantha-code-a2a.service` now reconnects to the
firehose forever at debug level instead of failing loudly, where v1's
tee-file follower would have simply stopped.

### 2026-08-26 — The bridge drives the SDK, so a task can be stopped

**Decision (the user's):** integrate `claude-agent-sdk` into the code
bridge, for two abilities and not for elegance — **`interrupt()`** and a
**session that continues**.

**What the spike found first, and it corrects the premise the request
arrived with** (`docs/superpowers/specs/2026-08-26-claude-agent-sdk-spike.md`):
the SDK is not an embedded engine. Inside, it runs
`claude --output-format stream-json --verbose` as a subprocess and
parses the lines — to the letter what `runner.py` already did. Nothing
is saved on parsing; what is bought is what sits on top.

**And it was buying a fix, not a feature.** `tasks/cancel` existed and
moved a task to CANCELED while the assistant carried on working to the
end. The protocol was saying one thing and the machine doing another,
which is worse than not offering cancel at all. Measured after: cancel
at 18.0 s, stream closed at 18.1 s, in the middle of a 90-second
command.

**Two things measured that invert the obvious reading:**

- **The permission gate is the `PreToolUse` hook, not `can_use_tool`.**
  The callback was never consulted for `Bash` — with `allowed_tools`,
  without it, and with `setting_sources=[]`. The SDK warns about the
  first case itself. Nothing here depends on it yet (the run is
  `bypassPermissions`, which is what `--dangerously-skip-permissions`
  was), but any future "JARVIS asks before an `rm`" is a hook.
- **A resumed session can decide the work is already done.** Asked twice
  for the same thing, the second run answered "Terminado, señor." in two
  seconds having done nothing — correct, and indistinguishable from a
  failure. `metadata: {"fresh": true}` is the way out, and sessions
  expire after two days on their own.

**Cost, stated rather than discovered:** a ~386 MB venv of its own for
the bridge (the SDK bundles the CLI; the widget's environment holds
Whisper and is not worth disturbing), and one path in this repo now tied
to Claude Code specifically. That is exactly why A2A stays the outward
face and the CLI stays the fallback: a box without the SDK, or with
OpenCode, behaves as it did before.

### 2026-08-26 — He delegates coding, and `terminal` stops being forbidden

**Decision (the user's):** JARVIS gets the `terminal` toolset, and
coding is delegated through the skills Hermes already ships —
`claude-code`, `opencode`, `codex`, installed in
`.hermes/home/skills/autonomous-ai-agents/`. This reverses "deliberately
absent: terminal, file, code_execution, browser" from the 2026-08-23
entry below.

**What forced it was not preference but a wall.** The design agreed
earlier that evening built the connection ourselves — an A2A bridge
(`Hermes/bridges/code-a2a/`) and a plugin to stream its output onto the
strip. The bridge works and is verified end to end. The plugin does not,
and the reason is in the model rather than the code: **it calls a tool
of ours with no arguments at all** — `args={}`, and Hermes' own
`user_task` arriving as the string `"None"`, measured across six calls.
That is the failure §4 already records for `mirar` ("no camera 5 times
out of 5, even when one was named"), and a wording that spelled it out
changed nothing there either.

It fills `terminal`'s arguments correctly, because it has been trained
on it. And the official skills are written entirely in those terms:

    terminal(command="claude -p '…'", workdir="/path", timeout=120)

Without `terminal`, every one of them is inert. The user's own pointer
is what found this — *"lo que se usa en otras implementaciones"* — after
an evening of building the thing that already existed.

**Verified the same night**, on a deliberately broken test: *"Hecho,
señor. Claude Code lo tenía claro desde el principio: `suma()` estaba
restando en vez de sumar. Corrigió la línea y el test pasa — uno de uno,
sin más cambios. Lo he verificado yo mismo antes de decirle que sí."*
The file was corrected, and he had checked it before saying so.

**Cost, stated rather than discovered:** he can run ANY command on this
box now, not only the assistant. What bounds it is `agent.max_turns: 25`,
llama-server's `--n-predict`, and the fact that this is one machine
belonging to the person talking to him. `file`, `code_execution` and
`browser` stay out.

**What the A2A work is still worth**, since it was not thrown away: the
bridge is the interoperable path — an agent on another machine, or one
that is not a CLI at all, reaches him without `terminal` and without a
shell. `a2a_call` works today and was verified before this. It is the
right answer for a peer; `terminal` is the right answer for a CLI
sitting on the same disk.

### 2026-08-26 — The alert grows a picture, and the wake word does not

**A sighting now shows the frame it was seen in** (user: "cuando captura
algún movimiento debe mostrar esa captura, no solo decirlo"). This
reverses the last paragraph of the 2026-08-25 entry below, which left
the unprompted alert deliberately mute in pictures and said the
mechanism was already there. It was: `write_jpeg` and `push_photo`
existed for `mirar`, and `_report` already held the frame it had just
run YOLO over. The words follow the picture, a failed photo never costs
the sentence, and the push goes onto the GATEWAY's loop rather than the
turn's — the distinction that cost this morning.

**And a wake word that is heard rather than read was built, measured and
switched off.** Hermes ships one (`tools/wake_word.py`, openWakeWord,
on-device, `hey_jarvis` among its bundled models) and the user asked to
use what exists rather than reinvent it. Its own module opens a second
microphone stream — which it warns about — so the engine was fed the
widget's frames instead. The numbers are why it is off:

| | score |
|---|---|
| synthesised Spanish "Hey Jarvis" | 0.359 |
| the user, real microphone, ×4 | 0.25, 0.25, 0.29, 0.29 |
| threshold for a usable detector | 0.60 |

There is no gap to put a threshold in: 0.25 fires on the television,
which this strip demonstrably hears. And it cost ~6 CPU points on every
frame to never fire — 18.3% → 14.1% when removed, measured while the
user was reporting the machine was warm. `SAMANTHA_WIDGET_HOTWORD`
defaults to empty; the code stays for a model trained on this voice, or
for the sherpa engine, which takes an arbitrary phrase and would hear
"Jarvis" without the "Hey".

**Two facts about openWakeWord worth keeping:** 0.4.0 takes model PATHS
(`wakeword_models=` is a later API and fails inside `AudioFeatures`),
and it needs 1280-sample chunks — the same audio peaks at 0.052 on 512
and 0.359 on 1280. It does not fail on short chunks; it just never
scores.

**The other two things measured today, both user-reported:**

- **"Se cortan palabras cuando se habla."** `SAMANTHA_WIDGET_DUMP`
  caught it: one sentence arriving as two turns two seconds apart, every
  utterance ending in exactly 0.7 s of silence — the threshold — and the
  second carrying speech from its first sample. A breath mid-sentence is
  longer than 0.7 s. `_SILENCE_SECONDS` is 1.2 now.
- **He had no internet, and it was one config line.** The comment above
  `platform_toolsets` said web search "waits on tokens". It does not:
  Hermes ships keyless providers, `check_web_api_key()` returns True
  with nothing configured, and a direct call came back with real results
  first try. The `browser` toolset — the alternative the user suggested,
  reasonably, since Hermes Desktop has one — needs the `agent-browser`
  CLI over npm, which §12 (2026-05-13) moved away from.

**And the accent that could not be fixed here.** Asked for an Andalusian
voice, `SAMANTHA_TTS_COSYVOICE_VOICE_PROMPT` is the lever §2.6 names and
it is only half of one: the accent comes from the REFERENCE CLIP, today
a neutral-accent advert. Measured by the only instrument available — the
user listening — the change was "un poco igual". A southern voice needs
a southern clip, and choosing it is not something a model that cannot
hear should do.

### 2026-08-26 — BarnDoor's rule back, and a ceiling on a turn

**Two decisions, and the second is what makes the first affordable.**

**The escalation is removed.** The user: "no es práctico si solo mira
cada cierto tiempo, es necesario usar el mismo que BarnDoor". This
reverses the first half of the 2026-08-24 entry below. What stays is
BarnDoor's rule whole — 180 s per `(camera, label)`, a person during
quiet hours beating it, and the 30 s night floor the user decided on
after the 19,200-utterances measurement. What goes is ours: the ×5 and
×20 widening, and the `_last_seen` / `_level` bookkeeping it needed.

**The cost is exactly the one the escalation was built for, and it is
now a test rather than a surprise:** six hours of somebody standing in
the driveway is 120 mentions, not eight. With `allow_gateway_injection`
on, each of those is a spoken turn and a model call. The trade the user
made is insistence over quiet, knowingly; the escalation's own cost was
that any person at a camera sitting at the hourly level was silenced for
up to an hour, which is the failure mode of a thing whose job is telling
you who is around the house.

**And `agent.max_turns: 25`.** Hermes is unlimited by default —
`resolve_turn_limit`: "max_turns is unlimited unless the user sets an
explicit positive integer cap" — which is what
`api_calls=1/9223372036854775807` meant in every log line. Twice on
2026-08-26 a turn looped on a tool this platform does not have and ran
until somebody noticed: 15,099 tokens in one generation, GPU at 93% and
391 W, the kiosk's 90 s watchdog having closed that turn minutes
earlier. 25 against the 1-4 an ordinary spoken turn uses. It is the
backstop `--n-predict 2048` is not: that caps one generation, this caps
a loop of them.

**A trap this uncovered, and it will bite again:** `apply-config.sh`
deep-merges the tracked config over the live one, so applying any
setting re-asserts every OTHER tracked value. Applying the timestamp fix
silently turned `allow_gateway_injection` back on — the switch that had
been off since 2026-08-25 — because the tracked file says `true`. A
local override that matters must be changed in the tracked file, not
only in `.hermes/home/config.yaml`.

### 2026-08-26 — The tools were reachable; the clock was not

**The user's complaint was that Hermes' tools do not get invoked, which
is the whole reason for using Hermes.** The investigation found one
cause underneath several symptoms, and it is a single line of Hermes'
own system prompt (`agent/prompt_builder.py:499`):

    - Current time, date, timezone → use terminal (e.g. date)

This platform has no `terminal`, deliberately (§12, 2026-08-23: "she
lives in a living room, and none of them can be used without narrating
what she is doing"). So the prompt sends him to a tool that is not
there, and everything else follows:

- **The runaway runs and the heat.** `'terminal' is not a deferrable
  tool`, met inside a loop with no iteration limit: 15,099 tokens in one
  request, GPU at 93% and 391 W, twice today and at least once
  yesterday.
- **Reminders that never arrive.** Having failed to find the clock he
  invents it. Asked at 14:23 for a reminder "in six minutes", he filed
  it for 17:34 — he believed it was 17:28. The cron was created
  correctly; it was simply three hours away.

**Fix: `gateway.message_timestamps.enabled`,** which prefixes every user
message with `[Wed 2026-08-26 14:34:47 CEST]`. Hermes defaults it OFF
because it changes what every gateway user sees; here it is the
difference between reminders working and not. Measured after: the time
asked and answered correctly, a two-minute reminder filed for exactly
two minutes later, fired, and spoken aloud by the strip.

**Two things this corrected in our own understanding, both worth
keeping:**

- **Hermes' real log is `.hermes/home/logs/agent.log`, not the journal.**
  `tool <name> completed` and `Turn ended: … tool_turns=N` live there.
  Reading the journal alone produced the confident and wrong conclusion
  that no tool was ever called — when `cronjob`, `todo`, `memory` and
  `ver_en_vivo` all were.
- **"He said he did it without doing it" was half wrong.** Asked to note
  a preference he answered "ya lo tenía apuntado" with `tool_turns=0` —
  and it WAS already in `memories/USER.md`, put there by the memory
  provider rather than by a tool call. Check the store before calling it
  a hallucination.

**And his memory had gone stale in a way that shaped his behaviour.**
`memories/MEMORY.md` still carried "El kiosko es solo voz: no hay
pantalla ni herramienta de visión… Responder con descripción verbal y
ofrecer a vigilar y avisar" — false since the band was built, and the
source of both the refusals to show a camera and the "¿le aviso?"
endings the user asked to remove the same morning. Corrected in place.
A persona edit does not reach what the agent has written down about
itself.

**Also decided here:** the tool-search bridge is off for this platform
(`tools.tool_search: false`). It activates as soon as a single
deferrable tool exists — `mirar` guaranteed that — and its catalogue
advertises tools this platform does not have, `terminal` included.

**Still open, and it is the real backstop:** nothing bounds a Hermes run
(`api_calls=1/9223372036854775807`). `--n-predict 2048` on llama-server
caps one generation, not a loop of them.

### 2026-08-26 — He answers to his name, and the strip gains two switches

**Decision (the user's):** he only wakes on a word, "Jarvis" by default,
and after he answers the next thirty seconds need no name. This reverses
"always listening… no wake word, no shortcut" — §2.8, and the 2026-08-22
entry below, where it was one of four things closed in that
brainstorming.

**Why the reversal is not a small one.** "Always listening" was a
product claim, not a technical default: he is present, and a presence
you have to summon is an application. What changed it is that the box
lives in a room where people talk to each other, and everything said in
it became a turn. The compromise is the window: a name opens the
conversation, and the conversation stays open for half a minute after
each answer, so only the FIRST sentence pays.

**Two measurements that decided the design, both of which invert the
obvious implementation:**

- **Whisper does not hear "Jarvis."** One synthesised sentence through
  the real path came back as "Carbis", "Harvish", "Jervis", "Jarvis"
  and "Harvies" in one morning. Exact matching would ignore four of
  five, and being ignored is the one failure a wake word cannot afford
  — the user repeats himself, louder, and concludes it is broken. The
  comparison is a similarity ratio at 0.6, which is where all five pass.
  It is ours, and measured; it is NOT a fifth BarnDoor constant.
- **The name was being thrown away before Whisper saw it.** The
  detector cleared its buffer on every frame under the VAD threshold,
  so a turn began at the first frame loud enough to count and the
  syllable in front of it was gone: "Jarvis, ¿qué día es hoy?" arrived
  as "¿Qué día es hoy?" and was dropped for not being addressed to him.
  It keeps half a second of run-up now. That discard cost nothing while
  everything heard was for him, which is why nothing found it in four
  months.

**And two switches, drawn at the right end of the wave** — his ears and
his voice. The strip had nothing to press at all (§1.5), and this is the
second exception after the photo. The argument for them is that the
alternative does not exist: "deja de escucharme" has to be heard to be
obeyed, and "cállate" has to be heard over his own voice. A switch you
press is the only kind that works when the thing being switched is the
one that would have to listen.

**Cost, stated plainly:** the strip is now something you can click, in
two places, and §1.5's "nothing to click" is true only of the rest of
it. The wave gives up a tenth of its width. And a wake word means a
sentence he genuinely should have heard can be missed — the loose
matching is what keeps that rare, and it buys the opposite error, where
he answers something not addressed to him.

### 2026-08-26 — Showing a camera is the moving picture, and it delivers on the gateway's loop

**Decision (the user's):** asking to see a camera gives the live view,
at 900x480, and a still only when a still is what was asked for. Before
this, "muéstrame la cámara de la entrada" took a photo — measured, twice
— because `mirar` was built first and both the tool descriptions and the
`platform_hint` were written in that order.

**What it took to make true was not the wording.** The live view had
never actually worked, and could not be seen to fail: the band opened at
900x480, stayed empty, and never closed. Three symptoms, one cause —
`LiveSession.open` captured its event loop with
`asyncio.get_running_loop()`, which is the loop of the TURN. That loop
stops running the moment the turn ends, so every packet the watcher
thread scheduled after it was queued onto a dead loop and dropped in the
one branch of `_schedule` that logged nothing. The ceiling never fired
either — it is only checked on a packet that arrives, and none did.

**The adapter now remembers the loop its websocket handler runs on** —
the gateway's own, which lives between turns — and the session asks for
it, falling back to the running loop when no strip has connected yet.

**Three things worth carrying, because each cost a round:**

- **The tests had normalised the bug.** `test_live.py`'s own docstring
  explained that "the loop `open()` captured has already been closed by
  the time `asyncio.run()` returns", and worked around it by driving
  whole scenarios inside one `asyncio.run`. That IS the production
  failure, written down as a quirk of testing.
- **Nothing was observable between the tap and the pixel.** The fix
  took one measurement and four rounds of instrumenting; the log lines
  stay — `tap installed`, `first packet`, `streaming`, `first frame
  landed`, and the loop's own `running=` flag. One per view, none per
  packet. A band that opens black is otherwise indistinguishable from
  one that works.
- **`ver_en_vivo` crashed on the argument Hermes actually passes.**
  Hermes hands a tool the whole argument dict as its first parameter,
  which `mirar` has always known (it calls it `args`); the live tool
  named it `camara` and met it with `.casefold()`. What he said out loud
  was "la imagen en directo no me llega ahora mismo" — a camera fault
  that was not one.

**And the hint taught him to lie.** "No tienes que pedirlo ni
anunciarlo, ya está ahí" was true of the photo, which appears as a side
effect of looking, and false of the live view, which appears only if he
opens it. Measured twice: "ya la tiene delante, señor", having called
nothing at all, band empty. What he need not announce is the machinery;
putting the camera up is still something he does.

**Measured after, against the house:** ~1.2 s from the camera's
burned-in clock to the screen, 11.7% CPU for the widget and 38.5% for
the gateway, and the ceiling closing at 120.0 s exactly after 1200
packets, with `_NET_WM_STATE_ABOVE/STICKY/SKIP_*` intact on the way
back to 900x96.

### 2026-08-25 — The photo reaches the strip and nothing else

**Decision:** when he is asked to look, the model's answer is **words**
and travels wherever the turn travels; the **picture** travels on a
separate channel, from the vision plugin to the strip, over the loopback
WebSocket those two processes already share. No adapter other than the
kiosk ever sees it.

**`MEDIA:` was the first design, and it fitted.** A tool result
containing `MEDIA:/path.jpg` is turned into a native attachment by
`extract_media()` on the **base** platform adapter
(`.hermes/src/gateway/platforms/base.py`), which the delivery path calls
generically on whatever adapter the turn landed on —
`adapter.extract_media(response)` at `.hermes/src/gateway/run.py:3505`,
`:22214` and `:22552` — with
`.hermes/src/gateway/stream_consumer.py` stripping the tag before the
text is shown. It is machinery every adapter inherits. One mechanism,
both surfaces, nothing to write.

**It was rejected because it is a *platform* convention, and that is the
whole of its purpose:** any adapter can render it. A tool that emits one
has no say in where its turn is delivered, so a picture of the inside of
the house would leave this box the first time a conversation was routed
to Telegram. The property "images never leave here" would then hold
because the platforms happen to be configured a certain way — and **a
privacy property held by convention is not held**. Config drifts, a
platform gets enabled, and nothing fails loudly.

Two paths, therefore, and the guarantee becomes structural rather than
conventional: not "we configured the platforms correctly" but "there is
no path by which an image reaches a third party". This is the same shape
as §1's "he is told, never made to recite" — Hermes' injection API only
accepts a *user* message, so reciting is not something we avoid, it is
something the API cannot express.

**The destination is a constant, not a config key.** `KIOSK_PLATFORM`
in `samantha_vision/__init__.py` is hard-coded for exactly this reason: a
setting naming the platform would put the rejected decision back, one
edit away.

**Cost, accepted explicitly:** the strip and Telegram no longer share a
mechanism. Two paths to maintain instead of one, and any future surface
that wants a picture has to be given one deliberately. That separation
*is* the feature, not an accident of it.

**A consequence worth stating, because it surprises people:** the
unprompted alert still carries **no** photo, anywhere. The picture is a
side effect of the `mirar` handler and an alert does not call `mirar`.
An image that appears unbidden over whatever you were doing is a larger
thing than one you asked for. If that is ever wanted, the mechanism is
already there.

### 2026-08-25 — The kiosk contract gains its first new frame

**Decision:** the `samantha_kiosk` protocol gains
`{"type": "photo", "path": …, "camera": …}`, **server to client only**.
`decode_client` is untouched. It is the first change to that contract
since it was written on 2026-08-22.

**Why the strip needed a frame when no other platform did.** Every other
adapter Hermes ships renders whatever the turn carries, because a chat
platform *is* a renderer: text goes in a bubble, an attachment goes
beside it. The strip is not a chat window. It has no message list to put
an attachment in, and what has to happen is that a window on somebody's
desktop **changes shape** — grows from 900×96 to 900×210, to 900×480 on
a click, and back. Nothing expressible inside a turn can say that. The
one surface that is not a platform is the one that needs a frame of its
own.

**It cost a fix in the strip first.** `decode_server` raised
`ProtocolError` on any type outside its set, so the first unknown frame
killed the turn carrying it. The gateway and the widget are versioned
separately and always will be; the strip now drops what it does not
recognise and handles what it does.

**The path is validated before it goes on the wire**, against the
snapshot directory, in the adapter. The socket is an unauthenticated
local listener and the strip opens whatever it is handed, so that check
is the trust boundary. A strip that is not connected is not an error: the
frame is dropped and the spoken answer is unaffected.

**What it cost beyond the code:** the kiosk's `platform_hint` said there
was no screen, and until that day it had been true. Measured on the live
gateway in the window where the photo was already being pushed and
nothing yet drew it, he declined correctly and for the wrong reason —
"sigo sin poder enseñarle nada en una pantalla, señor", once offering to
open Hermes Desktop instead. The hint therefore had to move in the same
change as the drawing, and it now says what he can show (one camera
still, briefly, and nothing else), that he need not announce it, and that
he does not see it himself. Remember §7: a hint reaches an existing
session only after `/new` and `/approve`.

**Deferred, deliberately:** the band is as wide as the strip and mostly
transparent, so while a photo is up it swallows pointer events over that
much desktop — 900×210, or 900×480 enlarged, for fifteen seconds. The
honest fix is `XShapeCombineRectangles` through the ctypes handle
(`Gdk.Surface.set_input_region` wants a `cairo.Region`, and Cairo is the
trap this machine is built around), which is a new X mechanism in the
file whose EWMH work cost this project days. The risk of the fix exceeds
the harm this week.

### 2026-08-24 — He stops repeating himself, and the password leaves the URL

**Three decisions from the whole-branch review and its re-review, all of
them behaviour the user hears or a credential he owns.**

**The camera anti-spam window widens.** 180 s stopped three-second spam
and nothing stopped three-minute spam: measured on the live gateway,
`entrada: alguien` five times in 35 minutes — ~480 spoken turns and ~480
model calls a day, running while the house sleeps. Consecutive re-fires
of the same `(camera, label)` now back the window off 180 s → 15 min →
hourly, resetting to the floor after a full window unseen. **The four
calibrated constants are untouched** — 180, 0.7, 23:00, 07:00 are
BarnDoor's, arrived at against these cameras; the ×5 and ×20 are ours. A
first sighting is never suppressed, and the quiet-hours person rule sits
outside the escalation in **three** ways: a widened window never gates it
(only the night floor below does), its firings never advance the level —
counting them would turn the override into its opposite at dawn — and it
resets the level, so the morning does not inherit the day's fatigue. The
third was added after measuring what its absence cost; see the night
floor below.

**Credentials move to `.env`.** The RTSP password lived inline inside the
camera URLs in the untracked `.hermes/home/config.yaml`, which is what
let PyAV write it into the journal in the first place. It now lives in
`.env` at the repo root — git-ignored, with a tracked `.env.example` —
which `Hermes/run-gateway.sh` sources; that is the single chokepoint, so
both units that start a Hermes process — `samantha-hermes.service` and
`samantha-hermes-serve.service` — and every manual invocation get it.
`samantha-widget.service` does not, and needs no credential. URLs say
`${RTSP_PASSWORD}` and the plugin expands it. The trap, handled
explicitly: an unset variable would be left as the literal text
`${RTSP_PASSWORD}`, which would then be used as the password and logged.
`_expand` therefore does the substitution itself and resolves each name
inside the callback, dropping the camera with a warning that names the
variable and never the URL. It deliberately does **not** call
`os.path.expandvars`, which also expands a bare `$NAME` — and a password
may contain a `$`, which cost a password fragment in the journal on
2026-08-24 before the pattern was narrowed to braces only.

**A 30 s floor under the night rule — the user's decision**, taken from
three options put to them after the re-review measured the alternative.
"A person at night beats the anti-spam" is BarnDoor's, and it was written
for a mailbox rather than a mouth: there it produced a notification, here
a spoken turn and a model call, and `worth_saying` runs once per sampled
frame. Measured against the real `Watcher`: **19,200 utterances over an
eight-hour night** with somebody standing in view. `NIGHT_FLOOR_SECONDS
= 30` caps it at one mention per 30 s per `(camera, label)`; the same
measurement afterwards gives 960.

**Its cost, stated plainly:** he now insists *less* at night than
BarnDoor's rule intended. The rule exists because the second sighting at
3am matters more than the first, and 29 of every 30 seconds of that
insistence are gone. The trade is that the alternative was not insistence
but continuous speech. 30 s is ours and is **not** a fifth calibrated
constant.

The same pass found the escalation level surviving the dawn boundary: a
key escalated to hourly in daylight and present all night got its first
morning mention 60.0 minutes after quiet hours ended, when the morning is
exactly when the user wakes and would want to know. The night path now
resets the level; measured again, 150 s.

**Cost:** the escalation is keyed on the label, so while a `(camera,
label)` sits at the hourly level any person at that camera is silenced
for up to an hour. That is inherent to a plugin that cannot tell one
person from another; the 180 s floor bounds it at the start of each
visit. And the tracked README no longer carries the house's camera
addresses — placeholders there, real values beside the URLs they
describe.

### 2026-08-24 — Vision moves out of the widget and into a Hermes plugin

**Decision:** the cameras live in the gateway, as the standalone plugin
`samantha_vision` (`Hermes/plugins/samantha_vision/`), one thread per
camera. The widget goes back to drawing, listening and speaking, and
opens no camera at all.

**This supersedes the placement half of the 2026-08-23 entry below**
("Why it belongs in the widget rather than in a service of its own").
The rest of that entry stands unchanged and was carried over whole: what
comes from BarnDoor and what does not, the quiet-rule numbers, and — the
part that matters — that a detection becomes a *prompt* and never a
sentence.

**Rationale:**
- **Watching should survive the widget restarting.** The strip is a
  window on a desktop; the gateway is a systemd service with a lifecycle,
  logs and supervision already paid for.
- **A camera you can question has to live beside the thing that
  answers.** The tool is plan 2, but it cannot exist in a UI process.
- **The strip should draw.** §2.3 claims the widget is the surface; a
  camera thread competing with the GTK main loop, Silero and Whisper was
  the counter-example.

**How a plugin speaks first, measured on the pinned Hermes:**
`ctx.inject_message(text, role="user",
session_key="agent:main:samantha_kiosk:dm:kiosk")`. Three properties
decided the design and are worth carrying:
- **No lifecycle hook fires after registration**, so `register(ctx)` is
  the only entry point and must start its own threads — while staying
  pure, because work that touches the outside world during registration
  turns a missing dependency into a plugin that never loads.
- **It can only push a *user* message.** There is no API for putting
  finished words in his mouth, which makes §1's "he is told, never made
  to recite" a property of the mechanism rather than of our discipline.
- **It fails silently, and not in the way it looks.** `False` means only
  that the gateway is not up yet — the injector installs after the last
  platform adapter connects — so retrying clears it. A **missing session
  row comes back `True`**: the lookup happens inside the coroutine, after
  the task is scheduled, and Hermes logs it itself as "Plugin message
  injection was not routed". (Corrected 2026-08-24; the opposite was
  stated here and in three other places, and sent a reader hunting for a
  log line that cannot exist.) A sighting with nowhere to go is retried
  three times and then dropped; queueing would make him recite stale
  news.

Injection is also a per-plugin permission, default-off:
`plugins.entries.samantha-vision.allow_gateway_injection: true`. Without
it the cameras watch and he never mentions a thing.

**Cost:** the camera threads now run inside the brain. If one wedges the
gateway, everything dies — so each thread catches everything, logs once
and backs off from 30 s to a 5-minute ceiling, and each camera owns its
own failure. And onnxruntime and PyAV stay in the widget's dependency
tree — onnxruntime declared, for Silero; PyAV transitively, because
faster-whisper brings it — but neither is there for vision any more.

**Verified against the real house, 2026-08-24** — one camera live, one
off, nothing faked:

    ← El de la entrada sigue plantado donde está, señor.

**Still not done:** he cannot be asked. `samantha_vision` registers no
tool and remembers nothing; `mirar`, `revisar` and the detections table
are plan 2.

### 2026-08-24 — The cameras become plural, and named

**Decision:** cameras are a list of `{name, url}` in the plugin's
config, not one environment variable. The anti-spam window is keyed by
camera **and** label. The names are interface, not configuration: they
are what he says out loud.

**Rationale:** somebody walking from `fuera` to `entrada` is two events
and should be; with a single unnamed camera it was one, and the second
half was swallowed by the 180 s window. Naming them is what makes the
distinction expressible at all.

**The measured trap, and it is not a small one.** Camera names are bare
nouns, so they carry no article. Put one inside a prepositional phrase
and the Spanish breaks — "en la fuera de casa", "en fuera de casa" — and
a model handed broken Spanish does not shrug: it *repairs* it by
inventing a place that fits. Twice on the live gateway, a camera named
`fuera` seeing somebody produced "Hay alguien en la entrada, señor."
Somebody outside, reported as somebody at the door — a wrong answer, not
a clumsy one, in a feature whose whole job is telling you who is around
the house. The fix was to stop putting the name inside a preposition at
all: it is handed over as a labelled value, `Dónde: fuera. Qué:
alguien.`, and he picks his own words around it.

**Cost, all of it in the configuration:**
- The URLs carry the RTSP password, so they live **only** in the
  git-ignored `.hermes/home/config.yaml`. The tracked
  `Hermes/samantha-config.yaml` carries the shape as a comment and
  nothing else — a live placeholder list there would be worse than
  useless, because `apply-config.sh` deep-merges dicts but **replaces
  lists wholesale** and would blind him on the next run.
- The list must sit under `settings:`. `ctx.get_config("cameras")` reads
  `plugins.entries.<id>.settings.cameras` and nothing else; put it at the
  entry root and the plugin loads, watches nothing, and says so in one
  line nobody is reading.
- PyAV puts the whole URL, password included, into every failure
  message. It reached the journal in plaintext once before everything
  logged went through `redact()`.

### 2026-08-23 — Samantha can see: BarnDoor's cameras, reused not integrated

**Decision:** the widget watches the house's cameras. What comes from
`~/git/barndoor` is the RTSP layout and a YOLOv9 model already converted
to ONNX — and nothing else. No Frigate, no MQTT, no Telegram, no second
agent. The two projects stay separate.

**Why it belongs in the widget rather than in a service of its own:**
zero new dependencies. `onnxruntime` was already there for Silero and
PyAV arrived with faster-whisper, so a widget that could already hear
was one import away from being able to look.

**The design decision that matters:** a detection does not become
speech. It becomes a `chat` frame with a prompt asking her to mention
what she noticed, in one short line, forbidding any reference to cameras
or detections. "Persona detectada en exterior" would be a machine
talking, and §1 says she never performs using her tools. Measured:

    cámara: alguien
    ← Oye. Hay alguien fuera de casa.

**What the user's suggestion to read BarnDoor's app was worth:** its
`agent/rules.py` had the numbers, arrived at against these very
cameras, that would otherwise have been guessed — confidence floor 0.7
(the guess was 0.45), anti-spam of 180 s per label, and a person during
quiet hours overriding that silence. Without the anti-spam a camera
says "alguien" every three seconds for as long as somebody stands in
the driveway.

**Cost:** a model call per event, affordable only because those rules
make events rare. And the privacy line moves again: what the cameras see
is described to a cloud LLM, in the same "eyes open, not absolute"
sense §1 already carries for conversation.

**Not done:** she cannot be asked what she sees. The camera speaks; it
cannot be questioned. That wants the vision path exposed as a Hermes
tool rather than a thread pushing prompts.

### 2026-08-23 — Electron reconsidered for the widget, and rejected again

**Decision:** the widget stays GTK4. Raised because Hermes Desktop —
Electron — was built and run on this machine the same day, and it works.

**Measured, side by side, on this box:**

| | widget (GTK4) | Hermes Desktop (Electron) |
|---|---|---|
| RSS | 389 MB, one process | 1257 MB across six |
| Installed | 268 KB of code | 338 MB packaged |
| Build | none | `npm install`, and it had to download its own Node |

The widget's 389 MB is almost entirely faster-whisper resident on the
GPU, not the interface.

**The reason that decides it is not the memory.** Silero, Whisper,
CosyVoice and playback share ONE Python process today. Electron splits
that into a Node process plus a Python helper over IPC, or forces VAD
and STT into JS. The Silero bug found this morning — 576-sample windows,
not 512, failing silently — would have been considerably harder to find
across a language boundary.

**Where Electron would genuinely win:** a transparent undecorated
always-on-top window is three lines there versus ~50 of EWMH here — but
that cost is already paid and tested. And rich graphics: if the OS1 3D
ribbon ever comes back, a browser gives it away free. **That** is the
conversation worth reopening, and `frontend/` is still there for it.

**Cheaper alternatives if the visualiser ever outgrows Cairo/GSK:**
`Gtk.GLArea` in-process, or an embedded WebKitGTK for the visual half
with Python still owning the audio. Neither breaks the single process.

**Cost of this decision:** none today. It is the fifth architecture this
project has considered (Tauri → Ubuntu Frame → Chromium kiosk → GTK4 →
Electron) and the fourth it has rejected; the point of writing the
numbers down is so the sixth conversation starts from evidence.

### 2026-08-23 — Samantha may act: agentic, but never visibly

**Decision:** Samantha uses Hermes' tools. §1 loses "❌ A productivity
assistant" and "❌ An agentic tool-using system (no function calling, no
web search)", and gains "❌ A visible agent" in their place.

**Rationale:** the spec contradicted itself. §1 forbade agentic tool
use; Phase 9 (§4) integrated Hermes explicitly *"to enable agéntico tool
use"*. Until today the prohibition won by default, which left Hermes
working as a text pipe — a sentence in, a sentence out — with an entire
tool ecosystem sitting unused underneath a device that lives in
somebody's living room.

The user's framing on 2026-08-23: *"Hermes funciona como un chatbot y no
es esa su utilidad, sino hacer tareas de agentes y aprovechar todo su
ecosistema de integración."*

**What is in, in priority order:** Home Assistant (the one that makes a
thing in the living room worth having), `memory` + `session_search`,
`cronjob` (reminders she raises out loud), web search, Spotify, and
Discord — the only social platform this pinned Hermes actually ships,
alongside Yuanbao and Feishu.

**Cost, and it is not small:**

- **The personality spec now has to police behaviour, not just prose.**
  "No visible agent" is a rule about what she does, and `docs/
  personality.md` was written for what she says.
- **The voice turn does not fit an agentic turn.** It assumes you speak,
  she thinks for a few seconds, she answers. A real task takes minutes,
  emits intermediate chatter (`↪ Redirected current run`, already seen
  in the wild) and trips the kiosk adapter's 90 s watchdog. The wave has
  no state for "still working".
- **`cronjob` inverts the conversation.** A reminder is Samantha talking
  first, which nothing in the widget or the adapter currently supports.
- **The privacy line moves again.** Web search and Home Assistant send
  the house's business outward. §1's "eyes open, not absolute" already
  covers it, but it is a wider aperture than the 2026-05-15 entry
  imagined.
- **Memory now has two homes.** Hermes has its own `memory` toolset and
  we have ChromaDB (§2.7) that the gateway path never touches. One of
  them has to win.

**Alternatives rejected:** keeping her purely conversational (leaves
Hermes pointless — a smaller local model would do), and going fully
task-oriented (that is Siri, and §1 has always said no).

### 2026-08-23 — The LLM came home: Qwen3.8-27B local, and Grok demoted

**Decision:** inference runs on this box by default. `llama-server` with
Qwen3.8-27B at UD-Q3_K_XL, 57 tok/s. Grok stays reachable behind a config
switch. This reverses the 2026-05-15 decision below.

**Rationale:** that decision rested on "8B-class models can't carry this
personality, and bigger ones don't fit". The second half stopped being
true — a 4090, a smaller quant and a current llama.cpp put a 27B beside
CosyVoice and Whisper with room to spare, four times faster than the
obvious quantisation. §2.5 has the table.

**Cost:** the box must hold everything at once (23.3 GB of 24.5), so
adding anything that wants VRAM now costs tokens per second. And
llama.cpp must be recent: b9115 refused the file outright, missing a
tensor of Qwen3.8's hybrid Gated DeltaNet.

**What it buys:** §1.1 back, honestly. Nothing said in the room leaves it.

---

### 2026-08-23 — Samantha becomes JARVIS

**Decision:** the persona is JARVIS — courteous, precise, dry, never
alarmed, addresses the user as "señor" without servility, and never
narrates his tools. Samantha's warmth was the right character for a
companion; the thing that ended up on the desk is a house presence.

**Cost:** the name is only changed in prose. `samantha_widget`,
`samantha_kiosk`, `SAMANTHA_*` and the repo itself keep the old name —
renaming them would touch every file, every unit and every env var to buy
nothing. Anyone reading the code should expect the mismatch.

**What the investigation cost, and it is the valuable part:** the persona
was correct for an entire afternoon while the strip kept answering "me
llamo Hermes". Two independent causes, both silent — `SOUL.md` never
reaching a gateway conversation at all, and the system prompt being
frozen when the *session* is born. §7 has both, and the fix (`/new`,
`/approve`).

---

### 2026-08-22 — The Chromium kiosk is replaced by a GTK4 desktop widget

**Decision:** the surface is a native GTK4 strip along the bottom of the
screen. It **replaces** the kiosk rather than coexisting with it. Taken
2026-08-22 in brainstorming, four answers closed: it replaces; GTK4 with
no webview; a floating strip, wide and low, terracotta; always listening,
with Silero deciding when the user speaks — no wake word, no shortcut.

**Rationale:** the appliance model (§1.5, as it was) assumed a device
that is only him. The real box is a desktop the user also works on, and a
full-screen kiosk on it is not a presence but an application that will
not go away. A strip is there without taking anything.

**Cost, accepted explicitly:**
- **`frontend/` dies.** React, Vite, Three.js, the OS1 ribbon, the four
  screens — all of it was the kiosk's UI. The user's condition was that
  it not be deleted until the widget convinces, which is why §2.10 and
  §3 still list it and why plan 3 is unwritten.
- **The UI is rewritten in GTK4/GSK**, a smaller and less familiar
  toolkit than a browser, on a machine where Cairo turned out not to
  work (§2.3).
- **X11 becomes a hard constraint** rather than a preference (§2.2).
- Boot-to-him and the auto-login chain are gone; a user service starts
  him inside the ordinary desktop session.

**What it bought, measured:** ~389 MB resident for the whole of him,
Whisper included; a wave that animates on the frame clock at no
measurable cost; and a surface with no window, no focus and nothing to
click, which is §1.5 made literal.

---

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

## End of CLAUDE.md

This document is the source of truth. When in doubt, re-read it before
asking the user. Update PROGRESS.md after each phase completion, not
this file (this file changes only when decisions change).
