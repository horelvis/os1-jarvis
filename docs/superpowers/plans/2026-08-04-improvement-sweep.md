# Improvement Sweep (Code + Architecture) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the findings of the 2026-08-04 full-project review (backend, Phase 11 voice pipeline WIP, frontend, docs/deploy), ordered so security/hygiene quick wins land first, then backend correctness, then the voice-pipeline defects that block Phase 11, then frontend robustness, then docs/deploy/CI.

**Architecture:** No architecture decisions change — every task is a targeted fix inside the existing FastAPI backend (`backend/samantha/`), the uncommitted Phase 11 voice pipeline, the React frontend (`frontend/src/`), the systemd units, or the docs. Backend fixes follow TDD against `backend/tests/`. Frontend has no test framework by project convention (CLAUDE.md §6) — verification is `pnpm typecheck` + `pnpm build` + a manual smoke checklist at the end of the frontend fase. CLAUDE.md edits are docs-sync only, aligning stale sections with decisions already recorded in its §12 Decision Log.

**Tech Stack:** Python 3.11 / FastAPI / pytest / httpx / pipecat-ai 0.0.89 / faster-whisper; React 18 / TypeScript / Vite / pnpm / react-speech-recognition 4.x / @ricky0123/vad-web; systemd user units; GitHub Actions.

## Global Constraints

- Working dir is the repo root: `/Volumes/Macintosh SSD - Daten/Users/horelvis/git/os1-samantha` (path has spaces — always quote it).
- Backend: run tests from `backend/` with `pytest tests/ -v`; format with `ruff format . && ruff check .` before committing.
- Frontend: run `pnpm typecheck` and `pnpm build` from `frontend/` before committing. Never `npm install` — pnpm only.
- Commit messages in English (conventional-commit style). User-facing strings in Spanish, in Samantha's voice (`docs/personality.md`).
- The user always runs `SAMANTHA_MODE=real` — never verify against mock mode only.
- **Test baseline (measured 2026-08-05).** The tracked suite is green: `pytest tests/ -q --ignore=tests/test_voice_pipeline.py` → **75 passed**. `backend/tests/test_voice_pipeline.py` is untracked WIP that pytest still collects, and its 7 tests **fail when run after the rest of the suite** (they pass in isolation) because its `_run` helper uses `asyncio.get_event_loop().run_until_complete`, which reuses a closed loop. Until Task 14 lands, every task must verify with `--ignore=tests/test_voice_pipeline.py` and treat those 7 failures as pre-existing and out of scope. Task 14 fixes the helper as its first act, and from Task 14 onward the full suite must be green with no ignore flag.
- Tasks marked `⚠ Requiere confirmación del usuario` must NOT be executed until the user explicitly approves them (CLAUDE.md §8: public-contract changes, deletions, renames).
- The `/voice` endpoint wiring itself belongs to the in-flight Phase 11 plan (`docs/superpowers/plans/2026-06-20-phase11-voice-loop.md`) — Fase 3 here fixes defects in that WIP, it does not duplicate its tasks.

## Tasks gated on user approval

These seven carry a `⚠` marker and must be skipped until the user says
otherwise; every other task is safe to execute in order. Skipping any of
them leaves the rest of the plan valid — no later task depends on their
output, with one exception noted below.

| Task | Why it's gated |
|---|---|
| 2 | Renames `voices/samatha.*` → `samantha.*` (global rule: don't rename files when fixing errors) |
| 3 | Moves the v7 mockup and deletes `test_pipecat_imports.py` |
| 9 | `/transcribe` and WS `listen` start returning 501/error in real mode (public contract) |
| 13 | Removes `ChatRequest.stream` and puts an admin token on `DELETE /profile` (public contract) |
| 27 | Deletes the `listen`/`transcription` WS types frontend-side (public contract) |
| 31 | Deletes the `tts-server/xtts/` directory |
| 32 | Creates the `.github/` top-level directory (CLAUDE.md §3) |

Exception: **Task 32 (CI) assumes Tasks 3, 4 and 14 have landed** — it runs
the test suite as those tasks leave it. If Task 3 is skipped, keep
`test_pipecat_imports.py` in the CI run; it passes either way.

## Review findings inventory (2026-08-04)

Source: three parallel review passes (backend, frontend, architecture/deploy). Each finding maps to a task below; the ID appears in the task it lands in.

**Críticos (High):**
- B-H4 api.py — `/profile` endpoints run blocking Memory/embedding work on the event loop (server freezes during onboarding). → Task 5
- B-H5 api.py — LLM `RuntimeError`s misclassified as client disconnects; UI hangs with no error frame. → Task 6
- V-H1 voice_pipeline.py — WS transport built without `serializer`; pipecat drops all inbound and outbound frames (pipeline deaf and mute). → Task 14
- V-H2 voice_pipeline.py — Whisper transcribes per 20 ms frame; no utterance aggregation. → Task 15
- V-H3 voice_pipeline.py — barge-in event never set by anyone; interruption feature inert. → Task 16
- V-H4 voice_pipeline.py — the resampler and the TTS stage construct bare `AudioRawFrame`, which is a dataclass *mixin*, not a `Frame`; `base_output` dispatches audio on `OutputAudioRawFrame`, so that audio could never reach the socket. Found while verifying the review against the installed pipecat. → Task 14
- V-H5 voice_pipeline.py — the pipeline cannot run at the browser's 48 kHz at all: `SileroVADAnalyzer.set_sample_rate()` raises for anything but 8/16 kHz, so resampling must happen at the protocol boundary, not as a pipeline stage after the VAD. → Task 14
- F-H4 tts.ts — a hung `speak()` leaves `busyRef` locked forever; conversation bricked until reload. → Task 20
- F-H1 ConversationScreen/Onboarding — speech-recognition errors swallowed; silent error→restart loop. → Task 21
- F-H2 useBargeIn.ts — VAD model/WASM fetched from CDN at runtime on a 24/7 appliance. → Task 22
- F-H3 store.ts — transcript unbounded + O(n) scans per streamed token. → Task 23
- A-H1 docs — Hermes API key still readable at HEAD in a tracked spec doc. → Task 1
- A-H2 CLAUDE.md — declared source of truth materially wrong (Piper/sounddevice/backend-static/etc.). → Task 29
- A-H3 CLAUDE.md §5 — deploy instructions enable a llama-server unit the kiosk box can't run. → Tasks 29/30

**Medios:** backend M1 (httpx singleton never closed / no lifespan → Task 7), M9 (memory-init failure latches forever → Task 8), M6 (mock STT paths live in real mode → Task 9), M7 (fresh httpx client per TTS call → Task 10), M8 (7 Chroma gets per turn + unbounded fact history → Task 11), M2+M10 (onboarding answers recovered by ±5 s wall-clock window; profile pokes `mem._collection` → Task 12); voice M3 (unsynchronized concurrent WS writes → Task 17), M4 (TTS waits for full reply; no sentence flush → Task 18), M5+M11+M12 (Whisper load/config, empty-frame crash, typing → Task 19), M13 (a fresh `WhisperSTTProcessor` per `/voice` client means multiple GB of weights reloaded on every reconnect — found during verification → Task 19); frontend M1–M5 (→ Tasks 24–26); deploy: systemd ordering/restart semantics (→ Task 30), Phase 11 deps promoted before any code path reaches them (→ Task 14 commits the WIP), xtts leftovers (→ Task 31), no CI (→ Task 32), voice-asset naming/typo mismatch vs config (→ Task 2), stray/untracked files + PROGRESS gaps (→ Task 3), pyproject/python-version drift (→ Task 4).

**Bajos:** bundled into Tasks 13 (backend), 27 (frontend), 4/29/30 (hygiene/docs) — dead `ChatRequest.stream`, unauthenticated `DELETE /profile`, mock imports in real mode, `FileResponse` 500 without built frontend, dead `listen`/`transcription` WS path, Wave.tsx layout read per frame, duplicated `micErrorMessage`, stale comments (vLLM/Whisper/Piper), hardcoded LAN IPs, `--split-mode row`, `sounddevice` extra with zero importers.

---
## Fase 1 — Seguridad e higiene (quick wins)

### Task 1: Redact the burned hermes API key from tracked docs

**Bug:** The hermes `API_SERVER_KEY` was removed from `systemd/samantha-hermes.service` in commit `4c7600e`, but the literal value is still readable at HEAD in `docs/superpowers/specs/hermes-agent-spike/REPORT.md:40` (env block) and `:50` (an `Authorization: Bearer ...` sentence). The untracked plan `docs/superpowers/plans/2026-06-11-bugfix-sweep.md:1318` also quotes the full value — and Task 3 is about to commit that file, which would re-introduce the secret at HEAD. This plan deliberately never spells out the full value; the regex below matches it without repeating it.

**Files:**
- Modify: `docs/superpowers/specs/hermes-agent-spike/REPORT.md`
- Modify: `docs/superpowers/plans/2026-06-11-bugfix-sweep.md` (untracked; committed later by Task 3)

- [ ] **Step 1: Redact every occurrence of the full key value**

The burned value matches `samantha-api-secret-key-<4 digits>`. Replace it everywhere without typing it out:

```bash
cd "/Volumes/Macintosh SSD - Daten/Users/horelvis/git/os1-samantha"
perl -pi -e 's/samantha-api-secret-key-\d+/<redacted — set via systemctl --user edit samantha-hermes>/g' \
  "docs/superpowers/specs/hermes-agent-spike/REPORT.md" \
  "docs/superpowers/plans/2026-06-11-bugfix-sweep.md"
```

After this, `REPORT.md:40` must read `API_SERVER_KEY=<redacted — set via systemctl --user edit samantha-hermes>`, `REPORT.md:50` must read `... enviando la cabecera \`Authorization: Bearer <redacted — set via systemctl --user edit samantha-hermes>\`.`, and the bugfix-sweep plan's Task 20 bug line must read `Environment=API_SERVER_KEY=<redacted — set via systemctl --user edit samantha-hermes>`.

- [ ] **Step 2: Sweep the whole tree for stragglers**

```bash
grep -rn "samantha-api-secret-key" . \
  --exclude-dir=.git --exclude-dir=node_modules --exclude-dir=.venv --exclude-dir=__pycache__
```

Expected remaining hits: only the *truncated* grep needle `samantha-api-secret-key` (no `-<digits>` suffix) inside the two plan documents' own grep instructions (e.g. `2026-06-11-bugfix-sweep.md:1333` and this task). If ANY hit still ends in a 4-digit year, redact it the same way before committing.

- [ ] **Step 3: Commit** (only `REPORT.md` — the bugfix-sweep plan is still untracked and gets committed by Task 3 already redacted)

```bash
git add "docs/superpowers/specs/hermes-agent-spike/REPORT.md"
git commit -m "docs(security): redact burned hermes API key from spike report"
```

- [ ] **Step 4: Record the rotation ruling (already decided — do NOT re-ask)**

Asked and answered on 2026-08-05: **the key will not be rotated**, on the grounds that the hermes gateway only listens on localhost. There is nothing to do on the kiosk box, and the user must not be prompted about it again. Task 33's PROGRESS entry records the decision verbatim as:

```
Rotación de la API_SERVER_KEY de hermes: descartada deliberadamente el
2026-08-05 (el gateway solo escucha en localhost). El valor histórico
queda quemado en el historial de git y en los units ya desplegados.
```

The redaction in Step 1 stands on its own merits regardless — a tracked document should not carry a live credential whatever its blast radius.

---

### Task 2: Voice reference assets — fix the `samatha` typo and track the transcript

> ⚠ Renombra un fichero — confirmar con el usuario antes de ejecutar (regla global: no renombrar al corregir).

**Bug:** `voices/samatha.wav` (typo) is the only tracked voice asset; its literal transcript `voices/samatha.txt` is UNTRACKED and would be lost on a fresh clone. `backend/samantha/config.py:84,88` expects the *correctly spelled* names at deploy time:

```python
    tts_cosyvoice_ref_wav: str = "~/.samantha/voices/ref/samantha.wav"
    ...
    tts_cosyvoice_ref_transcript_path: str = "~/.samantha/voices/ref/samantha.txt"
```

CosyVoice 3 zero-shot cannot work without the transcript (it conditions prosody on `prompt_text`), so the transcript is as load-bearing as the WAV. This is an asset rename to match what config loads — not a code-error rename — hence the explicit confirmation marker above.

**Files:**
- Rename: `voices/samatha.wav` → `voices/samantha.wav`
- Rename + track: `voices/samatha.txt` → `voices/samantha.txt`
- Create: `voices/README.md`

- [ ] **Step 1: Rename and track (after user confirmation)**

```bash
cd "/Volumes/Macintosh SSD - Daten/Users/horelvis/git/os1-samantha"
git mv voices/samatha.wav voices/samantha.wav
mv voices/samatha.txt voices/samantha.txt   # untracked — plain mv, then add
git add voices/samantha.txt
```

- [ ] **Step 2: Create `voices/README.md`**

````markdown
# voices/ — Samantha reference voice

Source assets for CosyVoice 3 zero-shot voice cloning (see
`backend/samantha/config.py`, `tts_cosyvoice_ref_*`):

- `samantha.wav` — ~8 s reference recording of Samantha's voice.
- `samantha.txt` — LITERAL transcript of the WAV. CosyVoice 3
  conditions prosody on this text (`inference_zero_shot`); if the WAV
  is re-recorded, this file MUST be updated to match word-for-word.

## Deploy

The backend loads these from `~/.samantha/voices/ref/`, not from the
repo. Copy on each box that runs the backend:

```bash
mkdir -p ~/.samantha/voices/ref
cp voices/samantha.wav voices/samantha.txt ~/.samantha/voices/ref/
```

Override paths via `SAMANTHA_TTS_COSYVOICE_REF_WAV` /
`SAMANTHA_TTS_COSYVOICE_REF_TRANSCRIPT_PATH` if they live elsewhere.
````

- [ ] **Step 3: Verify nothing references the old typo'd names**

```bash
grep -rn "samatha" . --exclude-dir=.git --exclude-dir=node_modules --exclude-dir=.venv --exclude-dir=__pycache__
```

Expected: no hits (verified at plan-writing time: the typo exists only in the filenames themselves).

- [ ] **Step 4: Commit**

```bash
git add voices/README.md
git commit -m "fix(voices): rename reference assets to match config paths; track transcript"
```

---

### Task 3: Repo strays — commit the bugfix-sweep plan, drop the pipecat smoke test, archive the mockup, backfill PROGRESS

> ⚠ Renombra/borra ficheros (mueve el mockup, borra un test) — confirmar con el usuario antes de ejecutar (regla global: no renombrar al corregir).

**Bug:** Four hygiene gaps: (a) `docs/superpowers/plans/2026-06-11-bugfix-sweep.md` is referenced by PROGRESS.md ("Bugfix Sweep (2026-06-11 plan)") but UNTRACKED — the plan the sweep executed isn't in git; (b) `backend/tests/test_pipecat_imports.py` was declared "new, smoke-only, deleted after Task 1" by the Phase 11 plan (`2026-06-20-phase11-voice-loop.md:55`) but is still tracked — it only asserts that pipecat/faster-whisper import paths resolve, which `test_voice_pipeline.py` (real `pipecat.frames`/`frame_processor` imports) and the runtime now cover for the paths that matter, and its `test_faster_whisper_imports` drags ctranslate2 into every CI run for no assertion value; (c) `samantha_mockup_v7.html` (48 KB) sits tracked at the repo root, referenced only historically (PROGRESS Phase 3, README); (d) CLAUDE.md §4 marks Phases 5 and 7 ✅ but PROGRESS.md has no entry for either.

Do NOT touch `backend/samantha/voice_pipeline.py` or `backend/tests/test_voice_pipeline.py` here — committing the Phase 11 WIP belongs to Task 14.

**Files:**
- Add: `docs/superpowers/plans/2026-06-11-bugfix-sweep.md` (as redacted by Task 1)
- Delete: `backend/tests/test_pipecat_imports.py`
- Move: `samantha_mockup_v7.html` → `docs/mockups/samantha_mockup_v7.html`
- Modify: `PROGRESS.md`

- [ ] **Step 1: Track the bugfix-sweep plan** (Task 1 must have run first — verify the key is redacted)

```bash
cd "/Volumes/Macintosh SSD - Daten/Users/horelvis/git/os1-samantha"
grep -cE "samantha-api-secret-key-[0-9]+" docs/superpowers/plans/2026-06-11-bugfix-sweep.md || true  # expect 0 / no match
git add docs/superpowers/plans/2026-06-11-bugfix-sweep.md
```

- [ ] **Step 2: Delete the pipecat import smoke test**

Verified content: 4 tests, each a bare `from pipecat... import ...` / `from faster_whisper import WhisperModel` plus `assert True` — no behavior tested. Known trade-off, accepted deliberately: `SileroVADAnalyzer` and `FastAPIWebsocketTransport` import paths are only exercised inside `voice_pipeline.build_pipeline()` (lazy imports, lines 293-298), which no test calls yet — a future pipecat version bump breaking those paths will surface at runtime or in Phase 11's own tests, which is what the Phase 11 plan intended when it scheduled this file for deletion.

```bash
git rm backend/tests/test_pipecat_imports.py
```

- [ ] **Step 3: Archive the mockup under docs/ (after user confirmation)**

```bash
mkdir -p docs/mockups
git mv samantha_mockup_v7.html docs/mockups/samantha_mockup_v7.html
```

`docs/mockups/` is a new *nested* directory (allowed by CLAUDE.md §3 rules — only new top-level dirs need asking). Historical mentions in PROGRESS.md:301 and README.md:61 describe Phase 3 as it happened and stay untouched.

- [ ] **Step 4: Backfill PROGRESS.md for Phases 5 and 7**

In `PROGRESS.md`, insert directly above the blockquote that begins `> **For Claude Code:** Append to this file after completing each phase` (line 46):

```markdown
## Phases 5 & 7 — backfilled 2026-08-04

- **Phase 5 — STT + TTS + audio ✅:** STT moved to the browser Web Speech API (`es-ES`, decision 2026-05-13); TTS server-side via `/speak`, iterated Piper → XTTS-v2 → CosyVoice 3 only (commit `2f7d6cf`).
- **Phase 7 — Kiosk deployment ✅:** systemd user units (`samantha-backend.service`, `samantha-ui.service`, `samantha-hermes.service`) + auto-login → openbox → Chromium `--kiosk`; llama-server runs manually on the 4090 box, never via systemd on the kiosk.

CLAUDE.md §4 marks both ✅ but no PROGRESS entry was recorded at the time.

---

```

- [ ] **Step 5: Run the backend suite (the deleted test must not break collection), then commit**

```bash
cd backend && pytest tests/ -v && cd ..
git add PROGRESS.md
git commit -m "chore(repo): track bugfix-sweep plan, drop pipecat smoke test, archive mockup, backfill PROGRESS"
```

---

### Task 4: pyproject + config hygiene — dead extra, stale comments, hardcoded LAN IP

**Bug:** (a) `backend/pyproject.toml` ships `[project.optional-dependencies] real = ["sounddevice>=0.4.7"]` with zero importers — the only `sounddevice` mentions in `backend/` are a historical comment at `api.py:181` and `.venv` internals; (b) `config.py:21` still claims mode `"real"` means "vLLM + Whisper + Piper" (reality: Grok API / llama-server + CosyVoice 3); (c) `config.py:81` defaults `tts_cosyvoice_url` to `http://192.168.100.58:8093` — this deployment's 4090 LAN IP — with no warning that any other install must override it. Python-version drift is verify-only here: pyproject already says `requires-python = ">=3.11"` and `target-version = "py311"`, matching the actual venv (3.11.9); CLAUDE.md's "3.12" claims are fixed by Task 29 to avoid double-editing.

Note: the working tree already carries an uncommitted pyproject hunk (`"numpy>=2.0"` → `"numpy>=1.26,<2"  # ... (<2 for ctranslate2/torch compat)`) from the Phase 11 WIP. It rides along in this task's commit deliberately — it is a deps fix independent of the voice-pipeline code, and Task 14 then commits only code.

**Files:**
- Modify: `backend/pyproject.toml`
- Modify: `backend/samantha/config.py`

- [ ] **Step 1: Remove the dead `real` extra**

In `backend/pyproject.toml`, replace:

```toml
[project.optional-dependencies]
real = [
    "sounddevice>=0.4.7",
]
dev = [
```

with:

```toml
[project.optional-dependencies]
dev = [
```

- [ ] **Step 2: Verify Python-version alignment (no edit expected)**

```bash
grep -n "requires-python\|target-version" backend/pyproject.toml
backend/.venv/bin/python --version
```

Expected: `requires-python = ">=3.11"`, `target-version = "py311"`, `Python 3.11.9`. If anything differs, STOP — the premise of Task 29's CLAUDE.md fix ("3.11+") would be wrong.

- [ ] **Step 3: Fix the stale mode comment in `config.py`**

Replace:

```python
    # === Modo de operación ===
    # "mock"  → respuestas falsas pero plausibles (desarrollo)
    # "real"  → vLLM + Whisper + Piper (producción)
    mode: str = "mock"
```

with:

```python
    # === Modo de operación ===
    # "mock"  → respuestas falsas pero plausibles (desarrollo)
    # "real"  → LLM real (Grok API por defecto / llama-server local)
    #           + CosyVoice 3 TTS (producción)
    mode: str = "mock"
```

- [ ] **Step 4: Flag the hardcoded LAN IP (keep the default)**

In `config.py`, replace:

```python
    # ── CosyVoice 3 server config ──
    # URL of the CosyVoice runtime FastAPI with our overlay
    # (tts-server/cosyvoice/docker-compose.yml). The overlay injects
    # the `<|endofprompt|>` system marker per request, so the client
    # sends plain Spanish.
    tts_cosyvoice_url: str = "http://192.168.100.58:8093"
```

with:

```python
    # ── CosyVoice 3 server config ──
    # URL of the CosyVoice runtime FastAPI with our overlay
    # (tts-server/cosyvoice/docker-compose.yml). The overlay injects
    # the `<|endofprompt|>` system marker per request, so the client
    # sends plain Spanish.
    #
    # ⚠ 192.168.100.58 is THIS deployment's 4090 box on the LAN.
    # Any other install (CI, laptop, new hardware) MUST override it:
    #   SAMANTHA_TTS_COSYVOICE_URL=http://<your-gpu-host>:8093
    # Kept as the default so the kiosk box needs zero env config.
    tts_cosyvoice_url: str = "http://192.168.100.58:8093"
```

- [ ] **Step 5: Test, format, commit** (includes the pre-existing numpy pin hunk — see task note)

```bash
cd backend && pytest tests/ -v && ruff format . && ruff check . && cd ..
git add backend/pyproject.toml backend/samantha/config.py
git commit -m "chore(backend): drop dead sounddevice extra, pin numpy<2, fix stale config comments"
```

---
## Fase 2 — Backend correctness

### Task 5: Move /profile endpoints' blocking Memory work off the event loop

**Bug:** `GET /profile` (`api.py:241` `_get_profile(mem)`), `POST /profile` (`api.py:262` `_is_onboarded(mem)` and `api.py:273` `_complete_onboarding(...)` — 6 fastembed ONNX embeddings + ~13 Chroma writes, seconds of CPU), and `DELETE /profile` (`api.py:290` `_delete_profile(mem)`) all run synchronous Memory work directly on the event loop. While onboarding persists, `/ping`, the WS, and `/speak` streaming freeze. `/ping` (`api.py:220`) already does this correctly via `asyncio.to_thread`.

**Files:**
- Modify: `backend/samantha/api.py:241`, `:262`, `:272-279`, `:290`
- Test: `backend/tests/test_api.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_api.py` (module-level `client` and `TestClient` already exist at the top of the file):

```python
# ========================================================================
# /profile — blocking Memory work must run off the event loop
# ========================================================================


def test_profile_endpoints_run_memory_work_off_event_loop(monkeypatch):
    """The profile helpers do fastembed + Chroma work (seconds of CPU).
    Inside asyncio.to_thread there is no running loop, so
    get_running_loop() raising RuntimeError proves we're off-loop."""
    import asyncio as aio

    from samantha import api as api_mod

    violations: list[str] = []

    def _record_if_on_loop(label: str) -> None:
        try:
            aio.get_running_loop()
            violations.append(label)
        except RuntimeError:
            pass  # worker thread — correct

    class FakeMem:
        pass

    monkeypatch.setattr(api_mod, "_memory", FakeMem())
    monkeypatch.setattr(api_mod.config, "memory_enabled", True)

    onboarded = {"value": False}
    profile = {"name": "Ana", "onboarding_completed_at": 123, "answers": []}

    def fake_is_onboarded(mem):
        _record_if_on_loop("is_onboarded")
        return onboarded["value"]

    def fake_get_profile(mem):
        _record_if_on_loop("get_profile")
        return profile if onboarded["value"] else None

    def fake_complete_onboarding(mem, name, answers):
        _record_if_on_loop("complete_onboarding")
        onboarded["value"] = True
        return {**profile, "name": name, "answers": answers}

    def fake_delete_profile(mem):
        _record_if_on_loop("delete_profile")
        onboarded["value"] = False
        return True

    monkeypatch.setattr(api_mod, "_is_onboarded", fake_is_onboarded)
    monkeypatch.setattr(api_mod, "_get_profile", fake_get_profile)
    monkeypatch.setattr(api_mod, "_complete_onboarding", fake_complete_onboarding)
    monkeypatch.setattr(api_mod, "_delete_profile", fake_delete_profile)

    body = {
        "name": "Ana",
        "answers": [
            {"q": "¿Cómo te llamo?", "a": "Ana"},
            {"q": "¿Cómo estás hoy?", "a": "bien"},
            {"q": "¿Qué te gusta?", "a": "leer"},
            {"q": "¿Algo que te ilusione?", "a": "viajar"},
            {"q": "¿Algo que te ronde?", "a": "trabajo"},
            {"q": "¿Directa o cuidadosa?", "a": "directa"},
        ],
    }
    assert client.post("/profile", json=body).status_code == 200
    assert client.get("/profile").status_code == 200
    assert client.delete("/profile").status_code == 200
    assert violations == [], f"ran on the event loop: {violations}"
```

- [ ] **Step 2: Run it — expect FAIL**

Run: `cd backend && pytest tests/test_api.py::test_profile_endpoints_run_memory_work_off_event_loop -v`
Expected: FAIL on `assert violations == []` with all four labels recorded (every helper currently runs inline in the async handler).

- [ ] **Step 3: Wrap the four call sites in `asyncio.to_thread`**

In `backend/samantha/api.py`, `get_profile_endpoint` — replace:

```python
    profile = _get_profile(mem)
```

with:

```python
    profile = await asyncio.to_thread(_get_profile, mem)
```

In `create_profile_endpoint` — replace:

```python
    if _is_onboarded(mem):
        raise HTTPException(status_code=409, detail="already_paired")
```

with:

```python
    if await asyncio.to_thread(_is_onboarded, mem):
        raise HTTPException(status_code=409, detail="already_paired")
```

and replace:

```python
    try:
        profile = _complete_onboarding(
            mem,
            name=name,
            answers=[a.model_dump() for a in req.answers],
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
```

with:

```python
    try:
        # 6 fastembed embeddings + ~13 Chroma writes — seconds of CPU.
        # Must not stall /ping, the WS, or /speak streaming.
        profile = await asyncio.to_thread(
            _complete_onboarding,
            mem,
            name=name,
            answers=[a.model_dump() for a in req.answers],
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
```

In `delete_profile_endpoint` — replace:

```python
    deleted = _delete_profile(mem)
```

with:

```python
    deleted = await asyncio.to_thread(_delete_profile, mem)
```

(`/ping` at `api.py:220` already wraps `_is_onboarded` — no change there.)

- [ ] **Step 4: Run the full suite, format, commit**

```bash
cd backend && pytest tests/ -v && ruff format . && ruff check .
git add backend/samantha/api.py backend/tests/test_api.py
git commit -m "fix(api): run profile memory work off the event loop"
```

---

### Task 6: WS — stop swallowing generator-side RuntimeErrors as "client disconnected"

**Bug:** `_ws_stream_chat` (`api.py:465-468`) re-raises `RuntimeError` as a disconnect signal, and the endpoint loop (`api.py:561-563`) logs it as "connection closed mid-send". But httpx raises `RuntimeError` for real faults too ("Cannot send a request, as the client has been closed", "Event loop is closed"). A real LLM failure is silently swallowed and the client never receives the `{"type":"error"}` frame — the UI hangs on "thinking". Only failures of `websocket.send_text` itself mean the client is gone.

**Files:**
- Modify: `backend/samantha/api.py:191-193` (add sentinel), `:458-477` (`_ws_stream_chat` try block), `:561-563` (endpoint except)
- Test: `backend/tests/test_api.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_api.py` (modeled on `test_ws_chat_handles_streaming_exception`):

```python
def test_ws_chat_reports_generator_runtime_error(monkeypatch):
    """httpx raises RuntimeError for real faults (client closed, event
    loop closed). Those come from the token GENERATOR, not from the
    socket — the client must receive an error frame, not silence."""
    from samantha import api

    async def mock_stream_tokens(*args, **kwargs):
        if False:
            yield ""
        raise RuntimeError("Cannot send a request, as the client has been closed")

    monkeypatch.setattr(api, "_stream_tokens", mock_stream_tokens)

    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "chat", "message": "hola"})
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert "llm_error" in msg["error"]
        assert "client has been closed" in msg["error"]
```

- [ ] **Step 2: Run it — expect FAIL**

Run: `cd backend && pytest tests/test_api.py::test_ws_chat_reports_generator_runtime_error -v`
Expected: FAIL — the RuntimeError is re-raised as a disconnect, no error frame arrives (the test times out or errors on `receive_json`).

- [ ] **Step 3: Add a send-failure sentinel and wrap only the send**

In `backend/samantha/api.py`, below:

```python
# Mirror ChatRequest's max_length — the WS path must not accept
# unbounded input the HTTP path rejects.
MAX_WS_MESSAGE_CHARS = 8000
```

add:

```python
class _ClientGone(Exception):
    """A websocket SEND failed because the client disconnected.

    Distinguishes send-side RuntimeErrors (client vanished mid-reply)
    from generator-side RuntimeErrors (httpx client closed, event loop
    closed) — the latter are real LLM faults the client must hear about.
    """
```

In `_ws_stream_chat`, replace:

```python
    reply_chunks: list[str] = []
    try:
        async for token in _stream_tokens(
            message, facts=facts, recall=recall, short_term=short, user_id=user_id
        ):
            reply_chunks.append(token)
            await websocket.send_text(json.dumps({"type": "token", "token": token}))
    except (WebSocketDisconnect, RuntimeError):
        # Client went away mid-reply — not an LLM error; don't try to
        # talk to a dead socket. The endpoint loop handles the close.
        raise
    except Exception as e:
        logger.exception("Error in websocket chat stream")
        try:
            await websocket.send_text(
                json.dumps({"type": "error", "error": f"llm_error: {str(e)}"})
            )
        except Exception:
            logger.info("ws: client gone before error could be delivered")
        return
```

with:

```python
    reply_chunks: list[str] = []
    try:
        async for token in _stream_tokens(
            message, facts=facts, recall=recall, short_term=short, user_id=user_id
        ):
            reply_chunks.append(token)
            try:
                await websocket.send_text(json.dumps({"type": "token", "token": token}))
            except (WebSocketDisconnect, RuntimeError) as e:
                # ONLY send failures mean "client gone". Anything the
                # generator raises falls through to the branches below.
                raise _ClientGone() from e
    except _ClientGone:
        # Don't try to talk to a dead socket; the endpoint loop closes.
        raise
    except WebSocketDisconnect:
        raise
    except Exception as e:
        logger.exception("Error in websocket chat stream")
        try:
            await websocket.send_text(
                json.dumps({"type": "error", "error": f"llm_error: {str(e)}"})
            )
        except Exception:
            logger.info("ws: client gone before error could be delivered")
        return
```

In `websocket_endpoint`, replace the final handler:

```python
    except RuntimeError:
        # send on an already-closed socket (client vanished mid-reply)
        logger.info("ws: connection closed mid-send")
```

with:

```python
    except (_ClientGone, RuntimeError):
        # _ClientGone: token send failed mid-reply. Bare RuntimeError
        # here can only come from sends issued by this loop itself
        # (error frames / the `done` frame) on an already-closed socket.
        logger.info("ws: connection closed mid-send")
```

- [ ] **Step 4: Run the full suite, format, commit**

```bash
cd backend && pytest tests/ -v && ruff format . && ruff check .
git add backend/samantha/api.py backend/tests/test_api.py
git commit -m "fix(ws): stop swallowing generator RuntimeErrors as client disconnects"
```

---

### Task 7: Wire a FastAPI lifespan that closes the LLM client and the memory store

**Bug:** `real_llm.py:37` holds a module-level `httpx.AsyncClient` singleton and `real_llm.aclose()` (`real_llm.py:97-102`) exists precisely for shutdown — but `api.py` never calls it (`app = FastAPI(...)` at `api.py:162` has no lifespan). The short-term ring's SQLite connection (`ShortTermBuffer.close()`, `short_term.py:118-120`) is likewise never closed. On every reload/restart these leak until process teardown.

**Files:**
- Modify: `backend/samantha/api.py` (lifespan + app construction), `backend/samantha/memory.py` (add `Memory.close()`)
- Test: `backend/tests/test_api.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_api.py`:

```python
# ========================================================================
# lifespan — shutdown must release long-lived resources
# ========================================================================


def test_lifespan_closes_llm_client():
    """real_llm.aclose() exists but was never wired to the app
    lifecycle — the shared httpx client must be released on shutdown."""
    from samantha import api as api_mod
    from samantha import real_llm

    with TestClient(api_mod.app):
        real_llm._get_client()
        assert real_llm._client is not None
    assert real_llm._client is None


def test_lifespan_closes_memory():
    """Shutdown closes the memory store (SQLite ring connection) and
    drops the singleton so a restart re-initializes cleanly."""
    from samantha import api as api_mod

    closed = {"value": False}

    class FakeMem:
        def close(self):
            closed["value"] = True

    with TestClient(api_mod.app):
        api_mod._memory = FakeMem()
    assert closed["value"] is True
    assert api_mod._memory is None
```

- [ ] **Step 2: Run them — expect FAIL**

Run: `cd backend && pytest tests/test_api.py::test_lifespan_closes_llm_client tests/test_api.py::test_lifespan_closes_memory -v`
Expected: both FAIL (no lifespan exists; `real_llm._client` stays set, `FakeMem.close` never called).

- [ ] **Step 3: Add `Memory.close()`**

In `backend/samantha/memory.py`, after the `stats` method (line ~420-425), add:

```python
    def close(self) -> None:
        """Release held resources: the short-term ring's SQLite
        connection. ChromaDB's PersistentClient exposes no public
        close; its handles are released on GC."""
        self._short_term.close()
```

- [ ] **Step 4: Add the lifespan in `api.py`**

Add to the stdlib imports (below `import asyncio`):

```python
from contextlib import asynccontextmanager
```

Directly above the `app = FastAPI(` block, add:

```python
@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Startup is lazy (memory and HTTP clients init on first use);
    shutdown releases whatever got created: the shared LLM httpx
    client and the memory store (SQLite ring connection)."""
    global _memory
    yield
    from . import real_llm

    await real_llm.aclose()
    if _memory is not None:
        await asyncio.to_thread(_memory.close)
        _memory = None
```

and replace:

```python
app = FastAPI(
    title="Samantha Backend",
    version=__version__,
    description="Backend local para Samantha. Solo accesible desde localhost.",
)
```

with:

```python
app = FastAPI(
    title="Samantha Backend",
    version=__version__,
    description="Backend local para Samantha. Solo accesible desde localhost.",
    lifespan=_lifespan,
)
```

(`AsyncIterator` is already imported from `typing` at `api.py:31`.)

- [ ] **Step 5: Run the full suite, format, commit**

```bash
cd backend && pytest tests/ -v && ruff format . && ruff check .
git add backend/samantha/api.py backend/samantha/memory.py backend/tests/test_api.py
git commit -m "fix(api): close LLM client and memory store on shutdown via lifespan"
```

---

### Task 8: Memory init failure retries after a backoff instead of latching forever

**Bug:** `api.py:107-110` sets `_memory_init_failed = True` on the first init error and `get_memory()` (`api.py:90`) then returns `None` for the life of the process. The repo/persist dir lives on an external volume that may mount late during boot — one early failure permanently disables memory until a manual restart.

**Files:**
- Modify: `backend/samantha/api.py:77-111`
- Test: `backend/tests/test_api.py` (new test + 4 existing references to `_memory_init_failed`)

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_api.py`:

```python
def test_memory_init_failure_retries_after_backoff(monkeypatch):
    """A failed init (e.g. external volume not yet mounted at boot)
    must not disable memory forever — retry after the backoff window."""
    import samantha.memory as memory_mod
    from samantha import api as api_mod

    monkeypatch.setattr(api_mod, "_memory", None)
    monkeypatch.setattr(api_mod, "_memory_init_failed_at", None)
    monkeypatch.setattr(api_mod.config, "memory_enabled", True)

    calls = {"n": 0}

    class FlakyMemory:
        def __init__(self, persist_dir):
            calls["n"] += 1
            if calls["n"] == 1:
                raise OSError("volume not mounted")

        def close(self):
            pass

    monkeypatch.setattr(memory_mod, "Memory", FlakyMemory)

    # First call fails and latches the failure timestamp.
    assert api_mod.get_memory() is None
    # Within the backoff window: no new attempt.
    assert api_mod.get_memory() is None
    assert calls["n"] == 1
    # Simulate the window elapsing.
    monkeypatch.setattr(
        api_mod,
        "_memory_init_failed_at",
        api_mod._memory_init_failed_at - api_mod.MEMORY_INIT_RETRY_S - 1,
    )
    assert api_mod.get_memory() is not None
    assert calls["n"] == 2
```

- [ ] **Step 2: Run it — expect FAIL**

Run: `cd backend && pytest tests/test_api.py::test_memory_init_failure_retries_after_backoff -v`
Expected: ERROR on `monkeypatch.setattr(api_mod, "_memory_init_failed_at", None)` — the attribute doesn't exist yet.

- [ ] **Step 3: Replace the latch with a timestamp + backoff**

In `backend/samantha/api.py`, replace the whole singleton block (from `_memory: "Memory | None" = None` through the end of `get_memory`, lines 77-111):

```python
_memory: "Memory | None" = None
_memory_init_failed: bool = False
_memory_lock = threading.Lock()


def get_memory() -> "Memory | None":
    """Lazily initialize the persistent memory store.

    Returns None if memory is disabled (config.memory_enabled=False) or
    if initialization fails — never raise into the request path.
    """
    global _memory, _memory_init_failed
    # Fast path: already initialized (or permanently failed/disabled).
    if not config.memory_enabled or _memory_init_failed:
        return None
    if _memory is not None:
        return _memory
    # Slow path: first init. Serialize across threads so only one
    # fastembed ONNX session and one chroma open happen.
    with _memory_lock:
        # Re-check inside the lock — another thread may have won the race.
        if _memory_init_failed:
            return None
        if _memory is not None:
            return _memory
        try:
            from .memory import Memory

            persist = os.path.expanduser(config.memory_persist_dir)
            _memory = Memory(persist_dir=persist)
        except Exception as e:  # pragma: no cover — defensive
            logger.error(f"memory: failed to initialize, disabling: {e}")
            _memory_init_failed = True
            return None
    return _memory
```

with:

```python
_memory: "Memory | None" = None
# Monotonic timestamp of the last failed init, or None. Failures are
# NOT permanent: the persist dir may live on a volume that mounts late
# during boot, so we retry after a backoff window instead of latching.
_memory_init_failed_at: float | None = None
_memory_lock = threading.Lock()

MEMORY_INIT_RETRY_S = 30.0


def _init_backoff_active() -> bool:
    return (
        _memory_init_failed_at is not None
        and (time.monotonic() - _memory_init_failed_at) < MEMORY_INIT_RETRY_S
    )


def get_memory() -> "Memory | None":
    """Lazily initialize the persistent memory store.

    Returns None if memory is disabled (config.memory_enabled=False) or
    while the retry backoff after a failed init is active — never raise
    into the request path.
    """
    global _memory, _memory_init_failed_at
    # Fast path: disabled, cooling down after a failure, or ready.
    if not config.memory_enabled or _init_backoff_active():
        return None
    if _memory is not None:
        return _memory
    # Slow path: first init. Serialize across threads so only one
    # fastembed ONNX session and one chroma open happen.
    with _memory_lock:
        # Re-check inside the lock — another thread may have won the race.
        if _memory is not None:
            return _memory
        if _init_backoff_active():
            return None
        try:
            from .memory import Memory

            persist = os.path.expanduser(config.memory_persist_dir)
            _memory = Memory(persist_dir=persist)
            _memory_init_failed_at = None
        except Exception as e:
            logger.error(f"memory: init failed, retrying in {MEMORY_INIT_RETRY_S:.0f}s: {e}")
            _memory_init_failed_at = time.monotonic()
            return None
    return _memory
```

(Requires `import time` — check the imports at the top of `api.py` and add it if missing.)

- [ ] **Step 4: Update the four existing test references**

In `backend/tests/test_api.py`, replace all three occurrences (in `test_profile_endpoints_full_cycle`, `test_profile_post_rejects_empty_first_answer`, `test_profile_post_rejects_re_pairing`) of:

```python
    api_mod._memory_init_failed = False
```

with:

```python
    api_mod._memory_init_failed_at = None
```

and in `test_chat_does_not_duplicate_current_message` replace:

```python
    monkeypatch.setattr(api_mod, "_memory_init_failed", False)
```

with:

```python
    monkeypatch.setattr(api_mod, "_memory_init_failed_at", None)
```

- [ ] **Step 5: Run the full suite, format, commit**

```bash
cd backend && pytest tests/ -v && ruff format . && ruff check .
git add backend/samantha/api.py backend/tests/test_api.py
git commit -m "fix(api): retry memory init after backoff instead of latching failure"
```

---

### Task 9: Real mode must not serve fake transcriptions

> ⚠ Requiere confirmación del usuario antes de ejecutar (CLAUDE.md §8: cambio de contrato público).

**Bug:** `/transcribe` (`api.py:350-367`) and the WS `listen` turn (`api.py:488-497`, dispatched at `:553-554`) return `FAKE_TRANSCRIPTS` regardless of `config.mode`. In real mode a caller gets "hola (mic en modo mock — Phase 5 cablea Whisper)" presented as a genuine transcription. STT lives in the browser (CLAUDE.md §2.8); the server paths must fail honestly in real mode: `501` from `/transcribe`, an error frame from WS `listen`. (Deleting the paths entirely is a bigger contract removal — kept for a separate proposal, as already flagged in the 2026-06-11 plan.)

**Files:**
- Modify: `backend/samantha/api.py:350-356`, `:488-497`
- Test: `backend/tests/test_api.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_api.py`:

```python
def test_transcribe_real_mode_returns_501(monkeypatch):
    """Real mode has no server-side STT (browser Web Speech per
    CLAUDE.md §2.8) — a fake transcript presented as real is a lie."""
    from samantha import api as api_mod

    monkeypatch.setattr(api_mod.config, "mode", "real")
    r = client.post(
        "/transcribe",
        files={"audio": ("test.wav", b"\x00" * 100, "audio/wav")},
    )
    assert r.status_code == 501
    assert "stt_not_implemented" in r.text


def test_ws_listen_real_mode_returns_error(monkeypatch):
    from samantha import api as api_mod

    monkeypatch.setattr(api_mod.config, "mode", "real")
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "listen"})
        msg = ws.receive_json()
        assert msg == {"type": "error", "error": "stt_not_implemented"}
