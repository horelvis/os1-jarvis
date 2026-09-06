# CLAUDE.md — JARVIS Project Specification (v4)

> **For Claude Code:** This is the single source of truth for this
> project. Read this entire document before making any changes. When in
> doubt about scope, architecture, or style, this document overrides your
> defaults. Update `PROGRESS.md` after completing each phase.
>
> **He is called JARVIS.** Until 2026-08-23 he was JARVIS, and most
> package names, environment variables and systemd units still carry that
> name — `jarvis_widget`, `jarvis_vision`, `SAMANTHA_*`. Renaming them
> is not worth the churn. In prose he is JARVIS; in code, mostly samantha
> — except the platform he speaks through, `jarvis` since 2026-08-28
> (§10, §12).
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

JARVIS — until 2026-08-23, JARVIS — is an **AI presence that lives on
the desktop**: a strip along the bottom edge of the screen that listens
all the time, speaks in a cloned voice, watches the house's cameras, and
can act on it. Not a window you open. Something that is there.

**Stack at a glance:**
- **Hardware:** one box with an RTX 4090 (24 GB VRAM). VRAM is the
  budget everything competes for — see the note below.
- **OS:** Ubuntu with GNOME on X11 (`DISPLAY=:0`). Wayland out of scope.
- **Surface:** `widget/` — a GTK4 strip, no browser, no webview.
  Transparent, borderless, always above, drawn with GSK.
- **Brain:** Hermes Agent gateway on `:7777` (plugin `jarvis`), which
  gives JARVIS tools: memory, reminders, session recall.
- **LLM:** local `llama-server` with Qwen3.8-27B **Heretic** (GGUF) — the
  decensored build, since 2026-09-01 — or X.AI's Grok API, a config
  switch. §2.5 and §12 carry the trade.
- **STT:** faster-whisper `large-v3-turbo`, on the GPU, in-process, **int8
  since 2026-09-01** — same model, 992 MiB cheaper, measured identical.
- **Endpointing:** a second engine, Vosk `small-es` on the CPU, decides
  when a sentence is finished and whether a sound over his voice is a
  person or his own echo. Its text reaches nobody (§2.6, §2.8, §12).
- **VAD:** Silero v5 over onnxruntime, CPU, always listening.
- **TTS:** CosyVoice 3 zero-shot on `:8093`, JARVIS' cloned voice.
- **Ears:** he answers to his name (§2.8). Everything else in the room
  is heard and dropped.
- **Vision:** YOLOv9 over onnxruntime against the house's RTSP cameras,
  borrowed from BarnDoor. Since 2026-08-24 it runs **inside the
  gateway**, as the plugin `jarvis_vision` — one thread per named
  camera. The widget no longer opens a camera. Since 2026-08-25 he can
  also be **asked** (`mirar`), and the still he takes appears above the
  strip and nowhere else (§12). Since 2026-08-26 asking to see a camera
  gives the **moving** picture at 900x480, and a still only when a still
  is what was asked for.
- **Memory:** Hermes' own (`memories/USER.md`, `state.db`). ChromaDB
  (§2.7) is gone with `backend/`, deleted 2026-09-03; the gateway path
  never used it.
- **Phones:** three iPhones on the house network reach him through
  `widget/jarvis_widget/remote.py` — a page with one button, held to
  speak. The phone is a peripheral of the widget, not a platform: the
  gateway still sees one strip and one session (§12, 2026-09-01).
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
│   + jarvis (surface)         │  └────────────────────────┘
│   + jarvis_voice (TTS)     │
│   + jarvis_vision (cameras)│
│   memory · cron · sessions   │       llama-server :8000
└───────────────┬──────────────┘       (Qwen3.8-27B, local)
                └──────────────────────────────┘
