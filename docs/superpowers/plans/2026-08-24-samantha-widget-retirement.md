# samantha-widget (plan 3) — the retirement

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The Chromium kiosk, `backend/` and `frontend/` leave the repo,
and JARVIS keeps working without them — verified by him hearing a human
being first.

**Architecture:** Nothing is deleted until Task 1 proves he works with a
real microphone. Then the two things that outlive `backend/` are moved
out of it — `samantha.tts` into the Hermes voice plugin that already
owns speech — the adapter stops serving a frontend BEFORE the frontend
is deleted, the kiosk units are stopped and left off for a day, and only
then does `git rm` run, one commit per piece.

**Tech Stack:** Python 3.12, pytest, systemd user units, git.

**Spec:** `docs/superpowers/specs/2026-08-23-samantha-widget-gtk4-design.md`
§7 (build order — this is plan 3), §8 (scope: "Deleting anything. All of
it is plan 3"), §11 (decision-log entries owed).

**Depends on:** plan 1 landed; plan 2 landed except its Task 8, which is
this plan's Task 1.

**Already closed, ahead of this plan:** the spec's §9 risk "Hermes
replies in its own persona, not Samantha's" was marked "resolved in
plan 3" and was in fact resolved on 2026-08-23 (commits `fcd9637`,
`978b947`): the persona rides in on `platform_hint`, and the system
prompt is fixed when the session is born. Nothing here needs to revisit
it. Likewise CLAUDE.md §1/§2.3/§2.8, which §7 of the spec assigned to
plan 3, were rewritten on 2026-08-24 (`0b694e2`) — Task 6 finishes what
that commit could not, because the code was still present then.

## Global Constraints

- **Task 1 is a lock, not a formality.** No task in this plan may run
  until Task 1 has passed with a real microphone and a real voice. If
  Task 1 fails, stop: the kiosk is still installed and still works, and
  that is the fallback this ordering exists to preserve.
- **Task 3 MUST land before Task 5.** `adapter.py:301-320` checks that
  `frontend/dist/index.html` and `assets/` exist and refuses to start
  the platform if either is missing — non-retryably. Deleting
  `frontend/` first takes `/ws` down with it, and the widget has no
  gateway to talk to.
- **`samantha.tts` moves to `Hermes/plugins/samantha_voice/tts.py`, not
  into the widget.** Three files in that plugin already import it
  (`announce.py:31`, `sync_provider.py:44`, `provider.py:14`) and so
  does the widget (`speech.py:189`). The plugin owns speech; the widget
  is one more consumer.
- **`tts.py` is CosyVoice-only already.** There is no Piper and no XTTS
  in it to remove — `stream()` calls `_stream_cosyvoice` and nothing
  else. Move it whole; do not "port" or rewrite it.
- **Keep `synth()`.** It looks like dead weight next to `stream()` and
  is not: `sync_provider.py:107` and `announce.py:35` call it.
- **One commit per deleted directory.** A revert must be able to bring
  back `frontend/` without bringing back `backend/`.
- **`user_id` is exactly `"primary"`** and the WebSocket is
  `ws://127.0.0.1:7777/ws`, unchanged by this plan.
- Identifiers and comments in **English**, user-facing strings in
  **Spanish** (CLAUDE.md §2.9).
- `ruff check` / `ruff format` and the full `pytest` gate every commit.

## What has already been run

Written 2026-08-24, after these were verified against the tree:

- `Hermes/plugins/samantha_voice/{announce,sync_provider,provider}.py`
  import `samantha.tts` — grepped, not assumed. This is why the module
  moves there and not into `widget/`.
- `Hermes/run-gateway.sh:33` exports
  `PYTHONPATH="$REPO_ROOT/backend:$REPO_ROOT"`, and
  `systemd/samantha-widget.service` exports the same pair. Both lose
  their `backend` half in Task 2 and keep the repo root, which
  `Hermes.plugins.samantha_voice.markers` needs.
- `backend/samantha/tts.py` imports only `asyncio`, `io`, `wave`,
  `pathlib`, `typing`, `httpx`, `loguru` and `.config`. The only
  `backend` coupling to break is `config`.
- `adapter.py` registers exactly three routes: `/ws`, `/assets` and
  `/`. Two of them serve a browser that will not exist.

