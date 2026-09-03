# JARVIS

An AI presence that lives on the desktop: a strip along the bottom edge
of the screen that listens all the time, speaks in a cloned voice,
watches the house's cameras, and can act on it. Not a window you open —
something that is there.

He was called JARVIS until 2026-08-23, after the film *Her*, and most
package names, environment variables and systemd units still carry that
name — except the platform he speaks through, `jarvis` since 2026-08-28.
The full specification is in **[CLAUDE.md](CLAUDE.md)**; this file is
the short version.

## Architecture

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

- **Surface:** `widget/` — a GTK4 strip on X11. No browser, no webview.
  Transparent, borderless, always above, drawn with GSK.
- **Brain:** the Hermes Agent gateway on `:7777`, through the `jarvis`
  plugin. It is what gives him memory, reminders and session recall.
- **LLM:** `llama-server` with Qwen3.8-27B (GGUF), on the box.
- **Ears:** Silero v5 VAD on the CPU decides when somebody is talking;
  faster-whisper `large-v3-turbo` transcribes on the GPU.
- **Voice:** CosyVoice 3 zero-shot, cloned, on `:8093`.
- **Eyes:** YOLOv9 over the house's RTSP cameras, inside the gateway as
  the `jarvis_vision` plugin. A detection never becomes a recited
  report — it becomes a turn, in his words. He can also be **asked** to
  look, and then the photo appears above the strip for a few seconds and
  reaches nothing else.
- **Hardware:** one box, one RTX 4090. VRAM is the budget everything
  competes for: CosyVoice ~5.5 GB, Whisper ~2.5 GB, and what is left
  decides the quantisation of the model.

**On privacy.** Inference runs here by default and nothing said in the
room leaves it. X.AI's Grok API is one config switch away, and flipping
it sends the conversation off the box — deliberately, with the trade
written down in CLAUDE.md §1 and §12. What the cameras see is described
to whichever model is active.

## Quick start

```bash
cd widget
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -e ".[dev]"

DISPLAY=:0 PYTHONNOUSERSITE=1 PYTHONPATH=$PWD/../backend:$PWD/.. \
  .venv/bin/python -m jarvis_widget
```

`--system-site-packages` is required (PyGObject and the GTK4 typelib are
system packages) and it makes the venv a minefield in two specific ways.
`widget/README.md` maps them, along with every environment switch, the
models to download, and the photo band. Read it before the first run
rather than after. The cameras are configured in the plugin, not here:
`Hermes/plugins/jarvis_vision/README.md`.

The gateway and CosyVoice have to be up for him to answer or speak;
`systemd/` holds the user units.

## What is still here and unused

`backend/` (FastAPI, `/chat`, `/speak`, ChromaDB) and `frontend/` (React,
Vite, the OS1 ribbon) served the Chromium kiosk that the widget replaced.
They stay until the widget has convinced — an explicit condition — and
removing them is plan 3, not yet written.

## Status

The strip, the voice turn and the vision path are built and running.
**The voice turn has never heard anybody**: this box has no microphone
plugged in, so the last task of plan 2 needs hardware, not code. The
switch `JARVIS_WIDGET_FAKE_MIC` is how everything downstream of the
microphone was proved without one.

See [PROGRESS.md](PROGRESS.md) for what each day cost and what it found.

## Documentation

- **[CLAUDE.md](CLAUDE.md)** — the specification, and the decision log
  that explains why anything is the way it is. Read first.
- **[widget/README.md](widget/README.md)** — running the strip: the venv,
  the models, the photo band, the environment switches.
- **[Hermes/plugins/jarvis_vision/README.md](Hermes/plugins/jarvis_vision/README.md)**
  — the cameras: configuring them, the quiet rules, and `mirar`.
- **[docs/personality.md](docs/personality.md)** — his voice, his style
  and what he never does. Required before writing any user-facing string.
- **[PROGRESS.md](PROGRESS.md)** — the log, newest first.
- **[backend/README.md](backend/README.md)** — the unused FastAPI backend.

## Project structure

```
os1-jarvis/
├── CLAUDE.md           ← the spec (read first)
├── PROGRESS.md         ← the log
├── widget/             ← the strip: GTK4, VAD, STT, TTS, the photo band
├── Hermes/             ← the pinned gateway, its config and his persona
├── tts-server/         ← CosyVoice 3, in Docker
├── systemd/            ← user units for gateway, widget, llama-server
├── docs/               ← designs, plans and decision records
├── voices/             ← the reference clip his voice is cloned from
├── backend/            ← FastAPI + ChromaDB (unused, see plan 3)
└── frontend/           ← React + Vite (unused, see plan 3)
```

## License

Private project for personal use. The OS1 loader visualization is
derived from work by Siyoung Park (MIT License) — attribution in source.
