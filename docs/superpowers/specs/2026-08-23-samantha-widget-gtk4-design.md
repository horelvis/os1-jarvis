# Samantha as a desktop widget — design

**Date:** 2026-08-23
**Status:** proposed — supersedes CLAUDE.md §2.3 (Chromium kiosk) if accepted
**Plans:** `docs/superpowers/plans/2026-08-23-samantha-widget-strip.md` (plan 1),
`docs/superpowers/plans/2026-08-23-samantha-widget-voice-turn.md` (plan 2)
**Predecessor:** `docs/superpowers/specs/2026-08-22-samantha-on-hermes-design.md`
— this design keeps its §3 (`samantha-voice`) and §5 (`samantha-kiosk`)
and replaces its §7 (frontend changes) and most of its §5.2/§5.3.

---

## 1. Goal and shape

Samantha stops being a screen you look at and becomes an object that
lives on the desktop: a wide, low strip floating at the bottom of the
display, terracotta `#d1684e`, no border, always on top, always
listening. No browser, no fullscreen, no kiosk. The user does not
"open" her — she is simply there, and she is always there.

Four decisions were closed in brainstorming on 2026-08-22 and are
inputs to this design, not questions it reopens:

1. **It replaces the kiosk**, it does not live beside it. The appliance
   model of CLAUDE.md §1 and decision §2.3 are abandoned.
2. **Native GTK4, no webview.** No Electron, no WebKitGTK, no
   `--app=` Chromium window pretending to be a widget.
3. **Form:** a floating bottom strip, wide and low, centred on the
   bottom edge, terracotta, borderless, always above.
4. **Always listening**, with a local VAD deciding when the user is
   speaking. No wake word, no hotkey.

### What this buys, stated plainly

The kiosk owns the whole screen, so Samantha is either everything or
nothing. A strip means she can be present while the user works — which
is the only way "always listening" is worth anything. It also removes
Chromium (~400 MB of RSS, a GPU process, a permission model that
needed `--use-fake-ui-for-media-stream` to not shatter the illusion)
from the runtime.

### What it costs, stated plainly

`frontend/` — React, Vite, Three.js, the OS1 ribbon, the four screens,
the whole v2 redesign — becomes dead code. The UI is rewritten in
GTK4/Cairo. **We do not delete it until the widget convinces**; that
was decision 2's explicit rider, and it is why the removal is plan 3
and not plan 1.

---

## 2. Runtime topology

The widget is a **client**, not a server. Everything it talks to
already exists and already runs.

```
┌─────────────────────────────────────────────────────────────┐
│  samantha-widget  (one Python process, GTK4 main loop)      │
│                                                             │
│   GTK main thread          │  asyncio thread                │
│   ───────────────          │  ───────────────               │
│   Gtk.ApplicationWindow    │  WS client ──────────┐         │
│     └ Gtk.DrawingArea      │  CosyVoice client ─┐ │         │
│        (the wave, Cairo)   │                    │ │         │
│                            │                    │ │         │
│   audio thread             │                    │ │         │
│   ────────────             │                    │ │         │
│   sounddevice in  16 kHz ──┼─ Silero VAD ─ faster-whisper   │
│   sounddevice out 24 kHz ◄─┼────────────────────┘ │         │
└─────────────────────────────────────────────────────┼───────┘
                                                      │
   ws://127.0.0.1:7777/ws  (samantha-kiosk adapter)   │
                    │                                 │
              ┌─────▼──────────────┐   http://127.0.0.1:8093
              │  Hermes gateway    │   /inference_zero_shot
              │  + samantha_voice  │            │
              │  + samantha_kiosk  │   ┌────────▼────────┐
              └────────────────────┘   │  CosyVoice 3    │
                                       └─────────────────┘
```

Three facts about this picture matter more than the picture:

- **The `samantha-kiosk` plugin is reused unchanged.** Its `/ws` speaks
  `chat` / `listen` up and `token` / `done` / `error` down
  (`Hermes/plugins/samantha_kiosk/protocol.py`). The widget speaks
  exactly that. `adapter.py:565-570` already allows a client that sends
  no `Origin` header — the comment names "a future native shell" as the
  case. That future is this document.
- **The static-file half of the adapter goes unused.** The widget never
  fetches `index.html`. That is wasted code, not broken code; plan 3
  decides whether to strip it.
- **The widget synthesises its own speech.** It does not wait for
  Hermes to send audio. See §5.

### The port