```

- [ ] **Step 2: Run them — expect FAIL**

Run: `cd backend && pytest tests/test_api.py::test_transcribe_real_mode_returns_501 tests/test_api.py::test_ws_listen_real_mode_returns_error -v`
Expected: both FAIL — 200 with a fake transcript / a `transcription` frame.

- [ ] **Step 3: Gate both paths on `config.mode`**

In `backend/samantha/api.py`, `transcribe` — replace:

```python
@app.post("/transcribe", response_model=TranscribeResponse)
async def transcribe(audio: UploadFile = File(...)) -> TranscribeResponse:
    """Mock transcription. Phase 5 swaps in faster-whisper."""
    contents = await audio.read()
```

with:

```python
@app.post("/transcribe", response_model=TranscribeResponse)
async def transcribe(audio: UploadFile = File(...)) -> TranscribeResponse:
    """Mock-only transcription. STT lives in the browser (Web Speech
    API, CLAUDE.md §2.8); in real mode this endpoint is explicitly
    unimplemented instead of returning a canned transcript."""
    if config.mode == "real":
        raise HTTPException(status_code=501, detail="stt_not_implemented")
    contents = await audio.read()
```

And `_ws_handle_listen` — replace:

```python
async def _ws_handle_listen(websocket: WebSocket) -> None:
    """Placeholder for the future audio-driven listen turn (Phase 5).

    For now: simulate a short capture, then send back a fake transcription.
    The frontend's mic button drives this; it never opens the browser mic.
    """
    await asyncio.sleep(random.uniform(0.8, 1.6))
```

with:

```python
async def _ws_handle_listen(websocket: WebSocket) -> None:
    """Deprecated listen turn (browser Web Speech replaced it).

    Mock mode still returns the clearly-labeled fake transcription for
    UI development; real mode reports an error frame instead of
    pretending to have heard the user.
    """
    if config.mode == "real":
        await websocket.send_text(
            json.dumps({"type": "error", "error": "stt_not_implemented"})
        )
        return
    await asyncio.sleep(random.uniform(0.8, 1.6))
```

(The frontend never calls `listen` in real mode — the mic path is `webkitSpeechRecognition` in `ConversationScreen.tsx` — and its WS client already handles `{"type":"error"}` frames.)

- [ ] **Step 4: Run the full suite, format, commit**

```bash
cd backend && pytest tests/ -v && ruff format . && ruff check .
git add backend/samantha/api.py backend/tests/test_api.py
git commit -m "fix(api): real mode rejects mock transcription paths (501 / error frame)"
```

---

### Task 10: TTS — one shared httpx client instead of a fresh client per synthesis

**Bug:** `tts.py:173` creates a new `httpx.AsyncClient` inside every `_stream_cosyvoice` call — a fresh connection pool and TCP handshake per `/speak`, on the latency-critical voice path. Fix: module-level shared client (mirroring `real_llm.py`'s `_get_client`/`aclose` pattern) wired into the Task-7 lifespan.

**Files:**
- Modify: `backend/samantha/tts.py`, `backend/samantha/api.py` (lifespan from Task 7)
- Test: `backend/tests/test_tts.py`, `backend/tests/test_api.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_tts.py`:

```python
def test_tts_shared_client_reused_and_closed():
    """stream() must reuse one AsyncClient; aclose() releases it."""
    import asyncio

    c1 = tts._get_client()
    c2 = tts._get_client()
    assert c1 is c2
    asyncio.run(tts.aclose())
    assert tts._client is None
```

Append to `backend/tests/test_api.py`:

```python
def test_lifespan_closes_tts_client():
    from samantha import api as api_mod
    from samantha import tts as tts_mod

    with TestClient(api_mod.app):
        tts_mod._get_client()
        assert tts_mod._client is not None
    assert tts_mod._client is None
```

- [ ] **Step 2: Run them — expect FAIL**

Run: `cd backend && pytest tests/test_tts.py::test_tts_shared_client_reused_and_closed tests/test_api.py::test_lifespan_closes_tts_client -v`
Expected: both FAIL with `AttributeError` — `tts._get_client` doesn't exist yet.

- [ ] **Step 3: Add the shared client to `tts.py`**

Below `OUTPUT_SAMPLE_RATE = 24000`, add:

```python
_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    """Shared AsyncClient: one connection pool for all synthesis calls
    instead of a fresh client (and TCP handshake) per /speak.

    `read` is httpx's per-read-operation (inter-chunk) timeout, not a
    whole-body cap: a healthy stream that keeps emitting chunks never
    trips it, while a wedged server (CUDA hang) fails loudly instead
    of freezing /speak forever.
    """
    global _client
    if _client is None:
        timeout = httpx.Timeout(
            connect=config.tts_cosyvoice_timeout_s,
            read=config.tts_cosyvoice_timeout_s,
            write=config.tts_cosyvoice_timeout_s,
            pool=config.tts_cosyvoice_timeout_s,
        )
        _client = httpx.AsyncClient(timeout=timeout)
    return _client