**Not verified, and Task 1 exists to verify it:** that he hears a human
voice at all. Everything downstream of the microphone was proved with
`SAMANTHA_WIDGET_FAKE_MIC`; the microphone itself has never carried
sound on this box.

---

## File Structure

| File | Responsibility | Fate |
|---|---|---|
| `Hermes/plugins/samantha_voice/tts.py` | CosyVoice client: `stream`, `synth`, `new_client`, `is_available`. | **Created** (moved from `backend/samantha/tts.py`) |
| `Hermes/plugins/samantha_voice/tts_config.py` | The five CosyVoice settings, read from the environment. | **Created** (extracted from `backend/samantha/config.py`) |
| `Hermes/plugins/samantha_voice/test_tts.py` | The TTS tests that survive the move. | **Created** (moved from `backend/tests/test_tts.py`) |
| `Hermes/plugins/samantha_kiosk/adapter.py` | The WebSocket surface. Loses `static_root`, `/assets`, `/` and `_index`. | Modified |
| `widget/samantha_widget/speech.py:189` | `from samantha import tts` → the new home. | Modified |
| `systemd/samantha-widget.service` | `PYTHONPATH` loses its `backend` half. | Modified |
| `Hermes/run-gateway.sh` | Same. | Modified |
| `backend/`, `frontend/` | — | **Deleted** (Task 5) |
| `systemd/samantha-{backend,ui}.service` | — | **Deleted** (Task 5) |
| `CLAUDE.md`, `README.md`, the widget spec | Stop describing the dead. | Modified (Task 6) |

---

## Task 1: Prove he hears a human being

> **This task is the lock.** Nothing else in this plan may run until it
> passes. It needs the microphone that is on its way, and it needs you
> to talk out loud — there is no way to automate it, and faking it is
> what this whole plan is designed not to trust.

**Files:** none. This task writes no code.

- [ ] **Step 1: Plug the microphone in and find out what PortAudio calls it**

```bash
cd /home/nexus/git/os1-samantha/widget
PYTHONNOUSERSITE=1 .venv/bin/python -c \
  "import sounddevice as sd; print(sd.query_devices())"
```

Expected: a capture device that is not "dummy" and not the HDMI sink.
Note its name — the widget opens PortAudio's **default** device
(`audio.py:143`, no `device=` argument), so if the default is wrong,
fix it at the system level before going further:

```bash
wpctl status                      # find the source's id
wpctl set-default <id>            # PipeWire, which is what runs here
```

- [ ] **Step 2: Confirm the input is no longer digital silence**

```bash
cd /home/nexus/git/os1-samantha/widget
PYTHONNOUSERSITE=1 .venv/bin/python - <<'PY'
import numpy as np, sounddevice as sd
print("Say something for three seconds...")
rec = sd.rec(int(3 * 16000), samplerate=16000, channels=1, dtype="int16")
sd.wait()
rms = float(np.sqrt(np.mean(rec.astype(np.float32) ** 2)))
print(f"RMS = {rms:.4f}")
PY
```

Expected: a number comfortably above zero. **`RMS = 0.0000` is the
failure this box has shown all along** — an unmuted source producing
digital silence. If you see it, the microphone is not reaching
PortAudio and no amount of widget debugging will change that.

- [ ] **Step 3: Start him with the gateway up, and talk to him**

```bash
systemctl --user status samantha-hermes.service   # must be running
systemctl --user restart samantha-widget.service
journalctl --user -u samantha-widget.service -f
```

Say one sentence out loud. In the log, expect in order: the chosen
device name, an utterance closing, a transcription that matches what
you said, and clauses being synthesised.

- [ ] **Step 4: Interrupt him mid-sentence**

Ask him something that takes a few seconds to say, and start talking
over him. Barge-in is already implemented (`turn.py:51-55`,
`speech.py:174`, `audio.py:226`); this proves it works against a real
room rather than a synthesised one.

Expected: he stops mid-word, the strip leaves `speaking`, and your
interruption becomes the next turn. **Watch for the failure this cannot
be tested without a room:** if he hears himself through the speakers and
answers himself, the microphone gate is not holding and that is a bug to
fix before anything is deleted.