`SAMANTHA_KIOSK_PORT`, default **7777**. Not 8642 — that is Hermes'
own API-server daemon (CLAUDE.md §4, Phase 9) and has nothing to do
with the kiosk adapter's aiohttp listener.

---

## 3. The window

The spike on 2026-08-22 (GNOME/X11, `DISPLAY=:1`) proved a
borderless, always-above, pixel-placed strip is possible, and proved
four things that no documentation says. They are requirements here,
not discoveries to re-make:

- **GTK4 has no `set_keep_above`, `move`, `set_position` or
  `get_position`.** Verified with `hasattr` against a real window.
  `gtk4-layer-shell`, the modern answer, is Wayland-only and this box
  runs X11.
- **EWMH over `ctypes` against `libX11` works and adds no
  dependency**: an `XSendEvent` of a `_NET_WM_STATE` `ClientMessage`
  to the root window, plus `XMoveResizeWindow`. Neither `python-xlib`,
  nor `wmctrl`, nor `xdotool` is installed on this machine and none is
  needed. ~50 lines.
- **`_NET_WM_STATE` carries only TWO properties per message**
  (`data[1]`, `data[2]`). A third is dropped silently, with no error —
  `SKIP_PAGER` never applied and it was only caught by reading
  `xprop`. Send them two at a time.
- **GTK4 paints a shadow around the window.** In a screenshot it reads
  as a halo. It must be removed in CSS or the strip looks like a
  window instead of an object.

Two more constraints follow from the environment as measured:

- `python3-gi` (3.48.2) and `gir1.2-gtk-4.0` (4.14.5) are installed,
  but they live in the **system** Python. `backend/.venv` is not a
  `--system-site-packages` venv, so the widget needs its own that is.
- The session is X11 on `:1`. Wayland is out of scope; if this box
  ever moves to Wayland, the EWMH module is the piece that dies and
  `gtk4-layer-shell` is its replacement.

**Geometry:** width `min(1100, screen_width - 2*48)`, height 96 px,
centred horizontally, bottom edge 48 px above the bottom of the work
area. Values live in one module-level constants block, because they
are the thing that will be tuned by eye against a screenshot.

**Verification trick, reusable:** `ffmpeg -f x11grab -video_size
1920x1080 -i :1 -frames:v 1 out.png` captures the screen to a file you
can then look at. This is how every visual claim in the plans is
checked. A visual claim with no screenshot behind it is not verified.

---

## 4. The visualiser

> **Revised again 2026-08-23, by the user, after seeing it run:** an
> **equaliser of 32 bars**, not the line. The line is kept and still
> works — `theme.VISUALIZER` switches between them — so this is a change
> of default, not a deletion.
>
> This reverses the "horizontal wave replaces orb" decision of
> CLAUDE.md §12 as far as the widget is concerned, and it is the user's
> call about their own product. Worth recording honestly: the line was
> not rejected for being a line. It was rejected while it was **wrong** —
> flat during speech, because nothing connected the player's level to
> it, and then lurching, because the level was sampled once per
> half-second CosyVoice chunk and read before the audio reached the
> buffer. Both were fixed (20 ms blocks, faster decay) and the line does
> follow the voice now. The equaliser was chosen after that, on looks.
>
> The bars are driven by a real FFT of the block being played —
> 32 logarithmic bands between 80 Hz and 8 kHz, mirrored about the
> centre line — not by a decorative animation keyed to volume.
> Logarithmic because linear bands put three quarters of the bars above
> 3 kHz, where speech has nothing, and the equaliser looks dead while
> somebody is talking.

The film's Samantha is a line, not a spectrum (CLAUDE.md §12,
2026-05). So the widget does not need an audio-visualisation library;
it needs to draw one polyline per frame.

**Decision: `Gtk.Snapshot` + `Gsk.PathBuilder`**, driven by
`add_tick_callback()` so the animation runs at the compositor's frame
clock rather than a timer that drifts.

> **Revised 2026-08-23, during plan 1 Task 6.** This section originally
> chose `Gtk.DrawingArea` + Cairo and dismissed GSK for having no
> comfortable arbitrary-path primitive. Both halves of that turned out
> to be wrong on this machine, and the correction is kept visible rather
> than quietly rewritten:
>
> - **Cairo does not work here at all.** PyGObject cannot hand a
>   `cairo.Context` to a draw function without `gi._gi_cairo`, which
>   ships in the system package `python3-gi-cairo` — not installed, and
>   `sudo` away. The failure is a `TypeError` raised *inside* the draw
>   callback, where GTK swallows it: the strip appears and simply never
>   draws its line. `python3-cairo` being installed is not enough and is
>   what makes this misleading to diagnose.
> - **GSK grew the primitive.** `Gsk.PathBuilder`, `Gsk.Stroke` and
>   `Gtk.Snapshot.append_stroke` arrived in GTK 4.14, which is the
>   version installed. Verified drawing all four states.
>
> For an appliance, one fewer system package to get right on the target
> machine is worth more than Cairo's familiarity.

