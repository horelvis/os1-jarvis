# Samantha

A fully local AI companion inspired by the film *Her*. Runs on a single
mini-PC. No cloud, no remote, no telemetry.

## Architecture (v3)

```
Ubuntu Server 24.04 LTS
    │
    ├── systemd: auto-login as user `samantha` on tty1
    │       ↓
    └── startx → openbox → Chromium kiosk
            │
            └── displays http://localhost:7777/
                    │
                    └── Python backend (FastAPI)
                        ├── /        → static HTML/CSS/JS
                        ├── /chat    → mock or real LLM
                        ├── /ws      → streaming WebSocket
                        └── orchestrates vLLM, Whisper, Piper, ChromaDB
```

## Quick start (development, mock mode)

```bash
cd backend
pip install -e ".[dev]"
python -m samantha.api
```

Then open `http://localhost:7777/` in any browser.

## Documentation

- **[CLAUDE.md](CLAUDE.md)** — Authoritative project specification (v3).
  Read this first.
- **[PROGRESS.md](PROGRESS.md)** — Phase completion log.
- **[backend/README.md](backend/README.md)** — Backend-specific docs.

## Project structure

```
samantha/
├── CLAUDE.md           ← Project spec (read first)
├── PROGRESS.md         ← Phase log
├── backend/            ← The whole application
│   ├── samantha/       ← Python package
│   ├── static/         ← Frontend served by FastAPI
│   └── tests/
├── systemd/            ← Service files (Phase 7)
└── docs/               ← Design docs
```

## Status

Currently in Phase 2 (mock backend) with Phase 0 (architecture v3)
completed. Phase 3 next: integrate the v7 mockup as the frontend.
See [PROGRESS.md](PROGRESS.md).

## License

Private project for personal use. The OS1 loader visualization is
derived from work by Siyoung Park (MIT License) — attribution in source.