async def aclose() -> None:
    """Release the shared HTTP client. Called from api.py's lifespan."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
```

In `_stream_cosyvoice`, replace:

```python
    url = f"{config.tts_cosyvoice_url.rstrip('/')}/inference_zero_shot"
    # `read` is httpx's per-read-operation (inter-chunk) timeout, not a
    # whole-body cap: a healthy stream that keeps emitting chunks never
    # trips it, while a wedged server (CUDA hang) fails loudly instead
    # of freezing /speak forever.
    timeout = httpx.Timeout(
        connect=config.tts_cosyvoice_timeout_s,
        read=config.tts_cosyvoice_timeout_s,
        write=config.tts_cosyvoice_timeout_s,
        pool=config.tts_cosyvoice_timeout_s,
    )
    # httpx multipart: (filename, content, content-type). filename=None
    # for text fields makes httpx emit them as plain form parts.
    files = {
        "tts_text": (None, text),
        "prompt_text": (None, transcript),
        "prompt_wav": (wav_name, wav_bytes, "audio/wav"),
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream("POST", url, files=files) as resp:
            if resp.status_code != 200:
                err = await resp.aread()
                raise RuntimeError(
                    f"cosyvoice {resp.status_code}: {err[:200].decode('utf-8', 'replace')}"
                )
            got_any = False
            async for chunk in resp.aiter_bytes(chunk_size=4096):
                if chunk:
                    got_any = True
                    yield chunk
            if not got_any:
                raise RuntimeError(
                    "cosyvoice returned 200 but no audio — most likely "
                    "tts_text shorter than prompt_text (hifigan kernel "
                    "size 4), or an unrecognized expression marker"
                )
```

with:

```python
    url = f"{config.tts_cosyvoice_url.rstrip('/')}/inference_zero_shot"
    # httpx multipart: (filename, content, content-type). filename=None
    # for text fields makes httpx emit them as plain form parts.
    files = {
        "tts_text": (None, text),
        "prompt_text": (None, transcript),
        "prompt_wav": (wav_name, wav_bytes, "audio/wav"),
    }

    client = _get_client()
    async with client.stream("POST", url, files=files) as resp:
        if resp.status_code != 200:
            err = await resp.aread()
            raise RuntimeError(
                f"cosyvoice {resp.status_code}: {err[:200].decode('utf-8', 'replace')}"
            )
        got_any = False
        async for chunk in resp.aiter_bytes(chunk_size=4096):
            if chunk:
                got_any = True
                yield chunk
        if not got_any:
            raise RuntimeError(
                "cosyvoice returned 200 but no audio — most likely "
                "tts_text shorter than prompt_text (hifigan kernel "
                "size 4), or an unrecognized expression marker"
            )
```

- [ ] **Step 4: Keep `synth()` loop-safe**

`synth()` runs inside a throwaway `asyncio.run()` loop; a shared client left open would stay bound to that dead loop. In `tts.py`, replace:

```python
async def _consolidate(text: str) -> tuple[bytes, str]:
    chunks: list[bytes] = []
    backend: str = ""
    async for chunk, label in stream(text):
        chunks.append(chunk)
        backend = label
```

with:

```python
async def _consolidate(text: str) -> tuple[bytes, str]:
    try:
        chunks: list[bytes] = []
        backend: str = ""
        async for chunk, label in stream(text):
            chunks.append(chunk)
            backend = label
    finally:
        # synth() runs in its own asyncio.run() loop — close the shared
        # client here so it can't outlive that loop and poison the next
        # caller. /speak (uvicorn's single loop) is unaffected.
        await aclose()
```

(Adjust the remainder of `_consolidate` so the post-loop code stays inside the `try` — read the function before editing.)

- [ ] **Step 5: Wire `tts.aclose()` into the Task-7 lifespan**

In `backend/samantha/api.py`, inside `_lifespan`, replace:

```python
    from . import real_llm

    await real_llm.aclose()
```

with:

```python
    from . import real_llm, tts

    await real_llm.aclose()
    await tts.aclose()
```

- [ ] **Step 6: Run the full suite, format, commit**

```bash
cd backend && pytest tests/ -v && ruff format . && ruff check .
git add backend/samantha/tts.py backend/samantha/api.py backend/tests/test_tts.py backend/tests/test_api.py
git commit -m "fix(tts): share one httpx client across synthesis calls, close on shutdown"
```

---

### Task 11: One batched Chroma get per turn for facts (was 7)

**Bug:** `context.py:43-48` runs `_collect_facts` on every turn, which issues 7 separate `mem.get_fact()` calls (name + 5 Big-Five + onboarding marker), and each `get_fact` (`memory.py:279-309`) fetches ALL historical rows for its kind and sorts in Python. That is 7 Chroma metadata scans per chat turn for values that essentially never change after onboarding. Fix: a single `collection.get` with `{"kind": {"$in": [...]}}` reduced in Python (no cache — one metadata get per turn is already cheap, and no invalidation logic to get wrong).

**Files:**
- Modify: `backend/samantha/memory.py` (add `latest_facts`, delegate `get_fact`), `backend/samantha/context.py:16-29`
- Test: `backend/tests/test_api.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_api.py` (memory section):

```python
def test_memory_latest_facts_batches_kinds(tmp_path):
    """One call, several kinds, newest entry per kind; missing kinds
    are simply absent."""
    import time

    from samantha.memory import Memory

    mem = Memory(persist_dir=str(tmp_path / "mem"))
    mem.set_fact("name", "Old Name", user_id="u1")
    time.sleep(1.1)
    mem.set_fact("name", "New Name", user_id="u1")
    mem.set_fact("big5_openness", "alta", user_id="u1")

    out = mem.latest_facts(("name", "big5_openness", "missing_kind"), user_id="u1")
    assert out["name"]["value"] == "New Name"
    assert out["big5_openness"]["value"] == "alta"
    assert "missing_kind" not in out


def test_collect_facts_uses_single_batched_query():
    """_collect_facts must issue ONE latest_facts call, never per-kind
    get_fact calls (7 Chroma scans per turn)."""
    from samantha.context import _collect_facts

    class FakeMem:
        def __init__(self):
            self.latest_calls = 0
            self.get_fact_calls = 0

        def latest_facts(self, kinds, *, user_id="primary"):
            self.latest_calls += 1
            return {
                "name": {
                    "id": "f1",
                    "kind": "name",
                    "value": "Ana",
                    "text": "El usuario se llama Ana",
                    "timestamp": 1,
                }
            }

        def get_fact(self, *args, **kwargs):
            self.get_fact_calls += 1
            return None

    mem = FakeMem()
    facts = _collect_facts(mem, user_id="primary")
    assert mem.latest_calls == 1
    assert mem.get_fact_calls == 0
    assert [f["kind"] for f in facts] == ["name"]
```

- [ ] **Step 2: Run them — expect FAIL**

Run: `cd backend && pytest tests/test_api.py::test_memory_latest_facts_batches_kinds tests/test_api.py::test_collect_facts_uses_single_batched_query -v`
Expected: FAIL — `Memory.latest_facts` doesn't exist; `_collect_facts` calls `get_fact` 7 times.

- [ ] **Step 3: Add `Memory.latest_facts` and delegate `get_fact`**

In `backend/samantha/memory.py`, add to the imports (below `from dataclasses import dataclass`):

```python
from collections.abc import Sequence
```

Then replace the whole `get_fact` method:

```python
    def get_fact(self, kind: str, *, user_id: str = "primary") -> dict | None:
        """Return the newest fact for `kind`, or None."""
        res = self._collection.get(
            where={
                "$and": [
                    {"user_id": user_id},
                    {"role": "fact"},
                    {"kind": kind},
                ]
            },
            include=["documents", "metadatas"],
        )
        ids = res.get("ids") or []
        if not ids:
            return None
        metas = res.get("metadatas") or []
        docs = res.get("documents") or []
        candidates = []
        for i, fid in enumerate(ids):
            m = metas[i] or {}
            candidates.append(
                {
                    "id": fid,
                    "kind": m.get("kind"),
                    "value": self._deserialize_fact_value(m),
                    "text": docs[i] if i < len(docs) else "",
                    "timestamp": int(m.get("timestamp", 0)),
                }
            )
        candidates.sort(key=lambda c: c["timestamp"], reverse=True)
        return candidates[0]
```

with:

```python
    def get_fact(self, kind: str, *, user_id: str = "primary") -> dict | None:
        """Return the newest fact for `kind`, or None."""
        return self.latest_facts((kind,), user_id=user_id).get(kind)

    def latest_facts(
        self,
        kinds: Sequence[str],
        *,
        user_id: str = "primary",
    ) -> dict[str, dict]:
        """Newest fact per kind, in ONE Chroma metadata get.

        Replaces per-kind get_fact loops (context._collect_facts used
        to issue 7 gets per chat turn). Facts are append-only, so we
        reduce to the max-timestamp entry per kind in Python.
        """
        if not kinds:
            return {}
        res = self._collection.get(
            where={
                "$and": [
                    {"user_id": user_id},
                    {"role": "fact"},
                    {"kind": {"$in": list(kinds)}},
                ]
            },
            include=["documents", "metadatas"],
        )
        ids = res.get("ids") or []
        metas = res.get("metadatas") or []
        docs = res.get("documents") or []
        latest: dict[str, dict] = {}
        for i, fid in enumerate(ids):
            m = metas[i] or {}
            kind = str(m.get("kind", ""))
            entry = {
                "id": fid,
                "kind": kind,
                "value": self._deserialize_fact_value(m),
                "text": docs[i] if i < len(docs) else "",
                "timestamp": int(m.get("timestamp", 0)),
            }
            prev = latest.get(kind)
            if prev is None or entry["timestamp"] > prev["timestamp"]:
                latest[kind] = entry
        return latest
```

- [ ] **Step 4: Use it from `_collect_facts`**

In `backend/samantha/context.py`, replace:

```python
def _collect_facts(mem: "Memory", *, user_id: str) -> list[dict]:
    """Gather facts surfaced into the system prompt.

    Order: name → Big-Five traits → onboarding_completed_at.
    """
    from .profile import BIG5_FACT_KINDS

    kinds = ("name", *BIG5_FACT_KINDS, "onboarding_completed_at")
    out: list[dict] = []
    for kind in kinds:
        f = mem.get_fact(kind, user_id=user_id)
        if f is not None:
            out.append(f)
    return out
```

with:

```python
def _collect_facts(mem: "Memory", *, user_id: str) -> list[dict]:
    """Gather facts surfaced into the system prompt.

    Order: name → Big-Five traits → onboarding_completed_at.
    One batched Chroma get for all kinds (was: 7 separate gets/turn).
    """
    from .profile import BIG5_FACT_KINDS

    kinds = ("name", *BIG5_FACT_KINDS, "onboarding_completed_at")
    by_kind = mem.latest_facts(kinds, user_id=user_id)
    return [by_kind[kind] for kind in kinds if kind in by_kind]
```

- [ ] **Step 5: Run the full suite, format, commit**

```bash
cd backend && pytest tests/ -v && ruff format . && ruff check .
git add backend/samantha/memory.py backend/samantha/context.py backend/tests/test_api.py
git commit -m "perf(memory): batch per-turn fact lookups into one Chroma get"
```

---

### Task 12: Recover onboarding answers by explicit slot metadata, not a ±5 s timestamp window

**Bug:** `profile.py:133-158` recovers the 6 onboarding answers by finding `role='user'` chunks within ±5 s of the `onboarding_completed_at` marker. Slow embedding (fastembed cold start easily takes seconds per chunk) pushes answer chunks out of the window → `get_profile` silently returns `answers: []`. Additionally, `profile.py:117-129` and `:137-147` reach into `mem._collection` (private). Fix: tag answer chunks with `onboarding_slot: i` metadata at write time and recover by metadata; promote `delete_facts` / `get_chunks` to public `Memory` methods. The old window recovery stays as a fallback for profiles stored before the tag existed.

**Files:**
- Modify: `backend/samantha/memory.py` (`remember` gains `extra_metadata`; add `delete_facts`, `get_chunks`), `backend/samantha/profile.py`
- Test: `backend/tests/test_profile.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_profile.py`:

```python
def test_memory_remember_with_extra_metadata(tmp_path):
    mem = Memory(persist_dir=str(tmp_path / "mem"))
    mem.remember("user", "respuesta uno", extra_metadata={"onboarding_slot": 3})
    items = mem.get_chunks({"onboarding_slot": {"$gte": 0}})
    assert len(items) == 1
    doc, meta = items[0]
    assert doc == "respuesta uno"
    assert meta["onboarding_slot"] == 3


def test_answers_survive_slow_onboarding_writes(tmp_path, monkeypatch):
    """Recovery must not depend on the ±5 s window. Simulate slow
    embedding: every clock read during onboarding advances a minute,
    spreading the chunks far beyond any timestamp window."""
    import itertools

    from samantha import memory as memory_mod

    mem = _make_mem(tmp_path)

    base = 1_800_000_000
    counter = itertools.count()
    # Patches time.time globally (memory.py and profile.py share the
    # stdlib module); monkeypatch restores it on teardown.
    monkeypatch.setattr(memory_mod.time, "time", lambda: base + 60 * next(counter))

    complete_onboarding(mem, name="Bob", answers=_six_answers())
    profile = get_profile(mem)
    assert profile is not None
    assert len(profile["answers"]) == 6


def test_legacy_profiles_recover_via_timestamp_window(tmp_path):
    """Profiles stored before the slot tag existed (plain chunks + a
    marker fact in the same second) must still recover their answers."""
    import time

    mem = _make_mem(tmp_path)
    for entry in _six_answers():
        mem.remember("user", f"[Q] {entry['q']} → [A] {entry['a']}")
    mem.set_fact("name", "Bob", text="El usuario se llama Bob")
    mem.set_fact("onboarding_completed_at", int(time.time()), text="Onboarding completado")

    profile = get_profile(mem)
    assert profile is not None
    assert len(profile["answers"]) == 6
```

(If `_make_mem` / `_six_answers` helpers don't exist in `test_profile.py`, check the file's existing fixtures and adapt these tests to its local conventions — the assertions stay the same.)

- [ ] **Step 2: Run them — expect FAIL**

Run: `cd backend && pytest tests/test_profile.py -v`
Expected: `test_memory_remember_with_extra_metadata` fails with `TypeError` (unexpected keyword `extra_metadata`); `test_answers_survive_slow_onboarding_writes` fails with `answers == []` (chunks fell out of the window); the legacy test passes (locks down the fallback).

- [ ] **Step 3: Extend `Memory.remember` and add the public methods**

In `backend/samantha/memory.py`, replace the `remember` method:

```python
    def remember(self, role: str, text: str, *, user_id: str = "primary") -> str:
        """Store a chunk in both long-term and short-term layers.

        Returns the chunk id (empty string if skipped).
        """
        if not text or not text.strip():
            return ""
        if role not in ("user", "samantha"):
            raise ValueError(f"role must be 'user' or 'samantha', got {role!r}")
        chunk_id = str(uuid.uuid4())
        ts = int(time.time())
        self._collection.add(
            ids=[chunk_id],
            documents=[text.strip()],
            metadatas=[
                {
                    "role": role,
                    "timestamp": ts,
                    "user_id": user_id,
                }
            ],
        )
```

with:

```python
    def remember(
        self,
        role: str,
        text: str,
        *,
        user_id: str = "primary",
        extra_metadata: dict[str, str | int | float | bool] | None = None,
    ) -> str:
        """Store a chunk in both long-term and short-term layers.

        `extra_metadata` lets callers tag chunks with scalar metadata
        (e.g. profile.py tags onboarding answers with their slot index
        so recovery doesn't depend on timestamps).

        Returns the chunk id (empty string if skipped).
        """
        if not text or not text.strip():
            return ""
        if role not in ("user", "samantha"):
            raise ValueError(f"role must be 'user' or 'samantha', got {role!r}")
        chunk_id = str(uuid.uuid4())
        ts = int(time.time())
        metadata: dict = {
            "role": role,
            "timestamp": ts,
            "user_id": user_id,
        }
        if extra_metadata:
            metadata.update(extra_metadata)
        self._collection.add(
            ids=[chunk_id],
            documents=[text.strip()],
            metadatas=[metadata],
        )
```

(The `# Mirror into short-term ring...` lines after the `add` call stay untouched.)

Then add two public methods, after `all_facts` (before `_deserialize_fact_value`):

```python
    def get_chunks(self, where: dict, *, user_id: str = "primary") -> list[tuple[str, dict]]:
        """Public metadata-filtered fetch: (document, metadata) pairs.

        `where` is a Chroma where-clause fragment; the user_id filter
        is added automatically. Replaces callers reaching into
        `self._collection` directly (profile.py used to).
        """
        res = self._collection.get(
            where={"$and": [{"user_id": user_id}, where]},
            include=["documents", "metadatas"],
        )
        docs = res.get("documents") or []
        metas = res.get("metadatas") or []
        return [(docs[i], metas[i] or {}) for i in range(len(docs))]

    def delete_facts(self, kinds: Sequence[str], *, user_id: str = "primary") -> int:
        """ADMIN: delete every historical fact whose kind is in `kinds`.

        Returns the number of chunks deleted. Used by
        profile.delete_profile — NOT wired to user input (Samantha
        never forgets conversational content; see module docstring).
        """
        if not kinds:
            return 0
        res = self._collection.get(
            where={
                "$and": [
                    {"user_id": user_id},
                    {"role": "fact"},
                    {"kind": {"$in": list(kinds)}},
                ]
            }
        )
        ids = res.get("ids") or []
        if not ids:
            return 0
        self._collection.delete(ids=ids)
        return len(ids)
```

(`Sequence` is imported in Task 11; if executing this task independently, add `from collections.abc import Sequence` to the imports.)

- [ ] **Step 4: Tag slots at write time and recover by metadata in `profile.py`**

In `backend/samantha/profile.py`, in `complete_onboarding`, replace:

```python
    # Insert the 6 answer chunks FIRST so they share a tight timestamp
    # window with the onboarding marker (recovery uses ±5s window).
    # Each big-5 answer is also promoted to a fact so it surfaces in
    # every prompt, not just when semantic recall pulls it in.
    for i, entry in enumerate(answers):
        q = (entry.get("q") or "").strip()
        a = entry.get("a")
        if not q or not a or not str(a).strip():
            continue
        a_clean = str(a).strip()
        chunk_text = f"[Q] {q} → [A] {a_clean}"
        mem.remember("user", chunk_text, user_id=user_id)
```

with:

```python
    # Each answer chunk carries its slot index as metadata — recovery
    # is by `onboarding_slot`, not by timestamp proximity (slow
    # embedding used to push chunks out of the old ±5 s window).
    # Each big-5 answer is also promoted to a fact so it surfaces in
    # every prompt, not just when semantic recall pulls it in.
    for i, entry in enumerate(answers):
        q = (entry.get("q") or "").strip()
        a = entry.get("a")
        if not q or not a or not str(a).strip():
            continue
        a_clean = str(a).strip()
        chunk_text = f"[Q] {q} → [A] {a_clean}"
        mem.remember(
            "user",
            chunk_text,
            user_id=user_id,
            extra_metadata={"onboarding_slot": i},
        )
```

Replace `delete_profile`'s body:

```python
    res = mem._collection.get(
        where={
            "$and": [
                {"user_id": user_id},
                {"role": "fact"},
                {"kind": {"$in": list(PROFILE_FACT_KINDS)}},
            ]
        }
    )
    ids = res.get("ids") or []
    if not ids:
        return False
    mem._collection.delete(ids=ids)
    return True
```

with:

```python
    return mem.delete_facts(sorted(PROFILE_FACT_KINDS), user_id=user_id) > 0
```

And replace the whole `_recover_answers` function:

```python
def _recover_answers(mem: Memory, anchor_ts: int, *, user_id: str = "primary") -> list[dict]:
    """Find role='user' chunks inserted within ±5 s of the onboarding marker."""
    if anchor_ts <= 0:
        return []
    res = mem._collection.get(
        where={
            "$and": [
                {"user_id": user_id},
                {"role": "user"},
                {"timestamp": {"$gte": anchor_ts - 5}},
                {"timestamp": {"$lte": anchor_ts + 5}},
            ]
        },
        include=["documents", "metadatas"],
    )
    docs = res.get("documents") or []
    metas = res.get("metadatas") or []
    items = list(zip(docs, metas))
    items.sort(key=lambda x: int(x[1].get("timestamp", 0)))
    out = []
    for doc, _meta in items:
        if "[Q]" in doc and "→ [A]" in doc:
            q = doc.split("[Q]", 1)[1].split("→ [A]", 1)[0].strip()
            a = doc.split("→ [A]", 1)[1].strip()
            out.append({"q": q, "a": a})
    return out
```

with:

```python
def _parse_answer(doc: str) -> dict | None:
    if "[Q]" in doc and "→ [A]" in doc:
        q = doc.split("[Q]", 1)[1].split("→ [A]", 1)[0].strip()
        a = doc.split("→ [A]", 1)[1].strip()
        return {"q": q, "a": a}
    return None


def _recover_answers(mem: Memory, anchor_ts: int, *, user_id: str = "primary") -> list[dict]:
    """Recover the 6 onboarding answers.

    Preferred: chunks tagged with `onboarding_slot` at write time
    (complete_onboarding). Fallback for profiles stored before the tag
    existed: role='user' chunks within ±5 s of the onboarding marker —
    fragile (slow embedding pushed chunks out of the window), kept only
    for backward compatibility with already-stored profiles.
    """
    items = mem.get_chunks({"onboarding_slot": {"$gte": 0}}, user_id=user_id)
    if items:
        items.sort(key=lambda x: int(x[1].get("onboarding_slot", 0)))
        out = [p for doc, _meta in items if (p := _parse_answer(doc)) is not None]
        if out:
            return out

    if anchor_ts <= 0:
        return []
    items = mem.get_chunks(
        {
            "$and": [
                {"role": "user"},
                {"timestamp": {"$gte": anchor_ts - 5}},
                {"timestamp": {"$lte": anchor_ts + 5}},
            ]
        },
        user_id=user_id,
    )
    items.sort(key=lambda x: int(x[1].get("timestamp", 0)))
    return [p for doc, _meta in items if (p := _parse_answer(doc)) is not None]
```

- [ ] **Step 5: Run the full suite, format, commit**

```bash
cd backend && pytest tests/ -v && ruff format . && ruff check .
git add backend/samantha/memory.py backend/samantha/profile.py backend/tests/test_profile.py
git commit -m "fix(profile): recover onboarding answers by slot metadata; public Memory API for profile ops"
```

---

### Task 13: Low-severity cleanups — mock import gating, dead `stream` field, admin token on DELETE /profile, honest 404

> ⚠ Requiere confirmación del usuario antes de ejecutar (CLAUDE.md §8: cambio de contrato público).

**Bug (4 bundled):**
1. `api.py:48` imports `mock_llm` unconditionally — mock code loads even in real mode (memory: "mock_llm is on the way out").
2. `schemas.py:45-49` `ChatRequest.stream` is a dead field — nothing reads `req.stream` and the frontend never sends it (verified: no `stream:` in `frontend/src`, no `ChatRequest` type in `frontend/src/core/types.ts`). Removing it is a contract change → marker above.
3. `api.py:283-291` `DELETE /profile` unpairs the device with a bare unauthenticated curl. Gate behind `SAMANTHA_ADMIN_TOKEN` + `X-Admin-Token` header (403 when unset or wrong) — also a contract change.
4. `api.py:201-204` `FileResponse(INDEX_FILE)` produces an opaque 500 when `frontend/dist` hasn't been built; return an explicit 404 `frontend_not_built`.

**Files:**
- Modify: `backend/samantha/api.py`, `backend/samantha/schemas.py`, `backend/samantha/config.py`
- Test: `backend/tests/test_api.py`
- Verify only (no change needed): `frontend/src/core/types.ts`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_api.py`:

```python
# ========================================================================
# low-severity hardening: admin token, frontend 404
# ========================================================================


def test_delete_profile_403_when_admin_token_unset(monkeypatch):
    """With no SAMANTHA_ADMIN_TOKEN configured the endpoint is disabled
    — an unauthenticated localhost curl must not unpair the device."""
    from samantha import api as api_mod

    monkeypatch.setattr(api_mod.config, "admin_token", "")
    r = client.delete("/profile")
    assert r.status_code == 403
    assert "admin_disabled" in r.text


def test_delete_profile_403_on_wrong_token(monkeypatch):
    from samantha import api as api_mod

    monkeypatch.setattr(api_mod.config, "admin_token", "secreto")
    r = client.delete("/profile", headers={"X-Admin-Token": "malo"})
    assert r.status_code == 403
    assert "forbidden" in r.text


def test_index_404_when_frontend_not_built(monkeypatch, tmp_path):
    from samantha import api as api_mod

    monkeypatch.setattr(api_mod, "INDEX_FILE", tmp_path / "missing.html")
    r = client.get("/")
    assert r.status_code == 404
    assert "frontend_not_built" in r.text
```

Run: `cd backend && pytest tests/test_api.py -k "admin_token or frontend_not_built" -v`
Expected: all three FAIL (`config.admin_token` doesn't exist yet → `AttributeError`; `/` returns a 500/`FileResponse` error, not 404).

- [ ] **Step 2: Add `admin_token` to `Config`**

In `backend/samantha/config.py`, after the `log_level: str = "INFO"` field, add:

```python
    # === Admin ===
    # Shared secret for admin-only endpoints (DELETE /profile). The
    # caller must send it in the X-Admin-Token header. Empty (default)
    # disables those endpoints entirely — set SAMANTHA_ADMIN_TOKEN from
    # an admin terminal when you actually need to unpair the device.
    admin_token: str = ""
```

and in `from_env`, after the `log_level=_get("LOG_LEVEL", cls.log_level),` line, add:

```python
            admin_token=_get("ADMIN_TOKEN", cls.admin_token),
```

- [ ] **Step 3: Gate `DELETE /profile`**

In `backend/samantha/api.py`, replace:

```python
@app.delete("/profile")
async def delete_profile_endpoint() -> dict:
    """ADMIN-only: clears name + onboarding_completed_at facts. The 6
    onboarding-answer chunks survive (Samantha never forgets)."""
    mem = await asyncio.to_thread(get_memory)
```

with:

```python
@app.delete("/profile")
async def delete_profile_endpoint(request: Request) -> dict:
    """ADMIN-only: clears name + onboarding_completed_at facts. The 6
    onboarding-answer chunks survive (Samantha never forgets).

    Gated by SAMANTHA_ADMIN_TOKEN via the X-Admin-Token header. With
    the env var unset the endpoint is disabled (403) — unpairing must
    be a deliberate admin act, not a stray curl."""
    if not config.admin_token:
        raise HTTPException(status_code=403, detail="admin_disabled")
    if request.headers.get("X-Admin-Token") != config.admin_token:
        raise HTTPException(status_code=403, detail="forbidden")
    mem = await asyncio.to_thread(get_memory)
```

(`Request` is already imported from `fastapi` at `api.py:37`.)

Update the three existing tests that call `client.delete("/profile")`:

In `test_profile_endpoints_full_cycle` and `test_profile_post_rejects_re_pairing`, add next to the other monkeypatches:

```python
    monkeypatch.setattr(api_mod.config, "admin_token", "test-token")
```

and change each `client.delete("/profile")` call in those two tests to:

```python
    client.delete("/profile", headers={"X-Admin-Token": "test-token"})
```

(in `test_profile_endpoints_full_cycle` the call is assigned: `r = client.delete("/profile", headers={"X-Admin-Token": "test-token"})`).

In `test_profile_endpoints_run_memory_work_off_event_loop` (Task 5), add the same `admin_token` monkeypatch and change the last assertion to:

```python
    assert (
        client.delete("/profile", headers={"X-Admin-Token": "test-token"}).status_code == 200
    )
```

- [ ] **Step 4: Honest 404 when the frontend isn't built**

In `backend/samantha/api.py`, replace:

```python
@app.get("/")
async def index() -> FileResponse:
    """Serve the SPA. Chromium in kiosk mode lands here at boot."""
    return FileResponse(INDEX_FILE)
```

with:

```python
@app.get("/")
async def index() -> FileResponse:
    """Serve the SPA. Chromium in kiosk mode lands here at boot."""
    if not INDEX_FILE.is_file():
        # Explicit 404 with a hint beats FileResponse's opaque 500
        # when `pnpm build` hasn't run yet.
        raise HTTPException(status_code=404, detail="frontend_not_built")
    return FileResponse(INDEX_FILE)
```

(`test_index_serves_frontend_html` already skips on 404 — no change needed there.)

- [ ] **Step 5: Gate the mock_llm import behind mock mode**

In `backend/samantha/api.py`, delete line 48:

```python
from .mock_llm import generate_reply as mock_generate_reply, tokenize_for_streaming
```

In `_stream_tokens`, replace:

```python
    # Mock path: brief "thinking" pause, then drip tokens.
    await asyncio.sleep(random.uniform(0.2, 0.6))
```

with:

```python
    # Mock path: brief "thinking" pause, then drip tokens. Imported
    # here so real mode never loads mock code (mirrors the real_llm
    # import above, which is also mode-local).
    from .mock_llm import generate_reply as mock_generate_reply, tokenize_for_streaming

    await asyncio.sleep(random.uniform(0.2, 0.6))
```

In `chat()`, replace:

```python
    else:
        latency = random.uniform(config.mock_min_latency_s, config.mock_max_latency_s)
```

with:

```python
    else:
        from .mock_llm import generate_reply as mock_generate_reply

        latency = random.uniform(config.mock_min_latency_s, config.mock_max_latency_s)
```

- [ ] **Step 6: Remove the dead `stream` field**

In `backend/samantha/schemas.py`, in `ChatRequest`, delete:

```python
    stream: bool = Field(
        default=False,
        description="Si True, devuelve Server-Sent Events token a token",
    )
```

(The SSE `/chat/stream` endpoint it described was replaced by the WebSocket in Phase 3 and no longer exists.) Then verify nothing consumes it:

```bash
grep -rn "req.stream\|\"stream\":\|stream:" backend/samantha backend/tests frontend/src --include="*.py" --include="*.ts" --include="*.tsx" | grep -v "_stream\|stream(\|streaming\|StreamingResponse\|stream_reply\|tts.stream"
```

Expected: no hits referencing `ChatRequest.stream`. `frontend/src/core/types.ts` has no `ChatRequest` counterpart (the frontend chats over the WS protocol), so no frontend edit is needed — this grep is the proof.

- [ ] **Step 7: Run the full suite, format, commit**

```bash
cd backend && pytest tests/ -v && ruff format . && ruff check .
git add backend/samantha/api.py backend/samantha/schemas.py backend/samantha/config.py backend/tests/test_api.py
git commit -m "chore(api): gate mock imports by mode, admin token on DELETE /profile, drop dead stream field, honest 404"
```

---
## Fase 3 — Voice pipeline (Phase 11 WIP)

> These tasks amend the in-flight Phase 11 plan
> (`docs/superpowers/plans/2026-06-20-phase11-voice-loop.md`). The `/voice`
> endpoint wiring and the frontend `useVoiceSocket` hook stay in THAT plan
> (its Tasks 5–7) — these tasks fix defects in the pipeline code it already
> produced. Phase 11's Task 5/6 must be written against the wire protocol
> defined in Task 14 below, not against the original docstring.
>
> **Every claim below was verified against the installed pipecat 0.0.89** in
> `backend/.venv/lib/python3.11/site-packages/pipecat/`. Re-verify before
> editing if the pin ever moves (`pyproject.toml` allows `>=0.0.89,<0.1.0`).

---

### Task 14: Commit the WIP, then make the pipeline able to hear and speak at all

**Bug (three defects, each of which alone breaks the whole loop):**

1. **No serializer → deaf and mute.** `voice_pipeline.py:304-314` builds
   `FastAPIWebsocketParams(...)` without `serializer`. In pipecat 0.0.89
   `FastAPIWebsocketParams.serializer` defaults to `None`
   (`transports/websocket/fastapi.py:62`), and then
   `_receive_messages` does `if not self._params.serializer: continue`
   (`fastapi.py:283-284` — every inbound message dropped) while
   `_write_frame` does `if not self._params.serializer: return`
   (`fastapi.py:459-460` — every outbound frame dropped). The unit tests
   monkeypatch `push_frame` and never touch the transport, so this is
   invisible to `pytest`.

2. **`AudioRawFrame` is not a `Frame`.** `pipecat.frames.frames.AudioRawFrame`
   (line 189) is a plain dataclass *mixin*: `OutputAudioRawFrame(DataFrame,
   AudioRawFrame)` and `InputAudioRawFrame(SystemFrame, AudioRawFrame)` are
   the real frames. Verified:
   `issubclass(AudioRawFrame, Frame) is False`. `Resample48kTo16kProcessor`
   and `CosyVoiceTTSProcessor._synthesize` both *construct* bare
   `AudioRawFrame(...)`, so they emit objects that are not frames at all —
   and `base_output.py:325,349` dispatches audio only on
   `isinstance(frame, OutputAudioRawFrame)`, so that audio would be silently
   discarded even with a serializer in place.

3. **The pipeline cannot run at 48 kHz.** `base_input.py:182-186` does
   `self._sample_rate = self._params.audio_in_sample_rate or
   frame.audio_in_sample_rate` and then
   `self._params.vad_analyzer.set_sample_rate(self._sample_rate)`, and
   `SileroVADAnalyzer.set_sample_rate` (`audio/vad/silero.py:184-187`)
   **raises `ValueError`** for anything but 8000/16000. So the browser's
   48 kHz capture must be downsampled *before* it becomes a pipeline frame —
   i.e. at the protocol boundary, in the serializer — and
   `Resample48kTo16kProcessor` (a pipeline stage, running after VAD) is in
   the wrong place by construction.

**Wire protocol decision.** `FastAPIWebsocketClient` picks bytes-vs-text
**once**, from `serializer.type`, and uses that for both directions
(`fastapi.py:112,116-121` — `iter_bytes()`/`send_bytes` or
`iter_text()`/`send_text`). The module docstring's "binary for audio, text
frames for JSON control" is therefore not expressible through the transport.
One binary channel with a 1-byte type prefix is, and it keeps a single
writer (which also fixes Task 17's race). No client exists yet — `/voice` is
unwired and `frontend/src` has no voice socket — so changing the protocol
breaks nothing.

**Files:**
- Modify: `backend/samantha/voice_pipeline.py`
- Modify: `backend/tests/test_voice_pipeline.py`

- [ ] **Step 1: Fix the broken test helper, then commit the WIP**

`test_voice_pipeline.py`'s `_run` uses `asyncio.get_event_loop().run_until_complete`,
which reuses a closed loop: its 7 tests pass in isolation and fail when run
after the rest of the suite (measured 2026-08-05). Committing a test file
with a helper that fails in suite order would make every later task's
verification unreadable, so fix it before it becomes tracked code. Replace:

```python
def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)
```

with:

```python
def _run(coro):
    # asyncio.get_event_loop() is deprecated from sync code on 3.11 and
    # reuses a closed loop when the suite has already run other async
    # tests; each test gets its own loop instead.
    return asyncio.run(coro)
```

Verify the whole suite is green — no ignore flag, all 82 tests:

```bash
cd backend && .venv/bin/python -m pytest tests/ -q
```

Expected: `82 passed`. Then commit the WIP with the fix folded in:

```bash
cd "/Volumes/Macintosh SSD - Daten/Users/horelvis/git/os1-samantha"
git add backend/samantha/voice_pipeline.py backend/tests/test_voice_pipeline.py
git commit -m "wip(voice): Phase 11 pipeline skeleton (pre-fix snapshot)"
```

- [ ] **Step 2: Re-verify the three pipecat facts before editing**

```bash
cd backend
P=.venv/lib/python3.11/site-packages
grep -n "serializer: Optional\[FrameSerializer\] = None" $P/pipecat/transports/websocket/fastapi.py
grep -n "if not self._params.serializer" $P/pipecat/transports/websocket/fastapi.py
grep -n "Silero VAD sample rate needs to be" $P/pipecat/audio/vad/silero.py
.venv/bin/python -c "from pipecat.frames.frames import AudioRawFrame, Frame; print('AudioRawFrame is Frame:', issubclass(AudioRawFrame, Frame))"
```

Expected: the default-`None` serializer line, both `if not self._params.serializer`
guards (receive ~283, write ~459), the Silero raise, and
`AudioRawFrame is Frame: False`. If any differs, STOP — the whole task's
premise is that specific pipecat build.

- [ ] **Step 3: Write the failing tests**

Replace the two `Resample48kTo16kProcessor` tests (`test_resample_output_length`
and `test_resample_non_audio_frame_passes_through`) in
`backend/tests/test_voice_pipeline.py` with:

```python
# ── resample_pcm16 ────────────────────────────────────────────────────────


def test_resample_output_length():
    """1 second of silence at 48 kHz → 16 000 samples (× 2 bytes) at 16 kHz."""
    from samantha.voice_pipeline import resample_pcm16

    out = resample_pcm16(make_silence(48_000, 1.0), 48_000, 16_000)
    assert len(out) == 16_000 * 2


def test_resample_same_rate_is_identity():
    from samantha.voice_pipeline import resample_pcm16

    audio = make_silence(16_000, 0.1)
    assert resample_pcm16(audio, 16_000, 16_000) == audio


# ── SamanthaWireSerializer ────────────────────────────────────────────────


def test_wire_serializer_deserializes_audio_at_pipeline_rate():
    """Browser PCM (48 kHz, 0x01-prefixed) → InputAudioRawFrame at 16 kHz.

    16 kHz is not a preference: SileroVADAnalyzer.set_sample_rate() raises
    for anything but 8/16 kHz, and base_input feeds it the pipeline rate.
    """
    from pipecat.frames.frames import InputAudioRawFrame

    from samantha.voice_pipeline import SamanthaWireSerializer

    ser = SamanthaWireSerializer()
    payload = bytes([SamanthaWireSerializer.AUDIO]) + make_silence(48_000, 1.0)

    frame = _run(ser.deserialize(payload))

    assert isinstance(frame, InputAudioRawFrame)
    assert frame.sample_rate == 16_000
    assert len(frame.audio) == 16_000 * 2


def test_wire_serializer_serializes_output_audio_and_control():
    """Outbound: audio gets the 0x01 prefix, control JSON the 0x02 one."""
    import json as _json

    from pipecat.frames.frames import (
        OutputTransportMessageUrgentFrame,
        TTSAudioRawFrame,
    )

    from samantha.voice_pipeline import SamanthaWireSerializer

    ser = SamanthaWireSerializer()

    audio = _run(
        ser.serialize(
            TTSAudioRawFrame(audio=b"\x01\x02", sample_rate=24_000, num_channels=1)
        )
    )
    assert audio == bytes([SamanthaWireSerializer.AUDIO]) + b"\x01\x02"

    ctrl = _run(
        ser.serialize(OutputTransportMessageUrgentFrame(message={"type": "token", "text": "hola"}))
    )
    assert ctrl[0] == SamanthaWireSerializer.CONTROL
    assert _json.loads(ctrl[1:].decode("utf-8")) == {"type": "token", "text": "hola"}


def test_wire_serializer_round_trip_control_message():
    from pipecat.frames.frames import InputTransportMessageFrame

    from samantha.voice_pipeline import SamanthaWireSerializer

    ser = SamanthaWireSerializer()
    wire = _run(ser.serialize(_urgent({"type": "ping"})))
    frame = _run(ser.deserialize(wire))
    assert isinstance(frame, InputTransportMessageFrame)
    assert frame.message == {"type": "ping"}


def test_wire_serializer_drops_garbage():
    from samantha.voice_pipeline import SamanthaWireSerializer

    ser = SamanthaWireSerializer()
    assert _run(ser.deserialize(b"")) is None
    assert _run(ser.deserialize(b"\x09whatever")) is None       # unknown prefix
    assert _run(ser.deserialize(b"\x02{not json")) is None      # broken control


def test_build_pipeline_configures_a_serializer(monkeypatch):
    """Regression for the deaf-and-mute pipeline.

    With FastAPIWebsocketParams.serializer left at its default None,
    pipecat 0.0.89 drops EVERY inbound message (_receive_messages) and
    EVERY outbound frame (_write_frame) — the loop looks alive and does
    nothing. The transport must never be built without one.
    """
    import pipecat.audio.vad.silero as silero_mod
    import pipecat.transports.websocket.fastapi as fastapi_mod
    from pipecat.processors.frame_processor import FrameProcessor
    from pipecat.serializers.base_serializer import FrameSerializerType

    from samantha.voice_pipeline import build_pipeline

    # Silero loads an ONNX model in __init__ — not wanted in unit tests.
    monkeypatch.setattr(silero_mod, "SileroVADAnalyzer", MagicMock())

    captured = {}

    class SpyTransport:
        def __init__(self, websocket, params, **kwargs):
            captured["params"] = params

        def input(self):
            return FrameProcessor()

        def output(self):
            return FrameProcessor()

    monkeypatch.setattr(fastapi_mod, "FastAPIWebsocketTransport", SpyTransport)

    build_pipeline(websocket=MagicMock(), mem=None)

    params = captured["params"]
    assert params.serializer is not None
    assert params.serializer.type is FrameSerializerType.BINARY
```

Add this helper next to `make_silence` at the top of the file (the round-trip
test uses it):

```python
def _urgent(message: dict):
    from pipecat.frames.frames import OutputTransportMessageUrgentFrame

    return OutputTransportMessageUrgentFrame(message=message)
```

And in `test_cosyvoice_tts_emits_audio_frames`, replace:

```python
    from pipecat.frames.frames import AudioRawFrame, TextFrame
```

with:

```python
    from pipecat.frames.frames import TextFrame, TTSAudioRawFrame
```

and:

```python
    audio_frames = [f for f in pushed if isinstance(f, AudioRawFrame)]
    assert len(audio_frames) == 1
    assert audio_frames[0].sample_rate == 24_000
```

with:

```python
    # TTSAudioRawFrame, not bare AudioRawFrame: base_output dispatches
    # audio on isinstance(frame, OutputAudioRawFrame) — a bare
    # AudioRawFrame is not even a Frame and never reaches the socket.
    audio_frames = [f for f in pushed if isinstance(f, TTSAudioRawFrame)]
    assert len(audio_frames) == 1
    assert audio_frames[0].sample_rate == 24_000
```

Apply the same two substitutions in `test_cosyvoice_tts_stops_on_barge_in`
(its import line and its `audio_frames = [...]` line; the
`assert len(audio_frames) == 0` stays).

- [ ] **Step 4: Run them — expect FAIL**

Run: `cd backend && pytest tests/test_voice_pipeline.py -v`
Expected: the `resample_pcm16` / `SamanthaWireSerializer` / `build_pipeline`
tests fail with `ImportError` or `AttributeError` (nothing of that name
exists yet); the two CosyVoice tests fail on `TTSAudioRawFrame` not being
found among the pushed objects.

- [ ] **Step 5: Replace the module header imports**

In `backend/samantha/voice_pipeline.py`, replace the docstring's pipeline
sketch and the import block — everything from `"""Server-side voice loop`
down to and including `from .tts import stream as _tts_stream` — with:

```python
"""Server-side voice loop — Pipecat-based pipeline for Phase 11.

Pipeline (assembled by build_pipeline):
  FastAPIWebsocketTransport.input()     ← SamanthaWireSerializer decodes to
                                          16 kHz InputAudioRawFrame + VAD
    → WhisperSTTProcessor               ← utterance audio → UserTranscriptFrame
    → SamanthaLLMProcessor              ← UserTranscriptFrame → TextFrames
    → CosyVoiceTTSProcessor             ← TextFrames → TTSAudioRawFrame 24 kHz
  FastAPIWebsocketTransport.output()   → SamanthaWireSerializer encodes

Wire protocol (ONE binary WebSocket channel, 1-byte type prefix — see
SamanthaWireSerializer): 0x01 + int16-LE PCM, 0x02 + UTF-8 JSON control.
pipecat's FastAPI transport picks bytes-or-text once from the serializer
type and uses it both ways, so audio and control cannot use separate
WebSocket frame types.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, AsyncIterator

import numpy as np
from loguru import logger
from pipecat.frames.frames import (
    AudioRawFrame,
    Frame,
    InputAudioRawFrame,
    InputTransportMessageFrame,
    OutputAudioRawFrame,
    OutputTransportMessageFrame,
    OutputTransportMessageUrgentFrame,
    TextFrame,
    TTSAudioRawFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.serializers.base_serializer import FrameSerializer, FrameSerializerType

if TYPE_CHECKING:
    from fastapi import WebSocket
    from pipecat.pipeline.task import PipelineTask

    from .memory import Memory, MemoryChunk

# ──────────────────────────────────────────────────────────────────────────
# Module-level aliases so tests can monkeypatch without touching real imports
# ──────────────────────────────────────────────────────────────────────────

from .context import gather_context
from .tts import stream as _tts_stream
```

(`PipelineTask` moves under `TYPE_CHECKING` so the `-> "PipelineTask"`
annotation on `build_pipeline` actually resolves — it was previously only
imported inside the function body, making the annotation unresolvable for
any typing tool.)

- [ ] **Step 6: Type `_stream_reply_impl`'s parameters**

Replace:

```python
async def _stream_reply_impl(
    message: str,
    *,
    facts=None,
    recall=None,
    short_term=None,
    user_id: str = "primary",
) -> AsyncIterator[str]:
```

with:

```python
async def _stream_reply_impl(
    message: str,
    *,
    facts: list[dict] | None = None,
    recall: "list[MemoryChunk] | None" = None,
    short_term: "list[MemoryChunk] | None" = None,
    user_id: str = "primary",
) -> AsyncIterator[str]:
```

- [ ] **Step 7: Replace `Resample48kTo16kProcessor` with `resample_pcm16` + the serializer**

Replace the whole `Stage 1 — Resample 48 kHz → 16 kHz` section (the banner
comment and the entire `Resample48kTo16kProcessor` class, i.e. everything
between the `LLMDoneFrame` dataclass and the `Stage 2 — Whisper STT` banner)
with:

```python
# ──────────────────────────────────────────────────────────────────────────
# Wire protocol: resampling + serializer
# ──────────────────────────────────────────────────────────────────────────


def resample_pcm16(audio: bytes, src_rate: int, dst_rate: int) -> bytes:
    """Linear-interpolation resample of int16 mono PCM.

    Lives at the protocol boundary (SamanthaWireSerializer), not as a
    pipeline stage: base_input hands the VAD analyzer the pipeline's
    sample rate, and SileroVADAnalyzer.set_sample_rate() raises for
    anything but 8/16 kHz — so audio must already be 16 kHz by the time
    it becomes a frame.
    """
    if not audio or src_rate == dst_rate:
        return audio
    src = np.frombuffer(audio, dtype=np.int16)
    if src.size == 0:
        return b""
    dst_len = max(1, int(src.size * dst_rate / src_rate))
    dst = np.interp(
        np.linspace(0, src.size - 1, dst_len),
        np.arange(src.size),
        src,
    ).astype(np.int16)
    return dst.tobytes()


class SamanthaWireSerializer(FrameSerializer):
    """Framed binary protocol between the browser and the voice pipeline.

    pipecat's FastAPIWebsocketClient decides bytes-vs-text ONCE, from
    `serializer.type`, and uses it for both directions — so audio and
    control JSON share a single binary channel and are told apart by a
    1-byte type prefix:

        0x01 + int16-LE mono PCM
        0x02 + UTF-8 JSON control message

    Without a serializer at all, pipecat 0.0.89 silently drops every
    inbound message and every outbound frame; this class existing is
    what makes the loop function.
    """

    AUDIO = 0x01
    CONTROL = 0x02

    def __init__(
        self,
        client_sample_rate: int = 48_000,
        pipeline_sample_rate: int = 16_000,
    ) -> None:
        self._client_rate = client_sample_rate
        self._pipeline_rate = pipeline_sample_rate

    @property
    def type(self) -> FrameSerializerType:
        return FrameSerializerType.BINARY

    async def serialize(self, frame: Frame) -> str | bytes | None:
        if isinstance(frame, OutputAudioRawFrame):
            return bytes([self.AUDIO]) + frame.audio
        if isinstance(frame, (OutputTransportMessageFrame, OutputTransportMessageUrgentFrame)):
            return bytes([self.CONTROL]) + json.dumps(frame.message).encode("utf-8")
        # Everything else (control/system frames pipecat pushes at the
        # transport) simply isn't part of the browser contract.
        return None

    async def deserialize(self, data: str | bytes) -> Frame | None:
        if isinstance(data, str) or len(data) < 2:
            return None
        kind = data[0]
        payload = bytes(data[1:])
        if kind == self.AUDIO:
            audio = resample_pcm16(payload, self._client_rate, self._pipeline_rate)
            if not audio:
                return None
            return InputAudioRawFrame(
                audio=audio, sample_rate=self._pipeline_rate, num_channels=1
            )
        if kind == self.CONTROL:
            try:
                message = json.loads(payload.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                logger.warning("voice: undecodable control message dropped")
                return None
            return InputTransportMessageFrame(message=message)
        logger.warning(f"voice: unknown wire prefix {kind:#04x}")
        return None
```

- [ ] **Step 8: Emit a real output frame from the TTS stage**

In `CosyVoiceTTSProcessor._synthesize`, replace:

```python
            await self.push_frame(
                AudioRawFrame(audio=chunk, sample_rate=self.OUTPUT_RATE, num_channels=1),
                direction,
            )
```

with:

```python
            # TTSAudioRawFrame (an OutputAudioRawFrame), not bare
            # AudioRawFrame: the latter is a dataclass mixin, NOT a Frame,
            # and base_output dispatches audio on isinstance(frame,
            # OutputAudioRawFrame) — a bare AudioRawFrame never reaches
            # the socket.
            await self.push_frame(
                TTSAudioRawFrame(audio=chunk, sample_rate=self.OUTPUT_RATE, num_channels=1),
                direction,
            )
```

- [ ] **Step 9: Rebuild the transport params and drop the dead stage**

In `build_pipeline`, replace the lazy-import block and everything after it
(from `from pipecat.audio.vad.silero import SileroVADAnalyzer` to the end of
the function) with:

```python
    from pipecat.audio.vad.silero import SileroVADAnalyzer
    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.pipeline.task import PipelineTask
    from pipecat.transports.websocket.fastapi import (
        FastAPIWebsocketParams,
        FastAPIWebsocketTransport,
    )

    if barge_in is None:
        barge_in = asyncio.Event()

    transport = FastAPIWebsocketTransport(
        websocket,
        FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            add_wav_header=False,
            vad_analyzer=SileroVADAnalyzer(),
            # Without this the transport drops every frame in both
            # directions (fastapi.py:283,459).
            serializer=SamanthaWireSerializer(),
        ),
    )

    pipeline = Pipeline(
        [
            transport.input(),
            WhisperSTTProcessor(),
            SamanthaLLMProcessor(websocket=websocket, mem=mem, user_id=user_id),
            CosyVoiceTTSProcessor(barge_in=barge_in),
            transport.output(),
        ]
    )

    return PipelineTask(pipeline)
```

Two deprecated params are gone deliberately: `vad_enabled=True` (base_input.py:90-99
warns and just sets `audio_in_enabled`, which we set explicitly) and
`vad_audio_passthrough=False` (base_input.py:101-110 warns and forces
passthrough **on** regardless — see Task 15). `Resample48kTo16kProcessor` is
gone from the pipeline because resampling now happens in the serializer.

- [ ] **Step 10: Run the suite, format, commit**

```bash
cd backend && pytest tests/ -v && ruff format . && ruff check .
git add backend/samantha/voice_pipeline.py backend/tests/test_voice_pipeline.py
git commit -m "fix(voice): add wire serializer, real output frames, 16 kHz boundary resampling"
```

---

### Task 15: Transcribe once per utterance, not once per 20 ms frame

**Bug:** `voice_pipeline.py:162-170` runs a full beam-size-5 Whisper
transcription on **every** `AudioRawFrame` at 16 kHz. Once Task 14 makes
audio actually arrive, that is one GPU transcription per ~20 ms chunk of
input — dozens per second, each on a fragment far too short to mean
anything, and each non-empty result emitting a `UserTranscriptFrame` that
triggers a complete LLM + TTS turn.

The obvious mitigation is not available: `vad_audio_passthrough=False` is
deprecated and **ignored** — `base_input.py:101-110` warns and sets
`audio_in_passthrough = True` unconditionally ("audio passthrough is now
always enabled"). So audio always flows downstream and the aggregation must
live in our processor.

The VAD gives us the brackets: `base_input._handle_user_interruption`
(lines 329-361) pushes `UserStartedSpeakingFrame` and
`UserStoppedSpeakingFrame` downstream on every SPEAKING↔QUIET transition.
Buffer between them, transcribe once on stop.

**Files:**
- Modify: `backend/samantha/voice_pipeline.py` (`WhisperSTTProcessor`)
- Modify: `backend/tests/test_voice_pipeline.py`

- [ ] **Step 1: Write the failing tests**

Replace `test_whisper_stt_emits_transcript_frame` in
`backend/tests/test_voice_pipeline.py` with:

```python
def test_whisper_stt_transcribes_once_per_utterance():
    """Audio between UserStartedSpeaking and UserStoppedSpeaking is ONE
    transcription — not one per 20 ms frame.

    We inject the fake model directly onto _model (bypassing the loader
    and the faster_whisper import) to avoid pulling in ctranslate2 →
    torch, which crashes on numpy ABI mismatch in the test process.
    """
    from pipecat.frames.frames import (
        InputAudioRawFrame,
        UserStartedSpeakingFrame,
        UserStoppedSpeakingFrame,
    )
    from pipecat.processors.frame_processor import FrameDirection

    from samantha.voice_pipeline import UserTranscriptFrame, WhisperSTTProcessor

    fake_segment = MagicMock()
    fake_segment.text = " hola mundo"
    fake_model = MagicMock()
    fake_model.transcribe.return_value = ([fake_segment], MagicMock())

    proc = WhisperSTTProcessor(model_size="tiny", language="es", device="cpu", compute_type="int8")
    proc._model = fake_model

    received = []

    async def run():
        async def fake_push(f, d):
            received.append(f)

        proc.push_frame = fake_push
        await proc.process_frame(UserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        # 25 × 20 ms of speech = 500 ms, comfortably over the minimum.
        for _ in range(25):
            await proc.process_frame(
                InputAudioRawFrame(
                    audio=make_silence(16_000, 0.02), sample_rate=16_000, num_channels=1
                ),
                FrameDirection.DOWNSTREAM,
            )
        await proc.process_frame(UserStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)

    _run(run())

    assert fake_model.transcribe.call_count == 1
    transcripts = [f for f in received if isinstance(f, UserTranscriptFrame)]
    assert [f.text for f in transcripts] == ["hola mundo"]
    # The VAD brackets must survive: CosyVoiceTTSProcessor needs
    # UserStartedSpeakingFrame downstream for barge-in.
    assert any(isinstance(f, UserStartedSpeakingFrame) for f in received)
    assert any(isinstance(f, UserStoppedSpeakingFrame) for f in received)


def test_whisper_stt_ignores_too_short_utterance():
    """A blip of VAD noise must not cost a GPU transcription (or a turn)."""
    from pipecat.frames.frames import (
        InputAudioRawFrame,
        UserStartedSpeakingFrame,
        UserStoppedSpeakingFrame,
    )
    from pipecat.processors.frame_processor import FrameDirection

    from samantha.voice_pipeline import UserTranscriptFrame, WhisperSTTProcessor

    fake_model = MagicMock()
    proc = WhisperSTTProcessor(model_size="tiny", language="es", device="cpu", compute_type="int8")
    proc._model = fake_model

    received = []

    async def run():
        async def fake_push(f, d):
            received.append(f)

        proc.push_frame = fake_push
        await proc.process_frame(UserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        await proc.process_frame(
            InputAudioRawFrame(
                audio=make_silence(16_000, 0.05), sample_rate=16_000, num_channels=1
            ),
            FrameDirection.DOWNSTREAM,
        )
        await proc.process_frame(UserStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)

    _run(run())

    assert fake_model.transcribe.call_count == 0
    assert not [f for f in received if isinstance(f, UserTranscriptFrame)]


def test_whisper_stt_ignores_audio_outside_an_utterance():
    """Frames arriving while the VAD says QUIET are dropped, not buffered."""
    from pipecat.frames.frames import InputAudioRawFrame, UserStoppedSpeakingFrame
    from pipecat.processors.frame_processor import FrameDirection

    from samantha.voice_pipeline import UserTranscriptFrame, WhisperSTTProcessor

    fake_model = MagicMock()
    proc = WhisperSTTProcessor(model_size="tiny", language="es", device="cpu", compute_type="int8")
    proc._model = fake_model

    received = []

    async def run():
        async def fake_push(f, d):
            received.append(f)

        proc.push_frame = fake_push
        for _ in range(25):
            await proc.process_frame(
                InputAudioRawFrame(
                    audio=make_silence(16_000, 0.02), sample_rate=16_000, num_channels=1
                ),
                FrameDirection.DOWNSTREAM,
            )
        await proc.process_frame(UserStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)

    _run(run())

    assert fake_model.transcribe.call_count == 0
    assert not [f for f in received if isinstance(f, UserTranscriptFrame)]
```

- [ ] **Step 2: Run them — expect FAIL**

Run: `cd backend && pytest tests/test_voice_pipeline.py -k whisper -v`
Expected: `test_whisper_stt_transcribes_once_per_utterance` fails with
`transcribe.call_count == 25` (one per frame), and the two "ignores" tests
fail the same way — the current code transcribes every 16 kHz audio frame
regardless of VAD state.

- [ ] **Step 3: Swap the frame imports**

`AudioRawFrame` (the non-Frame mixin) stops being referenced anywhere after
this task, and the two VAD frames start being. In
`backend/samantha/voice_pipeline.py`, replace:

```python
from pipecat.frames.frames import (
    AudioRawFrame,
    Frame,
    InputAudioRawFrame,
```

with:

```python
from pipecat.frames.frames import (
    Frame,
    InputAudioRawFrame,
```

and replace:

```python
    TextFrame,
    TTSAudioRawFrame,
)
```

with:

```python
    TextFrame,
    TTSAudioRawFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)
```

(`ruff check` enforces this both ways — an unused import fails F401, a
missing one fails F821.)

- [ ] **Step 4: Aggregate between the VAD brackets**

In `backend/samantha/voice_pipeline.py`, replace the `WhisperSTTProcessor`
docstring and `__init__` body's last line plus its `process_frame` — that is,
replace:

```python
class WhisperSTTProcessor(FrameProcessor):
    """Transcribe AudioRawFrame (16 kHz int16 mono) via faster-whisper.

    Lazy-loads the model on first frame so the process starts quickly.
    Emits UserTranscriptFrame when transcription is non-empty.
    """
```

with:

```python
class WhisperSTTProcessor(FrameProcessor):
    """Transcribe one user utterance at a time via faster-whisper.

    Audio is buffered between the VAD's UserStartedSpeakingFrame and
    UserStoppedSpeakingFrame and transcribed once, on stop. Transcribing
    per input frame instead would mean dozens of beam-size-5 GPU runs per
    second over meaningless ~20 ms fragments, each firing a full LLM+TTS
    turn — and pipecat always passes input audio downstream
    (`vad_audio_passthrough` is deprecated and ignored), so this
    processor has to do the gating itself.

    Emits UserTranscriptFrame when transcription is non-empty; forwards
    the VAD frames downstream (CosyVoiceTTSProcessor needs
    UserStartedSpeakingFrame for barge-in).
    """

    # 16 kHz × 2 bytes × 0.3 s. Shorter than this is VAD noise, not
    # speech, and Whisper on it produces confident garbage.
    MIN_UTTERANCE_BYTES = 9_600
```

and replace the whole `process_frame` method:

```python
    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, AudioRawFrame) and frame.sample_rate == 16_000:
            text = await asyncio.to_thread(self._transcribe, frame.audio)
            if text:
                logger.info(f"stt: {text!r}")
                await self.push_frame(UserTranscriptFrame(text=text), direction)
        else:
            await self.push_frame(frame, direction)
```

with:

```python
    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        if isinstance(frame, UserStartedSpeakingFrame):
            self._utterance.clear()
            self._capturing = True
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, UserStoppedSpeakingFrame):
            audio = b"".join(self._utterance)
            self._utterance.clear()
            self._capturing = False
            await self.push_frame(frame, direction)
            if len(audio) >= self.MIN_UTTERANCE_BYTES:
                text = await asyncio.to_thread(self._transcribe, audio)
                if text:
                    logger.info(f"stt: {text!r}")
                    await self.push_frame(UserTranscriptFrame(text=text), direction)
            return

        if isinstance(frame, InputAudioRawFrame):
            # Consumed here: raw PCM has no consumer downstream, and
            # audio outside an utterance is not ours to keep.
            if self._capturing:
                self._utterance.append(frame.audio)
            return

        await self.push_frame(frame, direction)
```

Finally, in `__init__`, replace:

```python
        self._model = None  # lazy
```

with:

```python
        self._model = None  # lazy
        self._utterance: list[bytes] = []
        self._capturing = False
```

- [ ] **Step 5: Run the suite, format, commit**

```bash
cd backend && pytest tests/ -v && ruff format . && ruff check .
git add backend/samantha/voice_pipeline.py backend/tests/test_voice_pipeline.py
git commit -m "fix(voice): transcribe once per VAD-bracketed utterance"
```

---

### Task 16: Make barge-in actually fire, and configure the pipeline explicitly

**Bug:** `CosyVoiceTTSProcessor` checks `self._barge_in` before each audio
chunk (`voice_pipeline.py:267`), but **nothing ever sets it** — no VAD-frame
consumer, no `/voice` handler, no client message path. The headline Phase 11
feature is inert. Separately, `PipelineTask(pipeline)` at line 327 is built
with no `PipelineParams`, so sample rates and interruption behaviour are all
implicit defaults.

Design choice: consume `UserStartedSpeakingFrame` (which base_input pushes
downstream on every QUIET→SPEAKING transition, verified at
`base_input.py:335-336`) and set the event **only while audio is actually
being produced**. pipecat's own interruption machinery
(`allow_interruptions=True` → `InterruptionFrame`) is enabled too, but it
cancels *frame processing*; it cannot reach inside our `async for` over the
CosyVoice HTTP stream, so the explicit event is what stops synthesis. The
external `barge_in` Event stays in the constructor so the `/voice` endpoint
can still trigger it out of band.

**Files:**
- Modify: `backend/samantha/voice_pipeline.py` (`CosyVoiceTTSProcessor`, `build_pipeline`)
- Modify: `backend/tests/test_voice_pipeline.py`

- [ ] **Step 1: Write the failing tests**

Replace `test_cosyvoice_tts_stops_on_barge_in` (as edited in Task 14) with:

```python
def test_cosyvoice_tts_stops_mid_stream_on_barge_in(monkeypatch):
    """The event set DURING synthesis stops it at the next chunk."""
    from pipecat.frames.frames import TextFrame, TTSAudioRawFrame
    from pipecat.processors.frame_processor import FrameDirection

    from samantha.voice_pipeline import CosyVoiceTTSProcessor, LLMDoneFrame

    barge_in = asyncio.Event()

    async def fake_tts_stream(text: str) -> AsyncIterator:
        yield b"\x00" * 4096, "cosyvoice"
        barge_in.set()  # the user starts talking over her
        yield b"\x00" * 4096, "cosyvoice"
        yield b"\x00" * 4096, "cosyvoice"

    monkeypatch.setattr("samantha.voice_pipeline._tts_stream", fake_tts_stream)

    proc = CosyVoiceTTSProcessor(barge_in=barge_in)
    pushed = []

    async def run():
        async def fake_push(f, d):
            pushed.append(f)

        proc.push_frame = fake_push
        await proc.process_frame(TextFrame(text="hola mundo"), FrameDirection.DOWNSTREAM)
        await proc.process_frame(LLMDoneFrame(), FrameDirection.DOWNSTREAM)

    _run(run())

    assert len([f for f in pushed if isinstance(f, TTSAudioRawFrame)]) == 1


def test_user_started_speaking_sets_barge_in_only_while_speaking():
    """The trigger that was missing entirely: a VAD start frame arms the
    abort — but only if Samantha is mid-utterance, otherwise the flag
    would linger and kill the FIRST chunk of the next reply."""
    from pipecat.frames.frames import UserStartedSpeakingFrame
    from pipecat.processors.frame_processor import FrameDirection

    from samantha.voice_pipeline import CosyVoiceTTSProcessor

    barge_in = asyncio.Event()
    proc = CosyVoiceTTSProcessor(barge_in=barge_in)
    pushed = []

    async def run():
        async def fake_push(f, d):
            pushed.append(f)

        proc.push_frame = fake_push

        proc._speaking = False
        await proc.process_frame(UserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        assert not barge_in.is_set()

        proc._speaking = True
        await proc.process_frame(UserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        assert barge_in.is_set()

    _run(run())

    # The frame must still travel downstream for the transport.
    assert len([f for f in pushed if isinstance(f, UserStartedSpeakingFrame)]) == 2


def test_build_pipeline_sets_explicit_pipeline_params(monkeypatch):
    """Sample rates must be stated, not inherited: 16 kHz in (Silero
    raises otherwise) and 24 kHz out (CosyVoice's native rate)."""
    import pipecat.audio.vad.silero as silero_mod
    import pipecat.pipeline.task as task_mod
    import pipecat.transports.websocket.fastapi as fastapi_mod
    from pipecat.processors.frame_processor import FrameProcessor

    from samantha.voice_pipeline import build_pipeline

    monkeypatch.setattr(silero_mod, "SileroVADAnalyzer", MagicMock())

    class SpyTransport:
        def __init__(self, websocket, params, **kwargs):
            pass

        def input(self):
            return FrameProcessor()

        def output(self):
            return FrameProcessor()

    monkeypatch.setattr(fastapi_mod, "FastAPIWebsocketTransport", SpyTransport)

    captured = {}
    real_task_cls = task_mod.PipelineTask

    def spy_task(pipeline, *args, **kwargs):
        captured["params"] = kwargs.get("params")
        return real_task_cls(pipeline, *args, **kwargs)

    monkeypatch.setattr(task_mod, "PipelineTask", spy_task)

    build_pipeline(websocket=MagicMock(), mem=None)

    params = captured["params"]
    assert params is not None
    assert params.audio_in_sample_rate == 16_000
    assert params.audio_out_sample_rate == 24_000
    assert params.allow_interruptions is True
```

- [ ] **Step 2: Run them — expect FAIL**

Run: `cd backend && pytest tests/test_voice_pipeline.py -k "barge_in or pipeline_params" -v`
Expected: the mid-stream test fails (3 audio frames — nothing aborts, since
the current check only sees a pre-set event that is never cleared/re-set),
the `UserStartedSpeakingFrame` test fails with `AttributeError: _speaking`,
and the params test fails on `params is None`.

- [ ] **Step 3: Consume the VAD start frame and track speaking state**

In `CosyVoiceTTSProcessor`, replace the class docstring:

```python
    """Accumulate TextFrames, synthesize on LLMDoneFrame, emit AudioRawFrame.

    A barge_in asyncio.Event (shared with the /voice endpoint) can abort
    synthesis mid-stream: checked before each chunk, cleared on fire.
    """
```

with:

```python
    """Accumulate TextFrames, synthesize on LLMDoneFrame, emit audio.

    Barge-in: UserStartedSpeakingFrame (pushed downstream by the VAD in
    base_input) sets the shared `barge_in` Event while synthesis is in
    flight, and the chunk loop stops at the next boundary. pipecat's own
    interruption machinery cancels frame processing but cannot reach
    inside our `async for` over the CosyVoice HTTP stream, so this
    explicit signal is what actually silences her. The Event is a
    constructor arg so the /voice endpoint can also trigger it.
    """
```

Replace `__init__`'s body:

```python
        super().__init__()
        self._barge_in = barge_in
        self._buffer: list[str] = []
```

with:

```python
        super().__init__()
        self._barge_in = barge_in
        self._buffer: list[str] = []
        self._speaking = False
```

Replace `process_frame`:

```python
    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, TextFrame):
            self._buffer.append(frame.text)
        elif isinstance(frame, LLMDoneFrame):
```

with:

```python
    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, UserStartedSpeakingFrame):
            # Only while she is actually mid-utterance: setting it when
            # idle would leave the flag armed and kill the first chunk
            # of the next reply.
            if self._speaking:
                logger.info("tts: user spoke over Samantha — arming barge-in")
                self._barge_in.set()
            await self.push_frame(frame, direction)
        elif isinstance(frame, TextFrame):
            self._buffer.append(frame.text)
        elif isinstance(frame, LLMDoneFrame):