Alternatives weighed and rejected:

| Option | Why not |
|---|---|
| `Gtk.DrawingArea` + Cairo | Needs `python3-gi-cairo` on the target machine, and fails silently inside the draw callback when it is missing. Rasterises on the CPU. Was the original choice; see the note above. |
| `Gtk.GLArea` + shaders | The right answer only if the OS1 3D ribbon comes back. PyOpenGL from Python is awkward and it is a lot of code for a line. Kept as the documented escape hatch. |
| GStreamer + `gtk4paintablesink` | Real, ready-made audio visualisers (`wavescope`, `spectrascope`). Pulls in all of GStreamer and looks like a media player from 2004. Not OS1. |
| Lottie / Rive | Pre-rendered vector animation. Cannot react to live amplitude without a fight. |

GSK composites on the GPU and needs nothing GTK4 does not already need.

**Four visual states**, one per phase of a turn, so the user always
knows what she is doing without a single word of UI text:

| State | Line |
|---|---|
| `idle` | Flat, slow breathing amplitude ≈ 1 px. She is there, she is not doing anything. |
| `listening` | Amplitude tracks the microphone RMS. The user sees the line answer their own voice. |
| `thinking` | A travelling packet crossing left to right, amplitude fixed. Nothing is being heard and nothing is being said. |
| `speaking` | Amplitude tracks the RMS of the PCM being played. |

The amplitude model is a pure function of (state, RMS, time) and is
**unit-tested without GTK**. Cairo drawing is verified by screenshot.
Anything that needs a display is not a unit test.

---

## 5. The turn

```
  VAD says the user started
        └─ wave → listening, TTS playback stops (barge-in)
  VAD says the user stopped
        └─ utterance (16 kHz mono int16) → faster-whisper → text
              └─ wave → thinking
              └─ WS  {"type":"chat","message":…,"user_id":"primary"}
                    └─ token / token / token …  → accumulate
                    └─ clause boundary reached → synthesise, queue, play
                          └─ wave → speaking
                    └─ done → turn closes
```

### 5.1 Why the widget synthesises its own speech

The alternative — plan 3b of the previous design, binary PCM frames
pushed down the same WebSocket — was written for a browser that could
not synthesise anything itself. The widget is a Python process on the
same machine as everything else. It can call `samantha.tts.stream()`
directly, which is the same CosyVoice client `samantha_voice` wraps.

That buys three things:

- **No new protocol.** The WebSocket stays text-only, exactly as
  `protocol.py` pins it, and plan 3b is never written.
- **Instant barge-in.** Stopping playback is a local call on the
  output stream, not a round trip through the gateway.
- **One less place for audio to be dropped.**

It costs one thing, and it is a real risk: **the gateway may also try
to speak.** `samantha_voice`'s manifest documents an auto-TTS path
that fires "after a turn that produced no audible audio". If both
speak, Samantha says everything twice. Plan 2's first task verifies
this against the running gateway before a line of playback code is
written, and disables it if present. This is the single most likely
way this design fails on first run.

### 5.2 Clause chunking

Waiting for `done` before speaking makes her feel dead. Speaking every
token makes CosyVoice stutter. The rule, taken from what
`samantha_voice` already learned against the live server
(`docs/…-samantha-on-hermes-design.md` §3.1):

- Flush on `.`, `?`, `!`, `…`, `\n`, or on a `,`/`;` that leaves ≥ 25
  characters buffered.
- Never flush a fragment shorter than 12 characters — CosyVoice
  handles very short clauses badly. Hold it and let it merge forward.
- Never split inside an expression marker. The markers are exactly
  `[laughter]`, `[breath]`, `[sigh]` and `<laughter>…</laughter>`
  (`backend/samantha/personality.py:58-61`), and the splitting logic
  already exists in `Hermes/plugins/samantha_voice/markers.py`. The
  widget imports it rather than reimplementing it.

### 5.3 STT