```

**The VRAM budget is the real constraint**, and it has FOUR claimants,
not three — the fourth is the one every arithmetic here has forgotten at
least once. Measured 2026-09-01 with everything resident:

| | MiB |
|---|---|
| llama-server (Heretic, KV q4) | 16,330 |
| CosyVoice | 5,080 |
| widget (Whisper int8) | 1,534 |
| **the desktop** — Xorg 99, gnome-shell 28, a browser tab 35 | ~240 |
| **free** | **1,380 of 24,564** |

A 27B at Q4_K_M does not fit alongside them at all and spills onto the
CPU: 13.7 tok/s that way against 57 when it fits (§12, 2026-08-23).
§1's "latency over correctness" is what decides the quantisation.

**Every claimant must be subtracted before changing any of them**, and
no unit does it for you: `jarvis-llamacpp.service` does not know the
widget exists, and nothing at all counts the desktop. Getting this wrong
is silent — it left him deaf for three days in August (§12, 2026-08-30).

**`backend/` and `frontend/` are gone**, deleted 2026-09-03 with the two
systemd units that served them. The widget had replaced both in August;
the condition for removing them was that it convince first, and it did.
That was "plan 3", and it is closed.

---

## 1. Vision & Product Principles

### What he is

JARVIS is **not** an assistant, a chatbot, an agent, or a tool. She is
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
   - **He now listens on the house network**, not only on loopback
     (2026-09-01). Nothing leaves the house, so this principle's letter
     holds — but the premise underneath it changed: authentication used
     to be "only from this machine" and is now a shared secret plus an
     origin check, and what is behind them is an agent holding
     `terminal`. The threat model is **whoever is on the wifi**, guests
     included.

2. **Conversational first, and able to act.** JARVIS is designed for
   the relationship. She remembers, she asks, she has opinions. She is
   NOT a Siri/Alexa replacement — but since 2026-08-23 she *can* do
   things in the house: control it, remember, remind, look something up
   when the conversation needs it.

   Since 2026-08-23 she also **sees**: the house's cameras, through
   YOLO, close enough to notice somebody outside. Seeing obeys the same
   rule as acting — she mentions what she noticed, in her words, and
   never reports a detection.

   The order in that sentence is the principle. Acting serves the
   conversation, never replaces it. She does not announce her tools and
   does not narrate steps. If a request would make her sound like a task
   runner, she talks instead.

   **She does say that she went outside, and what she found**, since
   2026-09-06: "He estado buscando sobre eso y he encontrado varios
   vídeos…", at the head of the answer, before the result. The reason it
   is a principle and not a courtesy is that a web search is the only
   thing here that leaves the house (§1.1), and that sentence is the only
   way anybody in the room learns it did. What stays forbidden is the
   machinery — tool names, step counts, "ejecutando 3 de 5", routine
   successes. The test survives unchanged: someone watching should not be
   able to tell where the conversation ended and the task began.

   **It is in the past tense, and that is a constraint rather than a
   preference** (measured 2026-09-06). Announcing it BEFORE — "voy a
   buscar en internet" — cannot be done from the persona at all: a turn
   reaches the strip as exactly ONE frame, the finished answer, measured
   three times over search turns. Nothing a model might say before a
   tool call has a path to the screen. `jarvis_code`'s live milestones
   are not a counter-example — they come from the A2A bridge's own event
   stream on `:9910`, not from a Hermes hook, and `jarvis/adapter.py`
   has no tool hook of any kind.

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
   experience — when the device boots, it boots into JARVIS… enforced
   by systemd + auto-login + Chromium kiosk mode". The appliance model
   went with the kiosk (§2.3, §12): the box is a desktop the user also
   works on, and taking the whole screen was the wrong trade.

### What he is NOT

- ❌ A cloud-LLM wrapper (conversational inference stays local — Qwen via llama-server)
- ❌ A coding assistant
- ❌ **A visible agent.** She uses tools; she never performs using them.
  No "ejecutando 3 de 5", no tool names out loud, no step-by-step
  progress. A task that cannot be done without narrating the machinery is
  a task she declines, in her own words.

  **Revised 2026-09-06** (see §12): this bullet used to forbid "progress
  reports" outright and "listing her own capabilities". Both went at the
  owner's instruction — the first because silence during a slow search
  reads as a hang rather than as restraint, the second because the first
  thing a new amo needs is to know what he is for. She says what she is
  doing and what she can do; she still never says how.

**Removed 2026-08-23** (see §12): "❌ A productivity assistant" and
"❌ An agentic tool-using system (no function calling, no web search)".
Both were contradicted by Phase 9, which integrated Hermes *for* agentic
tool use, and the contradiction was resolved in favour of acting.

**Removed 2026-09-05** (see §12): "❌ A multi-user system (single user,
always)" and "❌ A mobile app (this desktop only)". The first is the
oldest assumption in the project — older than the widget, older than
Hermes — and the whole phone path was built on it. Both went in one
conversation, for one reason: two teenagers in this house are going to
study with him.

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
- **Except one, since 2026-09-01:** the phone page binds the LAN
  interface. Never `0.0.0.0` — this box has twelve Docker bridges and no
  container has any business reaching JARVIS.

### 2.2 Operating System: Ubuntu with GNOME on X11

**Decision:** Ubuntu with a full GNOME desktop, running **X11**
(`DISPLAY=:0`). Wayland is out of scope.

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
- **A unit must NOT set `DISPLAY` itself.** GNOME imports `DISPLAY` and
  `XAUTHORITY` into the systemd user manager when the session starts
  (`systemctl --user show-environment`), and a unit that is `After=` /
  `PartOf=graphical-session.target` inherits them. `jarvis-widget.service`
  hardcoded `DISPLAY=:1` on a box whose session is `:0`, and the failure
  is silent in the worst way: the process dies in `Gtk couldn't be
  initialized` before any of our code runs, so the strip is simply absent
  while llama-server, the gateway and CosyVoice all look perfectly
  healthy. Found 2026-08-30, after it had been that way since the rename.

### 2.3 Display Layer: a GTK4 strip on the desktop

**Decision (2026-08-22, implemented 2026-08-23):** the surface is
`widget/` — a GTK4 window along the bottom edge of the screen.
Borderless, transparent, always above, drawn with GSK on the frame
clock, started by a systemd **user** service.

**Amended 2026-09-03:** "no browser and no webview anywhere in the
running system" held for four months and no longer does. The teacher's
card is a Markdown document rendered by WebKitGTK — one webview, inside
the strip, for content the strip cannot draw. §12 carries what forced
it and what it is fenced with. Everything else is still GSK: the wave,
the photo band, the live camera.

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
systemd --user: jarvis-widget.service
  ↓
python -m jarvis_widget      (venv with --system-site-packages)
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

### 2.4 Backend Stack: Python + FastAPI — SUPERSEDED

**Superseded 2026-08-23, deleted 2026-09-03.** No FastAPI server runs.
`127.0.0.1:7777` is the **Hermes gateway**, not uvicorn, and nothing
serves a frontend because there is no browser to serve it to. The v3
design that stood here — the `StaticFiles` mount at `/`, `/chat`,
`/speak`, the WebSocket, ChromaDB — is in `git log -- CLAUDE.md`, along
with the claim it kept for months after it stopped being true: that the
widget imported `backend/samantha/tts.py`. It imported
`Hermes/plugins/jarvis_voice/tts.py`, and the other file did not exist.

### 2.5 LLM Runtime + Model

**Decision (revised 2026-09-01 — the harness comes off):**
- **Default runtime:** llama.cpp `llama-server` on this box, `:8000`.
- **Default model:** **Qwen3.8-27B Heretic, RVN-IQ4_XS** GGUF — the
  decensored build. 16,330 MiB with the KV cache at q4_0, **47 tok/s**.
  §12 (2026-09-01) has what it buys, measured over nine requests, and
  what it costs.
- **Previous default:** Qwen3.8-27B UD-Q3_K_XL, 15,296 MiB, 52.5 tok/s.
  Still on disk, and the fallback if the Heretic ever has to go.
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
delivers it. Everything resident at once, **re-measured 2026-08-30**:
llama-server 15,296 MiB + CosyVoice 4,950 + the widget (Whisper inside)
2,476 = **22,947 MiB of 24,564, leaving 1,126 free.** That margin is the
number that matters, and it is why a model override is not a free
choice: a build 2 GB larger fits its own arithmetic and leaves Whisper
nothing. One did, on 2026-08-27 — see the comment in
`systemd/jarvis-llamacpp.service` and §12.

**Three things that each cost a round, now in `jarvis-config.yaml`:**
- **`enable_thinking: false`.** Qwen3.8 reasons by default and puts
  everything into `reasoning_content`; `content` comes back empty and the
  strip sits in "thinking" without ever speaking.
- **Provider and model are separate fields.** `model.default:
  custom:local` sends the literal string "custom:local" as a model name
  and the turn dies with a 404.
- **64K context is a hard floor.** Hermes refuses less and kills the
  turn, so `llama-server` must be started to match.

**The old default, for the record.** Between 2026-05-15 and 2026-08-23
the default was X.AI's Grok API, because an 8B local model could not
carry this personality and nothing bigger fitted. The A/B that chose it,
the alternatives rejected then (vLLM, Ollama, 70B local) and the privacy
cost are in the decision log (2026-05-15, reversed 2026-08-23). What
survives from it is the reason the switch is still one line: the client
speaks plain OpenAI-compatible `/v1/chat/completions`, so a provider is
config, not code.

### 2.6 STT/TTS

**Decision (TTS revised 2026-08; STT unchanged in kind, moved in place):**
- **STT:** faster-whisper `large-v3-turbo`, in-process inside the widget,
  on the GPU, **at int8 since 2026-09-01** — the same model, only cheaper
  arithmetic. **1,534 MiB** resident against float16's 2,521, ~2 s to
  load, 67-148 ms to transcribe. The quantisation was measured before it
  was adopted: transcription came back character-for-character identical
  on every dumped utterance and `wake.py` found his name 3 of 3, exactly
  as at float16. The 992 MiB it gives back is what lets the Heretic model
  sit beside it (§2.5). `JARVIS_WIDGET_STT_COMPUTE=float16` reverts it.
- **Endpointing:** Vosk `small-es` (39 MB, Apache 2.0, CPU, ~5% of one
  core) transcribes continuously and its text reaches nobody. It decides
  two things: when you have finished a sentence — 880 ms sooner than the
  1.2 s of silence, measured — and whether a sound while he speaks is a
  person or his own echo. **Whisper is deliberately not doing this job**:
  measured 2026-09-01, the best transcriber is the worst endpointer,
  because it completes the sentence it heard instead of leaving it
  hanging where the speaker did.
- **TTS:** **CosyVoice 3** zero-shot, in Docker on `:8093`, cloning his
  voice from one reference clip plus its transcript in `voices/`.
  24 kHz int16, synthesised clause by clause so he starts speaking
  before the sentence is finished. ~5.5 GB of VRAM.

**Piper was the v3 choice** (`es_ES-davefx-medium`, CPU, ~200 ms) and
lost on identity, not on latency: a preset voice is somebody else's.
XTTS-v2 was tried in between. `Hermes/plugins/jarvis_voice/tts.py`
dispatches across all three; CosyVoice is the default and the only one
used. (It lived in `backend/samantha/tts.py` until that tree was
retired, and this line said so long after it had moved.)

**A second lever, easy to miss:** CosyVoice takes a system prompt before
`<|endofprompt|>` that conditions *delivery* — pace, poise — not words.
The server injected a fixed "You are a helpful assistant." for months,
which is a personality too, just nobody's. Set it with
`JARVIS_TTS_COSYVOICE_VOICE_PROMPT`.

### 2.7 Memory: Hermes' own — SUPERSEDED

**Superseded 2026-08-23; the store went with `backend/` on 2026-09-03.**
Memory is Hermes' (`memories/USER.md`, `state.db`) and the gateway path
never touched ChromaDB. The v2 design that stood here — ChromaDB at
`~/.jarvis/memory/chroma/`, a SQLite ring buffer of the last 20 turns,
`role: "fact"` chunks in place of a `profile.json`, and fastembed with
multilingual MiniLM — is in `git log -- CLAUDE.md` and in the decision
log (2026-05-13).

**The user directive that came with it outlived its implementation:**
*JARVIS never forgets anything* (2026-05-12). Whether Hermes' own
`memory` toolset honours it has never been checked.

### 2.8 Audio I/O: everything in the widget, nothing in a browser

**Decision (revised 2026-08-23):** the widget owns the microphone and
the speakers, through PortAudio (`sounddevice`). There is no browser, so
there is no Web Speech API.

- **Always listening, and answering to his name since 2026-08-26.**
  Silero v5 VAD over onnxruntime, on the CPU, decides where an utterance
  starts and stops; `wake.py` then decides whether it was addressed to
  him. The 2026-08-22 decision below said "no wake word, no shortcut"
  and the user reversed it — a room he is in can now be talked in
  without talking to him. `JARVIS_WIDGET_WAKE_WORD` empty restores the
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
- **He can be interrupted, and it is decided on words rather than
  volume** (2026-09-01). `JARVIS_WIDGET_BARGE_RMS` survives as a
  silence floor (0.01); whether a sound is a person or his own echo is
  `EchoFilter` run against Vosk's live partial. The threshold it
  replaces could not work: the user's voice measures RMS 0.054-0.088 and
  his echo with the speakers beside the microphone measures 0.178 —
  louder than the person. `JARVIS_WIDGET_MIC_GATE=1` remains, off by
  default, as the fallback for a box where deciding it on words is not
  enough — it deafens the microphone for as long as he speaks, which
  works everywhere and costs being able to interrupt him at all.
- **The speech engine failing costs speed, never hearing** (2026-09-01).
  Vosk missing, or raising later, leaves the 1.2 s floor closing turns
  and every sound treated as a person: `VoskSwitch` turns the feature
  off on the first exception and logs once, and `audio.py`'s pump
  survives anything its callback raises. Both exist because the
  microphone thread calls that callback OUTSIDE its own `try` — one
  traceback there and he is deaf while looking perfectly healthy, which
  is exactly what an oversized Whisper model cost for three days on
  2026-08-27 (§2.5).

**Two things that cost days, both silent:**
- **PortAudio's `callback=` mode segfaults under GTK.** No traceback, and
  it surfaces inside whatever unrelated `import` happens to be running.
  Read blocking from a thread of our own. `JARVIS_WIDGET_NO_MIC=1`
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
`JARVIS_WIDGET_FAKE_MIC` remains how the path is exercised with
nobody in the room.

> **The v3 decision, superseded, kept only as a pointer.** Microphone
> capture and speech recognition happened in the **browser**, through the
> Web Speech API (`webkitSpeechRecognition`), and TTS playback was an
> `<audio>` element fed by `/speak`. Its rationale, and the kiosk flags
> it needed, are in `git log -- CLAUDE.md` and in the decision log
> (2026-05-13).

### 2.9 Language: Spanish (Spain)

**Decision:** All user-facing strings, voice synthesis, and prompts in
Spanish from Spain (peninsular).

**Code itself:**
- Code identifiers, comments, commit messages: **English**
- User-facing strings: **Spanish**
- Documentation: **English** (this file, READMEs)

### 2.10 Frontend Stack: React + Vite + TypeScript — SUPERSEDED

**Superseded 2026-08-23; the tree was deleted 2026-09-03.** `frontend/`
no longer exists. The four screens, the Zustand store and the Three.js
OS1 ribbon were the kiosk's UI, and the widget draws its own in GSK
(§2.3); Node and pnpm are not needed to run him at all. Why React was
chosen and why it was dropped are both in the decision log (2026-05-13,
2026-08-22).

## 3. Project Structure (Authoritative)

```
os1-jarvis/
├── CLAUDE.md               ← This file. Read first.
├── PROGRESS.md             ← The log: this month in full, and the index
│                             of every entry (you append to this)
├── README.md               ← The short version, for humans
│
├── widget/                 ← HIM. The GTK4 strip and everything it does.
│   ├── pyproject.toml
│   ├── README.md           ← the venv, the models, the switches. Read it.
│   ├── jarvis_widget/
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
│   ├── jarvis-config.yaml← model, provider, TTS. NOT the secrets.
│   ├── apply-config.sh
│   └── plugins/
│       ├── jarvis/          ← the surface he speaks through
│       ├── jarvis_voice/  ← CosyVoice, from inside the gateway
│       ├── jarvis_vision/ ← the cameras: YOLO, the quiet rules, the
│       │                      alert, and `mirar`. Its own README.
│       └── jarvis_teacher/  ← he teaches a subject: the course's state,
│                              the sources and the domain gate, the card
│                              on the strip. Its own README.
│
├── tts-server/             ← CosyVoice 3 in Docker, on :8093
├── voices/                 ← the reference clip his voice is cloned from
├── systemd/                ← user units: widget, hermes, hermes-serve,
│                             llamacpp
├── docs/
│   ├── decision-log.md     ← §12: why things are the way they are
│   ├── progress-2026-08.md ← the log, August: the widget era
│   ├── progress-kiosk-era.md ← the log, to June: phases 0–10, v1–v3
│   └── superpowers/        ← designs and plans, dated
│