- [ ] **Step 5: Write down what happened**

Append to `PROGRESS.md` under a `## 2026-XX-XX — Plan 2 Task 8` heading:
what you said, what he transcribed, what he answered, and whether
barge-in worked. Verbatim, including anything that went wrong.

- [ ] **Step 6: Decide, explicitly**

If he heard you and answered: this plan is unlocked. If he did not:
**stop here**. Fix it first, with the kiosk still installed and the
fallback `systemctl --user start samantha-ui.service` intact.

- [ ] **Step 7: Commit**

```bash
git add PROGRESS.md
git commit -m "docs: he heard somebody, and what it took"
```

---

## Task 2: `samantha.tts` changes address

**Files:**
- Create: `Hermes/plugins/samantha_voice/tts.py` (moved)
- Create: `Hermes/plugins/samantha_voice/tts_config.py`
- Create: `widget/tests/test_tts.py` (moved, adapted)
- Modify: `Hermes/plugins/samantha_voice/{announce,sync_provider,provider}.py`
- Modify: `widget/samantha_widget/speech.py:189`
- Modify: `systemd/samantha-widget.service`, `Hermes/run-gateway.sh`

**Interfaces:**
- Produces: `Hermes.plugins.samantha_voice.tts` with the same public API
  it has today — `OUTPUT_SAMPLE_RATE: int = 24000`, `VoiceMissingError`,
  `new_client() -> httpx.AsyncClient`, `is_available() -> bool`,
  `stream(text: str, *, client: httpx.AsyncClient | None = None) ->
  AsyncIterator[tuple[bytes, str]]`, `synth(text: str) -> tuple[bytes,
  str]`, `aclose() -> None`. Nothing is renamed; only the import path
  changes.
- Consumes: nothing from other tasks.

- [ ] **Step 1: Move the module with its history**

```bash
cd /home/nexus/git/os1-samantha
git mv backend/samantha/tts.py Hermes/plugins/samantha_voice/tts.py
```

`git mv` rather than copy-and-delete: this file's comments record
measurements against the live CosyVoice server (the short-text failure
rates on 2026-08-22), and `git log --follow` has to keep reaching them.

- [ ] **Step 2: Give it a config of its own**

The module's only tie to `backend/` is `from .config import config`,
which pulls a 216-line dataclass for five fields. Create
`Hermes/plugins/samantha_voice/tts_config.py`:

```python
"""The five settings tts.py needs, read from the environment.

Extracted from backend/samantha/config.py when backend/ was retired
(plan 3, 2026-08-24). The names of the environment variables are
unchanged — SAMANTHA_TTS_COSYVOICE_* — because they are set on the
kiosk box, in systemd units and in Hermes' config, and renaming them
would break a running system to gain nothing.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class TTSConfig:
    # CosyVoice 3 (Fun-CosyVoice3-0.5B-2512) with our server overlay.
    # Loopback since 2026-08-22: GPU and container are on this machine.
    # Split them again (CI, a laptop driving a remote GPU) with
    # SAMANTHA_TTS_COSYVOICE_URL=http://<your-gpu-host>:8093
    url: str = "http://127.0.0.1:8093"
    # Per-read timeout, not a whole-body cap: a healthy stream never
    # trips it, a wedged server fails loudly instead of hanging.
    timeout_s: float = 60.0
    # ~8 s of his voice, and the literal transcript of it. Zero-shot
    # needs both: cross_lingual discards prompt_text and sounds robotic.
    ref_wav: str = "~/.samantha/voices/ref/samantha.wav"
    ref_transcript_path: str = "~/.samantha/voices/ref/samantha.txt"
    # Character given to the VOICE, not to the words: a system prompt
    # before <|endofprompt|> that conditions delivery. Empty keeps the
    # server's own "You are a helpful assistant."
    voice_prompt: str = ""

    @classmethod
    def from_env(cls) -> "TTSConfig":
        def _get(key: str, default):
            val = os.environ.get(f"SAMANTHA_TTS_COSYVOICE_{key}")
            if val is None:
                return default
            if isinstance(default, float):
                return float(val)
            return val

        return cls(
            url=_get("URL", cls.url),
            timeout_s=_get("TIMEOUT_S", cls.timeout_s),
            ref_wav=_get("REF_WAV", cls.ref_wav),
            ref_transcript_path=_get("REF_TRANSCRIPT_PATH", cls.ref_transcript_path),
            voice_prompt=_get("VOICE_PROMPT", cls.voice_prompt),
        )


config = TTSConfig.from_env()
```