**faster-whisper `large-v3-turbo`, in-process, on the 4090**
(`device="cuda"`, `compute_type="float16"`). CLAUDE.md §2.6 already
named this model; it was never implemented, because the 2026-05-13
decision moved STT into the browser's Web Speech API. With the browser
gone, that decision dies with it and the original one comes back.

Measured headroom: the 4090 reports 24 564 MiB total, 5 355 MiB in use
by CosyVoice. `large-v3-turbo` in float16 needs roughly 1.5–2 GB. It
fits with room to spare.

The model loads in a background thread at startup, so the strip appears
immediately and is simply unable to hear for the first few seconds.
The wave shows `idle` throughout — an appliance does not show a
progress bar.

### 5.4 VAD

**Silero VAD via ONNX Runtime, CPU.** The `silero-vad` package
supports an ONNX backend that does not need torch — that saves ~2 GB
of dependency for a model that is 1.8 MB and runs comfortably on the
CPU in 32 ms frames.

Turn boundaries: speech starts after 3 consecutive speech frames
(~96 ms, kills keyboard clicks), ends after 700 ms of silence, and any
utterance shorter than 400 ms is discarded without being transcribed.
An utterance is hard-capped at 30 s so a stuck VAD cannot grow a
buffer forever.

### 5.5 Audio I/O

`sounddevice` (PortAudio) both ways. PipeWire with `pipewire-pulse` is
running on this box, so PortAudio finds a working default device
through the Pulse compatibility layer; ALSA sees the card directly
(`ALC897 Analog`) as a fallback.

- **In:** 16 kHz mono int16, 512-sample blocks (32 ms — Silero's
  native frame at this rate).
- **Out:** 24 kHz mono int16 — `samantha.tts.OUTPUT_SAMPLE_RATE`. No
  resampling anywhere, in either direction.

### 5.6 Threading

GTK's main loop and asyncio do not mix, and this is where a widget
like this usually dies.

- The **GTK main thread** owns every widget. Nothing else touches
  them, ever.
- One **asyncio thread** runs its own event loop and owns the
  WebSocket and the HTTP client to CosyVoice.
- One **audio thread** is PortAudio's callback thread. It does no
  work beyond pushing into a queue.
- Everything that has to reach the UI goes through `GLib.idle_add`.
  That is the only bridge, and the rule is absolute.

`gbulb` (an asyncio loop implemented over GLib) would remove the
thread, and is rejected: it is a dependency, it is thinly maintained,
and it makes every failure a two-library failure.

---

## 6. Project structure

A new top-level directory:

```
widget/
├── pyproject.toml           ← its own package, its own venv
├── README.md
├── samantha_widget/
│   ├── __init__.py
│   ├── __main__.py          ← entry point and wiring
│   ├── theme.py             ← the colour, the geometry constants, the CSS
│   ├── geometry.py          ← pure: monitor rect → strip rect
│   ├── ewmh.py              ← ctypes/libX11: always-above + place
│   ├── window.py            ← the GTK4 window and its CSS
│   ├── wave_model.py        ← pure: (state, level, time) → polyline
│   ├── wave.py              ← DrawingArea + Cairo, on the frame clock
│   ├── audio.py             ← sounddevice in (16 kHz) and out (24 kHz)
│   ├── vad.py               ← utterance boundaries + Silero over onnxruntime
│   ├── stt.py               ← faster-whisper
│   ├── speech.py            ← clause chunking + CosyVoice synthesis
│   ├── gateway.py           ← the WebSocket client
│   └── turn.py              ← the state machine tying it together
├── tools/                   ← hand-run probes, not tests
└── tests/
```

The split between `wave_model.py` and `wave.py`, and between the
`UtteranceDetector` and `SileroDetector` halves of `vad.py`, is the same
split throughout: **the half that can be tested without a display, a
microphone or a GPU does not import the thing that needs one.** Every
module in the left column above is import-clean of `gi`.

**This needs the user's approval under CLAUDE.md §3** ("MUST NOT add
new top-level directories without asking"). The precedent is
`Hermes/`, approved 2026-08-22 the same way. Lowercase, matching every
other directory in the repo except that one.

Why not inside `backend/`: the widget is a client of the backend's
`samantha.tts`, not part of the FastAPI service, and it needs a
`--system-site-packages` venv that `backend/` deliberately is not. Two
venvs, two `pyproject.toml`, one import direction (`widget` →
`samantha`, never back).

---

## 7. Build order

Each plan produces software that works on its own.