```

And replace `_synthesize`:

```python
    async def _synthesize(self, text: str, direction: FrameDirection) -> None:
        async for chunk, _ in _tts_stream(text):
            if self._barge_in.is_set():
                self._barge_in.clear()
                logger.info("tts: barge-in — synthesis stopped")
                return
```

with:

```python
    async def _synthesize(self, text: str, direction: FrameDirection) -> None:
        # Fresh turn: drop a stale signal (the user may have spoken while
        # the LLM was still thinking, or /voice set it out of band) so it
        # cannot kill this reply's opening chunk.
        self._barge_in.clear()
        self._speaking = True
        try:
            await self._stream_chunks(text, direction)
        finally:
            self._speaking = False

    async def _stream_chunks(self, text: str, direction: FrameDirection) -> None:
        async for chunk, _ in _tts_stream(text):
            if self._barge_in.is_set():
                self._barge_in.clear()
                logger.info("tts: barge-in — synthesis stopped")
                return
```

- [ ] **Step 4: Pass explicit `PipelineParams`**

In `build_pipeline`, add `PipelineParams` to the lazy import — replace:

```python
    from pipecat.pipeline.task import PipelineTask
```

with:

```python
    from pipecat.pipeline.task import PipelineParams, PipelineTask
```

and replace the final line:

```python
    return PipelineTask(pipeline)