- [ ] **Step 3: Point `tts.py` at it**

In `Hermes/plugins/samantha_voice/tts.py`, replace the import:

```python
# was: from .config import config
from .tts_config import config
```

Then rename the five attribute accesses, which lose their now-redundant
prefix. There are **12 occurrences**, counted 2026-08-24:

| Was | Becomes | Times | Where |
|---|---|---|---|
| `config.tts_cosyvoice_timeout_s` | `config.timeout_s` | 4 | `new_client` |
| `config.tts_cosyvoice_url` | `config.url` | 2 | `is_available`, `_stream_cosyvoice` |
| `config.tts_cosyvoice_ref_wav` | `config.ref_wav` | 2 | `is_available`, `_load_cosyvoice_refs` |
| `config.tts_cosyvoice_ref_transcript_path` | `config.ref_transcript_path` | 2 | same two |
| `config.tts_cosyvoice_voice_prompt` | `config.voice_prompt` | 2 | `_stream_cosyvoice` |

A single `sed` does it, since every name gains the same prefix removal:

```bash
sed -i 's/config\.tts_cosyvoice_/config./g' \
  Hermes/plugins/samantha_voice/tts.py
```

Verify none was missed:

```bash
grep -n 'tts_cosyvoice' Hermes/plugins/samantha_voice/tts.py
```

Expected: no output.

- [ ] **Step 4: Repoint the four consumers**

```bash
cd /home/nexus/git/os1-samantha
sed -i 's/^from samantha import tts$/from . import tts/' \
  Hermes/plugins/samantha_voice/announce.py \
  Hermes/plugins/samantha_voice/sync_provider.py \
  Hermes/plugins/samantha_voice/provider.py
grep -rn 'from samantha import tts\|from \. import tts' Hermes/plugins/samantha_voice/
```

Expected: three `from . import tts`, no `from samantha`.

Note that `announce.py:31` has its import inside a function; the anchored
`sed` above only matches a line with no indentation, so **check it by
hand** and fix it if it was skipped:

```bash
grep -n 'import tts' Hermes/plugins/samantha_voice/announce.py
```

Then the widget, in `widget/samantha_widget/speech.py:189`:

```python
    async def say(self, clause: str) -> None:
        from Hermes.plugins.samantha_voice import tts
```

The widget already reaches `Hermes.plugins.samantha_voice.markers` this
way (`speech.py:20`), so this needs no new path — it needs one fewer.

- [ ] **Step 5: Move the tests to a runner that exists**

`Hermes/` has no pytest configuration; `widget/` does
(`pyproject.toml:44`, `testpaths = ["tests"]`). Move the file there:

```bash
git mv backend/tests/test_tts.py widget/tests/test_tts.py
```

Then adapt it. Three of the seven tests were about the shared client
policy that only uvicorn used (`test_tts_shared_client_reused_and_closed`,
`test_synth_does_not_touch_the_shared_client`,
`test_shared_client_is_rebuilt_when_the_running_loop_changed`) — keep
them: `_get_client` survives the move, and the loop-mismatch bug they
pin is exactly the one the widget can still hit.

The import at the top changes, and so does what the monkeypatched
config looks like:

```python
from Hermes.plugins.samantha_voice import tts
from Hermes.plugins.samantha_voice.tts_config import TTSConfig


def test_is_available_false_when_refs_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(
        tts,
        "config",
        TTSConfig(
            ref_wav=str(tmp_path / "nope.wav"),
            ref_transcript_path=str(tmp_path / "nope.txt"),
        ),
    )
    assert tts.is_available() is False
```

Apply the same shape to `test_is_available_reflects_disk_state` and
`test_synth_raises_when_refs_missing`, which monkeypatch the same two
paths.

- [ ] **Step 6: Run them**

```bash
cd /home/nexus/git/os1-samantha/widget
PYTHONNOUSERSITE=1 PYTHONPATH=$PWD/.. .venv/bin/python -m pytest tests/test_tts.py -v
```