1. **Plan 1 — the strip.** The window, placed and always above, with
   the wave animating through its four states on a keyboard-driven
   demo, plus the systemd unit. Deliverable: **something on the screen
   that looks like her**, screenshot-verified. No audio, no gateway.
2. **Plan 2 — the voice turn.** VAD, STT, the WebSocket, clause-chunked
   synthesis and playback, wired into the state machine. Deliverable:
   **you talk to the strip and it answers out loud.**
3. **Plan 3 — the retirement.** Barge-in polish, onboarding, deleting
   `frontend/`, the Chromium unit, and the adapter's static half;
   CLAUDE.md §1/§2.3/§2.8 rewritten and §12 given its entry. Written
   only once plan 2 has convinced, per decision 2's rider.

Plan 3 is deliberately not written now. Nothing before it removes
anything: through plans 1 and 2 the Chromium kiosk still exists and
still works, and the fallback is `systemctl --user start
samantha-ui.service`.

---

## 8. Scope

**In:** the window, the wave, VAD, STT, the WS client, local
synthesis and playback, the systemd unit.

**Out, deliberately:**

- **Wake word.** Decision 4 settled this: always listening, no wake
  word. Silero decides.
- **Wayland.** X11 only, matching the box. Named here so that the
  EWMH module's death is a known consequence, not a surprise.
- **Multi-monitor placement rules.** Primary monitor, centred. If the
  user ever has two, this gets a decision of its own.
- **Text input.** There is no keyboard in front of the strip. The
  `chat` frame accepts text and the WS is symmetric, so a text path is
  cheap to add later; it is not a goal.
- **Onboarding.** The six questions are plan 3, and the profile they
  write already lives in `backend/samantha/profile.py`.
- **Deleting anything.** All of it is plan 3.

---

## 9. Risks and open questions

| Risk | Handling |
|---|---|
| **The gateway speaks too, and Samantha says everything twice.** §5.1. Most likely first-run failure. | Plan 2 Task 1 verifies against the running gateway before writing playback. |
| **Hermes replies in its own SOUL.md persona, not `backend/samantha/personality.py`.** Known and inherited — `samantha_kiosk/plugin.yaml` documents it as out of scope for plan 3a. It is still true, and the widget will speak whatever Hermes' persona says. | Not this design's to fix, but it is what the user will hear first. Flagged in plan 2's verification, resolved in plan 3. |
| **Always-listening means the mic is always open.** No wake word, by decision. | Local VAD; nothing leaves the machine until a turn commits. Note that when `SAMANTHA_LLM_API_KEY` is set, the *committed text* does leave — CLAUDE.md §1's eyes-open privacy line, unchanged by this design. |
| **She hears herself and answers herself.** Speaker bleeding into the mic while she speaks. | Gate the VAD while `speaking`, with a short tail after playback ends. If the room needs more, that is an AEC problem and a separate spike. |
| **GNOME repositions or re-stacks the window** after a workspace switch or a resolution change. | Re-assert EWMH on `notify::monitor` / map events. Verified by screenshot after a workspace switch. |
| **Whisper loading blocks the UI.** | Background thread; the strip shows `idle` and cannot hear until it is ready. |
| **PortAudio picks the wrong device** on a box with an HDMI sink and an analog card. | Device selectable by env var; the default is PortAudio's default. A wrong device is silent, so plan 2 logs the chosen device name once at startup. |

---

## 10. Testing

- **Unit, no display, no audio hardware:** the amplitude model, the
  clause chunker, the EWMH message layout (a `ClientMessage` struct
  built and asserted field by field, no X server), the WS protocol
  encode/decode, the VAD turn boundaries against synthetic PCM.
- **Integration, no hardware:** the WS client against a local
  `aiohttp` test server that speaks `token`/`done`/`error`.
- **Screenshot:** every visual claim, via `ffmpeg -f x11grab`. Placement,
  the absence of the GTK shadow, the colour, each wave state.
- **Manual, on the box:** a real turn, out loud, once plan 2 lands.

`pytest` and `ruff check` / `ruff format` gate every commit, matching
the rest of the repo.

---

## 11. Decision-log entries owed

CLAUDE.md §12 gets these when plan 3 lands, not before:

- **Chromium kiosk → GTK4 desktop widget.** Reverses §2.3 and the
  appliance principle in §1. Cost: `frontend/` dies.
- **STT returns to local faster-whisper.** Reverses the browser-Web-Speech
  half of the 2026-05-13 decision; the offline-relaxation half stands.
- **The widget synthesises locally.** Retires plan 3b's binary
  WebSocket protocol before it was written.
