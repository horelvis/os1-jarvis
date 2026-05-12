# PROGRESS.md — Samantha Phase Log

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