Expected: 7 passed. Note `PYTHONPATH` no longer names `backend`.

- [ ] **Step 7: Take `backend` out of both PYTHONPATHs**

In `systemd/samantha-widget.service`, the line becomes:

```
# Hermes' markers.py and tts.py, the same way Hermes/run-gateway.sh
# reaches them. Without this she runs and is mute: speech.py falls back
# to a local copy of has_unclosed_tag, so the only symptom is silence.
Environment=PYTHONPATH=%h/git/os1-samantha
```

In `Hermes/run-gateway.sh:33`:

```bash
export PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}"
```

And update the comment above it (`run-gateway.sh:10`), which says
PYTHONPATH "makes `samantha.tts` importable from inside a plugin" —
it is now a plugin-local import and the path is there for the package
root.

- [ ] **Step 8: Prove he still speaks, with `backend/` still present**

This is the point of doing it before the deletion: if the move broke
something, `backend/` is still there to compare against.

```bash
cp systemd/samantha-widget.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user restart samantha-hermes.service samantha-widget.service
SAMANTHA_WIDGET_SAY="Sigo aquí, y sigo teniendo voz." \
  systemctl --user restart samantha-widget.service
journalctl --user -u samantha-widget.service -f
```

Expected: he says it out loud. A silent widget with no error in the log
is the signature of a broken `PYTHONPATH` — check that first.

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "refactor(tts): speech moves in with the voice plugin that uses it"
```

---

## Task 3: The adapter stops serving a frontend

> **This must land before Task 5.** `adapter.py` refuses to start the
> platform when `frontend/dist/index.html` or `assets/` is missing, and
> that refusal is non-retryable. Delete `frontend/` first and `/ws`
> disappears with it.

**Files:**
- Modify: `Hermes/plugins/samantha_kiosk/adapter.py` (~lines 238-245,
  293-320, 325-330, 379-380)
- Modify: `Hermes/plugins/samantha_kiosk/plugin.yaml:30`

**Interfaces:**
- Produces: an adapter serving exactly one route, `/ws`. The WebSocket
  contract, the `Origin` policy and `user_id` handling are untouched.

- [ ] **Step 1: Delete the static-root check**

Remove the whole `missing = [...]` block and the `if missing:` branch
that follows it (`adapter.py:301-320`), including the
`samantha_kiosk_static_root_missing` fatal error. Leave the EADDRINUSE
branch below it exactly as it is — it guards a different failure.

- [ ] **Step 2: Delete the two browser routes**

```python
        app = web.Application()
        app.router.add_get("/ws", self._ws_handler)

        self._runner = web.AppRunner(app)
```

That is, drop `add_static("/assets", ...)` and `add_get("/", self._index)`
and the three-line comment above them about Vite's build.

- [ ] **Step 3: Delete `_index` and `static_root`**

Remove the `_index` method (`adapter.py:379-380`), the `static_root`
assignment in `__init__` (`:238-245`), and the `_ENV_STATIC_ROOT`
constant with any `SAMANTHA_KIOSK_STATIC_ROOT` documentation in
`plugin.yaml:30`.

- [ ] **Step 4: Confirm nothing else refers to them**

```bash
grep -rn 'static_root\|_index\|STATIC_ROOT\|frontend/dist' Hermes/plugins/samantha_kiosk/
```

Expected: no output.

- [ ] **Step 5: Prove the gateway still serves the WebSocket**

```bash
systemctl --user restart samantha-hermes.service
sleep 3
journalctl --user -u samantha-hermes.service -n 30 --no-pager | grep -i 'kiosk'
```

Expected: the platform starts, with no line about a missing frontend.
Then a real turn:

```bash
SAMANTHA_WIDGET_FAKE_MIC="¿Sigues escuchándome?" \
  systemctl --user restart samantha-widget.service