```

**Rules:**
- **MUST NOT** introduce Rust, Tauri or snap packaging (all rejected;
  see Decision Log §12)
- **A webview exists now, in exactly one place**: the card, drawn by
  WebKitGTK (`widget/jarvis_widget/ficha_area.py`), since 2026-09-03.
  That reversed this line's "or a browser / webview of any kind" at the
  user's instruction, and it is a carve-out rather than an opening: it
  renders one self-contained document, with JavaScript off and every
  network load refused. **MUST NOT** put a second one anywhere, and
  MUST NOT give this one JavaScript, a network or a `file://` base.
- **MUST NOT** add new top-level directories without asking
- **MUST NOT** recreate `backend/` or `frontend/`. They were deleted on
  2026-09-03 after four months unused. New work goes in `widget/`.
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
`jarvis_code` follows the A2A bridge's firehose on :9910 unless
`plugins.entries.jarvis-code.settings.bridge` is emptied, which selects
the v1 tee-file follower instead. What bridge mode buys is the console
showing milestones rather than raw lines, and three moments reaching the
user by voice — the assistant's own `AskUserQuestion`, a gate before
anything irreversible, and a closing checkpoint. The answer is routed by
the kiosk adapter straight to the bridge and never through the local
model, which fills its own tools with `args={}`. **So a box with no
`jarvis-code-a2a.service` on it is in bridge mode too**: it reconnects
forever, at a 30 s ceiling, and says so in the journal the first time and
on every drop after.

