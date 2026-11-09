# CLAUDE.md — JARVIS

> **For every agent:** this is the single source of truth for this
> project. Read it whole before changing anything; when it disagrees with
> your defaults, it wins. It describes **what runs today**. Why things are
> the way they are lives in [`docs/decision-log.md`](docs/decision-log.md)
> (indexed in §12); what happened day by day lives in `PROGRESS.md`.
> History does not go in this file.
>
> **Naming.** He is JARVIS. Until 2026-08-23 he was Samantha, and some
> environment variables and identifiers still say `SAMANTHA_*` or
> `samantha`. Renaming them is not worth the churn. The platform he speaks
> through has been `jarvis` since 2026-08-28.

---

## 0. TL;DR

JARVIS is an **AI presence that lives in the house**: he listens, speaks
in a cloned voice, watches the house's cameras, remembers, reminds, and
can act. He is a presence, not an application someone opens.

**What runs today (since 2026-09-23):**

- **Hardware:** one Ubuntu box with an RTX 4090 (24 GB VRAM). VRAM is the
  budget everything competes for (§2.1).
- **Brain:** Hermes Agent, the **standard install in `~/.hermes`**
  (v0.21.4, no local patches). Started through `Hermes/run-gateway.sh`.
  - gateway on `:7777`, with the `jarvis` platform plugin;
  - `hermes serve` on `127.0.0.1:9119`, which Hermes Desktop connects to.
- **Surface:** **Hermes Desktop**, and its native voice mode (streaming
  TTS, voice barge-in, transcript on screen). The phones reach Hermes
  through the `jarvis` plugin's mobile admission.
- **LLM:** local `llama-server` on `:8000`, **Ternary Bonsai 2 27B
  PTQ1_0**, on the **PrismML fork** of llama.cpp (§2.5).
- **TTS:** CosyVoice 3 zero-shot in Docker on `:8093`, JARVIS' cloned
  voice, registered in Hermes by `jarvis_voice`.
- **STT:** the Desktop's, set to `es` + `large-v3-turbo`.
- **Vision:** YOLOv9 over onnxruntime against the house's RTSP cameras,
  inside the gateway (`jarvis_vision`).
- **Memory:** Hermes' own (`memories/USER.md`, `state.db`). An Obsidian
  vault is a separate place he can *read*, not memory (§2.7).
- **Other plugins:** `jarvis_teacher` (courses grounded in sources),
  `jarvis_code` (delegated coding via the A2A bridge on `:9910`),
  `jarvis_minecraft` (a body in Minecraft, through a Node bridge).
- **Language:** Spanish (Spain) for everything he says.

**Deprecated, kept on disk:** `widget/` — the GTK4 strip that was the
surface from 2026-08-23 to 2026-09-23. `jarvis-widget.service` is stopped
and disabled. The tree stays because the teacher cards, the photos
(`mirar`) and the live camera were drawn there and have no other surface
yet except the phone, and because pieces of it (Silero VAD, the echo
filter, the wake-word matcher) may be reused. Do not build new features
on it without asking.

```
          Hermes Desktop            phones (LAN, TLS)
                │                          │
        127.0.0.1:9119               jarvis plugin
                │                          │
┌───────────────▼──────────────────────────▼────────┐
│  Hermes (~/.hermes)  gateway :7777 · serve :9119  │
│   jarvis · jarvis_voice · jarvis_vision ·         │
│   jarvis_teacher · jarvis_code · jarvis_minecraft │
└──────┬───────────────────┬─────────────────┬──────┘
       │                   │                 │
 llama-server :8000   CosyVoice :8093   A2A bridge :9910
 (Bonsai 2 27B)       (Docker)          Minecraft bridge
```

---

## 1. Product Principles (in priority order)