```

with:

```python
    return PipelineTask(
        pipeline,
        params=PipelineParams(
            # 16 kHz in is mandatory, not a preference: base_input hands
            # this number to SileroVADAnalyzer.set_sample_rate(), which
            # raises for anything but 8/16 kHz. 24 kHz out is CosyVoice's
            # native rate, so base_output has nothing to resample.
            audio_in_sample_rate=16_000,
            audio_out_sample_rate=24_000,
            allow_interruptions=True,
        ),
    )
```

- [ ] **Step 5: Run the suite, format, commit**

```bash
cd backend && pytest tests/ -v && ruff format . && ruff check .
git add backend/samantha/voice_pipeline.py backend/tests/test_voice_pipeline.py
git commit -m "fix(voice): wire barge-in to the VAD and state pipeline params explicitly"
```

---

### Task 17: One writer on the socket — control JSON goes through the transport

**Bug:** `SamanthaLLMProcessor._handle` (`voice_pipeline.py:206,222`) calls
`self._ws.send_text(...)` directly, on the very socket the transport's own
paced output task writes binary audio to, from a different task, with no
synchronization. Two writers on one Starlette WebSocket is a race — and
after Task 14 it is also a protocol violation: the client is in binary mode
(`FastAPIWebsocketClient.__init__` picks `send_bytes` when
`serializer.type is BINARY`), so a stray `send_text` frame is something the
browser's binary reader is not expecting at all.

Fix: push `OutputTransportMessageUrgentFrame` downstream. `base_output`
handles it out-of-band (line 311) and the serializer (Task 14) encodes it as
a `0x02` control message. The transport's output task becomes the single
writer, and `SamanthaLLMProcessor` no longer needs the websocket at all.

**Files:**
- Modify: `backend/samantha/voice_pipeline.py` (`SamanthaLLMProcessor`, `build_pipeline`)
- Modify: `backend/tests/test_voice_pipeline.py`

- [ ] **Step 1: Write the failing test**

Replace `test_samantha_llm_emits_text_frames` in
`backend/tests/test_voice_pipeline.py` with:

```python
def test_samantha_llm_emits_text_frames_and_control_frames(monkeypatch):
    """UserTranscriptFrame → TextFrames + LLMDoneFrame, and the transcript
    and token notifications travel as transport-message FRAMES.

    They must not be written to the socket directly: the transport's own
    output task is the single writer (and it is in binary mode).
    """
    from pipecat.frames.frames import OutputTransportMessageUrgentFrame, TextFrame
    from pipecat.processors.frame_processor import FrameDirection

    from samantha.voice_pipeline import LLMDoneFrame, SamanthaLLMProcessor, UserTranscriptFrame

    async def fake_stream_reply(msg, *, facts=None, recall=None, short_term=None, user_id="primary"):
        for tok in ["hola", " Horelvis"]:
            yield tok

    async def fake_gather(mem, message, user_id):
        return [], [], []

    monkeypatch.setattr("samantha.voice_pipeline.gather_context", fake_gather)
    monkeypatch.setattr("samantha.voice_pipeline._stream_reply_impl", fake_stream_reply)

    proc = SamanthaLLMProcessor(mem=None, user_id="primary")

    pushed = []

    async def run():
        async def fake_push(f, d):
            pushed.append(f)

        proc.push_frame = fake_push
        await proc.process_frame(UserTranscriptFrame(text="hola"), FrameDirection.DOWNSTREAM)

    _run(run())

    text_frames = [f for f in pushed if isinstance(f, TextFrame)]
    assert [f.text for f in text_frames] == ["hola", " Horelvis"]
    assert any(isinstance(f, LLMDoneFrame) for f in pushed)

    messages = [
        f.message for f in pushed if isinstance(f, OutputTransportMessageUrgentFrame)
    ]
    assert {"type": "transcript", "text": "hola"} in messages
    assert {"type": "token", "text": "hola"} in messages
    assert {"type": "token", "text": " Horelvis"} in messages
```

- [ ] **Step 2: Run it — expect FAIL**

Run: `cd backend && pytest tests/test_voice_pipeline.py -k samantha_llm -v`
Expected: FAIL with `TypeError: __init__() missing 1 required positional
argument: 'websocket'`.

- [ ] **Step 3: Drop the websocket and push control frames**

In `backend/samantha/voice_pipeline.py`, replace the `SamanthaLLMProcessor`
docstring and `__init__`:

```python
class SamanthaLLMProcessor(FrameProcessor):
    """On UserTranscriptFrame: gather context, stream reply tokens.

    Side-effects per turn:
      - Sends {"type":"transcript","text":"..."} JSON to browser.
      - Sends {"type":"token","text":"..."} JSON per token to browser.
      - Persists the full Samantha reply in memory.
    """

    def __init__(
        self,
        websocket: "WebSocket",
        mem: "Memory | None",
        user_id: str = "primary",
    ) -> None:
        super().__init__()
        self._ws = websocket
        self._mem = mem
        self._user_id = user_id
```

with:

```python
class SamanthaLLMProcessor(FrameProcessor):
    """On UserTranscriptFrame: gather context, stream reply tokens.

    Side-effects per turn:
      - Emits {"type":"transcript","text":"..."} as a transport message.
      - Emits {"type":"token","text":"..."} per token, likewise.
      - Persists the full Samantha reply in memory.

    Control messages travel as OutputTransportMessageUrgentFrame rather
    than a direct websocket.send_text: the transport's output task is the
    only writer on that socket (and it is in binary mode — see
    SamanthaWireSerializer), so a second writer would be both a race and
    a protocol violation.
    """

    def __init__(
        self,
        mem: "Memory | None",
        user_id: str = "primary",
    ) -> None:
        super().__init__()
        self._mem = mem
        self._user_id = user_id

    async def _notify(self, message: dict) -> None:
        await self.push_frame(
            OutputTransportMessageUrgentFrame(message=message), FrameDirection.DOWNSTREAM
        )
```

Then in `_handle`, replace:

```python
        await self._ws.send_text(json.dumps({"type": "transcript", "text": text}))
```

with:

```python
        await self._notify({"type": "transcript", "text": text})
```

and replace:

```python
            await self._ws.send_text(json.dumps({"type": "token", "text": token}))
```

with:

```python
            await self._notify({"type": "token", "text": token})
```

- [ ] **Step 4: Update the call site**

In `build_pipeline`, replace:

```python
            SamanthaLLMProcessor(websocket=websocket, mem=mem, user_id=user_id),
```

with:

```python
            SamanthaLLMProcessor(mem=mem, user_id=user_id),
```

(`build_pipeline` keeps its `websocket` parameter — the transport still
needs it.)

- [ ] **Step 5: Drop the now-unused test imports**

The replaced test was the only user of `AsyncMock` (it stubbed
`ws.send_text`) and of the module-level `json` (it decoded the socket
writes) in `backend/tests/test_voice_pipeline.py`. `ruff check` fails on
both (F401), so replace:

```python
import asyncio
import json
from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock
```

with:

```python
import asyncio
from typing import AsyncIterator
from unittest.mock import MagicMock
```

(In `voice_pipeline.py` itself `json` stays — `SamanthaWireSerializer` uses
it.)

- [ ] **Step 6: Run the suite, format, commit**

```bash
cd backend && pytest tests/ -v && ruff format . && ruff check .
git add backend/samantha/voice_pipeline.py backend/tests/test_voice_pipeline.py
git commit -m "fix(voice): route control JSON through the transport, single socket writer"
```

---

### Task 18: Speak at sentence boundaries instead of waiting for the whole reply

**Bug:** `CosyVoiceTTSProcessor` buffers every `TextFrame` and only
synthesizes on `LLMDoneFrame` (`voice_pipeline.py:257-261`), so
time-to-first-audio is *full LLM generation + full synthesis of the entire
paragraph*. That is the opposite of the project's "latency over correctness"
principle (CLAUDE.md §1.4) — and it is the whole reason to run the loop
server-side.

The constraint that makes naive chunking dangerous: CosyVoice 3 zero-shot
conditions on the reference `prompt_text`, and hifigan produces no audio (a
200 with an empty body — `tts.py` raises `RuntimeError` naming exactly this)
when `tts_text` is much shorter than `prompt_text`. So flush only when the
buffered text is comfortably long AND ends a sentence; hold short fragments
for the next flush; and let a failed synthesis log rather than kill the turn.

**Files:**
- Modify: `backend/samantha/voice_pipeline.py` (`CosyVoiceTTSProcessor`)
- Modify: `backend/tests/test_voice_pipeline.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_voice_pipeline.py`:

```python
def test_cosyvoice_flushes_at_sentence_boundaries(monkeypatch):
    """A long reply is spoken in sentence-sized pieces, so audio starts
    before the LLM has finished — not after."""
    from pipecat.frames.frames import TextFrame
    from pipecat.processors.frame_processor import FrameDirection

    from samantha.voice_pipeline import CosyVoiceTTSProcessor, LLMDoneFrame

    synthesized: list[str] = []

    async def fake_tts_stream(text: str) -> AsyncIterator:
        synthesized.append(text)
        yield b"\x00" * 4096, "cosyvoice"

    monkeypatch.setattr("samantha.voice_pipeline._tts_stream", fake_tts_stream)

    proc = CosyVoiceTTSProcessor(barge_in=asyncio.Event())

    # Two sentences, each comfortably over MIN_FLUSH_CHARS.
    first = (
        "Hoy he estado pensando en lo que me contaste sobre tu hermano y me "
        "he quedado con una imagen muy concreta. "
    )
    second = (
        "No sé si es la que tú tenías en la cabeza, pero se me ha quedado "
        "dando vueltas toda la tarde."
    )

    async def run():
        async def fake_push(f, d):
            pass

        proc.push_frame = fake_push
        for token in (first + second).split(" "):
            await proc.process_frame(TextFrame(text=token + " "), FrameDirection.DOWNSTREAM)
        await proc.process_frame(LLMDoneFrame(), FrameDirection.DOWNSTREAM)

    _run(run())

    assert len(synthesized) >= 2, synthesized
    assert synthesized[0].endswith("."), synthesized[0]
    # Nothing is lost or duplicated between the pieces.
    assert "".join(s + " " for s in synthesized).split() == (first + second).split()


def test_cosyvoice_holds_short_fragments_for_the_final_flush(monkeypatch):
    """Short sentences must not be synthesized alone: CosyVoice's hifigan
    returns no audio when tts_text is much shorter than the reference
    prompt_text."""
    from pipecat.frames.frames import TextFrame
    from pipecat.processors.frame_processor import FrameDirection

    from samantha.voice_pipeline import CosyVoiceTTSProcessor, LLMDoneFrame

    synthesized: list[str] = []

    async def fake_tts_stream(text: str) -> AsyncIterator:
        synthesized.append(text)
        yield b"\x00" * 4096, "cosyvoice"

    monkeypatch.setattr("samantha.voice_pipeline._tts_stream", fake_tts_stream)

    proc = CosyVoiceTTSProcessor(barge_in=asyncio.Event())

    async def run():
        async def fake_push(f, d):
            pass

        proc.push_frame = fake_push
        for token in ["Sí.", " Claro.", " Vale."]:
            await proc.process_frame(TextFrame(text=token), FrameDirection.DOWNSTREAM)
        await proc.process_frame(LLMDoneFrame(), FrameDirection.DOWNSTREAM)

    _run(run())

    assert synthesized == ["Sí. Claro. Vale."]


def test_cosyvoice_synthesis_failure_does_not_kill_the_turn(monkeypatch):
    """A CosyVoice error (e.g. the known short-text case) is logged, and
    the pipeline keeps running."""
    from pipecat.frames.frames import TextFrame
    from pipecat.processors.frame_processor import FrameDirection

    from samantha.voice_pipeline import CosyVoiceTTSProcessor, LLMDoneFrame

    async def failing_tts_stream(text: str) -> AsyncIterator:
        raise RuntimeError("cosyvoice returned 200 but no audio")
        yield  # pragma: no cover — makes this an async generator

    monkeypatch.setattr("samantha.voice_pipeline._tts_stream", failing_tts_stream)

    proc = CosyVoiceTTSProcessor(barge_in=asyncio.Event())

    async def run():
        async def fake_push(f, d):
            pass

        proc.push_frame = fake_push
        await proc.process_frame(TextFrame(text="hola"), FrameDirection.DOWNSTREAM)
        await proc.process_frame(LLMDoneFrame(), FrameDirection.DOWNSTREAM)

    _run(run())  # must not raise
    assert proc._speaking is False
```

- [ ] **Step 2: Run them — expect FAIL**

Run: `cd backend && pytest tests/test_voice_pipeline.py -k "flushes or short_fragments or synthesis_failure" -v`
Expected: the boundary test fails with one single synthesis of the whole
reply; the failure test fails with `RuntimeError` propagating out of
`process_frame`. (`test_cosyvoice_holds_short_fragments_for_the_final_flush`
passes already — it locks in behaviour that must survive the change.)

- [ ] **Step 3: Add `re` to the imports**

In `backend/samantha/voice_pipeline.py`, replace:

```python
import asyncio
import json
```

with:

```python
import asyncio
import json
import re
```

- [ ] **Step 4: Flush at sentence boundaries**

In `CosyVoiceTTSProcessor`, replace:

```python
    OUTPUT_RATE = 24_000
```

with:

```python
    OUTPUT_RATE = 24_000

    # Flush only when a sentence has ended AND the piece is long enough.
    # CosyVoice 3 zero-shot conditions on the reference prompt_text and
    # its hifigan returns no audio when tts_text is much shorter (tts.py
    # raises RuntimeError naming this case), so short fragments ride
    # along with the next one instead of being spoken alone.
    MIN_FLUSH_CHARS = 80
    _SENTENCE_END = re.compile(r"[.!?…]['\"»)\]]*\s")
```

Replace the `__init__` line added in Task 16:

```python
        self._buffer: list[str] = []
        self._speaking = False
```

with:

```python
        self._pending = ""
        self._speaking = False
```

Replace the `TextFrame`/`LLMDoneFrame` branches of `process_frame`:

```python
        elif isinstance(frame, TextFrame):
            self._buffer.append(frame.text)
        elif isinstance(frame, LLMDoneFrame):
            text = "".join(self._buffer).strip()
            self._buffer.clear()
            if text:
                await self._synthesize(text, direction)
```

with:

```python
        elif isinstance(frame, TextFrame):
            self._pending += frame.text
            ready = self._take_flushable()
            if ready:
                await self._synthesize(ready, direction)
        elif isinstance(frame, LLMDoneFrame):
            tail = self._pending.strip()
            self._pending = ""
            if tail:
                # The remainder goes out even if it is short — a one-word
                # reply still has to be spoken, and tts.py reports the
                # hifigan case as an error we survive (see _synthesize).
                await self._synthesize(tail, direction)
```

Add `_take_flushable` directly above `_synthesize`:

```python
    def _take_flushable(self) -> str:
        """Pop a sentence-terminated prefix of at least MIN_FLUSH_CHARS.

        Returns "" while the buffer is too short or has no sentence end
        past the threshold — the text stays pending for the next token.
        """
        if len(self._pending) < self.MIN_FLUSH_CHARS:
            return ""
        for match in self._SENTENCE_END.finditer(self._pending):
            if match.end() >= self.MIN_FLUSH_CHARS:
                chunk = self._pending[: match.end()].strip()
                self._pending = self._pending[match.end() :]
                return chunk
        return ""
```

- [ ] **Step 5: Survive a synthesis failure**

Replace `_synthesize`'s body (as left by Task 16):

```python
        self._barge_in.clear()
        self._speaking = True
        try:
            await self._stream_chunks(text, direction)
        finally:
            self._speaking = False
```

with:

```python
        self._barge_in.clear()
        self._speaking = True
        try:
            await self._stream_chunks(text, direction)
        except Exception as e:
            # One failed piece (wedged GPU, or the known "tts_text much
            # shorter than prompt_text" hifigan case) must not tear down
            # the whole voice session.
            logger.error(f"tts: synthesis failed for {text[:40]!r}: {e}")
        finally:
            self._speaking = False
```

- [ ] **Step 6: Run the suite, format, commit**

```bash
cd backend && pytest tests/ -v && ruff format . && ruff check .
git add backend/samantha/voice_pipeline.py backend/tests/test_voice_pipeline.py
git commit -m "perf(voice): synthesize at sentence boundaries, survive TTS failures"
```

---

### Task 19: STT configuration, one shared model, and the remaining small defects

**Bug (four bundled):**
1. **Whisper is configured nowhere and reloaded per connection.**
   `WhisperSTTProcessor.__init__` hardcodes `device="cuda"` (raises on the
   dev Mac — ctranslate2 has no Metal backend) and none of
   model/device/compute_type is reachable through `config.py`, unlike every
   other subsystem. Worse, `build_pipeline` constructs a fresh processor per
   `/voice` client, so each reconnect lazy-loads multiple GB of weights
   again, mid-conversation, on the first utterance.
2. **`resample_pcm16` on an empty payload.** With `src.size == 0`,
   `dst_len = max(1, 0)` forces one output sample while `np.interp`'s `xp`
   is empty → `ValueError` kills the pipeline task. (Task 14 already wrote
   the guard; this step is its test, so the behaviour is locked in.)
3. ~~**Deprecated event-loop access in the tests.**~~ Already fixed in
   Task 14 Step 1 — it had to land before the file became tracked, because
   the helper made the whole suite fail in run order. Listed here only so
   the finding is not lost.
4. **`tests/conftest.py` does not pin STT env**, so a developer with
   `SAMANTHA_STT_DEVICE=cuda` exported would have the new config defaults
   leak into tests.

**Files:**
- Modify: `backend/samantha/config.py`
- Modify: `backend/samantha/voice_pipeline.py`
- Modify: `backend/tests/test_voice_pipeline.py`
- Test: `backend/tests/test_config.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_config.py` (match the file's existing import
style — it already imports `Config`):

```python
def test_config_exposes_stt_settings(monkeypatch):
    """The voice loop's Whisper must be configurable like every other
    subsystem — the dev Mac has no CUDA."""
    monkeypatch.setenv("SAMANTHA_STT_DEVICE", "cpu")
    monkeypatch.setenv("SAMANTHA_STT_COMPUTE_TYPE", "int8")
    monkeypatch.setenv("SAMANTHA_STT_MODEL", "tiny")

    cfg = Config.from_env()

    assert cfg.stt_device == "cpu"
    assert cfg.stt_compute_type == "int8"
    assert cfg.stt_model == "tiny"
    assert cfg.stt_language == "es"
```

Append to `backend/tests/test_voice_pipeline.py`:

```python
def test_resample_empty_payload_returns_empty():
    """np.interp with an empty xp raises — an empty frame must not kill
    the pipeline task."""
    from samantha.voice_pipeline import resample_pcm16

    assert resample_pcm16(b"", 48_000, 16_000) == b""


def test_whisper_processor_defaults_come_from_config(monkeypatch):
    from samantha import config as config_mod
    from samantha.voice_pipeline import WhisperSTTProcessor

    monkeypatch.setattr(config_mod.config, "stt_model", "tiny")
    monkeypatch.setattr(config_mod.config, "stt_device", "cpu")
    monkeypatch.setattr(config_mod.config, "stt_compute_type", "int8")

    proc = WhisperSTTProcessor()

    assert proc._model_size == "tiny"
    assert proc._device == "cpu"
    assert proc._compute_type == "int8"


def test_whisper_model_is_loaded_once_per_process(monkeypatch):
    """A fresh processor is built per /voice connection; loading GBs of
    weights on every reconnect is not acceptable on the kiosk."""
    import samantha.voice_pipeline as vp

    monkeypatch.setattr(vp, "_whisper_model", None)
    monkeypatch.setattr(vp, "_whisper_model_key", None)

    loads = {"n": 0}

    def fake_load(model_size, device, compute_type):
        loads["n"] += 1
        return MagicMock()

    monkeypatch.setattr(vp, "_load_whisper_model", fake_load)

    async def run():
        a = await vp.get_whisper_model("tiny", "cpu", "int8")
        b = await vp.get_whisper_model("tiny", "cpu", "int8")
        return a, b

    a, b = _run(run())

    assert a is b
    assert loads["n"] == 1