journalctl --user -u samantha-widget.service -f
```

Expected: he answers. The fake microphone is the right tool here —
Task 1 already proved the real one, and this step is testing the
gateway, not the room.

- [ ] **Step 6: Commit**

```bash
git add Hermes/plugins/samantha_kiosk/
git commit -m "refactor(kiosk): the surface serves a socket, not a website"
```

---

## Task 4: Turn the kiosk off before deleting it

**Files:** none. This task changes the machine, not the repo.

> The point of this task is a day of ordinary use with the kiosk off but
> recoverable. Deleting is cheap to do and expensive to undo at 23:00 on
> a Tuesday when he stops speaking and you cannot remember whether it was
> the deletion.

- [ ] **Step 1: Find out what is actually installed**

```bash
for s in samantha-backend samantha-ui; do
  printf "%-20s %s / %s\n" "$s" \
    "$(systemctl --user is-enabled $s.service 2>&1)" \
    "$(systemctl --user is-active $s.service 2>&1)"
done
```

On the machine this plan was written on, both answer `not-found`: the
kiosk was configured in the repo but never installed here (PROGRESS.md,
2026-08-23). **If that is what you see, this task is already done** —
record it and move on. If they exist, continue.

- [ ] **Step 2: Stop and disable them**

```bash
systemctl --user disable --now samantha-ui.service
systemctl --user disable --now samantha-backend.service
systemctl --user status samantha-widget.service samantha-hermes.service
```

Expected: the widget and the gateway are unaffected. Nothing about the
strip depends on either unit — Task 3 removed the last thing that did.

- [ ] **Step 3: Live with it for a day**

Use him normally. What you are watching for is anything that used to
work and now does not: a reminder that never arrives, a voice that goes
missing, an announcement that used to come through the browser.

- [ ] **Step 4: Record the result in PROGRESS.md, and only then continue**

If something broke, it is recoverable right now with
`systemctl --user enable --now samantha-ui.service`. After Task 5 it is
recoverable only from git.

---

## Task 5: The deletion

**Files:**
- Delete: `frontend/` (whole directory)
- Delete: `backend/` (whole directory)
- Delete: `systemd/samantha-backend.service`, `systemd/samantha-ui.service`

**Interfaces:** none. Nothing may still import from either directory —
Tasks 2 and 3 removed the last two consumers.

- [ ] **Step 1: Prove nothing references them any more**

```bash
cd /home/nexus/git/os1-samantha
grep -rn 'from samantha import\|import samantha\b\|frontend/dist\|backend/samantha' \
  --include='*.py' --include='*.sh' --include='*.service' --include='*.yaml' \
  widget/ Hermes/ systemd/ tts-server/
```

Expected: no output. **If anything appears, stop and fix it here** — the
next step is the irreversible one.

- [ ] **Step 2: Delete the frontend, on its own commit**

```bash
git rm -r --quiet frontend/
git commit -m "chore: the four screens the widget replaced

React, Vite, Three.js and the OS1 ribbon were the kiosk's UI. The strip
draws its own in GSK, and nothing has loaded frontend/dist since the
adapter stopped serving it.

It is not lost: this is git, and a mobile client — which is the one thing
a browser could still be good for here — would want a different design
anyway, not four full-screen terracotta panels built for a kiosk."
```

- [ ] **Step 3: Delete the backend, on its own commit**

```bash
git rm -r --quiet backend/
git commit -m "chore: FastAPI, ChromaDB and the six questions

The server has not run since Hermes took :7777. The two things worth
keeping already left: tts.py to the voice plugin (plan 3 Task 2), and
its tests to widget/.

That takes profile.py and the onboarding with it, deliberately. The six
questions calibrated Samantha's personality; JARVIS has a different one,
and Hermes' own memory learns the user by talking to them instead of
interviewing them once."
```

- [ ] **Step 4: Delete the two units**

```bash
git rm --quiet systemd/samantha-backend.service systemd/samantha-ui.service
git commit -m "chore: the units that started a browser and a server"
```

- [ ] **Step 5: Prove he still works, from a clean checkout state**

```bash
git status --porcelain          # expect: empty
systemctl --user restart samantha-hermes.service samantha-widget.service
sleep 5
SAMANTHA_WIDGET_SAY="Ya no queda nada del kiosco." \
  systemctl --user restart samantha-widget.service
journalctl --user -u samantha-widget.service -f
```

Expected: he says it. Then talk to him out loud, once, the way Task 1
did — the deletion is exactly the kind of change that breaks something
nobody thought to test.

- [ ] **Step 6: Run every test that still exists**

```bash
cd widget && PYTHONNOUSERSITE=1 PYTHONPATH=$PWD/.. \
  .venv/bin/python -m pytest -v && .venv/bin/ruff check .