**Not working / not done:**
- ~~**He has never heard a human voice.**~~ **He has, since 2026-08-25.**
  A USB microphone (`UACDemoV1.0`, `hw:2,0`) is plugged in, PipeWire's
  `default` source routes to it, and the local override that kept the
  microphone shut — `jarvis-widget.service.d/no-mic.conf` — is gone.
  Five spoken turns, transcribed clean, answered out loud. That was the
  last task of widget plan 2 and it is done. `JARVIS_WIDGET_FAKE_MIC`
  stays: it is still how the path is exercised without a human present.
- **He can be asked to look — and that is the whole of what "asking"
  means.** Since 2026-08-25 the `mirar` tool answers "enséñame la
  entrada" with a sentence, and the photo appears above the strip for
  fifteen seconds. He does not see that photo: the model is text-only
  and is told only what YOLO labelled, so any visual detail beyond
  those eight labels is invented — and measured live, he invents it
  ("puerta cerrada, el porche vacío" against a tool that said only
  "no hay nadie"). ~~He also calls `mirar` with **no** camera 5 times
  out of 5, even when one was named.~~ **Fixed 2026-09-03**: the cause
  was our own schema shape, not the model and not Hermes — §12's
  2026-08-26 entry carries it. Measured after the fix, a course opened
  live received its `tema` and filed an eleven-point syllabus; `mirar`
  itself has not been asked again since. **Corrected 2026-08-26:** the
  "no camera 5 times out of 5" was measured through `mirar`, whose handler
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
- ~~**Plan 3 is unwritten:** removing the kiosk, `backend/` and
  `frontend/`.~~ **Done 2026-09-03**, folded into the rename: both trees
  and their two dead units are deleted.