```

- [ ] **Step 2: Run them — expect FAIL**

Run: `cd backend && pytest tests/test_config.py tests/test_voice_pipeline.py -k "stt or whisper_model or whisper_processor or empty_payload" -v`
Expected: `AttributeError` on `cfg.stt_device` / `vp._load_whisper_model`;
the empty-payload test passes already (Task 14 wrote the guard) and locks it
in.

- [ ] **Step 3: Add the STT block to `config.py`**

In `backend/samantha/config.py`, after the CosyVoice block (directly above
`# === Logging ===`), add:

```python
    # === STT — faster-whisper (Phase 11 server-side voice loop only) ===
    # The text-chat path still uses the browser's Web Speech API
    # (CLAUDE.md §2.8); these settings apply to /voice.
    stt_model: str = "large-v3-turbo"
    stt_language: str = "es"
    # "cuda" on the GPU box. On the dev Mac use "cpu" + "int8":
    # ctranslate2 has no Metal backend, so "cuda" raises at load time.
    #   SAMANTHA_STT_DEVICE=cpu SAMANTHA_STT_COMPUTE_TYPE=int8
    stt_device: str = "cuda"
    stt_compute_type: str = "float16"
```

and in `from_env`, directly above the `log_level=...` line, add:

```python
            stt_model=_get("STT_MODEL", cls.stt_model),
            stt_language=_get("STT_LANGUAGE", cls.stt_language),
            stt_device=_get("STT_DEVICE", cls.stt_device),
            stt_compute_type=_get("STT_COMPUTE_TYPE", cls.stt_compute_type),
```

- [ ] **Step 4: Share one Whisper model per process**

In `backend/samantha/voice_pipeline.py`, add `config` to the local imports —
replace:

```python
from .context import gather_context
from .tts import stream as _tts_stream
```

with:

```python
from .config import config
from .context import gather_context
from .tts import stream as _tts_stream
```

Then, directly above the `Stage 2 — Whisper STT` banner comment, add:

```python
# ──────────────────────────────────────────────────────────────────────────
# Whisper model cache (process-wide)
# ──────────────────────────────────────────────────────────────────────────

# build_pipeline() constructs a fresh WhisperSTTProcessor per /voice
# client, and the weights are multiple GB — reloading them on every
# reconnect (mid-conversation, on the user's first utterance) is not
# acceptable on the kiosk. Module-level asyncio.Lock is safe to build at
# import time on 3.10+, where it no longer binds an event loop.
_whisper_model = None
_whisper_model_key: tuple[str, str, str] | None = None
_whisper_lock = asyncio.Lock()


def _load_whisper_model(model_size: str, device: str, compute_type: str):
    from faster_whisper import WhisperModel

    logger.info(f"stt: loading whisper {model_size} on {device} ({compute_type})")
    model = WhisperModel(model_size, device=device, compute_type=compute_type)
    logger.info("stt: whisper ready")
    return model


async def get_whisper_model(model_size: str, device: str, compute_type: str):
    """Return the shared Whisper model, loading it off the event loop."""
    global _whisper_model, _whisper_model_key
    key = (model_size, device, compute_type)
    if _whisper_model is not None and _whisper_model_key == key:
        return _whisper_model
    async with _whisper_lock:
        # Re-check inside the lock — another connection may have won.
        if _whisper_model is not None and _whisper_model_key == key:
            return _whisper_model
        _whisper_model = await asyncio.to_thread(
            _load_whisper_model, model_size, device, compute_type
        )
        _whisper_model_key = key
    return _whisper_model


async def preload_stt() -> None:
    """Load the Whisper model before the first utterance.

    Call this when the /voice connection is accepted (Phase 11 plan,
    Task 5) — otherwise the load lands in the middle of the user's first
    sentence and costs seconds, or a multi-GB download.
    """
    await get_whisper_model(config.stt_model, config.stt_device, config.stt_compute_type)
```

- [ ] **Step 5: Take the processor's defaults from config and use the cache**

In `WhisperSTTProcessor`, replace:

```python
    def __init__(
        self,
        model_size: str = "large-v3-turbo",
        language: str = "es",
        device: str = "cuda",
        compute_type: str = "float16",
    ) -> None:
        super().__init__()
        self._model_size = model_size
        self._language = language
        self._device = device
        self._compute_type = compute_type
```

with:

```python
    def __init__(
        self,
        model_size: str | None = None,
        language: str | None = None,
        device: str | None = None,
        compute_type: str | None = None,
    ) -> None:
        super().__init__()
        self._model_size = model_size or config.stt_model
        self._language = language or config.stt_language
        self._device = device or config.stt_device
        self._compute_type = compute_type or config.stt_compute_type
```

Replace the `_load` method entirely:

```python
    def _load(self) -> None:
        from faster_whisper import WhisperModel

        logger.info(f"stt: loading whisper {self._model_size} on {self._device}")
        self._model = WhisperModel(
            self._model_size,
            device=self._device,
            compute_type=self._compute_type,
        )
        logger.info("stt: whisper ready")
```

with:

```python
    async def _ensure_model(self) -> None:
        """Bind the process-wide model (loaded off the event loop, once)."""
        if self._model is None:
            self._model = await get_whisper_model(
                self._model_size, self._device, self._compute_type
            )
```

and in `_transcribe`, replace:

```python
    def _transcribe(self, audio_bytes: bytes) -> str:
        if self._model is None:
            self._load()
        audio = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
```

with:

```python
    def _transcribe(self, audio_bytes: bytes) -> str:
        """Runs in a worker thread — the model is bound by _ensure_model."""
        audio = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
```

Finally, in `process_frame`'s `UserStoppedSpeakingFrame` branch (Task 15),
replace:

```python
            if len(audio) >= self.MIN_UTTERANCE_BYTES:
                text = await asyncio.to_thread(self._transcribe, audio)
```

with:

```python
            if len(audio) >= self.MIN_UTTERANCE_BYTES:
                await self._ensure_model()
                text = await asyncio.to_thread(self._transcribe, audio)
```

- [ ] **Step 6: Pin the STT env for tests**

(The `_run` helper was already switched to `asyncio.run` in Task 14 Step 1 —
it had to happen before the file became tracked. Nothing to do here for it;
confirm with `grep -n "def _run" -A3 backend/tests/test_voice_pipeline.py`
that it reads `asyncio.run(coro)`, and move on.)

In `backend/tests/conftest.py`, append:

```python
# The voice-loop tests never load a real model, but a developer with
# SAMANTHA_STT_DEVICE=cuda exported would otherwise see it in the
# processor defaults. Pin the CI/dev-safe combination.
os.environ.setdefault("SAMANTHA_STT_DEVICE", "cpu")
os.environ.setdefault("SAMANTHA_STT_COMPUTE_TYPE", "int8")
```

- [ ] **Step 7: Run the suite, format, commit**

```bash
cd backend && pytest tests/ -v && ruff format . && ruff check .
git add backend/samantha/config.py backend/samantha/voice_pipeline.py backend/tests/test_voice_pipeline.py backend/tests/conftest.py backend/tests/test_config.py
git commit -m "fix(voice): configurable STT, one shared Whisper model per process, test hygiene"
```

- [ ] **Step 8: Hand the protocol change off to the Phase 11 plan**

Task 14 replaced the wire protocol that plan's remaining tasks were written
against. Its Task 5 (`/voice` endpoint) and Task 6 (`useVoiceSocket` hook)
must be updated before they are executed, or the frontend will speak the
old, unimplementable "binary audio + text JSON" protocol at a transport that
is in binary mode.

Insert directly below the `## Global Constraints` heading of
`docs/superpowers/plans/2026-06-20-phase11-voice-loop.md`:

Insert directly below that plan's `## Global Constraints` heading:

```markdown
> **AMENDED 2026-08-04 (improvement sweep, Fase 3).** The wire protocol
> changed: the WebSocket carries a SINGLE binary channel with a 1-byte type
> prefix (`0x01` + int16-LE PCM, `0x02` + UTF-8 JSON), because pipecat's
> FastAPI transport picks bytes-or-text once from `serializer.type` and uses
> it in both directions. The browser sends its native capture rate (48 kHz)
> and `SamanthaWireSerializer` resamples to 16 kHz at the boundary — the
> pipeline cannot run at 48 kHz because `SileroVADAnalyzer.set_sample_rate()`
> raises for anything but 8/16 kHz. Tasks 5 and 6 below must be implemented
> against `backend/samantha/voice_pipeline.py:SamanthaWireSerializer`, not
> against the original "binary audio + text JSON" description, and the
> `/voice` endpoint should `await voice_pipeline.preload_stt()` before
> starting the pipeline task.
```

Then commit:

```bash
git add docs/superpowers/plans/2026-06-20-phase11-voice-loop.md
git commit -m "docs(phase11): amend wire protocol after the voice-pipeline fixes"
```

---
## Fase 4 — Frontend robustness

### Task 20: TTS — `speak()` must never hang the turn forever (resume gate, WAV abort, watchdog)

**Bug:** Three independent ways `speak()` can pend forever, each leaving `sendMessage`'s `finally` unreached so `busyRef.current` stays `true` and the guard at the top of `sendMessage` silently drops every later utterance until page reload:
1. `frontend/src/net/tts.ts:70` — `await audioCtx.resume()` on an autoplay-gated context neither resolves nor rejects.
2. `frontend/src/net/tts.ts:46-57` — the WAV fallback's promise only resolves via `ended`/`error`/`play().catch`; the abort path just pauses and clears `src`, which does not reliably fire either event.
3. Any other unforeseen wedge inside `speak()` (wedged PCM stream reader, etc.) — no outer bound exists.

**Files:**
- Modify: `frontend/src/net/tts.ts` (resume gate, WAV abort path)
- Modify: `frontend/src/screens/ConversationScreen.tsx` (watchdog around the `speak()` call)

- [ ] **Step 1: Gate AudioContext creation behind a timeout-raced resume**

In `frontend/src/net/tts.ts`, add above `export async function speak(`:

```ts
const RESUME_TIMEOUT_MS = 1500;

// AudioContext.resume() on an autoplay-gated context neither resolves
// nor rejects — awaiting it bare hangs speak() (and the caller's busy
// flag) forever. Race a timeout; on timeout retry once with a fresh
// context (a user gesture may have landed since), then fail loudly so
// the caller's catch runs and the turn is released.
async function createRunningAudioContext(
  sampleRate: number,
): Promise<AudioContext> {
  for (let attempt = 0; attempt < 2; attempt++) {
    const ctx = new AudioContext({ sampleRate });
    if (ctx.state !== "suspended") return ctx;
    const resumed = await Promise.race([
      ctx.resume().then(() => true),
      new Promise<boolean>((r) => setTimeout(() => r(false), RESUME_TIMEOUT_MS)),
    ]);
    if (resumed) return ctx;
    await ctx.close().catch(() => {});
  }
  throw new Error("speak_failed: audio_context_suspended");
}
```

Then replace:

```ts
  const audioCtx = new AudioContext({ sampleRate });
  // Browsers gate AudioContext on a user gesture; speak() is called
  // from a button/keypress handler so resume should always succeed.
  if (audioCtx.state === "suspended") await audioCtx.resume();
```

with:

```ts
  const audioCtx = await createRunningAudioContext(sampleRate);
```

- [ ] **Step 2: Make the WAV fallback resolve on abort**

In the same file, replace:

```ts
  // Fallback (tone WAV). Old-style blob playback.
  if (contentType.startsWith("audio/wav")) {
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const audio = new Audio(url);
    const onAbort = () => {
      audio.pause();
      audio.src = "";
    };
    signal?.addEventListener("abort", onAbort, { once: true });
    await new Promise<void>((resolve) => {
      audio.addEventListener("ended", () => resolve(), { once: true });
      audio.addEventListener("error", () => resolve(), { once: true });
      audio.play().catch(() => resolve());
    });
    signal?.removeEventListener("abort", onAbort);
    URL.revokeObjectURL(url);
    return;
  }
```

with:

```ts
  // Fallback (complete WAV). Old-style blob playback.
  if (contentType.startsWith("audio/wav")) {
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const audio = new Audio(url);
    await new Promise<void>((resolve) => {
      // Every exit path must resolve: pausing + clearing src does NOT
      // reliably fire "ended"/"error", so an abort used to leave this
      // promise pending forever (and the caller's busy flag stuck).
      const onAbort = () => {
        audio.pause();
        audio.src = "";
        resolve();
      };
      signal?.addEventListener("abort", onAbort, { once: true });
      const settle = () => {
        signal?.removeEventListener("abort", onAbort);
        resolve();
      };
      audio.addEventListener("ended", settle, { once: true });
      audio.addEventListener("error", settle, { once: true });
      audio.play().catch(settle);
    });
    URL.revokeObjectURL(url);
    return;
  }
```

- [ ] **Step 3: Add a watchdog around the `speak()` call in `sendMessage`**

In `frontend/src/screens/ConversationScreen.tsx`, below the existing debounce constant — after:

```ts
// How long a user's pause has to be before we treat the utterance as
// "complete" and ship it to the LLM. Web Speech API commits a final
// segment on its own ~1.5s of silence, but it sometimes splits a long
// sentence into multiple finals; this debounce stitches them.
const TRANSCRIPT_DEBOUNCE_MS = 800;
```

add:

```ts
// Outer bound on one TTS turn. Streamed synthesis + playback of a
// reply comfortably fits base + per-char; anything beyond it is a
// wedge (gated AudioContext, stuck reader), and the watchdog aborts
// so the busy flag can never stay stuck for the rest of the session.
const SPEAK_WATCHDOG_BASE_MS = 30_000;
const SPEAK_WATCHDOG_PER_CHAR_MS = 150;
```

Then, inside `sendMessage`, replace:

```ts
      const full = cleanReply.trim();
      if (full && mountedRef.current) {
        setWaveMode("speaking");
        const ac = new AbortController();
        speakAbortRef.current = ac;
        setIsSpeaking(true);
        try {
          await speak(full, ac.signal);
        } catch (e) {
          console.warn("speak failed", e);
        } finally {
          setIsSpeaking(false);
          speakAbortRef.current = null;
        }
      }
```

with:

```ts
      const full = cleanReply.trim();
      if (full && mountedRef.current) {
        setWaveMode("speaking");
        const ac = new AbortController();
        speakAbortRef.current = ac;
        setIsSpeaking(true);
        // Belt-and-braces: even if a hang inside speak() slips past
        // its internal fixes, this abort releases the turn.
        const watchdog = setTimeout(() => {
          console.warn("[conv] speak watchdog fired — aborting TTS");
          ac.abort();
        }, SPEAK_WATCHDOG_BASE_MS + full.length * SPEAK_WATCHDOG_PER_CHAR_MS);
        try {
          await speak(full, ac.signal);
        } catch (e) {
          console.warn("speak failed", e);
        } finally {
          clearTimeout(watchdog);
          setIsSpeaking(false);
          speakAbortRef.current = null;
        }
      }
```

- [ ] **Step 4: Typecheck, build, commit**

```bash
cd frontend && pnpm typecheck && pnpm build
git add frontend/src/net/tts.ts frontend/src/screens/ConversationScreen.tsx
git commit -m "fix(tts): speak() can no longer hang the turn (resume timeout, WAV abort resolve, watchdog)"
```

---

### Task 21: Surface speech-recognition errors and break the error-restart loop

**Bug:** `micErrorMessage` in `ConversationScreen.tsx` maps codes (`no-speech`, `network`, `audio-capture`, `aborted`) but nothing ever feeds it a native error: react-speech-recognition 4.0.1's own `onError` handles only `not-allowed` (everything else is swallowed), and in continuous mode `onRecognitionDisconnect` auto-restarts on `onend`. A dead mic or offline Web Speech service therefore loops error→restart forever while the UI shows "listening".

**Files:**
- Modify: `frontend/src/screens/ConversationScreen.tsx`

- [ ] **Step 1: Verify the library internals the fix depends on**

Note: 4.0.1 as installed ships its source as `dist/index.js` — the `lib/RecognitionManager.js` path referenced by the 2026-06-11 plan does not exist in this build. Run:

```bash
grep -n "this.recognition.onerror\|onError(event)\|not-allowed\|onRecognitionDisconnect\|getRecognition()" frontend/node_modules/react-speech-recognition/dist/index.js
```

Confirm: (a) the manager assigns `this.recognition.onerror = this.onError.bind(this)`; (b) `onError(event)` acts **only** when `event.error === "not-allowed"`; (c) `onRecognitionDisconnect` restarts listening when `continuous` is true and `pauseAfterDisconnect` is false; (d) `getRecognition()` returns the manager's shared recognition instance. If any of these differ, STOP and re-derive before editing — the fix chains onto exactly this state machine.

- [ ] **Step 2: Add the breaker constants and ref**

Below the `SPEAK_WATCHDOG_PER_CHAR_MS` constant (Task 20), add:

```ts
// Error-rate breaker for continuous recognition: the library restarts
// the recognizer on every `onend`, so a dead mic or offline Web
// Speech service loops error→restart forever while the UI claims to
// listen. This many errors inside the window means "hang up".
const MIC_ERROR_WINDOW_MS = 10_000;
const MIC_MAX_ERRORS_IN_WINDOW = 4;
```

Below `const [isSpeaking, setIsSpeaking] = useState(false);` add:

```ts
  // Timestamps of recent native recognition errors (breaker above).
  const micErrorTimesRef = useRef<number[]>([]);
```

- [ ] **Step 3: Chain a native `onerror` after the library's handler**

Directly below the existing effect:

```ts
  // react-speech-recognition reports permission problems only through
  // this flag — startListening() swallows its own failures.
  useEffect(() => {
    if (isMicrophoneAvailable) return;
    setStatusMessage(micErrorMessage("not-allowed"));
    setConversationActive(false);
  }, [isMicrophoneAvailable]);
```

add:

```ts
  // The library's own onerror reacts only to "not-allowed"; every
  // other recognition error (no-speech, network, audio-capture) is
  // swallowed, and in continuous mode the manager auto-restarts on
  // `onend` — a dead mic loops silently forever. Chain a native
  // handler AFTER the library's so its not-allowed logic still runs,
  // surface the code, and trip a breaker on repeated failures.
  useEffect(() => {
    const rec = SpeechRecognition.getRecognition();
    if (!rec) return;
    const libOnError = rec.onerror;
    rec.onerror = (ev: SpeechRecognitionErrorEvent) => {
      libOnError?.call(rec, ev);
      // "aborted" is us muting the mic on purpose before TTS — noise.
      if (ev.error === "aborted") return;
      setStatusMessage(micErrorMessage(ev.error));
      const now = Date.now();
      const recent = micErrorTimesRef.current.filter(
        (t) => now - t < MIC_ERROR_WINDOW_MS,
      );
      recent.push(now);
      micErrorTimesRef.current = recent;
      if (recent.length >= MIC_MAX_ERRORS_IN_WINDOW) {
        micErrorTimesRef.current = [];
        setConversationActive(false);
        void SpeechRecognition.abortListening();
        setStatusMessage(
          "No me llega nada del micro. Cuelgo yo — inténtalo otra vez cuando funcione.",
        );
      }
    };
    return () => {
      rec.onerror = libOnError;
    };
  }, []);
```

(`SpeechRecognitionErrorEvent` is ambient via `@types/dom-speech-recognition`, pulled in by `@types/react-speech-recognition` — no import needed.)

- [ ] **Step 4: Typecheck, build, commit**

```bash
cd frontend && pnpm typecheck && pnpm build
git add frontend/src/screens/ConversationScreen.tsx
git commit -m "fix(mic): surface native recognition errors and break the error-restart loop"
```

---

### Task 22: Vendor the VAD/ONNX assets — no CDN dependency on a 24/7 appliance

**Bug:** `frontend/src/core/useBargeIn.ts:66-69` loads the Silero VAD ONNX model, the audio worklet, and the ONNX Runtime WASM from `cdn.jsdelivr.net` at runtime on every mount. An offline boot silently disables barge-in, and a CDN compromise is a live supply-chain surface on the kiosk. Verified against the installed packages: `MicVAD` defaults to `model: "legacy"` and fetches `baseAssetPath + "vad.worklet.bundle.min.js"` and `baseAssetPath + "silero_vad_legacy.onnx"` (`node_modules/@ricky0123/vad-web/dist/real-time-vad.js:34-38,353`); onnxruntime-web 1.26.0 fetches `ort-wasm-simd-threaded.mjs`/`.wasm` from `wasmPaths`.

**Files:**
- Modify: `frontend/package.json` (repeatable copy script), `frontend/src/core/useBargeIn.ts`
- Create (vendored, committed): `frontend/public/vad/*`, `frontend/public/ort/*` (~15 MB of binaries — accepted trade-off: the appliance must work with the network cable pulled)

- [ ] **Step 1: Add a repeatable vendor script**

In `frontend/package.json`, replace:

```json
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview",
    "typecheck": "tsc --noEmit"
  },
```

with:

```json
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview",
    "typecheck": "tsc --noEmit",
    "vendor:vad": "mkdir -p public/vad public/ort && cp node_modules/@ricky0123/vad-web/dist/vad.worklet.bundle.min.js node_modules/@ricky0123/vad-web/dist/silero_vad_legacy.onnx public/vad/ && cp node_modules/onnxruntime-web/dist/ort-wasm-simd-threaded.mjs node_modules/onnxruntime-web/dist/ort-wasm-simd-threaded.wasm public/ort/"
  },
```

- [ ] **Step 2: Copy the assets**

```bash
cd "/Volumes/Macintosh SSD - Daten/Users/horelvis/git/os1-samantha/frontend" && pnpm vendor:vad
ls -la public/vad public/ort
```

Expected: `public/vad/vad.worklet.bundle.min.js` (~2.5 KB), `public/vad/silero_vad_legacy.onnx` (~1.8 MB), `public/ort/ort-wasm-simd-threaded.mjs` (~24 KB), `public/ort/ort-wasm-simd-threaded.wasm` (~13 MB). Re-run this script whenever `@ricky0123/vad-web` or `onnxruntime-web` is bumped — the vendored files must match the installed package versions.

- [ ] **Step 3: Point the hook at same-origin paths**

In `frontend/src/core/useBargeIn.ts`, replace:

```ts
      const vad = await MicVAD.new({
        // vad-web 0.0.30 changed defaults to expect assets locally
        // (`./silero_vad_legacy.onnx`), which 404s on our Vite dev
        // server. Point both asset paths at jsDelivr until we vendor
        // them under /public/ for the kiosk build.
        baseAssetPath:
          "https://cdn.jsdelivr.net/npm/@ricky0123/vad-web@0.0.30/dist/",
        onnxWASMBasePath:
          "https://cdn.jsdelivr.net/npm/onnxruntime-web@1.26.0/dist/",
```

with:

```ts
      const vad = await MicVAD.new({
        // Assets are vendored under frontend/public/ (pnpm vendor:vad)
        // and served same-origin: Vite serves public/ in dev, and the
        // build copies it into dist/ for the kiosk. A 24/7 appliance
        // must not depend on a CDN at runtime — offline boot would
        // silently lose barge-in. Re-run `pnpm vendor:vad` when
        // @ricky0123/vad-web or onnxruntime-web is bumped.
        baseAssetPath: "/vad/",
        onnxWASMBasePath: "/ort/",
```

Also replace the stale header note:

```ts
// - The library bundles a worklet + ONNX model + WASM runtime; by
//   default they load from a CDN. That's fine for dev; for the kiosk
//   deployment we should vendor them under /public/ later.
```

with:

```ts
// - The worklet + ONNX model + WASM runtime are vendored under
//   frontend/public/ (vad/ and ort/) and served same-origin — no CDN
//   at runtime. `pnpm vendor:vad` re-copies them from node_modules.
```

and the kill-switch comment inside the effect:

```ts
    // Kill switch (`sam.bargeIn = 0`): skip entirely — no extra
    // getUserMedia stream, no ONNX/WASM downloads from jsDelivr.
    if (!enabled) return;
```

with:

```ts
    // Kill switch (`sam.bargeIn = 0`): skip entirely — no extra
    // getUserMedia stream, no worklet/ONNX/WASM loads at all.
    if (!enabled) return;
```

- [ ] **Step 4: Verify no CDN reference remains, then build**

```bash
cd frontend && grep -rn "cdn.jsdelivr.net" src/ ; pnpm typecheck && pnpm build && ls dist/vad dist/ort
```

Expected: the grep prints nothing; the build succeeds and `dist/vad` + `dist/ort` contain the four vendored files.

- [ ] **Step 5: Commit (binaries included, deliberately)**

```bash
git add frontend/package.json frontend/src/core/useBargeIn.ts frontend/public/vad frontend/public/ort
git commit -m "fix(barge-in): vendor VAD/ONNX assets same-origin — offline kiosk keeps barge-in, no CDN at runtime"
```

---

### Task 23: Bound the transcript store and drop the per-render reverse scan

**Bug:** `frontend/src/core/store.ts:22-29` — `appendMessage` never trims, so the transcript grows without bound on a 24/7 kiosk, and `patchMessage` remaps the whole array once per streamed token (O(n) per token, n unbounded). `frontend/src/screens/ConversationScreen.tsx:355` — `[...transcript].reverse().find(...)` copies and reverses the whole array on every render, and this component renders once per token/interim event.

**Files:**
- Modify: `frontend/src/core/store.ts`, `frontend/src/screens/ConversationScreen.tsx`, `frontend/tsconfig.json` (lib bump for `findLast`)

- [ ] **Step 1: Cap the transcript ring in `appendMessage`**

In `frontend/src/core/store.ts`, add below the imports:

```ts
// Hard cap on the in-memory transcript. The kiosk runs 24/7 and every
// token patch remaps the whole array — unbounded growth turns a long
// evening into a per-token O(n) tax and an ever-growing history DOM.
// 200 messages is hours of conversation; long-term memory lives in
// the backend (ChromaDB), not in this UI buffer. Trimming can, in
// theory, drop a bubble that is still being patched mid-stream after
// 200 newer messages — patchMessage then no-ops, which is fine.
const MAX_TRANSCRIPT_MESSAGES = 200;
```

and replace:

```ts
  appendMessage: (m) =>
    set((state) => ({ transcript: [...state.transcript, m] })),
```

with:

```ts
  appendMessage: (m) =>
    set((state) => {
      const next = [...state.transcript, m];
      return {
        transcript:
          next.length > MAX_TRANSCRIPT_MESSAGES
            ? next.slice(next.length - MAX_TRANSCRIPT_MESSAGES)
            : next,
      };
    }),
```

- [ ] **Step 2: Enable `findLast` in the TS lib**

`Array.prototype.findLast` is ES2023 (in Chromium since 97 — the kiosk target is latest stable, per CLAUDE.md §6). In `frontend/tsconfig.json`, replace:

```json
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
```

with:

```json
    "lib": ["ES2023", "DOM", "DOM.Iterable"],
```

(`"target": "ES2022"` stays — `findLast` is a runtime method, not syntax; nothing needs downleveling.)

- [ ] **Step 3: Replace the reverse scan**

In `frontend/src/screens/ConversationScreen.tsx`, replace:

```ts
  const lastSamantha = [...transcript].reverse().find((m) => m.role === "samantha");
```

with:

```ts
  // findLast beats [...].reverse().find(): no copy + reverse per
  // render, and this component renders once per streamed token.
  const lastSamantha = transcript.findLast((m) => m.role === "samantha");
```

- [ ] **Step 4: Typecheck, build, commit**