```

Expected: everything passes. The count grows by the 7 tests Task 2
moved in and loses the 99 that lived in `backend/tests/`.

---

## Task 6: The documentation stops quoting the dead

**Files:**
- Modify: `CLAUDE.md` (§2.4, §2.6, §2.8, §2.10, §3, §5, §6, §9, §10, §12)
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-08-23-samantha-widget-gtk4-design.md` §7, §8

- [ ] **Step 1: Retire the quoted blocks in CLAUDE.md**

§2.4, §2.8 and §2.10 currently keep v3's reasoning as quoted blocks
under a SUPERSEDED note, because the code was still there to explain.
It is not any more. Delete the quoted text and leave the heading plus a
pointer — §12 is where history lives, and a spec carrying its own
archaeology in the body stops being readable. Concretely:

```markdown
### 2.4 Backend Stack: Python + FastAPI — GONE 2026-08-2X

`backend/` was deleted in plan 3. `127.0.0.1:7777` is the Hermes
gateway. The one module that outlived it, `tts.py`, lives in
`Hermes/plugins/samantha_voice/`. §12 has the decision.

### 2.8 Audio I/O: everything in the widget, nothing in a browser
[keep the whole live section as it stands; delete only the quoted v3
block at its end — the Web Speech decision is recorded in §12]

### 2.10 Frontend Stack: React + Vite + TypeScript — GONE 2026-08-2X

`frontend/` was deleted in plan 3. The strip draws its own UI in GSK
(§2.3). Node and pnpm are no longer needed to build or run anything.
§12 has the decision.
```

- [ ] **Step 2: Fix the §2.6 error**

§2.6 says `backend/samantha/tts.py` "still dispatches across all three"
backends (Piper, XTTS, CosyVoice). **That was never true of the code** —
`stream()` calls `_stream_cosyvoice` and nothing else. It was written on
2026-08-24 from the decision log rather than from the file. Correct it,
and point at the module's new address:

```markdown
- **TTS:** **CosyVoice 3** zero-shot, in Docker on `:8093` […]
  The client is `Hermes/plugins/samantha_voice/tts.py`. Piper and
  XTTS-v2 were tried and are gone; nothing dispatches between backends.
```

- [ ] **Step 3: Purge the dead directories from §3, §5, §9 and §10**

- §3: drop the `backend/` and `frontend/` rows from the tree, and the
  rule "MUST NOT add code to `backend/` or `frontend/`" — there is
  nothing left to add it to. Add `Hermes/plugins/samantha_voice/` with
  `tts.py` named.
- §5: delete the whole "Legacy: backend and frontend" subsection, and
  correct the widget's `PYTHONPATH` to the single path Task 2 left.
- §6: delete the JavaScript subsection outright. It survived this long
  as "no longer part of the running system"; now there is no JavaScript
  in the repo at all.
- §9: the row pointing at `backend/samantha/tts.py` moves to the new
  address.
- §10: drop "Mock mode / Real mode" — the backend they described is
  gone. Keep "Chromium kiosk" and "openbox" as history, since §12 refers
  to them.

- [ ] **Step 4: Give §12 the three entries it is owed**

The spec (§11) lists two, and this plan adds a third. Insert them above
the 2026-08-23 entries, newest first:

```markdown
### 2026-08-2X — The retirement: the kiosk, the backend and the frontend

**Decision:** `frontend/`, `backend/` and the two systemd units are
deleted. `samantha.tts` moves to `Hermes/plugins/samantha_voice/`, which
already used it; the kiosk adapter stops serving a website and serves
only `/ws`.

**Why now:** the condition set on 2026-08-22 was "not until the widget
convinces". It convinced on 2026-08-2X, when it heard a human voice for
the first time — see the entry for plan 2's Task 8.

**Cost:** the onboarding goes with `backend/profile.py`. The six
questions calibrated Samantha; JARVIS has a different personality and
Hermes' memory learns by conversation rather than by interview. If a
first encounter is ever wanted, it gets designed then, not resurrected.

**What it buys:** one language, one process, one place to look. And the
`PYTHONPATH` that pointed at a directory nobody ran is gone.

---

### 2026-08-2X — STT returns to local faster-whisper

**Decision:** transcription is faster-whisper in the widget's own
process. This reverses the browser-Web-Speech half of the 2026-05-13
decision; the offline-relaxation half stands.

**Rationale:** the Web Speech API needed a Chromium to live in. When the
browser went, so did it. faster-whisper on the GPU transcribes 3.5 s of
speech in 0.23 s, which is faster than the API ever was, and it is the
one piece of the path that never leaves the machine.

**Cost:** ~2.5 GB of VRAM held for the process's lifetime, and 81 s of
first load.

---

### 2026-08-2X — The widget synthesises its own speech

**Decision:** the widget calls CosyVoice directly, clause by clause,
rather than receiving audio over the WebSocket.

**Rationale:** it retires plan 3b's binary WS protocol before it was
written. Barge-in becomes a local call — stop the player, bump a
generation counter — instead of a message the gateway has to honour.

**Cost:** the widget needs the TTS client on its `PYTHONPATH`, which is
the one thread still connecting it to Hermes' plugin directory.
```

Replace `2026-08-2X` with the real dates as you write them.

- [ ] **Step 5: The README loses its unused half**

Delete the "What is still here and unused" section. In "Project
structure", drop the two directories and add `Hermes/plugins/` with the
two plugins named. The Quick start's `PYTHONPATH` loses `../backend`.

- [ ] **Step 6: Correct the widget spec's §7 and §8**

§7 describes plan 3 as "barge-in polish, onboarding, deleting
`frontend/`, the Chromium unit, and the adapter's static half". Three
corrections, dated and left visible rather than silently rewritten:

- Barge-in was implemented in plan 2, not polished in plan 3.
- The onboarding is **not** built. It is cancelled, and §12 says why.
- `backend/` was not in the original scope and is now, because
  `samantha.tts` turned out to be the only thing anybody used from it.

§8's line "**Deleting anything.** All of it is plan 3." can now say
plan 3 landed, with this plan's filename.

- [ ] **Step 7: Check every internal link still resolves**

```bash
cd /home/nexus/git/os1-samantha
grep -ohE '\]\([^)h][^)]*\)' README.md CLAUDE.md | tr -d ']()' | sort -u | \
  while read f; do [ -e "$f" ] || echo "ROTO: $f"; done
```

Expected: no output.

- [ ] **Step 8: Commit**

```bash
git add CLAUDE.md README.md docs/superpowers/specs/
git commit -m "docs: the spec stops explaining code that no longer exists"
```

---

## Task 7: Write down what it cost

**Files:** Modify `PROGRESS.md`

- [ ] **Step 1: Append the entry, newest first**

Follow the format the file already uses: a dated heading, two or three
lines of summary, **Changed files**, **Tests**, and **Notes** carrying
what was surprising. The notes are the part worth writing — candidates
that are already known:

- The adapter's fatal check on `frontend/dist` meant the deletion had a
  required order, and doing it the obvious way would have taken `/ws`
  down with the frontend.
- `samantha.tts` had four consumers, three of them inside Hermes. The
  plan was drafted believing the widget was the only one.
- `tts.py` was already CosyVoice-only; CLAUDE.md §2.6 said otherwise,
  written from the decision log rather than the file.

Add whatever Task 1 through Task 6 turn up that is not on that list.

- [ ] **Step 2: Commit**

```bash
git add PROGRESS.md
git commit -m "docs: what the retirement cost, and what it found"
```

- [ ] **Step 3: Push**

```bash
git push origin development
```

---

## What this plan deliberately does not do

- **No onboarding.** Cancelled, not postponed. §12 records it.
- **No barge-in work.** It was built in plan 2; Task 1 verifies it
  against a real room and that is all it needs.
- **`voices/` stays.** The reference clip and its transcript are what
  his voice is cloned from.
- **`tts-server/` stays.** CosyVoice is the voice.
- **No renaming.** `samantha_widget`, `samantha_kiosk`, `SAMANTHA_*` and
  the repository keep the old name. CLAUDE.md's header explains the
  mismatch; changing it would touch every file to buy nothing.