- **The Hermes config is git-ignored**, so `tts:` must be re-applied by
  hand on any new box. Without it his words are synthesised by Edge TTS
  — which means they leave for Microsoft. `Hermes/apply-config.sh`.

### Completed phases (kiosk era, 1–9)

Phases 0–9 built the Chromium kiosk: FastAPI backend, React frontend,
llama.cpp, STT/TTS, ChromaDB memory, systemd deployment, the UI redesign
and the Hermes-Agent integration. All ✅, all superseded as a *surface*
by the widget — the LLM, TTS and Hermes work carried straight over.
`docs/progress-kiosk-era.md` has each one; `PROGRESS.md` indexes them.

### Since (dated, not numbered)

- **2026-08-22** — decision: the widget replaces the kiosk (§12).
- **2026-08-23** — widget plan 1: the strip ✅
- **2026-08-23** — widget plan 2: the voice turn ⏸ blocked on a microphone
- **2026-08-23** — he may act: reminders that arrive unprompted ✅
- **2026-08-23** — JARVIS: the persona, the cloned voice ✅
- **2026-08-23** — vision: the cameras speak ✅
- **2026-08-23** — the LLM comes home: Qwen3.8-27B local, 57 tok/s ✅
- **2026-08-24** — vision moves into the gateway: the `jarvis_vision`
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