```bash
cd frontend && pnpm typecheck && pnpm build
git add frontend/src/core/store.ts frontend/src/screens/ConversationScreen.tsx frontend/tsconfig.json
git commit -m "perf(frontend): cap transcript ring at 200 messages, findLast for last caption"
```

---

### Task 24: Cancellable turns (hang-up/Esc during thinking) + race-free post-turn transcript wipe

**Bug:** (a) `ConversationScreen.tsx` — "hang up" (stop square) or Escape during the *thinking* phase doesn't cancel the turn: `speakAbortRef` is only populated once TTS starts, so the pending `sendMessage` continues and starts speaking after the user already left the call. (b) The busy-flip effect (`if (busy) return; … resetTranscript();`) runs after React re-renders, which can land AFTER the debounce `.then` has already resumed the recognizer — `resetTranscript()` then aborts+restarts the just-resumed session and eats the user's first words. The fix moves the wipe into `sendMessage`'s `finally` (guaranteed to run before the `.then` that resumes listening) and deletes the effect, preserving the `bargedInRef` keep-the-interruption semantics from the 2026-06-11 sweep.

**Files:**
- Modify: `frontend/src/screens/ConversationScreen.tsx` (builds on the Task 20 state of `sendMessage`)

- [ ] **Step 1: Create the turn's AbortController at turn start**

In `sendMessage`, replace:

```ts
    setBusy(true);
    setWaveMode("thinking");

    const replyId = crypto.randomUUID();
```

with:

```ts
    setBusy(true);
    setWaveMode("thinking");

    // The whole turn — thinking included — is cancellable: Esc or
    // hanging up aborts this controller while the LLM is still
    // streaming, and the reply is then shown but never spoken. Typed
    // turns run with conversationActive === false and are exempt from
    // the hang-up check (isVoiceTurn) — only the explicit abort
    // cancels them.
    const turnAbort = new AbortController();
    speakAbortRef.current = turnAbort;
    const isVoiceTurn = activeRef.current;

    const replyId = crypto.randomUUID();
```

- [ ] **Step 2: Gate the speak branch on the turn still being wanted**

Replace the Task-20 speak block:

```ts
      const full = cleanReply.trim();
      if (full && mountedRef.current) {
        setWaveMode("speaking");
        const ac = new AbortController();
        speakAbortRef.current = ac;
        setIsSpeaking(true);
        // Belt-and-braces: even if a hang inside speak() slips past
        // its internal fixes, this abort releases the turn.
        const watchdog = setTimeout(() => {
          console.warn("[conv] speak watchdog fired — aborting TTS");
          ac.abort();
        }, SPEAK_WATCHDOG_BASE_MS + full.length * SPEAK_WATCHDOG_PER_CHAR_MS);
        try {
          await speak(full, ac.signal);
        } catch (e) {
          console.warn("speak failed", e);
        } finally {
          clearTimeout(watchdog);
          setIsSpeaking(false);
          speakAbortRef.current = null;
        }
      }
```

with:

```ts
      const full = cleanReply.trim();
      // Cancelled while thinking (Esc/watchdog) or the voice call was
      // hung up mid-turn → show the text, stay silent.
      const cancelled =
        turnAbort.signal.aborted || (isVoiceTurn && !activeRef.current);
      if (full && mountedRef.current && !cancelled) {
        setWaveMode("speaking");
        setIsSpeaking(true);
        // Belt-and-braces: even if a hang inside speak() slips past
        // its internal fixes, this abort releases the turn.
        const watchdog = setTimeout(() => {
          console.warn("[conv] speak watchdog fired — aborting TTS");
          turnAbort.abort();
        }, SPEAK_WATCHDOG_BASE_MS + full.length * SPEAK_WATCHDOG_PER_CHAR_MS);
        try {
          await speak(full, turnAbort.signal);
        } catch (e) {
          console.warn("speak failed", e);
        } finally {
          clearTimeout(watchdog);
          setIsSpeaking(false);
        }
      }
```

- [ ] **Step 3: Move the transcript wipe into the turn's `finally`**

Replace:

```ts
    } finally {
      busyRef.current = false;
      setBusy(false);
      setWaveMode("idle");
    }
```

with:

```ts
    } finally {
      // Wipe any echo captured during the turn BEFORE the debounce
      // .then resumes listening (that .then runs strictly after this
      // finally), so the wipe can never abort a just-restarted
      // recognizer and eat the user's first words. A barge-in
      // transcript is the user's interruption — keep it.
      if (bargedInRef.current) {
        bargedInRef.current = false;
      } else {
        resetTranscript();
      }
      speakAbortRef.current = null;
      busyRef.current = false;
      setBusy(false);
      setWaveMode("idle");
    }
```

- [ ] **Step 4: Delete the busy-flip wipe effect** (its semantics — including the `bargedInRef` exception — now live in the `finally` above). Remove entirely:

```ts
  // Tail-echo guard: even though the turn now aborts recognition
  // up-front, results already in flight when the abort lands can
  // still arrive. Anything captured DURING busy is presumed to be
  // Samantha's own voice; when busy flips false we wipe it so the
  // debounce effect can't ship it as a user message — EXCEPT right
  // after a barge-in, where the in-flight transcript is the user's
  // interruption and must survive.
  useEffect(() => {
    if (busy) return;
    if (bargedInRef.current) {
      bargedInRef.current = false;
      return;
    }
    resetTranscript();
  }, [busy, resetTranscript]);
```

Also update the now-stale ref comment — replace:

```ts
  // Set when the VAD interrupts Samantha; tells the busy-flip wipe to
  // KEEP the transcript (it's the user's interruption, not echo).
  const bargedInRef = useRef(false);
```

with:

```ts
  // Set when the VAD interrupts Samantha; tells the end-of-turn wipe
  // in sendMessage's finally to KEEP the transcript (it's the user's
  // interruption, not echo).
  const bargedInRef = useRef(false);
```

- [ ] **Step 5: Hang-up and Esc abort the in-flight turn**

In `toggleConversation`, replace:

```ts
    if (conversationActive) {
      setConversationActive(false);
      SpeechRecognition.stopListening();
    } else {
```

with:

```ts
    if (conversationActive) {
      setConversationActive(false);
      // Hanging up mid-turn kills the turn too: the pending reply is
      // still rendered, but Samantha must not start talking to an
      // empty room.
      speakAbortRef.current?.abort();
      SpeechRecognition.stopListening();
    } else {
```

And update the Escape handler comment (behavior is now broader) — replace:

```ts
    Escape: () => {
      // If Samantha is talking, Esc cuts her off (manual barge-in
      // fallback for when the VAD doesn't fire — e.g. typed input
      // mode, or headphone setup where the mic can't hear).
      if (speakAbortRef.current) {
        speakAbortRef.current.abort();
        return;
      }
```

with:

```ts
    Escape: () => {
      // Esc cancels the in-flight turn: cuts TTS mid-utterance, and
      // during *thinking* it marks the turn cancelled so the reply is
      // shown but never spoken (manual barge-in fallback for when the
      // VAD doesn't fire — typed input mode, headphones).
      if (speakAbortRef.current) {
        speakAbortRef.current.abort();
        return;
      }
```

- [ ] **Step 6: Typecheck, build, commit**

```bash
cd frontend && pnpm typecheck && pnpm build
git add frontend/src/screens/ConversationScreen.tsx
git commit -m "fix(conversation): whole-turn cancellation and race-free post-turn transcript wipe"
```

---

### Task 25: Onboarding answer window must not close instantly; Boot screen auto-retries in Spanish

**Bug:** (a) `OnboardingScreen.tsx:132-136` — after `setStep("listening")`, the effect `if (step === "listening" && !listening) setStep("review")` can fire before the recognizer's async start flips `listening` to true; on a slow frame the answer window closes instantly and the user never gets to speak. (b) `BootScreen.tsx:45-56,70` — a failed `/profile` probe shows raw English `e.message` inside the Spanish UI and waits for a manual "Reintentar" click; on an appliance the boot race (frontend up before backend) must resolve itself.

**Files:**
- Modify: `frontend/src/screens/OnboardingScreen.tsx`, `frontend/src/screens/BootScreen.tsx`

- [ ] **Step 1: Gate the listening→review transition on a real listening edge**

In `OnboardingScreen.tsx`, below `const speakAbortRef = useRef<AbortController | null>(null);` add:

```ts
  // True once `listening` has actually been true for the CURRENT
  // question. The review transition must wait for this edge —
  // otherwise, right after setStep("listening"), the recognizer's
  // async start hasn't flipped `listening` yet and the answer window
  // would close instantly on a slow frame.
  const hasListenedRef = useRef(false);
```

Replace `startListening`:

```ts
  const startListening = () => {
    setMicError(null);
    resetTranscript();
    setValue("");
    try {
```

with:

```ts
  const startListening = () => {
    setMicError(null);
    resetTranscript();
    setValue("");
    // New answer window: wait for a fresh listening→true edge, not
    // the previous question's.
    hasListenedRef.current = false;
    try {
```

Then replace the transition effect:

```ts
  // Transition from listening to review once the user stops talking (natural pause)
  useEffect(() => {
    if (step === "listening" && !listening) {
      setStep("review");
    }
  }, [listening, step]);
```

with:

```ts
  // Arm on the listening→true edge for the current question.
  useEffect(() => {
    if (step === "listening" && listening) hasListenedRef.current = true;
  }, [listening, step]);

  // Transition listening → review once the user stops talking — but
  // only after the recognizer really opened. If it never opens (slow
  // start, silent failure), a grace timeout moves on instead of
  // deadlocking in "te escucho…".
  useEffect(() => {
    if (step !== "listening" || listening) return;
    if (hasListenedRef.current) {
      hasListenedRef.current = false;
      setStep("review");
      return;
    }
    const grace = setTimeout(() => setStep("review"), 4000);
    return () => clearTimeout(grace);
  }, [listening, step]);
```

- [ ] **Step 2: BootScreen — Spanish error copy + auto-retry with backoff**

In `BootScreen.tsx`, add above `export function BootScreen() {`:

```ts
// The /profile probe fails two ways: the fetch itself dies (backend
// down or still booting — a TypeError) or the backend answers non-2xx.
// Either way the kiosk shows Samantha's words, never `e.message` in
// English; the technical detail goes to the console.
function backendErrorMessage(e: unknown): string {
  if (e instanceof TypeError)
    return "Todavía me estoy despertando. Dame un momento — sigo intentándolo.";
  return "Algo dentro de mí no responde. Sigo intentándolo.";
}
```

Below `const [attempt, setAttempt] = useState(0);` add:

```ts
  // Backoff for the automatic /profile re-probe (2s → 4s → … 15s max).
  const retryDelayRef = useRef(2000);
```

In the effect, replace:

```ts
  useEffect(() => {
    let cancelled = false;
    setError(null);
```

with:

```ts
  useEffect(() => {
    let cancelled = false;
    let retryTimer: ReturnType<typeof setTimeout> | undefined;
    setError(null);
```

replace the catch:

```ts
      } catch (e) {
        await minDelay;
        if (cancelled) return;
        setError(e instanceof Error ? e.message : "no consigo hablar con el backend");
      }
```

with:

```ts
      } catch (e) {
        await minDelay;
        if (cancelled) return;
        console.warn("[boot] profile probe failed:", e);
        setError(backendErrorMessage(e));
        // Auto-retry: the kiosk boots in parallel with the backend and
        // must recover from that race on its own — the button below is
        // only a manual shortcut.
        const delay = retryDelayRef.current;
        retryDelayRef.current = Math.min(delay * 2, 15_000);
        retryTimer = setTimeout(() => setAttempt((a) => a + 1), delay);
      }
```

and the cleanup:

```ts
    return () => {
      cancelled = true;
      clearTimeout(morphTimer);
    };
```

with:

```ts
    return () => {
      cancelled = true;
      clearTimeout(morphTimer);
      clearTimeout(retryTimer);
    };
```

Then fix the error UI — replace:

```ts
          No oigo al backend. ({error})
```

with:

```ts
          {error}
```

and the button label:

```ts
          Reintentar
```

with:

```ts
          reintentar ahora
```

- [ ] **Step 3: Typecheck, build, commit**

```bash
cd frontend && pnpm typecheck && pnpm build
git add frontend/src/screens/OnboardingScreen.tsx frontend/src/screens/BootScreen.tsx
git commit -m "fix(onboarding,boot): keep the answer window open until listening really ran; boot auto-retries with Spanish copy"
```

---

### Task 26: WSClient refuses a second concurrent `chat()`

**Bug:** `frontend/src/net/wsClient.ts:12,44-46` — the client keeps ONE handler per message type in a `Map`; a second concurrent `chat()` overwrites the first turn's `token`/`done`/`error` handlers, so the first promise never settles and replies cross-contaminate. The UI-level `busyRef` guard (2026-06-11 Task 14) already serializes turns; this makes the client itself refuse, so a future UI regression corrupts nothing.

**Files:**
- Modify: `frontend/src/net/wsClient.ts`, `frontend/src/screens/ConversationScreen.tsx` (error copy)

- [ ] **Step 1: Add the in-flight guard to `chat()`**

In `wsClient.ts`, replace the whole `chat` method:

```ts
  async chat(
    message: string,
    onToken: (t: string) => void,
    userId = "primary",
  ): Promise<{ reply: string; thinkingMs: number }> {
    await this.whenOpen();
    const socket = this.ws;
    return new Promise((resolve, reject) => {
      let full = "";
      const restore = () => {
        this.handlers.delete("token");
        this.handlers.delete("done");
        this.handlers.delete("error");
        socket?.removeEventListener("close", onClose);
      };
      const onClose = () => {
        restore();
        reject(new Error("ws_not_connected"));
      };
      socket?.addEventListener("close", onClose);

      this.on("token", (m) => { full += m.token; onToken(m.token); });
      this.on("done", (m) => { restore(); resolve({ reply: full, thinkingMs: m.thinking_ms }); });
      this.on("error", (m) => { restore(); reject(new Error(m.error)); });
      if (!this.send({ type: "chat", message, user_id: userId })) {
        restore();
        reject(new Error("ws_not_connected"));
      }
    });
  }
```

with:

```ts
  // True while a chat() promise is unsettled. The handlers Map keeps
  // ONE handler per message type, so a second concurrent chat() would
  // silently steal the first turn's token/done/error handlers and
  // strand its promise. The UI already serializes turns (busyRef);
  // this makes the client itself refuse instead of corrupting state
  // if that guard ever regresses.
  private chatPending = false;

  async chat(
    message: string,
    onToken: (t: string) => void,
    userId = "primary",
  ): Promise<{ reply: string; thinkingMs: number }> {
    if (this.chatPending) throw new Error("chat_in_flight");
    this.chatPending = true;
    try {
      await this.whenOpen();
      const socket = this.ws;
      return await new Promise((resolve, reject) => {
        let full = "";
        const restore = () => {
          this.handlers.delete("token");
          this.handlers.delete("done");
          this.handlers.delete("error");
          socket?.removeEventListener("close", onClose);
        };
        const onClose = () => {
          restore();
          reject(new Error("ws_not_connected"));
        };
        socket?.addEventListener("close", onClose);

        this.on("token", (m) => { full += m.token; onToken(m.token); });
        this.on("done", (m) => { restore(); resolve({ reply: full, thinkingMs: m.thinking_ms }); });
        this.on("error", (m) => { restore(); reject(new Error(m.error)); });
        if (!this.send({ type: "chat", message, user_id: userId })) {
          restore();
          reject(new Error("ws_not_connected"));
        }
      });
    } finally {
      // `return await` above guarantees this runs after the promise
      // settles, not when it is created.
      this.chatPending = false;
    }
  }
```

- [ ] **Step 2: Map the new error code in the UI**

In `ConversationScreen.tsx`, inside `chatErrorMessage`, replace:

```ts
  if (code === "message_too_long")
    return "Eso es mucho de golpe. Cuéntamelo en trozos más pequeños.";
  return "Algo se me ha cruzado. Inténtalo de nuevo.";
```

with:

```ts
  if (code === "message_too_long")
    return "Eso es mucho de golpe. Cuéntamelo en trozos más pequeños.";
  if (code === "chat_in_flight")
    return "Espera, aún estoy con lo de antes. Ahora te escucho.";
  return "Algo se me ha cruzado. Inténtalo de nuevo.";
```

- [ ] **Step 3: Typecheck, build, commit**

```bash
cd frontend && pnpm typecheck && pnpm build
git add frontend/src/net/wsClient.ts frontend/src/screens/ConversationScreen.tsx
git commit -m "fix(ws): client rejects a second concurrent chat() instead of clobbering handlers"
```

---

### Task 27: Low-priority cleanups — dead listen protocol, comment rot, leaks, duplication

> ⚠ Requiere confirmación del usuario antes de ejecutar (CLAUDE.md §8: cambio de contrato público).