1. **Privacy by default, not as a property.** All inference runs on this
   box: LLM, voice, ears, eyes. Nothing said in the room leaves it by
   default. Silent leaks to know about:
   - **Hermes' `tts.provider` defaults to `edge`** (Microsoft's cloud). If
     the `tts:` block from `Hermes/jarvis-config.yaml` is not merged into
     `~/.hermes/config.yaml`, his words are synthesised in the cloud and it
     *looks* like it works. Re-apply with `Hermes/apply-config.sh` on every
     box.
   - Cron/reminders resolve their own model, separately from the gateway.
     Pin both or the path splits.
   - A web search is the only thing that normally leaves the house — which
     is why he says so (principle 2).
   - Switching the LLM to X.AI's Grok API is one config line, and then the
     conversation leaves the house.
   - The phones reach him over the house network, behind a shared secret
     and TLS. The threat model is **whoever is on the wifi**, guests
     included, and what is behind it is an agent holding `terminal`.

2. **Conversational first, able to act, never a visible agent.** He
   remembers, asks, has opinions. He can control the house, remind, look
   things up, see the cameras, delegate code. Acting serves the
   conversation, never replaces it:
   - He never names tools, counts steps ("ejecutando 3 de 5") or narrates
     routine successes.
   - He *does* say, in the past tense and before the result, that he went
     outside and what he found ("He estado buscando sobre eso y he
     encontrado…"). Announcing it *before* the tool call is impossible: a
     turn reaches the surface as one finished frame.
   - He mentions what he noticed on a camera in his own words; he never
     reports a detection.
   - He may say what he can do for someone new; he never says how.

3. **Aesthetic restraint.** One colour (`#d1684e`), one typography pair
   (Cormorant Garamond + Inter Tight), no badges, no emojis in UI, no
   marketing language. (The Desktop pet, `display.pet`, lives outside this
   rule by decision — §12, 2026-09-22.)

4. **Latency over correctness.** A fast answer that is 90% as good beats a
   slow perfect one. Choose the faster model; ≥30 tok/s is the floor.

5. **Present, not launched.** Systemd user services start everything; the
   desktop stays the user's.

**What he is NOT:** a cloud-LLM wrapper; a coding assistant (he delegates
code, he does not *become* one); a visible agent (see principle 2). He is
**multi-user** — several people in the house, including two teenagers who
study with him (`jarvis_teacher`).

---

## 2. Architecture Decisions (Non-Negotiable)

Do NOT revisit these without explicit user permission. Each has its
reasoning in the decision log.

### 2.1 Hardware and the VRAM budget

One box, RTX 4090, 24,564 MiB. **Four claimants**, and the fourth — the
desktop — is the one every arithmetic here has forgotten at least once.
Last full measurement, 2026-09-19 (with the strip still running):

| | MiB |
|---|---|
| llama-server (Bonsai 2 27B PTQ1_0, KV q4_0, 64K) | 8,044 |
| CosyVoice (mid-synthesis) | 5,086 |
| widget Whisper int8 — **now off; the Desktop's STT replaces it, unmeasured** | 1,457 |
| the desktop (Xorg, gnome-shell, a browser tab) | ~240 |
| **free** | **~9,300** |

**Subtract every claimant before changing any of them.** No unit does it
for you, and getting it wrong is silent (it left him deaf for three days
in August). Re-measure with `nvidia-smi` before the next model change.

Everything runs on loopback except the phone admission, which binds the
LAN interface — **never `0.0.0.0`**: the box has a dozen Docker bridges.

### 2.2 OS: Ubuntu, GNOME on X11

`DISPLAY=:0`; Wayland is out of scope. All services are systemd **user**
units. **A unit must not set `DISPLAY` itself**: GNOME imports `DISPLAY`
and `XAUTHORITY` into the user manager, and units `After=` /
`PartOf=graphical-session.target` inherit them. Hardcoding the wrong one
fails silently.

### 2.3 Surface: Hermes Desktop

Since 2026-09-23 the surface is Hermes Desktop pointed at
`http://127.0.0.1:9119`. Its native voice mode is better than the strip's
hand-built pipeline: one audio clock, sentence-streamed TTS, full-duplex
barge-in without cutting itself off on its own echo, and it writes what
it says.

- `jarvis-hermes-serve.service` must be running, and needs
  `HERMES_DASHBOARD_SESSION_TOKEN` in a drop-in or it does not
  authenticate.
- Teacher cards, photos and the live camera **have no desktop surface**
  right now. That is a known gap, not a bug to patch onto the deprecated
  strip.
- **Rules that still hold:** MUST NOT introduce Rust, Tauri, Electron of
  our own, snap packaging, or a browser/webview we ship. The one webview
  carve-out (WebKitGTK for the teacher card, JS off, network refused, no
  `file://` base) lives in the deprecated widget and must not spread.

### 2.4 Brain: Hermes in `~/.hermes`

- The standard install (`~/.hermes/hermes-agent`), official release,
  **no core patches**. The in-repo pinned runtime (`.hermes/src`,
  `Hermes/setup-runtime.sh`, `*.patch`) is deprecated.
- `Hermes/run-gateway.sh` is the one entry point: it sources the
  git-ignored `.env` (credentials such as `RTSP_PASSWORD`), sets
  `HERMES_HOME=~/.hermes`, puts the repo root on `PYTHONPATH` (plugins
  import the `Hermes` package; without it TTS falls through to Edge), and
  puts `Hermes/bin` first on `PATH`. It calls the venv binary directly
  because `~/.local/bin/hermes` unsets `PYTHONPATH`.
- Plugins are symlinked into `~/.hermes/plugins`. **Hermes resolves
  plugins per profile**: a profile without its own `plugins/` links sees
  core tools only, and nothing errors. Profile multiplexing is off.
- Repo settings live in `Hermes/jarvis-config.yaml` and are merged into
  `~/.hermes/config.yaml` by `Hermes/apply-config.sh`. Only
  `plugins.enabled` gates loading; `entries.<id>.enabled` does not.
- **Lost with the patches:** the streaming-TTS echo fix and the phone's
  toolset override. A text turn with `auto_tts: true` tries to synthesise
  a whole-file WAV the text adapter cannot deliver.

### 2.5 LLM: Bonsai 2 27B on the PrismML fork

- Runtime: PrismML's prebuilt `llama-server` (`prism-b10709`, CUDA 12.4)
  at `~/.jarvis/bin/llama-prism/`. **Not** upstream llama.cpp: the ternary
  packings need a runtime Walsh–Hadamard transform upstream lacks, and a
  stock build loads them silently and outputs gibberish.
- Model: Ternary Bonsai 2 27B **PTQ1_0** (1.76 bpw, 5.93 GB on disk).
  ~8.2 GB resident at 64K with q4_0 KV, **88.6 tok/s**. Its cost is
  prefill: half of PQ2_0's (1,569 vs 3,117 pp512); the owner chose decode.
- Sampling: temp 0.5, top-p 0.85, top-k 20, min-p 0.
- **Thinking off** with `--chat-template-kwargs '{"enable_thinking":
  false}'`. `--reasoning-budget 0` does not work on this fork, and
  `--reasoning-format none` leaks a literal `<think>`. With thinking on,
  `content` comes back empty and he never speaks.
- **64K context is a hard floor**: Hermes refuses less and kills the turn.
- **Provider and model are separate fields**: `model.default:
  custom:local` sends that literal string as the model name (404).
- Rollbacks on disk: Bonsai PQ2_0, Gemma 4 26B-A4B IQ4_XS, Qwen3.8-27B
  GSQ-RCO. Remote fallback: X.AI `grok-4-1-fast-non-reasoning` (§1.1).

### 2.6 Voice

- **TTS:** CosyVoice 3 zero-shot, Docker, `:8093`, cloned from the clip +
  transcript in `voices/`. 24 kHz int16. fp16 autocast
  (`COSYVOICE_FP16=1`, default); weights stay fp32. The text before
  `<|endofprompt|>` conditions *delivery*, not words — set it with
  `JARVIS_TTS_COSYVOICE_VOICE_PROMPT`.
- `Hermes/plugins/jarvis_voice/` registers `cosyvoice` in both Hermes TTS
  registries; the `tts` toolset is disabled.
- **STT:** the Desktop's, `es` + `large-v3-turbo`. It ships as `en` +
  `base` and then transcribes Spanish into English.

### 2.7 Memory and the vault

- **Memory** is Hermes': `memories/USER.md` is injected into every turn.
  Directive (2026-05-12): *JARVIS never forgets anything* — never
  verified against Hermes' `memory` toolset.
- **The vault** is the user's Obsidian Markdown, read through Hermes'
  `note-taking/obsidian` skill and the `file` toolset, only when the
  conversation asks. Never write the same fact into both.
  - It is grep, not retrieval: fine for tens of notes, silently blind at
    thousands.
  - `file` is not a sandbox: absolute paths reach the whole disk.
  - Path: `OBSIDIAN_VAULT_PATH` in the git-ignored `.env`; without it the
    skill falls back to `~/Documents/Obsidian Vault`.
  - Syncing it through Obsidian Sync or iCloud breaks §1.1; Syncthing
    between the user's own machines does not.

### 2.8 Vision

`jarvis_vision` runs YOLOv9 (onnxruntime) inside the gateway, one thread
per named camera. Camera URLs reference `${RTSP_PASSWORD}` from `.env`.
The model is text-only: he is told only what YOLO labelled, so any visual
detail beyond those labels is invented. Details and quiet rules:
`Hermes/plugins/jarvis_vision/README.md`.

### 2.9 Language

- Everything he says, prompts, user-facing strings: **Spanish (Spain)**.
- Code identifiers, comments, commit messages, this file, READMEs:
  **English**. (`PROGRESS.md` and the decision log are written in
  Spanish by the owner; keep each file's existing language.)

---

## 3. Project Structure

```
os1-jarvis/
├── CLAUDE.md            ← this file
├── AGENTS.md            ← points here
├── PROGRESS.md          ← the log, newest first; you append to it
├── README.md
├── Hermes/              ← what the repo adds to Hermes
│   ├── jarvis-soul.md       ← the persona (§7)
│   ├── jarvis-config.yaml   ← settings merged into ~/.hermes/config.yaml
│   ├── apply-config.sh
│   ├── run-gateway.sh       ← the one entry point (§2.4)
│   ├── bin/claude           ← wrapper that tees coding output
│   ├── bridges/code-a2a/    ← the A2A bridge for delegated coding (:9910)
│   └── plugins/
│       ├── jarvis/          ← the platform: adapter, protocol, mobile auth, policy
│       ├── jarvis_voice/    ← CosyVoice inside Hermes
│       ├── jarvis_vision/   ← cameras, YOLO, `mirar`, live view
│       ├── jarvis_teacher/  ← courses, sources and their domain gate
│       ├── jarvis_code/     ← follows the A2A bridge
│       └── jarvis_minecraft/← a body in Minecraft (Node bridge + tools)
├── tts-server/          ← CosyVoice 3 in Docker
├── voices/              ← the reference clip
├── systemd/             ← user units
├── widget/              ← DEPRECATED: the GTK4 strip (§0)
└── docs/
    ├── decision-log.md  ← why; indexed in §12
    ├── progress-*.md    ← older months of the log
    └── superpowers/     ← designs and plans, dated
```

**Rules:**
- MUST NOT add top-level directories without asking.
- MUST NOT recreate `backend/` or `frontend/` (deleted 2026-09-03).
- New Hermes-side work goes in `Hermes/plugins/`. New surface work: ask
  first — the strip is deprecated and the Desktop is not ours.

---

## 4. Current Status

**Working:** Hermes Desktop with native voice; the local LLM; CosyVoice;
vision on the named cameras; reminders; memory; the vault; delegated
coding through the bridge; the phones.

**Open:**
- Teacher cards, photos and the live camera have no desktop surface.
- The streaming-TTS echo fix and the phone toolset override were lost with
  the core patches (§2.4).
- "Who came this morning" has no answer: no detections table, no
  `revisar` (vision plan 2).
- Minecraft: verified by probe; a test with a person talking is pending.
- VRAM not re-measured since the strip stopped (§2.1).
- `frontend/` still holds four tracked build leftovers.

`PROGRESS.md` is the authority on what each day cost.

---

## 5. Common Commands

```bash
# Units
cp systemd/*.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now jarvis-llamacpp.service     # LLM :8000
systemctl --user enable --now jarvis-hermes.service       # gateway :7777
systemctl --user enable --now jarvis-hermes-serve.service # serve :9119 (Desktop)
loginctl enable-linger $USER
journalctl --user -u jarvis-hermes.service -f

# Optional: jarvis-code-a2a.service (:9910), jarvis-minecraft-bridge.service
# CosyVoice: Docker, from tts-server/cosyvoice/, on :8093. Without it he is mute.

# Hermes CLI against this instance
Hermes/run-gateway.sh --version
Hermes/run-gateway.sh plugins list
Hermes/apply-config.sh            # re-merge jarvis-config.yaml

# Plugin tests (each plugin has its own tests/)
python -m pytest Hermes/plugins -q
ruff check . && ruff format --check .
```

**After changing the persona:** restart `jarvis-hermes.service`, then send
`/new`, then `/approve`. Both are needed (§7).

**He hears you and says nothing:**
- **A run is stuck** (any command answers `⏳ Agent is running`, new turns
  are `↪ Redirected` into it). `/stop` clears it.
- **A new session eats its first turn** with `📬 No home channel is set`.
  `/sethome` fixes it; re-apply on a new box or after losing `state.db`.
- **Plugin tools missing** from the model's payload: check the profile's
  `plugins/` links (§2.4).

---

## 6. Coding Conventions

- **Python 3.12+**, `ruff format` + `ruff check`, type hints on all public
  functions, `loguru` (never `print()`).
- Raise specific exceptions. A thread that talks to the outside world
  catches everything, logs once and backs off.
- Naming: snake_case files and functions, SCREAMING_SNAKE_CASE constants.
- **Tests:** pytest, in each plugin's `tests/` (and `widget/tests/`). No
  test touches the network or the GPU. Every behaviour change updates its
  tests.
- Nothing about voice, screen or room is provable by a test: measure it,
  or put it in front of a person.
- No JavaScript of ours, except the Minecraft bridge (Node, Mineflayer).

---

## 7. The Personality

The persona is **[`Hermes/jarvis-soul.md`](Hermes/jarvis-soul.md)**, the
only one. Read it before writing anything he might say — replies, errors,
loading text.

**The trap:** it is delivered through the `jarvis` platform's
`platform_hint`, **not** `SOUL.md` (Hermes reads `SOUL.md` only for cron).
The hint is built once, when the plugin registers at gateway start, and a
session's system prompt is fixed when the session is born. So after any
persona change: **restart the gateway, then `/new`, then `/approve`.**
Hermes Desktop may *appear* to obey instantly because it opens its own
session — that discrepancy is the clue.

---

## 8. Agent Behavior

**MAY proceed without asking:** bug fixes that don't change observable
behaviour, refactors within a file, tests for existing behaviour,
comments and docs, type hints, formatting.

**MUST ask before:** changing anything in §2; adding top-level
directories; adding Python or JS dependencies; changing a plugin's
protocol/contract (`Hermes/plugins/jarvis/protocol.py`); deleting or
renaming public APIs; changing the persona; building on the deprecated
widget.

**MUST always:** read this file at session start; run the relevant tests
before declaring done; `ruff format` before committing; write what he says
in Spanish and code in English; check new user-facing text against §7;
append to `PROGRESS.md` after finishing a piece of work; when a decision
changes, add it to `docs/decision-log.md`, one line to §12, and update the
section it changes in the same commit.

**Communication:** concise, show evidence ("tests pass" with output), name
trade-offs. A decision not covered here → stop and ask. A test failure not
resolved in 3 attempts → stop, report, ask.

---

## 9. Critical Files

| Topic | Files |
|---|---|
| Starting Hermes, env, credentials | `Hermes/run-gateway.sh`, `.env` (git-ignored) |
| Settings he cannot be without | `Hermes/jarvis-config.yaml`, `Hermes/apply-config.sh` |
| Identity | `Hermes/jarvis-soul.md` (§7) |
| The platform surface, frames, delivery | `Hermes/plugins/jarvis/{adapter,protocol,delivery}.py` |
| Phone admission and policy | `Hermes/plugins/jarvis/{mobile_auth,policy,alta}.py` |
| CosyVoice in Hermes | `Hermes/plugins/jarvis_voice/tts.py`, `tts-server/cosyvoice/server.py` |
| Cameras, `mirar`, live view | `Hermes/plugins/jarvis_vision/` (and its README) |
| Courses and sources | `Hermes/plugins/jarvis_teacher/{curso,fuentes}.py` |
| Delegated coding | `Hermes/bridges/code-a2a/`, `Hermes/plugins/jarvis_code/` |
| Minecraft | `Hermes/plugins/jarvis_minecraft/` |
| LLM flags and why | `systemd/jarvis-llamacpp.service` |
| Services | `systemd/*.service` |
| Why anything is the way it is | `docs/decision-log.md` |

---

## 10. Glossary

| Term | Meaning |
|---|---|
| **Gateway** | Hermes' daemon on `:7777`: brain, memory, tools, plugins. |
| **Serve** | `hermes serve` on `127.0.0.1:9119`, what Hermes Desktop connects to. |
| **The strip / la tira** | The GTK4 widget along the bottom of the screen; the surface until 2026-09-23, now deprecated. |
| **The turn** | One exchange, from someone starting to talk to his last spoken clause. |
| **`samantha_kiosk`** | The platform's name until 2026-08-28; plans under `docs/superpowers/` still use it. Now `jarvis`. |
| **Terracotta `#d1684e`** | The one colour, from *Her*. |

---

## 11. References

- *Her* (2013), Spike Jonze — the aesthetic.
- Hermes Agent: https://github.com/NousResearch/hermes-agent
- CosyVoice: https://github.com/FunAudioLLM/CosyVoice
- llama.cpp: https://github.com/ggml-org/llama.cpp
- Silero VAD: https://github.com/snakers4/silero-vad
- faster-whisper: https://github.com/SYSTRAN/faster-whisper

---

## 12. Decision Log — the index

The log is **[`docs/decision-log.md`](docs/decision-log.md)**: append-only,
newest first, each entry with the measurement that decided it. **Read the
entry before reversing what it decided** — several ideas ("why not
Electron", "why not an avatar") have already been rejected twice.

- **2026-09-23** — Hermes leaves the repo, and the strip retires: the Desktop is the surface
- **2026-09-22** — Hermes moves to 0.21.4, and the core patch moves with the refactor
- **2026-09-22** — A Minecraft body, and a routed profile was hiding every plugin tool
- **2026-09-22** — The mascot becomes Hermes' own pet, and the bóxer goes
- **2026-09-19** — Bonsai 2 27B: a ternary 27B that gives back 4 GB of VRAM
- **2026-09-08** — Gemma makes the turn fast enough to disappear
- **2026-09-08** — Precision moves where it matters, and JARVIS gets VRAM back
- **2026-09-08** — Grok 4.6 is tried, and reasoning costs a conversation
- **2026-09-07** — The credential moves to a header, and the web page goes
- **2026-09-06** — He gains a vault, and it is not his memory
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