# Run him. PYTHONPATH reaches the voice plugin's tts.py and markers.py;
# PYTHONNOUSERSITE keeps ~/.local out of the way (§2.8). It named
# `backend/` too until that tree was deleted on 2026-09-03.
DISPLAY=:0 PYTHONNOUSERSITE=1 \
  PYTHONPATH=$PWD/.. \
  .venv/bin/python -m jarvis_widget

# Tests + lint
.venv/bin/python -m pytest -v
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

`widget/README.md` documents every environment switch — freezing the
wave for a screenshot, running with no microphone, speaking INTO him,
dumping utterances to WAV. Read it before the first run. The cameras are
not among them any more — they are in
`Hermes/plugins/jarvis_vision/README.md`.

### The services around him

```bash
# Install / refresh the user units
cp systemd/*.service ~/.config/systemd/user/
systemctl --user daemon-reload

systemctl --user enable --now jarvis-llamacpp.service   # the LLM, :8000
systemctl --user enable --now jarvis-hermes.service     # the gateway, :7777
systemctl --user enable --now jarvis-widget.service     # him
loginctl enable-linger $USER    # so they survive without a login

journalctl --user -u jarvis-widget.service -f
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
  Jarvis` (title-cased from the platform name; it read `JARVIS_Kiosk`
  before the 2026-08-28 rename, §12), which the strip correctly discards
  as a system message — so the question that triggered it is simply
  gone. Fixed for good with `/sethome` (`Home channel set to JARVIS`,
  was `Kiosk`), which must be re-applied on any new box or after
  `state.db` is lost — see the migration cost in §12.

To tell "the gateway is stuck" from "the strip cannot reach it", stop
the strip first — a second connection replaces the first, so a probe
racing a running widget proves nothing:

```bash
systemctl --user stop jarvis-widget.service
cd widget && PYTHONNOUSERSITE=1 ./.venv/bin/python tools/probe_gateway.py "¿Qué hora es?"
```

### Verifying anything visual

```bash
ffmpeg -y -f x11grab -video_size 1920x1080 -i :0 -frames:v 1 /tmp/strip.png
xwininfo -name "JARVIS"            # did you photograph the strip, or the lock screen?
# The title is "JARVIS" — window.py:101 sets it (it was "JARVIS"
# until 2026-08-28), and no code anywhere calls the window
# "jarvis-widget"; that is only the unit's name. Asking for the wrong
# one answers "No window with name ... exists!" with the strip on screen
# and running (2026-08-25).
```

Nothing about his appearance is provable from a test, and a screenshot of
a locked session is a convincing picture of the wrong thing.

**A press CAN be sent, since 2026-08-26.** `widget/tools/click.py` drives
the pointer through XTEST by ctypes, the way `ewmh.py` reaches libX11 —
`libXtst` is installed even though `xdotool` is not. Anywhere this file
says a keystroke or a click cannot be delivered to the strip (§2.3, the
`JARVIS_WIDGET_STATE` note above), that is now only true of the
keyboard.

```bash
DISPLAY=:0 widget/.venv/bin/python widget/tools/click.py 1309 1032
```

### Legacy: backend and frontend

Both trees were deleted on 2026-09-03. Nothing to run, and nothing to
keep green. `git log -- backend frontend` is where they went.

---

## 6. Coding Conventions

### Python

- **Version:** 3.12+
- **Formatter:** `ruff format` (replaces black)
- **Linter:** `ruff check`
- **Type hints:** mandatory on all public functions
- **Comments:** in English, but JARVIS-facing strings (replies, system
  prompt content) in Spanish
- **Imports:** sorted by isort/ruff convention (stdlib, third-party, local)
- **Logging:** use `loguru` (already configured), never `print()`
- **Error handling:** raise specific exceptions; a thread that talks to
  the outside world catches everything, logs once and backs off (§2.8).
- **Concurrency:** threads around the GTK main loop, not asyncio —
  except `gateway.py`, which owns the only event loop in the widget.

### JavaScript — none is left

There is no browser (§2.3) and `frontend/` is deleted (§3), so no
JavaScript governs anything that runs, and none should be written.

