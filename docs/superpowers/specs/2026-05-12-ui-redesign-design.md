# Samantha UI Redesign v2 — Design Spec

**Date:** 2026-05-12
**Status:** Brainstormed, pending implementation plan
**Supersedes:** Phase 3 frontend (commit `58ba75f`, mockup migration)

---

## 1. Context

The Phase 3 frontend was a faithful migration of `samantha_mockup_v7.html` into modular vanilla-JS files. It works but reads as a prototype:

- **Onboarding repeats on every page reload** — no way to know "this user already met Samantha". (The fix lives in Samantha's memory itself, not in a parallel file — see §9.)
- **Conversation screen lacks "presence"** between turns — just a wave with a small transcript and an input bar.
- **No idle/ambient state** — when the user isn't actively chatting, there's no screen that says "she's still here".
- **No way to view or interact with memory** — ChromaDB stores chunks but they're invisible to the user.
- **Debug panel in production** — bottom-left "↻ reiniciar" / "→ conversación" breaks the appliance illusion.
- **`app.js` is monolithic** (~400 lines mixing boot, calibration, voiceprint, questions, generating, welcome, conversation, mic, TTS).
- **`index.html` stacks all 7 screens** in one DOM tree.
- **No typography system** — each screen picks font sizes ad hoc.

This redesign addresses all of the above plus introduces a structural change: the frontend moves to **React + Vite + TypeScript**, replacing the vanilla-JS-no-build approach declared in CLAUDE.md §3.

## 2. Goals

1. Eliminate onboarding-repeats-on-reload by storing the onboarding-complete marker as a fact in Samantha's memory and gating onboarding on its presence. No separate profile file.
2. Introduce an **Ambient** screen as the default landing post-onboarding — minimal but alive, communicates "she's here".
3. Redesign **Conversation** as immersive (wave centered behind text, no chrome) with a one-tap/one-key toggle to the message history.
4. Replace the wave model with a **traveling wave packet** (oscillation pulses that propagate through the line like waves on a taut string).
5. Define a real **type and color system** with named tokens, applied consistently.
6. Break the monolith into per-screen modules and isolated layers (core / net / components / screens).
7. Adopt React + Vite + TypeScript for component model and dev ergonomics.
8. Remove the debug panel from production UI.

## 3. Non-goals

- **Samantha proactiva** (her initiating conversation on her own) — deferred. The architecture leaves room for a future initiative engine, but v2 ships without it.
- **Real STT/TTS** — Phase 5 territory. The redesign's mic button still triggers a WS `listen` and the mock backend responds; Piper/Whisper integration is separate.
- **Multi-user** — Samantha remains single-user (CLAUDE.md §1).
- **Mobile/responsive** — kiosk target is a fixed-size display.
- **Theme variations** (dark/light, color modes) — one terracotta `#d1684e`, one palette, per CLAUDE.md §1.

## 4. Flow architecture

Four primary states; first-encounter is a compound state visited only when no profile exists.

```
                                  ┌────────────── 404 ──────────────┐
                                  │                                  │
   ┌──────┐    ┌────────────┐    ┌─┴────────────────────┐         ┌─────────────┐
   │ boot │──▶ │ GET /profile │──▶│   ¿hay profile?     │── no ──▶│ FIRST       │
   │ ~1.5s│    │              │   └──────────────────────┘         │ ENCOUNTER   │
   └──────┘    └────────────┘     │                                │ (compound)  │
                                  │ sí (200)                        │ ─ calib    │
                                  ▼                                 │ ─ voicprt  │
                              ┌────────────┐    touch              │ ─ greet    │
                              │  AMBIENT   │ ◀────────┐            │ ─ Q1..Q6   │
                              │  (home)    │          │            │ ─ gen      │
                              └─────┬──────┘          │            │ ─ welcome  │
                                    │ touch / tap    5 min idle    └──────┬─────┘
                                    ▼                  │                  │
                              ┌────────────┐           │      POST /profile│
                              │CONVERSATION│ ──────────┘                   │
                              │ (default:  │                               │
                              │  immersive)│ ◀─────────────────────────────┘
                              └────────────┘
                                    │
                                    │  H key / ≡ icon
                                    ▼
                              ┌────────────┐
                              │CONVERSATION│ — historial visible
                              │ (history)  │   se vuelve al inmersivo con
                              └────────────┘   misma tecla / icono ×
```

**Lifecycle rules:**

- Boot is a brief intro (~1.5 s) showing the OS1 cinta. It calls `GET /profile`. On `404` → first-encounter. On `200` → Ambient.
- First-encounter runs the existing 6-question flow plus the calibration/voiceprint pre-flow. On completion it calls `POST /profile` (which also seeds memory with the 6 answers), then navigates to Ambient.
- Ambient is the "home" of the appliance. Tap/click anywhere → Conversation.
- Conversation has two visual states: immersive (default) and history (toggled). A 5-min idle timer returns to Ambient. Conversation state itself (transcript) persists in memory across returns.

## 5. Screen-by-screen design

### 5.1 Boot

- Solid terracotta `#d1684e`.
- Centered OS1 ribbon (Three.js) at "small" size (200×200 px container).
- The word "samantha" appears below in uppercase Inter Tight, letter-spaced.
- Duration ~1.5 s, only enough to mask the `GET /profile` round-trip.

### 5.2 First-encounter

A compound screen with its own sub-router. Sub-screens:

1. **Calibration** — text "escuchando el ambiente" → "ahora tu voz". Audio visualizer canvas. The real audio capture lands in Phase 5; for now the timings are scripted (matches current behaviour).
2. **Voiceprint** — quoted phrase «Hola Samantha, soy yo». Recording indicator, brief audio viz, then a transformation flash (white fade) → cinta morphs to disc.
3. **Greet** — wave (idle mode) + "Hola. Estoy aquí." displayed, button "empezar".
4. **Six questions** — same questions as today, with progress dots, text input, mic button, "saltar pregunta" hint.
5. **Generating** — large OS1 disc + status messages cycling ("Procesando…", "Calibrando tono", "Casi lista") → final transformation flash.
6. **Welcome** — wave + "Hola, [name]. Soy Samantha. Encantada de conocerte." → button "conversar".

On completion of welcome:
- `POST /profile` with `{name, answers}`.
- The 6 answers are ALSO inserted into ChromaDB memory as `role: "user"` chunks with their timestamp.
- Navigate to Ambient.

### 5.3 Ambient

**Layout** (datos sutiles variant, approved):

```
┌──────────────────────────────────────────────────────┐
│                                                      │
│   jueves                                  23:14      │  ← labels: 0.68rem, 0.34em tracking, weight 400, opacity 0.9
│                                                      │
│                                                      │
│              ──── (wave idle) ────                   │  ← wave at vertical center
│                                                      │
│                                                      │
│                                                      │
│                   tarde tranquila                    │  ← Cormorant italic 1.5rem
│                                                      │
└──────────────────────────────────────────────────────┘
```

**Contextual phrase logic** (fixed deterministic mapping from local hour to one specific phrase — no randomness):

- 00:00–05:59 → "madrugada"
- 06:00–11:59 → "buenos días"
- 12:00–14:59 → "buena hora"
- 15:00–19:59 → "tarde tranquila"
- 20:00–22:59 → "ya es de noche"
- 23:00–23:59 → "fin del día"

The mapping is a pure function `hour → phrase` so the same hour always shows the same phrase. Recomputed every minute by a `setInterval`.

Tap/click anywhere on the screen → navigate to Conversation.

The wave runs in `idle` mode with very low amplitude pulses (almost a flat line). See §6 for wave spec.

### 5.4 Conversation

Two visual states, same screen. Toggle is **instant** (no transition); the underlying chat state is identical.

**Common header** (both states):

- Top-left: `← ambient` (icon + label). Tap or `Esc` returns to Ambient.
- Top-right: `≡` (history) or `×` (back to immersive) + clock + optional state label ("escuchando" / "pensando" / "hablando").

**Immersive (default):**

- Wave packet **occupies the full center vertically** behind everything (z-index 1).
- Only the last Samantha message is shown, centered horizontally, slightly below center vertically, Cormorant italic 1.2 rem, full opacity. User messages are NOT shown in immersive — only Samantha.
- Big circular mic button at bottom-center (48 px diameter, white fill).
- No text input visible.

**History (toggled by `≡` icon or `H` key):**

- Wave fades to a thin static line at top (visual marker, doesn't move).
- The transcript fills most of the screen: messages flow chronologically with masking gradient at top edge.
- Samantha messages in Cormorant italic; user messages in Inter Tight, right-aligned, prefixed with `—`.
- Active (latest) message at `--ink` opacity; previous at `--ink-soft`; older at `--ink-dim`; oldest at `--ink-faint`.
- Mic button at bottom-center (smaller, 42 px) with a thin top border separating it from the transcript.

**Text input fallback:**

- Hidden by default.
- Revealed by the `T` key (no visible UI affordance — keeping with the aesthetic-restraint principle). A thin input fades in under the mic.
- Pressing Enter submits the message and hides the input again.
- `Esc` while the input is focused dismisses the input without leaving Conversation; a second `Esc` returns to Ambient.
- For a touch-only deployment without a keyboard, a future iteration can add a long-press on the mic button to reveal the input. v2 does not implement this.

**Keyboard bindings (kiosk + dev):**

| Key | Action |
|---|---|
| `Esc` | Back to Ambient |
| `H` | Toggle immersive ↔ history |
| `T` | Toggle text input visibility |
| `Space` | Push-to-talk (alternative to tap on mic) |
| `Enter` (in input) | Submit text message |

**Idle behaviour:** 5 minutes without interaction (no key, no tap, no message exchange) → automatically return to Ambient. The transcript stays in memory; returning re-shows the last messages.

## 6. The wave

The wave is the visual identity of Samantha. It is a horizontal line on which **pulses propagate**, like waves traveling on a taut string.

### 6.1 Conceptual model

- The line is a "string" anchored to both edges of the screen.
- Each "event of voice" emits **two pulses** that travel in opposite directions from the center of the screen toward the edges.
- A pulse is a **wave packet**: a sinusoidal carrier inside a Gaussian amplitude envelope.
- Pulses propagate, attenuate, and die as they travel.
- Multiple pulses sum linearly (a busier wave is just more overlapping pulses).
- In idle, pulses are rare and tiny; in speaking, pulses are dense and tall.

### 6.2 Math

For a list of active pulses, the displayed `y` at coordinate `x` and time `t` is:

```
y(x, t) = baseline − Σ pulse.amp(t) · exp(−((x − pulse.center(t))/σ)²) · cos(2π · freq · (x − pulse.center(t)))
```

Where each `pulse` has:
- `t_emit` — timestamp when emitted
- `dir` — +1 or −1 (direction of travel)
- `amp_0` — initial amplitude
- `σ` — Gaussian envelope width
- `freq` — carrier frequency

And:
- `pulse.center(t) = 0.5 + pulse.dir · (t − pulse.t_emit) · v` (normalized x coords; `v` is speed)
- `pulse.amp(t) = pulse.amp_0 · max(0, 1 − (t − pulse.t_emit) / lifetime)` (linear decay)

### 6.3 Visual specification

| Property | Value |
|---|---|
| `stroke-width` | 0.6 px (scales with device-pixel-ratio) |
| `stroke-opacity` | 0.85 (idle) · 0.95 (active modes) |
| Color | `--ink` (white) |
| `linecap` / `linejoin` | `round` / `round` |
| Halo / glow | None |

### 6.4 Modes (mode-driven defaults)

| Mode | Pulse rate | `amp_0` | `σ` | `freq` | Pulse speed `v` | Lifetime |
|---|---|---|---|---|---|---|
| idle | 0.1 / s | ~1 px | 0.10 | 3 cycles/width | 0.15 widths/s | 1.5 s |
| listening | 0.5 / s | ~12 px | 0.20 | 7 cycles/width | 0.25 widths/s | 1.5 s |
| thinking | 2 / s | ~8 px | 0.15 | 10 cycles/width | 0.25 widths/s | 0.8 s |
| speaking | 3–5 / s | up to 35 px | 0.20 | 10 cycles/width | 0.25 widths/s | 1.2 s |

Mode is `setMode(mode)` API on the wave component. Switching modes lerps the per-pulse defaults so the transition is smooth.

In speaking mode, the actual pulse rate can also be **TTS-driven**: when Phase 5 lands real TTS, each syllable boundary can manually emit a pulse via `wave.pulse(amp)`.

## 7. Design tokens

### 7.1 Color

Single hue (`#d1684e` terracotta) plus 6 tiers of white-with-opacity for text and accents. The rule: **labels stay white at high opacity**; opacity is reduced only to explicitly demote something.

| Token | Value | Use |
|---|---|---|
| `--bg` | `#d1684e` | Background of all screens |
| `--ink` | `rgba(255,255,255,1.0)` | Active Samantha message; wave in speaking mode |
| `--ink-label` | `rgba(255,255,255,0.9)` | **Default for all small labels/icons** (time, day, "ambient", "escuchando", brand, etc.) |
| `--ink-soft` | `rgba(255,255,255,0.85)` | Ambient phrase; idle wave; penultimate Samantha message |
| `--ink-dim` | `rgba(255,255,255,0.6)` | Recent user message in history |
| `--ink-faint` | `rgba(255,255,255,0.4)` | Old messages in history; input placeholder |
| `--ink-trace` | `rgba(255,255,255,0.2)` | Borders, dividers |
| `--mic-active` | `#ffffff` | Mic button fill (CTA primario) |

### 7.2 Typography

Two families. Cormorant Garamond italic = "voz de Samantha". Inter Tight uppercase letter-spaced = "voz del sistema". User speaks in Inter Tight regular.

| Token | Size | Family / style | Use |
|---|---|---|---|
| `--text-display` | 2.4 rem | Cormorant italic 300 | Greet, Welcome |
| `--text-ambient` | 1.5 rem | Cormorant italic 300 | Frase contextual de Ambient |
| `--text-her-large` | 1.2 rem | Cormorant italic 300 | Último mensaje de Samantha en immersive |
| `--text-her-history` | 0.95 rem | Cormorant italic 300 | Mensajes pasados de Samantha |
| `--text-user` | 0.95 rem | Inter Tight 300 | Mensajes de usuario |
| `--text-brand` | 0.82 rem | Inter Tight 400 · spacing 0.42 em · uppercase | "samantha" en boot |
| `--text-input` | 0.75 rem | Cormorant italic 300 | Placeholder del input |
| `--text-label` | 0.68 rem | Inter Tight 400 · spacing 0.34 em · uppercase | Hora, día, controles, estado |

### 7.3 Spacing

Base 8 px. Multiples only.

| Token | Value |
|---|---|
| `--space-xs` | 8 px |
| `--space-sm` | 16 px |
| `--space-md` | 24 px |
| `--space-lg` | 40 px |
| `--space-xl` | 64 px |

## 8. Code organization (React + Vite + TypeScript)

The vanilla-JS architecture from Phase 3 is replaced.

### 8.1 Project layout

```
os1-samantha/
├── backend/                       (unchanged structurally)
│   ├── samantha/
│   │   ├── api.py                 ← Mounts frontend/dist/ at "/", adds /profile routes
│   │   ├── memory.py              ← Extended with set_fact/get_fact (§9.3)
│   │   ├── profile.py             ← NEW thin facade (~30 LoC). All state lives in memory.
│   │   └── …
│   └── tests/
│
├── frontend/                      ← NEW. Replaces backend/static/
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts             ← proxy /ws, /chat, /speak, /profile → :7777
│   ├── index.html                 ← Vite entry. Loads main.tsx
│   ├── public/
│   └── src/
│       ├── main.tsx               ← createRoot + <App/>
│       ├── App.tsx                ← Router + global key bindings
│       ├── styles/
│       │   ├── tokens.css         ← CSS variables
│       │   ├── base.css           ← reset, body
│       │   └── components.css     ← .btn, .mic-btn, .msg, …
│       ├── core/
│       │   ├── router.ts          ← useScreen hook
│       │   ├── store.ts           ← zustand (userName, transcript)
│       │   ├── useKeys.ts         ← keyboard hook
│       │   └── types.ts           ← shared types (Profile, WSMessage, …)
│       ├── net/
│       │   ├── wsClient.ts        ← WebSocket + typed protocol
│       │   ├── tts.ts             ← /speak → audio
│       │   ├── mic.ts             ← listen via WS
│       │   └── profile.ts         ← /profile API
│       ├── components/
│       │   ├── Wave.tsx           ← canvas wave packet
│       │   └── OS1Loader.tsx      ← Three.js, lazy
│       └── screens/
│           ├── BootScreen.tsx
│           ├── OnboardingScreen.tsx
│           ├── AmbientScreen.tsx
│           └── ConversationScreen.tsx
```

### 8.2 Import rules

- `screens/` may import from `core/`, `net/`, `components/`.
- `components/` are self-contained — they receive props, they do not call the network.
- `net/` knows only HTTP/WS + promises. No DOM, no React imports.
- `core/` is pure — no `net`, no `components`.

### 8.3 State management

- A small **zustand** store holds: `userName: string | null`, `transcript: Message[]`, `screen: ScreenName`.
- Each screen subscribes to what it needs via selectors.
- The router is a custom hook that wraps a single piece of state (`screen`) and exposes `route(name)` plus `goBack()` (for Esc).

### 8.4 Key types

```ts
export type ScreenName = 'boot' | 'onboarding' | 'ambient' | 'conversation';

export type WaveMode = 'idle' | 'listening' | 'thinking' | 'speaking';

export interface Profile {
  version: 1;
  user_id: string;
  name: string;
  created_at: number;
  onboarding_completed_at: number;
  answers: Array<{ q: string; a: string }>;
}

export type WSMessage =
  | { type: 'chat'; message: string; user_id: string }
  | { type: 'listen' }
  | { type: 'token'; token: string }
  | { type: 'done'; thinking_ms: number }
  | { type: 'transcription'; text: string }
  | { type: 'error'; error: string };

export interface PingResponse {
  status: 'ok';
  version: string;
  timestamp: number;
  mode: 'mock' | 'real';
  has_profile: boolean;
}
```

### 8.5 Dev workflow

| Command | Effect |
|---|---|
| `cd backend && python -m samantha.api` | Backend on `:7777`. Serves `frontend/dist/` if it exists. |
| `cd frontend && npm install` | One time. Pulls React, Vite, TS, types. |
| `cd frontend && npm run dev` | Vite dev on `:5173` with HMR. Proxy to `:7777`. |
| `cd frontend && npm run build` | Production build → `frontend/dist/`. |
| `cd frontend && npm run typecheck` | `tsc --noEmit`. |

### 8.6 Production deployment

In Phase 7 the kiosk script must run `cd frontend && npm install && npm run build` once before starting the backend. The `samantha-llamacpp.service` and `samantha-backend.service` units are unchanged.

The mini-PC needs Node only at deploy/build time. Runtime requires just the backend Python + Chromium. To avoid Node on the kiosk entirely, a future iteration can build on a dev machine and rsync `frontend/dist/` to the kiosk — but v2 does not optimize for this yet.

## 9. Memory architecture

Two layers + structured facts, all anchored in `~/.samantha/memory/`. No separate `profile.json` — everything Samantha knows about the user lives in her memory ("el profile va dentro del conocimiento de Samantha").

Informed by the Mem0 spike (`docs/superpowers/specs/mem0-spike/REPORT.md`): we keep ChromaDB but adopt a short/long term distinction and swap the embedder to a multilingual model.

### 9.1 Three components

**Short-term memory** — the last N turns, verbatim.

- Storage: SQLite table `short_term` in `~/.samantha/memory/state.db`.
- Capacity: ring buffer, 20 entries (configurable).
- Inserted into every LLM call under "# Conversación reciente" — regardless of similarity to the current turn.
- Solves the "previous exchange was about something unrelated" problem that pure-similarity retrieval has.

**Long-term memory** — everything else, retrieved by semantic similarity.

- Storage: ChromaDB at `~/.samantha/memory/chroma/`.
- Same chunks short-term has (everything written to short-term is ALSO written to long-term — eviction from the ring buffer doesn't remove from long-term).
- Embedder: **fastembed** (ONNX runtime) with `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`. Multilingual, Spanish-strong, ~80 MB cached.
- Recall: top-k by cosine similarity, k=5 default. Excludes `role: "fact"` chunks AND any chunks already in the current short-term buffer.

**Structured facts** — append-only key/value pairs.

- Storage: ChromaDB, same collection, marked with `role: "fact"`.
- Used for: user's name, onboarding completion timestamp, future preferences.
- Excluded from conversational recall (would be noise — we don't want "name = Horelvis" coming up when chatting about coffee).
- Retrieved by explicit `kind` filter on metadata.

### 9.2 Why two layers (not one)

Pure-similarity retrieval has a well-known failure mode: the LAST EXCHANGE may not be semantically similar to the new message, so it doesn't come back in top-k. The conversation feels discontinuous.

Short-term holds the recent context verbatim regardless of similarity. Long-term holds everything older and only surfaces when relevant. This is the pattern used by ChatGPT Memory, Mem0, Claude Projects.

### 9.3 Storage layout

```
~/.samantha/memory/
├── state.db                  ← SQLite. Short-term ring buffer.
└── chroma/                   ← ChromaDB persistent client + fastembed embeddings
    ├── chroma.sqlite3
    └── <segments>/
```

### 9.4 Chunk schema (unified across both layers)

| Field | Type | Notes |
|---|---|---|
| `id` | UUIDv4 string | |
| `role` | `"user" \| "samantha" \| "fact"` | controls how recall treats it |
| `text` | string | raw turn ("qué tal el día?") or fact sentence ("El usuario se llama Horelvis") |
| `timestamp` | int (unix seconds) | |
| `user_id` | string | always `"primary"` today |
| `kind` (facts only) | string in metadata | `"name"`, `"onboarding_completed_at"`, ... |
| `value` (facts only) | JSON scalar in metadata | `"Horelvis"`, `1778595500`, ... |

### 9.5 `Memory` API

`backend/samantha/memory.py` is restructured:

```python
class Memory:
    def __init__(self, persist_dir: str, *,
                 embedder_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
                 short_term_capacity: int = 20): ...

    # ---- Write (writes to BOTH layers) ----
    def remember(self, role: str, text: str, *, user_id: str = "primary") -> str:
        """Append a chunk to short-term (ring) AND long-term (vector store)."""

    def set_fact(self, kind: str, value: Any, *,
                 text: str | None = None, user_id: str = "primary") -> str:
        """Append a fact (role='fact'). Stored long-term only — facts are
        not part of conversational continuity, no point in the ring."""

    # ---- Read ----
    def short_term(self, *, user_id: str = "primary") -> list[Chunk]:
        """All entries currently in the ring, oldest-first."""

    def recall(self, query: str, *,
               k: int = 5,
               user_id: str = "primary",
               include_facts: bool = False) -> list[Chunk]:
        """Top-k similar from long-term. Excludes role='fact' and any
        chunks already in the short-term buffer (no duplication in prompt)."""

    def get_fact(self, kind: str, *, user_id: str = "primary") -> dict | None:
        """Newest fact for (kind, user_id), or None."""

    def all_facts(self, kind: str | None = None, *,
                  user_id: str = "primary") -> list[dict]: ...

    # ---- Admin (NOT wired to user input) ----
    def clear_facts(self, *, user_id: str = "primary") -> int: ...
    def clear_long_term(self, *, user_id: str = "primary") -> int: ...
```

`remember()` writes to both layers atomically. The short-term ring evicts its oldest entry when capacity is reached, but that entry remains in long-term forever (per "Samantha nunca olvida").

`recall()` filters out short-term entries from its results so the LLM doesn't see the same text twice (once in "Conversación reciente", once in "Recuerdas").

### 9.6 Prompt assembly

For every chat turn, the system prompt becomes:

```
{SYSTEM_PROMPT}                                ← personality.py v2

# Lo que sabes de ella
- el usuario se llama {name}                   ← from get_fact("name")
- te conocisteis el {date}                     ← from get_fact("onboarding_completed_at")

# Lo que recuerdas relevante
- 2026-03-15 (ella): Trabajo en una agencia    ← top-k from long-term,
- 2026-04-20 (ella): Toby ha cumplido 8 años     excluding short-term

# Conversación reciente
ella: ¿qué tal el día?                         ← short-term verbatim,
tú:   bien, sólo cansado                         in chronological order
ella: ¿algo concreto?
```

The user's current message is the final `user` message in the OpenAI-style `messages` array — separate from the system prompt above.

### 9.7 Embedder details

- Library: `fastembed` (Python). Pulls only `onnxruntime` + numpy, NOT PyTorch.
- Model: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`.
- Dimension: 384 (matches the index built by ChromaDB).
- First-use download: ~80 MB to `~/.cache/fastembed/`. One-time per machine.
- Inference: ~10 ms per text on CPU (no GPU needed).

Why fastembed not sentence-transformers directly: avoids pulling PyTorch (~600 MB). ONNX runtime + a single model file is the whole stack.

Why multilingual: ChromaDB's default `all-MiniLM-L6-v2` was trained primarily on English. Recall quality on Spanish drops noticeably (~15-20% on benchmarks). The multilingual variant is the same architecture trained on 50 languages including strong Spanish coverage.

### 9.8 Endpoints (unchanged in shape)

| Method/path | Behaviour |
|---|---|
| `GET /profile` | 200 + `{name, onboarding_completed_at, answers}` if onboarded. 404 if `Memory.get_fact("onboarding_completed_at")` is None. |
| `POST /profile` | Body `{name, answers}` (see schema below). Calls `set_fact("name", ...)`, then `remember("user", ...)` for each answer, then `set_fact("onboarding_completed_at", now)`. |
| `GET /ping` (modified) | Adds `has_profile: bool` from `get_fact("onboarding_completed_at") is not None`. |
| `DELETE /profile` | Admin-only. Clears the `name` and `onboarding_completed_at` facts. **Never touches conversational chunks** — the 6 answers stay; per "Samantha never forgets". |

**`POST /profile` request schema (Pydantic):**

```python
class ProfileCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    answers: list[ProfileAnswer] = Field(min_length=6, max_length=6)

class ProfileAnswer(BaseModel):
    q: str = Field(min_length=1, max_length=400)
    a: str | None = Field(default=None, max_length=2000)  # None = user skipped
```

Response is `{name, onboarding_completed_at, answers}`. Empty `name` after trim → 422; frontend must pass non-empty even if Q1 skipped (see §13 criterion 2 for the fallback rule).

### 9.9 Backend module structure

```
backend/samantha/memory.py     ← Memory class with short/long/facts (extended)
backend/samantha/profile.py    ← thin facade (~30 LoC), routes /profile to Memory
backend/samantha/api.py        ← /profile endpoints, prompt assembly for /ws and /chat
```

`profile.py` (illustrative):

```python
def is_onboarded(mem: Memory, user_id: str = "primary") -> bool:
    return mem.get_fact("onboarding_completed_at", user_id=user_id) is not None

def get_profile(mem: Memory, user_id: str = "primary") -> dict | None:
    if not is_onboarded(mem, user_id):
        return None
    name = mem.get_fact("name", user_id=user_id)
    ts = mem.get_fact("onboarding_completed_at", user_id=user_id)
    answers = _recover_answers_from_memory(mem, user_id)
    return {"name": name["value"], "onboarding_completed_at": ts["value"], "answers": answers}

def complete_onboarding(mem: Memory, name: str, answers: list[dict],
                        user_id: str = "primary") -> dict:
    mem.set_fact("name", name, text=f"El usuario se llama {name}", user_id=user_id)
    for a in answers:
        if a["a"]:
            mem.remember("user", f"[Q] {a['q']} → [A] {a['a']}", user_id=user_id)
    mem.set_fact("onboarding_completed_at", int(time.time()), user_id=user_id)
    return get_profile(mem, user_id)
```

The `/chat` and `/ws` handlers in `api.py` build the prompt per §9.6 every turn: `Memory.get_fact` for facts, `Memory.short_term` for the buffer, `Memory.recall(query, k=5)` for similarity.

### 9.10 Edge cases

- **Short-term ring fills:** oldest entry evicted from ring, stays in long-term. Recall can still surface it by similarity if relevant.
- **Corrupt SQLite/ChromaDB:** logs error; treats user as not-onboarded. Onboarding repeats. New chunks overwrite the corrupt store on re-save. Lost facts are not recovered.
- **First-run model download:** ~30 s on first boot for fastembed to fetch the multilingual ONNX model. Either tolerate it on first launch or pre-download as part of kiosk deployment.
- **Concurrent writes:** single-process backend, not a concern. SQLite and ChromaDB both handle internal locking.
- **Recovery of `answers` from memory:** `_recover_answers_from_memory` queries `role: "user"` chunks created within ±5 s of `onboarding_completed_at`, in insertion order.
- **Mem0 future migration:** the architecture stays compatible. `Memory` could become a façade over Mem0 if v3 needs automatic fact extraction — the public API (`remember`, `recall`, `get_fact`) doesn't change.

## 10. CLAUDE.md changes required

This redesign requires updates to several CLAUDE.md sections. The changes are documented here and applied as part of the implementation plan.

### 10.1 §2 Architecture Decisions

- **§2.4 Backend stack**: append "The frontend lives in `frontend/` separate from `backend/`. Vite builds to `frontend/dist/`, which FastAPI's `StaticFiles` mounts at `/`."
- **§2.7 Memory**: update to reflect short/long-term architecture and fastembed multilingual embedder (see §9 of this spec). Drop the "swappable later" language — multilingual is the chosen default now.
- **§2.10 (new) Frontend stack**:
  > **Decision:** React 18 + Vite + TypeScript.
  >
  > **Rationale:** The UI grew beyond what vanilla DOM manipulation handles cleanly (4 screens with state, a wave canvas, a toggleable history, a router). Component model + types + HMR pay back the build-step cost quickly. The original vanilla-JS decision (CLAUDE.md §12, 2026-05) was correct for the original scope; that scope changed with the v2 redesign.
  >
  > **Cost:** Node.js as a dev dependency. Production deploy needs `npm install && npm run build` once during install. Runtime on the kiosk still needs only Python + Chromium.

### 10.2 §3 Rules

Remove:
- `**MUST NOT** add a frontend framework (React, Vue, Svelte, etc.)`
- `**MUST NOT** add a JS build step (webpack, vite, esbuild, etc.)`

Keep:
- `**MUST NOT** introduce Rust, Tauri, or snap packaging`
- `**MUST NOT** add new top-level directories without asking` (note: `frontend/` is the only such addition required for this spec; it's pre-authorized here).

### 10.3 §5 Common commands

Add a new subsection "Frontend (Vite)" with the dev workflow commands.

### 10.4 §7 Phase 7 deployment

Add `cd frontend && npm install && npm run build` before the systemd unit copy.

### 10.5 §12 Decision Log

New entry at top:

> ### 2026-05-12 — Vanilla JS → React + Vite + TypeScript
>
> **Decision:** Replace the vanilla-JS-no-build frontend with React + Vite + TypeScript.
>
> **Rationale:** v2 UI redesign expanded scope (Ambient screen added, immersive Conversation with history toggle, traveling-wave-packet visualization, persistence layer). The original "UI scope is small" rationale no longer applies. Component model and types are now load-bearing for dev velocity.
>
> **Cost:** Node.js required for dev and build. `node_modules/` adds ~100 MB to the dev environment. Production kiosk runs only Python + Chromium (Node not required at runtime; only at build time).
>
> **Lessons:** Architectural decisions should be revisited when product scope shifts substantially. The original vanilla decision was right at that time.

## 11. What ships in this spec vs out of scope

### Ships

- Persistence layer (`profile.json`, `/profile` endpoints, `/ping` enhancement).
- Frontend rewrite in React + Vite + TypeScript.
- Ambient screen (new).
- Conversation immersive + history toggle.
- Wave packet model with traveling pulses.
- Design tokens (color, typography, spacing) applied consistently.
- Debug panel removed (entirely; not gated by env).
- CLAUDE.md updates.

### Deferred

- **Samantha proactiva** (initiative engine). Architecture leaves the door open: the Ambient screen has a designated state for "she has something", and the backend has space to add an initiative loop later. v2 ships without any spontaneous emission.
- **Agentic Samantha (v3 territory)** — managing emails, calendar, taking initiatives like in the film. CLAUDE.md §1's "not an agent" framing is a v1 scope restriction, not an identity claim. v3 will revisit this. A scoped evaluation of NousResearch's **Hermes-Agent** as a possible foundation is parked at `docs/superpowers/specs/2026-05-12-hermes-agent-spike-scope.md` (to be executed in parallel with or after v2 implementation).
- **Real STT (faster-whisper)** and **real TTS (Piper)** — Phase 5.
- **Memory browser UI** — viewing/editing what Samantha remembers from inside the app. The `Memory` admin API exists but no UI surface is built yet.
- **Notifications surface** — if Samantha ever needs to alert the user outside conversation (e.g., system events), there's no UI for it yet.

## 12. Open questions

- **Onboarding theatricality post-Phase-5**: once STT/TTS are real, calibration/voiceprint can use real mic audio. The current scripted timing (4 s silence, 4 s voice, 4 s flash) may need adjustment.
- **Quiet hours** (e.g., "no me hables 23:00–08:00") — relevant only when proactivity ships, but worth deciding by the time we tackle it.
- **Text input affordance** — `T` key reveals it; should there be a visible affordance for non-keyboard users? Currently only revealed via key. Could add a tiny "·T·" hint, but that conflicts with "aesthetic restraint". TBD.
- **Where do the 6 answers go in memory exactly?** Decision: as separate `role: "user"` chunks, one per question, with the question stored in the text ("[Q] ¿Cómo te llamo? → [A] Horelvis"). Alternative: collapse them into a single chunk. The separate-chunk approach is friendlier to recall, so that's the default unless real-conversation testing says otherwise.

## 13. Acceptance criteria

The redesign is complete when:

1. Visiting `http://localhost:7777/` (mock or real mode) loads the React app.
2. First boot with no profile → onboarding flow → `POST /profile` succeeds → lands on Ambient. If the user skips Q1 ("¿Cómo te llamo?"), the frontend submits `name: "tú"` as a default and `answers[0].a: null`; the user can correct it later from a future settings UI.
3. Second boot with profile present → boots directly to Ambient (no onboarding screens flash).
4. Ambient shows correct time, day, and contextual phrase for the current hour.
5. Tapping Ambient navigates to Conversation in immersive mode.
6. Sending a message via mic or text shows token-streaming in the wave (mode flips to `speaking`) and a Samantha reply appears.
7. Toggling history (`H` key or `≡` icon) shows the full transcript, then back to immersive (`H` or `×`).
8. `Esc` from Conversation returns to Ambient.
9. 5 min idle in Conversation auto-returns to Ambient.
10. **Memory works as designed:** the 6 onboarding answers are queryable via `Memory.recall()` (similarity hit). `Memory.get_fact("name")` returns the user's name and `Memory.get_fact("onboarding_completed_at")` returns the timestamp. `Memory.short_term()` returns the last 20 conversation turns in chronological order. Recall on a Spanish query (e.g., "qué mascota tiene") returns the relevant Spanish chunk among top-5 (multilingual embedder works).
11. No debug panel visible.
12. `cd frontend && npm run typecheck` passes.
13. `cd backend && pytest tests/` passes (existing tests + new ones for `/profile`).
14. CLAUDE.md reflects all the changes in §10.

---

End of spec.