**Bug (bundle):** L1 dead code: `WSClient.listen()`, the `"listen"`/`"transcription"` WS message variants and `PingResponse` are referenced by nothing in `frontend/src` (frontend-side removal only; the backend's `_ws_handle_listen` is out of scope for this Fase). L2 `wsClient.ts:8` claims "the kiosk reloads the page on backend restart" — no such logic exists anywhere. L3 `tts.ts:37` returns silently on `!res.ok` so a dead TTS backend looks like a mute turn. L4 `Wave.tsx:95` calls `getBoundingClientRect()` on every rAF frame (forced layout read at 60 fps). L5 `tts.ts` tail-wait registers an abort listener it never removes on normal completion. L6 `micErrorMessage` is duplicated in two screens and `handleContinue`/`handleSkip` in `OnboardingScreen` are ~110 near-identical lines. L7 an un-`void`ed `startListening` and a magic `Array(6)`.

**Files:**
- Modify: `frontend/src/net/wsClient.ts`, `frontend/src/core/types.ts`, `frontend/src/net/tts.ts`, `frontend/src/components/Wave.tsx`, `frontend/src/screens/ConversationScreen.tsx`, `frontend/src/screens/OnboardingScreen.tsx`
- Create: `frontend/src/core/micErrors.ts`

- [ ] **Step 1: Confirm the dead surface really is dead**

```bash
grep -rn "PingResponse\|\.listen(\|transcription" frontend/src/
```

Expected: hits only inside `frontend/src/net/wsClient.ts` (the `listen()` method itself) and `frontend/src/core/types.ts` (the declarations). If anything else appears, STOP — do not delete.

- [ ] **Step 2 (L1+L2): Delete `listen()` and fix the reconnect comment**

In `wsClient.ts`, delete the entire `listen` method:

```ts
  async listen(): Promise<string> {
    await this.whenOpen();
    const socket = this.ws;
    return new Promise((resolve, reject) => {
      const restore = () => {
        this.handlers.delete("transcription");
        socket?.removeEventListener("close", onClose);
      };
      const onClose = () => {
        restore();
        reject(new Error("ws_not_connected"));
      };
      socket?.addEventListener("close", onClose);

      this.on("transcription", (m) => {
        restore();
        resolve(m.text);
      });
      if (!this.send({ type: "listen" })) {
        restore();
        reject(new Error("ws_not_connected"));
      }
    });
  }
```

And replace the class comment:

```ts
// WebSocket wrapper with auto-reconnect (exponential backoff to 8s).
// The kiosk reloads the page on backend restart, but the WS reconnects
// in place if the backend just drops the connection.
```

with:

```ts
// WebSocket wrapper with auto-reconnect (exponential backoff to 8s).
// There is no reload-on-restart logic anywhere in the kiosk: this
// reconnect loop is the ONLY thing that re-attaches the UI to a
// restarted backend, so it must keep retrying forever.
```

- [ ] **Step 3 (L1): Delete the dead contract types**

In `frontend/src/core/types.ts`, delete:

```ts
export interface PingResponse {
  status: "ok";
  version: string;
  timestamp: number;
  mode: "mock" | "real";
  has_profile: boolean;
}
```

and replace:

```ts
// WebSocket protocol mirrors backend/samantha/api.py:_ws_handler.
export type WSClientToServer =
  | { type: "chat"; message: string; user_id: string }
  | { type: "listen" };

export type WSServerToClient =
  | { type: "token"; token: string }
  | { type: "done"; thinking_ms: number }
  | { type: "transcription"; text: string }
  | { type: "error"; error: string };
```

with:

```ts
// WebSocket protocol mirrors backend/samantha/api.py:_ws_handler.
// The deprecated "listen"/"transcription" pair was removed frontend-
// side; the backend handler still answers it for old clients until
// its own removal is confirmed separately.
export type WSClientToServer = { type: "chat"; message: string; user_id: string };

export type WSServerToClient =
  | { type: "token"; token: string }
  | { type: "done"; thinking_ms: number }
  | { type: "error"; error: string };
```

- [ ] **Step 4 (L3): `/speak` failures throw instead of silently muting**

In `frontend/src/net/tts.ts`, replace:

```ts
  if (!res.ok || !res.body) return;
```

with:

```ts
  // A dead TTS backend must be a visible error, not a silently mute
  // turn — callers catch and surface a status.
  if (!res.ok) throw new Error(`speak_failed: ${res.status}`);
  if (!res.body) throw new Error("speak_failed: empty_body");
```

And in `ConversationScreen.tsx`, make the caller show it — replace (inside the speak branch, post-Task-24 state):

```ts
        } catch (e) {
          console.warn("speak failed", e);
        } finally {
          clearTimeout(watchdog);
          setIsSpeaking(false);
        }
```

with:

```ts
        } catch (e) {
          console.warn("speak failed", e);
          if (!turnAbort.signal.aborted) {
            setStatusMessage("Me he quedado sin voz un momento — léeme aquí arriba.");
          }
        } finally {
          clearTimeout(watchdog);
          setIsSpeaking(false);
        }
```

- [ ] **Step 5 (L5): Remove the leaked tail-wait abort listener**

In `tts.ts`, replace:

```ts
      await new Promise<void>((resolve) => {
        const t = setTimeout(resolve, remainingS * 1000 + 100);
        signal?.addEventListener("abort", () => {
          clearTimeout(t);
          resolve();
        }, { once: true });
      });
```

with:

```ts
      await new Promise<void>((resolve) => {
        // Named handler so normal completion removes it — the once:
        // true listener otherwise lingers on the signal until GC.
        const onTailAbort = () => {
          clearTimeout(t);
          resolve();
        };
        const t = setTimeout(() => {
          signal?.removeEventListener("abort", onTailAbort);
          resolve();
        }, remainingS * 1000 + 100);
        signal?.addEventListener("abort", onTailAbort, { once: true });
      });
```

- [ ] **Step 6 (L4): Stop reading `getBoundingClientRect` per frame in `Wave.tsx`**

Replace the resize handler:

```ts
    const dpr = Math.min(window.devicePixelRatio, 2);
    const resize = () => {
      const rect = canvas.getBoundingClientRect();
      canvas.width = rect.width * dpr;
      canvas.height = rect.height * dpr;
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.scale(dpr, dpr);
    };
```

with:

```ts
    const dpr = Math.min(window.devicePixelRatio, 2);
    // Cache the CSS size here: getBoundingClientRect() per rAF frame
    // is a forced layout read at 60 fps. The strip containers only
    // change size with the window, which re-triggers this handler.
    let w = 0;
    let h = 0;
    const resize = () => {
      const rect = canvas.getBoundingClientRect();
      w = rect.width;
      h = rect.height;
      canvas.width = w * dpr;
      canvas.height = h * dpr;
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.scale(dpr, dpr);
    };
```

and inside `frame`, replace:

```ts
      const rect = canvas.getBoundingClientRect();
      const w = rect.width;
      const h = rect.height;
      const baseline = h / 2;
```

with:

```ts
      const baseline = h / 2;
```

- [ ] **Step 7 (L6): Hoist `micErrorMessage` into `core/micErrors.ts`**

Create `frontend/src/core/micErrors.ts`:

```ts
// Web Speech recognition error codes → Samantha-voiced Spanish, shared
// by ConversationScreen and OnboardingScreen (it used to be duplicated
// in both, and the copies had already started to drift).
export function micErrorMessage(code: string): string {
  switch (code) {
    case "not-allowed":
    case "service-not-allowed":
      return "No tengo permiso. Permite el micrófono en el navegador.";
    case "no-speech":
      return "No te he oído. Vuelve a intentarlo.";
    case "network":
      return "Sin red — el reconocimiento de voz pasa por el navegador.";
    case "audio-capture":
      return "No encuentro el micrófono.";
    case "aborted":
      return "Captura cancelada.";
    case "speech_recognition_unavailable":
      return "Tu navegador no soporta reconocimiento de voz.";
    default:
      return `Mic: ${code}`;
  }
}
```

In `ConversationScreen.tsx`: delete the local `function micErrorMessage(code: string): string { ... }` block (lines 21-39, identical to the hoisted copy) and add to the imports:

```ts
import { micErrorMessage } from "../core/micErrors";
```

In `OnboardingScreen.tsx`: delete its local `function micErrorMessage(code: string): string { ... }` block (lines 11-29, same body) and add the same import.

- [ ] **Step 8 (L6): Collapse `handleContinue`/`handleSkip` into one `advance()`**

In `OnboardingScreen.tsx`, replace both handlers — the entire block from `const handleContinue = async () => {` through the closing `};` of `handleSkip` (the two functions are line-for-line identical except for what lands in `nextAnswers[idx]` and the `nameRequired` guard) with:

```ts
  // One path for "continuar" (answer = the field's text) and "saltar"
  // (answer = null): store the answer, silence any prompt, and either
  // move to the next question or finalize.
  const advance = async (answer: string | null) => {
    if (nameRequired && !answer) return;
    const nextAnswers = [...answers];
    nextAnswers[idx] = answer;
    setAnswers(nextAnswers);
    setValue("");

    if (speakAbortRef.current) {
      speakAbortRef.current.abort();
      speakAbortRef.current = null;
    }
    SpeechRecognition.stopListening();

    if (idx < QUESTIONS.length - 1) {
      const nextIdx = idx + 1;
      setIdx(nextIdx);
      if (!browserSupportsSpeechRecognition) {
        setStep("review");
        return;
      }
      setStep("speaking");
      const ac = new AbortController();
      speakAbortRef.current = ac;
      try {
        await speak(VOICE_PROMPTS[nextIdx], ac.signal);
        if (!ac.signal.aborted) {
          setStep("listening");
          startListening();
        }
      } catch (e) {
        console.warn("speak failed", e);
        if (!ac.signal.aborted) setStep("review");
      }
    } else {
      setStep("done");
      if (!browserSupportsSpeechRecognition) {
        await finalize(nextAnswers);
        return;
      }
      const ac = new AbortController();
      speakAbortRef.current = ac;
      try {
        await speak(
          "Gracias. Un momento mientras calibro mi configuración... Listo, ya estoy aquí.",
          ac.signal
        );
      } catch (e) {
        console.warn("outro speak failed", e);
      }
      if (!ac.signal.aborted) {
        await finalize(nextAnswers);
      }
    }
  };

  const handleContinue = () => { void advance(value.trim() || null); };
  const handleSkip = () => { void advance(null); };
```

(Guard equivalence: `handleContinue`'s old `if (nameRequired && !value.trim()) return;` and `handleSkip`'s old `if (nameRequired) return;` both collapse into `advance`'s `if (nameRequired && !answer) return;` — skip passes `null`, so `nameRequired` still blocks it.)

- [ ] **Step 9 (L7): `void` the resume; kill the magic 6**

In `ConversationScreen.tsx`, inside the debounce commit's `.then`, replace:

```ts
        if (activeRef.current) {
          // Conversation still active → resume listening.
          SpeechRecognition.startListening({
            continuous: true,
            language: "es-ES",
          });
        }
```

with:

```ts
        if (activeRef.current) {
          // Conversation still active → resume listening.
          void SpeechRecognition.startListening({
            continuous: true,
            language: "es-ES",
          });
        }
```

In `OnboardingScreen.tsx`, replace:

```ts
  const [answers, setAnswers] = useState<(string | null)[]>(Array(6).fill(""));
```

with:

```ts
  const [answers, setAnswers] = useState<(string | null)[]>(
    Array(QUESTIONS.length).fill(""),
  );
```

- [ ] **Step 10: Typecheck, build, commit**

```bash
cd frontend && pnpm typecheck && pnpm build
git add frontend/src/net/wsClient.ts frontend/src/core/types.ts frontend/src/net/tts.ts frontend/src/components/Wave.tsx frontend/src/screens/ConversationScreen.tsx frontend/src/screens/OnboardingScreen.tsx frontend/src/core/micErrors.ts
git commit -m "refactor(frontend): drop dead listen/transcription WS surface, fix leaks and comment rot, dedupe onboarding flow"
```

---

### Task 28: Fase 4 manual smoke test (kiosk behavior)

No automated harness for this by design. With the backend running (`SAMANTHA_MODE=real`) and `pnpm dev` (repeat the barge-in item once more against the built frontend on `http://localhost:7777/` so the vendored assets are exercised from `dist/`):

- [ ] **Busy-lock recovery (Task 20):** stop the TTS server so `/speak` fails, send a message → reply text appears, status "Me he quedado sin voz un momento…" shows, and the NEXT utterance is still processed (mic reopens; `busyRef` released). Then spam Esc during a normal spoken reply several turns in a row — every turn ends cleanly, none sticks in "thinking".
- [ ] **Mic error surfacing + breaker (Task 21):** mid-conversation, revoke the mic permission or unplug the USB mic → a Spanish status appears (not silence), and within ~10 s Samantha hangs up by herself instead of showing a dead "listening" call. Re-granting + tapping the mic works again.
- [ ] **Offline barge-in from vendored assets (Task 22):** DevTools Network tab → confirm requests go to `/vad/silero_vad_legacy.onnx`, `/vad/vad.worklet.bundle.min.js`, and `/ort/ort-wasm-simd-threaded.wasm` (status 200, same-origin) and that NO request touches `cdn.jsdelivr.net`. Interrupt Samantha mid-sentence by voice → TTS stops and your words become the next message.
- [ ] **Hang-up mid-thinking stays silent (Task 24):** ask something long, tap the stop square (or press Esc) while the wave shows "thinking" → the reply appears in the history but is never spoken; no audio starts seconds later.
- [ ] **Post-turn first words survive (Task 24):** immediately after Samantha finishes speaking, start talking with no pause → your full sentence (including the first word) is committed as the next message.
- [ ] **Onboarding answer window (Task 25):** run onboarding by voice (delete the profile first) → after each spoken question, "te escucho…" stays open until you actually stop talking; it never jumps straight to review before you said a word.
- [ ] **Boot auto-recovery (Task 25):** load the UI with the backend stopped → Spanish message in Samantha's voice (no English `fetchProfile failed: …`), and after starting the backend the kiosk proceeds on its own within ~15 s without pressing "reintentar ahora".
- [ ] **Serialized turns (Task 26):** with a turn in flight, hammer Enter in text mode → exactly one reply, no interleaved tokens, no stuck busy state.
- [ ] **Transcript cap (Task 23):** after a long session, check via React DevTools that the store's `transcript` length never exceeds 200 and the history view stays smooth while tokens stream.

---
## Fase 5 — Docs, deploy y CI

### Task 29: CLAUDE.md consolidation — sync stale sections to already-logged decisions

**Bug:** CLAUDE.md is the declared source of truth but §0/§2.6/§3/§5/§6/§9/§11 still describe the v1 stack: Piper `es_ES-davefx-medium`, sounddevice audio I/O, nomic-embed-text embeddings, local Qwen LLM, a `backend/static/` frontend, `audio_capture.py`/`stt.py` files that don't exist, deploy steps that enable `samantha-llamacpp.service` on the kiosk (llama-server runs manually on the 4090 box), "Python 3.12+", and references to `docs/01-setup-ubuntu.md` / `docs/03-design-decisions.md` which don't exist. Every replacement below syncs to decisions already recorded in §12 (2026-05-13 STT/frontend/memory entries, 2026-05-15 Grok entry) or to shipped code (`2f7d6cf` CosyVoice-only, `config.py`). **No decision changes.**

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: §0 TL;DR — stack list (lines 23-34)**

Replace:

```markdown
- **Backend:** Python 3.12 + FastAPI on localhost:7777 (serves frontend AND API)
- **Frontend:** Static HTML/CSS/JS served by FastAPI, rendered by Chromium
- **LLM:** Qwen 3.5-9B Instruct (8GB VRAM target; final model TBD on first run)
- **STT:** faster-whisper Large v3 Turbo
- **TTS:** Piper (Spanish voice preset `es_ES-davefx-medium`)
- **Memory:** ChromaDB with nomic-embed-text embeddings
- **Audio I/O:** sounddevice (Python, native, no browser permissions)
```

with:

```markdown
- **Backend:** Python 3.11 + FastAPI on localhost:7777 (serves frontend AND API)
- **Frontend:** React + Vite + TypeScript in `frontend/`, built to `frontend/dist/`, served by FastAPI (§2.10)
- **LLM:** X.AI Grok API (`grok-4-1-fast-non-reasoning`) by default; local llama-server (Qwen3-8B Q8) as config override (§2.5)
- **STT:** browser Web Speech API (`es-ES`); faster-whisper server-side only in the Phase 11 voice loop (in progress)
- **TTS:** CosyVoice 3 zero-shot voice cloning, served from the 4090 box (`tts-server/cosyvoice/`)
- **Memory:** ChromaDB + SQLite ring + facts; fastembed multilingual MiniLM-L12-v2 embeddings (§2.7)
- **Audio I/O:** browser (Web Speech mic + `<audio>` playback of `/speak`) (§2.8)
```

- [ ] **Step 2: §0 diagram (lines 36-53)**

Replace the `**Two processes, one machine:**` heading and its fenced box with:

````markdown
**Two processes on the kiosk (GPU services live on the 4090 box):**

```
┌────────────────────────────────────────────────────┐
│  Chromium in --kiosk mode (fullscreen, no chrome)  │
│  - Launched by systemd at boot                     │
│  - Loads http://localhost:7777/                    │
│  - Web Speech API mic capture (es-ES)              │
├────────────────────────────────────────────────────┤
│  Python Backend (FastAPI on :7777)                 │
│  - Serves frontend/dist (React build)              │
│  - POST /chat, /speak, /profile (API)              │
│  - WebSocket /ws (streaming conversation)          │
│  - LLM: Grok API (default) or local llama-server   │
│  - TTS: CosyVoice 3 on the 4090 box (:8093)        │
│  - Memory: ChromaDB + SQLite ring (local)          │
└────────────────────────────────────────────────────┘
```
````

- [ ] **Step 3: §2.4 and §6 Python version**

Line 201, replace `**Decision:** Python 3.12 + FastAPI + uvicorn, serving on` with `**Decision:** Python 3.11 + FastAPI + uvicorn, serving on`. Line 593 (§6), replace `- **Version:** 3.12+` with ``- **Version:** 3.11+ (matches pyproject `requires-python >=3.11` and the kiosk venv)``.

- [ ] **Step 4: §2.6 STT/TTS decision (lines 278-284)**

Replace:

```markdown
### 2.6 STT/TTS

**Decision:**
- **STT:** faster-whisper Large v3 Turbo (~1.5GB model, runs on GPU
  when LLM is not actively generating)
- **TTS:** Piper with voice `es_ES-davefx-medium` (~40MB, CPU-only,
  ~200ms latency)
```

with:

```markdown
### 2.6 STT/TTS

**Decision (as evolved via the §12 log):**
- **STT:** browser Web Speech API (`webkitSpeechRecognition`, `es-ES`)
  — default since 2026-05-13, see §2.8. faster-whisper runs server-side
  only inside the Phase 11 voice loop (in progress).
- **TTS:** CosyVoice 3 (`Fun-CosyVoice3-0.5B-2512`) zero-shot voice
  cloning, served by `tts-server/cosyvoice/` on the 4090 box (port
  8093). Reference WAV + literal transcript deploy to
  `~/.samantha/voices/ref/samantha.{wav,txt}` (repo copies in
  `voices/`). Piper and XTTS-v2 backends were removed (commit
  `2f7d6cf`).
```

- [ ] **Step 5: §3 project structure — replace the whole fenced tree (lines 372-413)**

````markdown
```
samantha/
├── CLAUDE.md                   ← This file. Read first.
├── PROGRESS.md                 ← Phase completion log (you update this)
├── README.md                   ← Brief overview for humans
│
├── backend/                    ← The application (Python 3.11)
│   ├── pyproject.toml
│   ├── README.md
│   ├── samantha/
│   │   ├── __init__.py
│   │   ├── api.py              ← FastAPI app + endpoints + /ws + frontend/dist serving
│   │   ├── config.py           ← Env-var-based config (SAMANTHA_*)
│   │   ├── schemas.py          ← Pydantic models (API contract)
│   │   ├── mock_llm.py         ← Pattern-matched mock responses
│   │   ├── real_llm.py         ← OpenAI-compat streaming client (Grok / llama-server / hermes)
│   │   ├── context.py          ← gather_context (facts + recall + short-term)
│   │   ├── tts.py              ← CosyVoice 3 streaming client
│   │   ├── voice_pipeline.py   ← Pipecat server-side voice loop (Phase 11, in progress)
│   │   ├── memory.py           ← ChromaDB + fastembed long-term memory
│   │   ├── short_term.py       ← SQLite ring buffer (last N turns)
│   │   ├── profile.py          ← Facts facade over Memory
│   │   └── personality.py      ← System prompt + persona
│   └── tests/                  ← pytest suite (conftest disables memory persistence)
│
├── frontend/                   ← React + Vite + TypeScript (§2.10); pnpm only
│   └── src/                    ← components/ core/ net/ screens/ styles/
│
├── tts-server/
│   └── cosyvoice/              ← CosyVoice 3 docker overlay (runs on the 4090 box)
│
├── voices/                     ← Reference voice assets (deploy → ~/.samantha/voices/ref/)
│
├── systemd/                    ← User units for kiosk deployment
│   ├── samantha-backend.service    ← Python backend
│   ├── samantha-ui.service         ← Chromium kiosk launcher
│   ├── samantha-hermes.service     ← Hermes-Agent gateway (Phase 9)
│   └── samantha-llamacpp.service   ← OPTIONAL local-LLM fallback (normally manual, 4090 box)
│
└── docs/
    ├── personality.md          ← The soul (§7)
    ├── 02-system-prompt-iterations.md
    ├── mockups/                ← Historical HTML mockups
    └── superpowers/            ← Specs + implementation plans
```
````

- [ ] **Step 6: §5 dev workflow + deployment**

Line 551, replace `cd frontend && npm run dev` with `cd frontend && pnpm dev`. Then replace the deployment block (lines 572-584):

```bash
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

with:

```bash
# 4. Install systemd services (backend + kiosk UI; hermes optional).
#    samantha-llamacpp.service is NOT enabled: the default LLM is the
#    Grok API, and the local fallback llama-server runs MANUALLY on the
#    separate 4090 box (see the unit's header comment).
cp systemd/*.service ~/.config/systemd/user/
systemctl --user enable samantha-backend.service
systemctl --user enable samantha-ui.service
loginctl enable-linger samantha    # Services start without login

# 5. Enable auto-login on tty1
sudo systemctl edit getty@tty1
# (TODO: docs/01-setup-ubuntu.md is not yet written — the auto-login
#  drop-in lives in the operator's host notes for now)

# 6. Reboot — Samantha takes over the screen
sudo reboot
```

- [ ] **Step 7: §9 critical-files table — replace rows (lines 708-721)**

```markdown
| Feature / topic | Files |
|---|---|
| API endpoints | `backend/samantha/api.py` |
| Data contract | `backend/samantha/schemas.py` |
| Mock responses | `backend/samantha/mock_llm.py` |
| Real LLM | `backend/samantha/real_llm.py`, `personality.py` |
| Memory (3 layers) | `backend/samantha/memory.py`, `short_term.py`, `profile.py`, `context.py` |
| TTS client (CosyVoice 3) | `backend/samantha/tts.py`, `tts-server/cosyvoice/` |
| Voice loop (Phase 11) | `backend/samantha/voice_pipeline.py` |
| The wave visualizer | `frontend/src/components/Wave.tsx` |
| The OS1 loader (cinta) | `frontend/src/components/OS1Loader.tsx` |
| Screen state machine | `frontend/src/core/store.ts`, `frontend/src/screens/` |
| WebSocket client | `frontend/src/net/wsClient.ts` |
| Server config | `backend/samantha/config.py` |
| systemd services | `systemd/*.service` |
| Setup guide (Phase 7) | TODO — `docs/01-setup-ubuntu.md` not yet written |
```

- [ ] **Step 8: §8 always-do list — drop the contradicted vanilla-JS rule**

§8 still orders "Keep frontend in vanilla JS (no React, no build tools)",
which §2.10 and the 2026-05-13 log entry reversed. An agent reading §8 as
binding would refuse to touch `frontend/src`. Replace:

```markdown
- Keep frontend in vanilla JS (no React, no build tools)
```

with:

```markdown
- Keep the frontend on React + Vite + TypeScript with pnpm (§2.10) — never
  run `npm` in `frontend/`
```

- [ ] **Step 9: §11 references — swap the dead Piper line**

Replace `- **Piper TTS:** https://github.com/rhasspy/piper` with `- **CosyVoice:** https://github.com/FunAudioLLM/CosyVoice`.

- [ ] **Step 10: Append a §12 entry** — insert directly after `Significant decisions made during development. Append-only.` (newest entries sit at the top of the log):

```markdown
### 2026-08-04 — Docs-sync: CLAUDE.md realigned with shipped reality

**Decision:** No architecture change. §0, §2.4, §2.6, §3, §5, §6, §9
and §11 rewritten to match decisions already recorded in this log and
in the code: Grok API default LLM (2026-05-15), browser Web Speech STT
(2026-05-13), React frontend in `frontend/` (2026-05-13), fastembed
multilingual embeddings (2026-05-13), CosyVoice 3 as the only TTS
backend (commit `2f7d6cf`, config in `backend/samantha/config.py`),
Python floor 3.11 (pyproject + kiosk venv), and
`samantha-llamacpp.service` marked optional/other-host (llama-server
runs manually on the 4090 box).

**Rationale:** The file is the declared source of truth but still
described the v1 Piper/sounddevice/`backend/static/` stack; agents and
humans reading it were being actively misled.

**Cost:** None — text only. Missing setup docs are marked TODO instead
of being silently referenced.
```

- [ ] **Step 11: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: sync CLAUDE.md with shipped reality (no decision changes)"
```

---

### Task 30: systemd unit fixes — restart semantics, bounded startup, honest ordering docs

**Bug:** (a) `samantha-ui.service` uses `Restart=on-failure`, so a *clean* Chromium exit leaves a black screen on an appliance forever; its `ExecStartPre` curl loop is unbounded (`until ...; do sleep 1; done`) against the default 90 s `TimeoutStartSec`; and `After=samantha-backend.service` cannot order against X/openbox, which start outside systemd via `.xinitrc`. (b) `samantha-backend.service` orders on `network-online.target`, which is not populated in the *user* manager — inert lines that look load-bearing. (c) `samantha-llamacpp.service` carries no hint that it is optional/other-host (Grok is the default; llama-server runs manually on the 4090 box) and passes `--split-mode row`, a multi-GPU tensor-split flag, on single-GPU hosts.

**Files:**
- Modify: `systemd/samantha-ui.service`
- Modify: `systemd/samantha-backend.service`
- Modify: `systemd/samantha-llamacpp.service`

- [ ] **Step 1: Rewrite `systemd/samantha-ui.service`** with this full content:

```ini
# Chromium kiosk pointed at the backend. Waits for /ping so the user
# never sees a connection-refused page at boot.
#
# X11 NOTE: this unit cannot order against X/openbox — they start
# OUTSIDE systemd (tty1 auto-login → ~/.bash_profile → startx →
# ~/.xinitrc). DISPLAY=:0 must already exist when this unit runs;
# start it from ~/.xinitrc after openbox is up (or let Restart= retry
# until X exists). After=samantha-backend.service below orders only
# against the backend, nothing else.
#
# Install:
#   1. Copy this file to ~/.config/systemd/user/, then:
#        systemctl --user daemon-reload
#        systemctl --user enable --now samantha-ui.service
#
# Override defaults without editing this file:
#   systemctl --user edit samantha-ui
# and set Environment= lines in the override.

[Unit]
Description=Samantha UI (Chromium kiosk)
After=samantha-backend.service
Wants=samantha-backend.service

[Service]
Type=simple
Environment=DISPLAY=:0
# Bounded wait: 150 × 1 s, kept below TimeoutStartSec so a dead backend
# fails this unit visibly instead of wedging ExecStartPre forever.
ExecStartPre=/bin/sh -c 'i=0; while [ $i -lt 150 ]; do curl -fsS http://127.0.0.1:7777/ping >/dev/null 2>&1 && exit 0; i=$((i+1)); sleep 1; done; echo "backend never answered /ping" >&2; exit 1'
ExecStart=/usr/bin/chromium-browser \
  --kiosk \
  --noerrdialogs \
  --disable-infobars \
  --no-first-run \
  --use-fake-ui-for-media-stream \
  --app=http://localhost:7777/
# always, not on-failure: on an appliance, a CLEAN Chromium exit
# (crashed-tab dance, stray Alt+F4, kiosk escape) must also bring the
# UI back — Restart=on-failure would leave a black screen.
Restart=always
RestartSec=3
TimeoutStartSec=180

[Install]
WantedBy=default.target
```

- [ ] **Step 2: Document the inert ordering in `samantha-backend.service`** — replace:

```ini
[Unit]
Description=Samantha backend (FastAPI on :7777)
After=network-online.target
Wants=network-online.target
```

with:

```ini
[Unit]
Description=Samantha backend (FastAPI on :7777)
# NOTE: network-online.target is effectively inert in the *user*
# manager (no NetworkManager-wait-online there) — kept for documentary
# value only. Real resilience is Restart= below: the backend simply
# retries until the LAN (4090 box: TTS) and the internet (Grok API)
# are reachable; both are probed lazily per request anyway.
After=network-online.target
Wants=network-online.target
```

- [ ] **Step 3: Mark `samantha-llamacpp.service` optional and drop the multi-GPU flag** — replace the header:

```ini
# Samantha LLM runtime — llama-server (llama.cpp)
#
# Install (production):
```

with:

```ini
# Samantha LLM runtime — llama-server (llama.cpp)
#
# OPTIONAL — NOT part of the default kiosk deploy. The default LLM
# path is X.AI's Grok API (CLAUDE.md §2.5); the local fallback
# llama-server normally runs MANUALLY on the separate 4090 box, not as
# a systemd unit on the kiosk. Keep this file only as a reference for
# a fully-local, single-box install.
#
# Install (production):
```

and in `ExecStart`, replace:

```ini
    --jinja \
    --flash-attn auto \
    --split-mode row \
    --temp 0.6 \
```

with:

```ini
    --jinja \
    --flash-attn auto \
    --temp 0.6 \
```

(`--split-mode row` splits tensors across multiple GPUs; both candidate hosts — kiosk RTX 4070 Mobile and the 4090 box — are single-GPU, where the flag is at best a no-op.)

- [ ] **Step 4: Validate syntax where possible**

```bash
command -v systemd-analyze >/dev/null && systemd-analyze verify systemd/*.service || echo "no systemd on this host — validate on the kiosk box"
```

(macOS has no systemd — skipping locally is expected; Task 33 re-checks.)

- [ ] **Step 5: Commit**

```bash
git add systemd/samantha-ui.service systemd/samantha-backend.service systemd/samantha-llamacpp.service
git commit -m "fix(systemd): kiosk restarts on clean exit, bounded startup wait, honest unit docs"
```

---

### Task 31: Delete the leftover XTTS server

> ⚠ Borra un directorio — confirmar con el usuario antes de ejecutar.

**Bug:** `tts-server/xtts/` (tracked: `docker-compose.yml`, `main.py`) is a leftover from before commit `2f7d6cf` ("refactor(tts): drop xtts and piper backends, CosyVoice 3 only"). No code references it — verified: `backend/samantha/` has zero `xtts` mentions; the only hits are historical text in `docs/superpowers/plans/*` and PROGRESS, which stay.

**Files:**
- Delete: `tts-server/xtts/` (whole directory, plus its untracked `__pycache__/`)

- [ ] **Step 1: Re-verify nothing live references it**

```bash
cd "/Volumes/Macintosh SSD - Daten/Users/horelvis/git/os1-samantha"
grep -rn "xtts" --include="*.py" --include="*.yml" --include="*.md" --include="*.toml" backend/ systemd/ docs/ tts-server/ | grep -v "tts-server/xtts/"
```

Expected: hits only in `docs/superpowers/plans/2026-06-11-bugfix-sweep.md` and `docs/superpowers/plans/2026-08-04-improvement-sweep.md` (historical plan text — keep). Any hit in `backend/`, `systemd/`, or `tts-server/cosyvoice/` means STOP and investigate.

- [ ] **Step 2: Delete (after user confirmation)**

```bash
git rm -r tts-server/xtts
rm -rf tts-server/xtts   # sweeps the untracked __pycache__/ remnant
```

- [ ] **Step 3: Commit**

```bash
git commit -m "chore(tts): delete leftover xtts server (CosyVoice 3 only since 2f7d6cf)"
```

---

### Task 32: Minimal CI — GitHub Actions for backend and frontend

> 🚫 **NO APROBADA — NO EJECUTAR.** El usuario revisó las tareas con marcador
> el 2026-08-05 y aprobó todas menos esta. Se conserva escrita por si cambia
> de opinión; el resto del plan no depende de ella (ver Task 33 Step 6).

**Bug:** No CI exists (`.github/` absent). The suite is CI-safe: `backend/tests/conftest.py` sets `SAMANTHA_MEMORY_ENABLED=false` before app import so integration tests never persist to `$HOME`; dedicated Memory tests use `tmp_path` (they do construct the fastembed embedder — a one-time model download, cached below); `test_voice_pipeline.py` injects a fake model onto `WhisperSTTProcessor._model` specifically to avoid importing ctranslate2/torch (verified: its docstring at line 108-112 says exactly this), so no GPU is needed; the pipecat import-crash risk left with `test_pipecat_imports.py` (deleted in Task 3). Install target verified against `backend/pyproject.toml`: extra is named `dev` (`pytest`, `httpx`, `ruff`), so `pip install -e ".[dev]"` from `backend/`. Frontend verified against `frontend/package.json`: scripts `typecheck` (`tsc --noEmit`) and `build` (`tsc -b && vite build`); `pnpm-lock.yaml` exists; esbuild's postinstall is already whitelisted via `pnpm.onlyBuiltDependencies`, so no `approve-builds` step is needed in CI.

Ordering note: Tasks 3 (test deletion), 4 (numpy pin) and 14 (commits `voice_pipeline.py` + `test_voice_pipeline.py`) must have landed first — otherwise CI checks out a tree whose test suite differs from the local one.

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: Confirm the suite is green locally first** (CI must not be born red)

```bash
cd backend && pytest tests/ -v && ruff check . && cd ../frontend && pnpm typecheck && pnpm build && cd ..
```

- [ ] **Step 2: Create `.github/workflows/ci.yml`**

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:

jobs:
  backend:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: backend
    env:
      # Pin fastembed's model cache so actions/cache can persist the
      # one-time multilingual MiniLM download (~130 MB).
      FASTEMBED_CACHE_PATH: /home/runner/.cache/fastembed
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip
          cache-dependency-path: backend/pyproject.toml
      - name: Cache fastembed embedding model
        uses: actions/cache@v4
        with:
          path: /home/runner/.cache/fastembed
          key: fastembed-paraphrase-multilingual-MiniLM-L12-v2
      - name: Install backend (editable + dev extra)
        run: pip install -e ".[dev]"
      - name: Lint
        run: ruff check .
      - name: Tests
        run: pytest tests/ -v

  frontend:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: frontend
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 20
      - name: Enable pnpm (corepack)
        run: corepack enable && corepack prepare pnpm@latest --activate
      - name: Install
        run: pnpm install --frozen-lockfile
      - name: Typecheck
        run: pnpm typecheck
      - name: Build
        run: pnpm build
```

- [ ] **Step 3: Sanity-check the YAML parses**

```bash
backend/.venv/bin/python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/ci.yml')); print('yaml ok')" \
  || python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml')); print('yaml ok')"
```

(If PyYAML isn't available in either interpreter, skip — GitHub validates on push.)

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add GitHub Actions workflow (backend pytest+ruff, frontend typecheck+build)"
```

---

### Task 33: Final verification pass

- [ ] **Step 1: Full backend suite from clean**: `cd backend && pytest tests/ -v` — all green (no skips introduced by this sweep).
- [ ] **Step 2: Lint + format**: `cd backend && ruff check . && ruff format --check .` — clean.
- [ ] **Step 3: Frontend**: `cd frontend && pnpm typecheck && pnpm build` — clean.
- [ ] **Step 4: systemd**: `command -v systemd-analyze >/dev/null && systemd-analyze verify systemd/*.service || echo "no systemd here — verify on the kiosk box"` (expected to skip on macOS; run for real on the kiosk at next deploy).
- [ ] **Step 5: Secret re-check at HEAD**: `git grep -I "samantha-api-secret-key" -- . | grep -E "key-[0-9]{4}"` must return nothing (only truncated needles may remain, per Task 1).
- [ ] **Step 6: SKIP — Task 32 (CI) was not approved**, so there is no workflow to check. Confirm no `.github/` directory was created: `test -d .github && echo "UNEXPECTED — Task 32 was not approved" || echo "ok, no CI"`.
- [ ] **Step 7: Update `PROGRESS.md`** — insert at the top (below the title line), following the file's newest-first format:

```markdown
## 2026-08-04 — Improvement Sweep ✅

Full-project sweep from the 2026-08-04 review (plan:
`docs/superpowers/plans/2026-08-04-improvement-sweep.md`): security/
hygiene quick wins, backend correctness, Phase 11 voice-pipeline
defects, frontend robustness, docs/deploy/CI.

**Fase 1:** burned hermes key redacted from tracked docs (rotation
confirmed with user: <sí/no — fill from Task 1 Step 4>); voice assets
renamed to match config (`voices/samantha.{wav,txt}` + README); repo
strays resolved (bugfix-sweep plan tracked, pipecat smoke test
deleted, mockup archived to `docs/mockups/`, Phases 5/7 backfilled);
pyproject/config hygiene (dead `sounddevice` extra removed, numpy<2
pin, stale comments fixed, LAN-IP default flagged).

**Fase 5:** CLAUDE.md synced with shipped reality (no decision
changes; §12 entry 2026-08-04); systemd fixes (kiosk Restart=always,
bounded /ping wait + TimeoutStartSec=180, llamacpp marked
optional/other-host, `--split-mode row` dropped); leftover
`tts-server/xtts/` deleted; GitHub Actions CI added (backend
pytest+ruff on 3.11, frontend pnpm typecheck+build on Node 20).

**Changed files:** fill from `git log --name-only --oneline` since the
sweep's first commit, one line per fase.

**Tests:** <N> passed (backend), tsc clean, pnpm build succeeds.

**Notes:** append the middle-fase summaries (backend correctness,
voice pipeline, frontend) from their tasks' commit messages.
```

Fill every `<...>` from the actual run before committing — the entry must ship with real values, not markers.

- [ ] **Step 8: Commit**

```bash
git add PROGRESS.md
git commit -m "docs: log 2026-08-04 improvement sweep in PROGRESS"
```