**The UI language is Python + GTK4**, under the Python rules above, with
one addition: `gi.require_version()` must run before the import it
guards, so those imports cannot be at the top of the file and carry
`# noqa: E402`. E402 is off in ruff's default set and is enabled
explicitly in `widget/pyproject.toml` — otherwise ruff flags the noqa
itself as unused.

### Naming

- **Files:** snake_case (`wave_model.py`)
- **Functions:** snake_case
- **Constants:** SCREAMING_SNAKE_CASE

### Testing

- **Python:** pytest, in `widget/tests/` and each plugin's own `tests/`.
  No test in this repo touches the network or the GPU.
- **Every behavior change MUST update existing tests if applicable.**
- **What no test can settle** is anything on screen or in the room
  (§2.3): capture the screen, or put it in front of a person.

---

## 7. The Personality (The Soul)

The persona is **[`Hermes/jarvis-soul.md`](Hermes/jarvis-soul.md)**, and
it is the only one. Read it before writing any string he might say: it
governs everything user-facing — replies, error messages, even the text
that shows while something loads. Any reference to "§7" or "personality
§7" elsewhere points there.

**`docs/personality.md` was deleted on 2026-09-03**, at the user's
instruction, and it had earned it: it described Samantha — warm,
feminine, "she" — while `jarvis-soul.md` was what actually reached him
through the `platform_hint`. Two persona documents, one of them
delivered and the other merely cited, is how a project ends up with an
assistant whose written character and spoken character disagree. The
old text is in `git log -- docs/personality.md`.

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
`/approve`** through the strip after any persona change.

**And restarting the gateway is necessary as well** — this line used to
say only that it "is not enough", which reads as "do not bother", and
that cost a measurement on 2026-09-06. `plugins/jarvis/__init__.py`
builds the hint at REGISTRATION time (`platform_hint=_platform_hint()`,
evaluated once when `register()` runs), so a `/new` alone opens a fresh
session around the persona the process read at boot. The order is:
**restart `jarvis-hermes.service`, then `/new`, then `/approve`.** Hermes Desktop
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
| The process: threads and wiring | `widget/jarvis_widget/__main__.py` |
| One turn, as a state machine | `widget/jarvis_widget/turn.py` |
| The window: borderless, above, and how it grows | `widget/jarvis_widget/{window,ewmh,geometry}.py` |
| The photo band (drawing / pure model) | `widget/jarvis_widget/{photo_area,photo}.py` |
| The wave (drawing / pure model) | `widget/jarvis_widget/{wave,wave_model,bars_model}.py` |
| Colour, and the shadow to kill | `widget/jarvis_widget/theme.py` |
| Listening: VAD and transcription | `widget/jarvis_widget/{vad,stt}.py` |
| Deciding you have finished (rule / model) | `widget/jarvis_widget/endpoint.py` |
| The clock that asks, and the one that decides | `widget/jarvis_widget/vad.py` |
| Speaking: clauses and playback | `widget/jarvis_widget/{speech,audio}.py` |
| The link to the brain | `widget/jarvis_widget/gateway.py` |
| Vision, and what is worth saying | `Hermes/plugins/jarvis_vision/{vision,cameras}.py` |
| Being asked to look, and the JPEG it leaves | `Hermes/plugins/jarvis_vision/{tool,snapshot}.py` |
| The `photo` frame, and the path it refuses | `Hermes/plugins/jarvis/{protocol,adapter}.py` |
| A sighting becomes a turn, not a sentence | `Hermes/plugins/jarvis_vision/alert.py` |
| The cameras, and where the password goes | `Hermes/plugins/jarvis_vision/README.md` |
| Whether he was being spoken to | `widget/jarvis_widget/wake.py` |
| The two switches (drawing / pure model) | `widget/jarvis_widget/{wave,switches}.py` |
| The live view: session, tools, decoding | `Hermes/plugins/jarvis_vision/{live,live_tool}.py`, `widget/jarvis_widget/live_decode.py` |
| Testing without a microphone | `widget/jarvis_widget/fake_mic.py` |
| The phone: socket, auth, audio, enrolment | `widget/jarvis_widget/{remote,remote_auth,remote_audio,enrol,certs}.py` |
| What one scan hands a phone | `widget/jarvis_widget/enrol.py` (`sobre`), `certs.py` (`spki_fingerprint`) |
| The page it serves | `widget/jarvis_widget/static/movil.html` |
| A course's state: the plan, concepts, questions | `Hermes/plugins/jarvis_teacher/curso.py` |
| The sources, and the domain gate in front of them | `Hermes/plugins/jarvis_teacher/fuentes.py` |
| The card, drawn and as state | `widget/jarvis_widget/{ficha_area,ficha}.py` |
| The surface Hermes speaks through | `Hermes/plugins/jarvis/` |
| His identity | `Hermes/jarvis-soul.md` (and §7 — sessions!) |
| Model, provider, TTS provider | `Hermes/jarvis-config.yaml` |
| CosyVoice, and the voice prompt | `tts-server/cosyvoice/server.py`, `Hermes/plugins/jarvis_voice/tts.py` |
| The reference clip | `voices/` |
| Services | `systemd/*.service` |
| Why a thing is the way it is | `docs/decision-log.md` (indexed in §12) |
| Designs and plans, dated | `docs/superpowers/` |

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
| **`samantha_kiosk`** | What the platform, the plugin and the chat were called until 2026-08-28. Every plan and spec under `docs/superpowers/` still says it, because they are the record of the day they were written. In the running system it is `jarvis` (§12). |
| **OS1 / cinta** | The Three.js 3D ribbon loader from the film, attributed to Siyoung Park (MIT). Lived in `frontend/`, deleted with it. |
| **The wave / línea** | The line that represents him on the strip, drawn in GSK. Four states: idle, listening, thinking, speaking. |
| **The band / la banda** | The strip's second half, above the wave and zero pixels tall until a photo arrives. It grows the window rather than opening one. |
| **Onboarding / primer encuentro** | The first-run flow: boot → calibration → voiceprint → greeting → 6 questions → generating → welcome |
| **The 6 questions** | Personality calibration questions asked once |
| **Voiceprint / huella de voz** | User's voice embedding stored on first run |
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
- **FastAPI:** https://fastapi.tiangolo.com/ (v3's backend, deleted)

---

## 12. Decision Log — the index

The log itself is **[`docs/decision-log.md`](docs/decision-log.md)**:
append-only, newest first, every entry with the measurement that decided
it. It lived here until 2026-09-06 and was moved out unedited — it had
grown to 60% of a file that is read whole at the start of every session.

**Read the entry before reversing what it decided.** Several of these
record the same idea being rejected twice, on numbers; §12 is where
"why not Electron" and "why not an avatar" already have answers.

- **2026-09-06** — One scan carries the house, not a link to it
- **2026-09-06** — He says what he is doing, and what he is for
- **2026-09-05** — The house becomes several people, and he gets a face
- **2026-09-03** — The card gets a webview, and the estimate goes
- **2026-09-03** — He teaches, grounded in sources he went and fetched
- **2026-09-01** — He stops being tied to the desk
- **2026-09-01** — The harness comes off, and three claimants pay for it
- **2026-09-01** — The engine that cannot punctuate gets the job
- **2026-09-01** — He gets no face: the avatar is dropped, all of it
- **2026-08-28** — The kiosk stops being a kiosk
- **2026-08-27** — Two things the suites could not see, and a chain bounded
- **2026-08-27** — The console gets milestones, and JARVIS can be asked
- **2026-08-26** — The bridge drives the SDK, so a task can be stopped
- **2026-08-26** — He delegates coding, and `terminal` stops being forbidden
- **2026-08-26** — The alert grows a picture, and the wake word does not
- **2026-08-26** — BarnDoor's rule back, and a ceiling on a turn
- **2026-08-26** — The tools were reachable; the clock was not
- **2026-08-26** — He answers to his name, and the strip gains two switches
- **2026-08-26** — Showing a camera is the moving picture, and it delivers on the gateway's loop
- **2026-08-25** — The photo reaches the strip and nothing else
- **2026-08-25** — The kiosk contract gains its first new frame
- **2026-08-24** — He stops repeating himself, and the password leaves the URL
- **2026-08-24** — Vision moves out of the widget and into a Hermes plugin
- **2026-08-24** — The cameras become plural, and named
- **2026-08-23** — Samantha can see: BarnDoor's cameras, reused not integrated
- **2026-08-23** — Electron reconsidered for the widget, and rejected again
- **2026-08-23** — Samantha may act: agentic, but never visibly
- **2026-08-23** — The LLM came home: Qwen3.8-27B local, and Grok demoted
- **2026-08-23** — Samantha becomes JARVIS
- **2026-08-22** — The Chromium kiosk is replaced by a GTK4 desktop widget
- **2026-05-15** — LLM switched from local Qwen3-8B to Grok API
- **2026-05-13** — Offline-only requirement relaxed; STT moves to browser
- **2026-05-13** — npm → pnpm (corepack)
- **2026-05-13** — Vanilla JS → React + Vite + TypeScript
- **2026-05-13** — Memory architecture: short/long-term + facts + fastembed
- **2026-05-12** — vLLM → llama.cpp
- **2026-05** — Ubuntu Frame → Chromium kiosk
- **2026-05** — Ubuntu Server 24.04 LTS (not Ubuntu Core)
- **2026-04** — Local-only architecture (no remote iPad)
- **2026-04** — macOS → Linux
- **2026-05** — Qwen 3.5-9B as default model
- **2026-05** — Horizontal wave replaces orb

**Adding one:** the entry goes in `docs/decision-log.md`, one line comes
here, and whatever section it changes (§0–§11) changes in the same commit.

---

## End of CLAUDE.md

This document is the source of truth. When in doubt, re-read it before
asking the user. Update PROGRESS.md after each phase completion, not
this file (this file changes only when decisions change).
