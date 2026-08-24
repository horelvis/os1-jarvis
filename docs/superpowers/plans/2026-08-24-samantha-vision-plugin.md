# samantha-vision (plan 1) — the cameras move in, and speak

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** JARVIS watches every camera in the house from inside the
gateway, and tells you when one of them sees something worth saying.
Nothing is asked of him yet — that is plan 2.

**Architecture:** A `standalone` Hermes plugin owns the cameras. One
thread per camera decodes a sub-stream, samples one frame in ten,
runs YOLOv9-t through onnxruntime, and applies the quiet rules. What
survives those rules becomes a turn delivered to the strip, in his
words. `vision.py` moves out of the widget unchanged; the widget's
camera thread and its environment switches are deleted in the same
change that turns the plugin on.

**Tech Stack:** Python 3.12, onnxruntime (YOLOv9-t), PyAV (RTSP),
Hermes plugin API (`register_tool`, `register_platform` for reference),
pytest.

**Spec:** `docs/superpowers/specs/2026-08-24-samantha-vision-plugin-design.md`
— read §3 (lifecycle), §5 (the cameras) and §6.1 (the alert) before
Task 1. §6.2 and §6.3 are plan 2 and are NOT built here.

**Depends on:** nothing outstanding. The widget's vision path works
today and keeps working until Task 6.

## Global Constraints

- **`vision.py` moves whole.** `Detector`, `CameraStream`, `Watcher`,
  `Detection`, `describe()`, `WATCHED_CLASSES`, `DEFAULT_THRESHOLD`
  (0.7), `ANTI_SPAM_SECONDS` (180), `QUIET_START_HOUR` (23),
  `QUIET_END_HOUR` (7). Use `git mv`. These numbers came from BarnDoor's
  `agent/rules.py`, arrived at against these same cameras — do not
  re-derive them, do not "tune" them.
- **`register()` must be pure.** It registers and returns. It opens no
  camera, binds nothing, and reads no network. Work done during
  registration turns a missing dependency into a plugin that never
  loads, which Hermes reports as a retry-forever loop at DEBUG — the
  same shape the kiosk adapter's static-root check was written to
  prevent (spec §3).
- **A camera that is off, unplugged or rebooting is a Tuesday.** It logs
  once and retries on a backoff. One dead camera never stops the others;
  each thread owns its own failure and lets nothing propagate to the
  gateway. The gateway is the brain: if it dies, everything dies.
- **He is told, not made to recite** (CLAUDE.md §1). A detection never
  becomes speech directly. It becomes a turn carrying a prompt that asks
  for one short line in his own words and forbids any mention of cameras
  or detections. "Persona detectada en exterior" is a machine talking.
- **The anti-spam key is `(camera, label)`, not `label`.** Someone
  walking from `fuera` to `entrada` is two events. That is the point of
  naming cameras.
- **Nothing that needs a camera, a GPU or a network runs in a unit
  test.** Every such boundary sits behind a small interface with a fake.
  A recording is as good as a live camera for everything except proving
  the network.
- **Nothing is deleted from the widget before Task 6**, and Task 6
  deletes the widget's camera path in the same commit that enables the
  plugin — never one without the other, or every event is announced
  twice (spec §9).
- Identifiers and comments in **English**, user-facing strings in
  **Spanish** (CLAUDE.md §2.9).
- `ruff check` / `ruff format` and the full `pytest` gate every commit.
  Use `widget/.venv/bin/ruff` and `widget/.venv/bin/python -m pytest`.

## What has already been run

Verified against the pinned runtime on 2026-08-24, before this plan was
written. Do not re-derive these:

- `_VALID_PLUGIN_KINDS` (`hermes_cli/plugins.py:625`) =
  `{"standalone", "backend", "exclusive", "platform", "model-provider"}`.
- `register_tool(name, toolset, schema, handler, check_fn=None,
  requires_env=None, is_async=False, description="", emoji="",
  override=False)` — `plugins.py:1705`. Overriding a built-in needs
  `plugins.entries.<id>.allow_tool_override: true`; we never override.
- `samantha-config.yaml` disables only the `tts` toolset, so `core`,
  `code_execution`, `browser` and `cronjob` are live.
- A cronjob reached the strip unprompted on 2026-08-23 (commit
  `3fb7c89`), and `unwrap_delivery()` in
  `widget/samantha_widget/speech.py` already strips the scaffolding such
  a delivery arrives wrapped in.
- The plugin registration pattern is `def register(ctx)` calling a
  `ctx.register_*` method, with `check_fn` for requirements and a
  factory that receives `cfg` — see `Hermes/plugins/samantha_kiosk/__init__.py`.

**Not known, and Task 1 exists to find out:** how a *plugin* delivers a
turn nobody asked for, and where a `standalone` plugin is allowed to
start background work. The cron path is proof the delivery exists; it is
not proof this is how a plugin reaches it.

---

## File Structure

| File | Responsibility |
|---|---|
| `Hermes/plugins/samantha_vision/plugin.yaml` | The manifest, and how this plugin fails silently. |
| `Hermes/plugins/samantha_vision/__init__.py` | `register(ctx)` — pure. Declares the plugin and starts nothing. |
| `Hermes/plugins/samantha_vision/vision.py` | Moved from the widget. The detector, the stream, the rules. Untouched logic. |
| `Hermes/plugins/samantha_vision/cameras.py` | Config → a list of named cameras. One thread each; their lifecycle. |
| `Hermes/plugins/samantha_vision/alert.py` | A detection becomes a turn: the prompt, and the delivery. |
| `Hermes/plugins/samantha_vision/tests/` | The rules, the config parsing, the prompt. No hardware. |
| `widget/samantha_widget/vision.py` | **Deleted in Task 6.** |
| `widget/samantha_widget/__main__.py:414` | `_watch_camera` and its thread — **deleted in Task 6.** |

---

## Task 1: Find out how a plugin speaks first

> **A probe, not a feature.** Its output is a written answer plus the
> smallest code that proves it. Everything after this task depends on
> the answer, and guessing it would mean building the alert twice.

**Files:**
- Create: `Hermes/plugins/samantha_vision/PROBE.md` (findings; deleted
  or folded into the spec at the end of the plan)
- Create: `Hermes/plugins/samantha_vision/probe_deliver.py` (throwaway)

- [ ] **Step 1: Find what a plugin is handed at registration**

```bash
cd /home/nexus/git/os1-samantha
grep -nE 'def register_[a-z_]+\(|def (on_|start|shutdown|ready)' \
  .hermes/src/hermes_cli/plugins.py | head -40
```

Look for lifecycle hooks — anything a plugin can implement that runs
*after* registration. The kiosk platform gets one indirectly (its
adapter's `connect()`); a `standalone` plugin may or may not.

- [ ] **Step 2: Find how a message reaches a platform unprompted**

The cron path is the proof it exists. Read how it delivers:

```bash
grep -rn 'deliver' .hermes/src/hermes/cron/*.py | head -20
grep -rn 'def .*deliver\|origin' .hermes/src/hermes/cron/scheduler.py | head -20
```

Answer three questions in writing:
1. What object does cron hold to deliver through — a platform registry,
   a gateway handle, a bus?
2. Is that object reachable from a plugin's `ctx`, or only from cron?
3. Does delivery take a **user message** (which the model then answers,
   which is what we want) or a **finished assistant message** (which
   would bypass his voice entirely)?

Question 3 decides the design of Task 5. The spec assumes the first:
a detection becomes a *turn*, and what he says is his.

- [ ] **Step 3: Prove it with the smallest possible plugin**

Write a throwaway plugin that, five seconds after the gateway starts,
delivers the message `"probe: di algo corto"` down whatever path Step 2
identified. Enable it, restart the gateway, and watch the strip.

```bash
systemctl --user restart samantha-hermes.service
journalctl --user -u samantha-hermes.service -f
```

Expected: he says something short, unprompted, in his own words. If
instead you see the literal probe text spoken back, delivery hands over
a finished assistant message and Task 5 must change — write that down.

- [ ] **Step 4: Write down what you found**

`PROBE.md`: the hook that runs after registration (or the absence of
one, and what you used instead), the delivery object and how a plugin
reaches it, the answer to question 3, and the exact code that worked.
Verbatim. The next four tasks are written against this file.

- [ ] **Step 5: Commit**

```bash
git add Hermes/plugins/samantha_vision/
git commit -m "probe(vision): how a plugin says something nobody asked for"
```

---

## Task 2: A plugin that loads and does nothing

**Files:**
- Create: `Hermes/plugins/samantha_vision/plugin.yaml`
- Create: `Hermes/plugins/samantha_vision/__init__.py`
- Create: `Hermes/plugins/samantha_vision/tests/__init__.py`

**Interfaces:**
- Produces: a plugin named `samantha_vision`, `kind: standalone`, that
  Hermes loads without error and that starts nothing.

- [ ] **Step 1: Write the manifest**

Follow `samantha_kiosk/plugin.yaml`'s convention: the manifest is the
first file an operator opens, so it names the ways this plugin fails
**silently**.

```yaml
manifest_version: 2
api_version: 1
name: samantha-vision
label: Samantha (vision)
kind: standalone
version: 1.0.0
description: >
  Owns the house cameras. Watches them, and says something when one of
  them sees something worth saying.
author: Horelvis Castillo

# ─────────────────────────────────────────────────────────────────────
# How this plugin fails, and how it fails SILENTLY.
#
# 1. NO CAMERAS CONFIGURED. With an empty `cameras` list the plugin
#    registers, starts nothing, and logs one line. That is correct on a
#    box with no cameras and indistinguishable from a typo in the config
#    key. The line says which key it read and that it was empty.
#
# 2. A CAMERA THAT NEVER CONNECTS. Logged once per camera, then retried
#    on a backoff. It does not repeat every attempt: a camera that is
#    off for a week would otherwise fill the journal.
#
# 3. THE MODEL FILE IS MISSING. yolov9-t-320.onnx (~8 MB) is not in the
#    repo. Without it no thread starts and the plugin is inert. Named
#    here because "he stopped noticing people" has no other symptom.
```

- [ ] **Step 2: Write `register()`, and keep it pure**

```python
"""samantha-vision — the house cameras, and what is worth saying."""


def check_requirements() -> bool:
    """True when the plugin can run at all. No network, no cameras."""
    try:
        import av  # noqa: F401
        import onnxruntime  # noqa: F401
    except ImportError:
        return False
    return True


def register(ctx):
    """Declare the plugin. Start nothing.

    Registration is pure on purpose (spec §3). Anything here that
    touches the outside world turns a missing dependency into a plugin
    that never loads, and Hermes reports that as a retry-forever loop at
    DEBUG level — the failure the kiosk adapter's static-root check was
    written to avoid, reached from the other direction.

    The camera threads start in Task 3, from the hook Task 1 found.
    """
    ctx.log.info("samantha-vision: registered")
```

- [ ] **Step 3: Enable it and confirm the gateway loads it**

```bash
cd /home/nexus/git/os1-samantha
# the same mechanism the other two plugins use — see Hermes/apply-config.sh
systemctl --user restart samantha-hermes.service
sleep 4
journalctl --user -u samantha-hermes.service -n 40 --no-pager | grep -i vision
```

Expected: `samantha-vision: registered`, and **no** traceback. Then
confirm the other two plugins still work by talking to him:

```bash
cd widget && timeout 40 env DISPLAY=:1 PYTHONUNBUFFERED=1 \
  PYTHONNOUSERSITE=1 PYTHONPATH=/home/nexus/git/os1-samantha \
  SAMANTHA_WIDGET_FAKE_MIC="¿Sigues ahí?" \
  ./.venv/bin/python -m samantha_widget > /tmp/vision-t2.log 2>&1
grep -E '→|←' /tmp/vision-t2.log
```

Expected: a full turn. A plugin that loads but breaks the gateway is
the failure this step exists to catch.

- [ ] **Step 4: Commit**

```bash
git add Hermes/plugins/samantha_vision/
git commit -m "feat(vision): a plugin that loads, and deliberately does nothing"
```

---

## Task 3: The cameras become a named list

**Files:**
- Create: `Hermes/plugins/samantha_vision/vision.py` (moved)
- Create: `Hermes/plugins/samantha_vision/cameras.py`
- Create: `Hermes/plugins/samantha_vision/tests/test_cameras.py`

**Interfaces:**
- Produces: `Camera(name: str, url: str)` (frozen dataclass) and
  `parse_cameras(cfg: dict) -> list[Camera]`, which never raises on bad
  config — it logs and drops the bad entry. Later tasks consume both.

- [ ] **Step 1: Move the module, with its history**

```bash
cd /home/nexus/git/os1-samantha
git mv widget/samantha_widget/vision.py \
       Hermes/plugins/samantha_vision/vision.py
git mv widget/tests/test_vision.py \
       Hermes/plugins/samantha_vision/tests/test_vision.py
```

`git mv`, not copy-and-delete: the thresholds in this file carry
comments explaining where each number came from, and `git log --follow`
has to keep reaching them. **Do not edit the logic in this step** — only
whatever import path the move breaks.

- [ ] **Step 2: Write the failing test for config parsing**

```python
# Hermes/plugins/samantha_vision/tests/test_cameras.py
from Hermes.plugins.samantha_vision.cameras import Camera, parse_cameras


def test_two_named_cameras():
    cams = parse_cameras({"cameras": [
        {"name": "fuera", "url": "rtsp://x/1"},
        {"name": "entrada", "url": "rtsp://x/2"},
    ]})
    assert cams == [Camera("fuera", "rtsp://x/1"), Camera("entrada", "rtsp://x/2")]


def test_no_cameras_is_not_an_error():
    assert parse_cameras({}) == []
    assert parse_cameras({"cameras": []}) == []


def test_entry_without_a_name_is_dropped_not_fatal():
    # A typo in one entry must not take the working cameras with it.
    cams = parse_cameras({"cameras": [
        {"url": "rtsp://x/1"},
        {"name": "entrada", "url": "rtsp://x/2"},
    ]})
    assert cams == [Camera("entrada", "rtsp://x/2")]


def test_duplicate_names_keep_the_first():
    # Two cameras answering to one name makes the tool ambiguous; the
    # first wins and the second is dropped with a log line.
    cams = parse_cameras({"cameras": [
        {"name": "fuera", "url": "rtsp://x/1"},
        {"name": "fuera", "url": "rtsp://x/2"},
    ]})
    assert cams == [Camera("fuera", "rtsp://x/1")]


def test_a_file_path_is_a_valid_url():
    # A recording is how this is tested while the cameras are off.
    cams = parse_cameras({"cameras": [{"name": "prueba", "url": "/tmp/clip.mp4"}]})
    assert cams == [Camera("prueba", "/tmp/clip.mp4")]
```

- [ ] **Step 3: Run them and watch them fail**

```bash
cd /home/nexus/git/os1-samantha
PYTHONNOUSERSITE=1 ./widget/.venv/bin/python -m pytest \
  Hermes/plugins/samantha_vision/tests/test_cameras.py -v
```

Expected: `ModuleNotFoundError: No module named
'Hermes.plugins.samantha_vision.cameras'`.

- [ ] **Step 4: Write `cameras.py`**

```python
"""The cameras of the house, by name.

The names are interface, not configuration: they are what he says
("en la entrada") and what the user asks for. That is why a nameless
entry is dropped rather than auto-numbered — "cámara 2" is not
something anybody would say out loud.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from loguru import logger


@dataclass(frozen=True)
class Camera:
    name: str
    url: str


def parse_cameras(cfg: dict[str, Any]) -> list[Camera]:
    """Read the `cameras` config key. Never raises.

    A broken entry must not take the working ones with it: a typo in one
    camera's config is the likeliest failure here, and losing the whole
    house to it would be absurd.
    """
    raw = cfg.get("cameras") or []
    out: list[Camera] = []
    seen: set[str] = set()
    for entry in raw:
        name = (entry or {}).get("name")
        url = (entry or {}).get("url")
        if not name or not url:
            logger.warning(f"samantha-vision: camera entry without name or url: {entry!r}")
            continue
        if name in seen:
            logger.warning(f"samantha-vision: duplicate camera name {name!r}, keeping the first")
            continue
        seen.add(name)
        out.append(Camera(str(name), str(url)))
    if not out:
        logger.info("samantha-vision: no cameras configured (config key 'cameras' empty)")
    return out
```

- [ ] **Step 5: Run the tests**

Expected: 5 passed.

- [ ] **Step 6: Start one thread per camera, from the hook Task 1 found**

Add to `cameras.py` a `CameraFleet` that owns the threads:

- `start(cameras: list[Camera], on_detections: Callable[[str, list], None])`
  — one daemon thread per camera, named `camera-<name>` so
  `journalctl` and a traceback both say which one.
- Each thread: open the stream, sample one frame in ten, detect, and
  call `on_detections(camera_name, detections)`. Never let an exception
  escape the thread — log once per camera and retry on a backoff.
- `stop()` — set a flag, join each thread with a short timeout, abandon
  any thread wedged inside a decoder read (spec §3).

For this task `on_detections` only logs. The alert is Task 5.

- [ ] **Step 7: Point it at a recording and watch the log**

```bash
# a recording is as good as a live camera for everything except
# proving the network — and the cameras may be off
ls ~/git/barndoor/**/*.mp4 2>/dev/null | head -3
```

Configure one camera pointing at a real recording, restart the gateway,
and confirm the log shows detections arriving with the camera's name.
Then configure a second camera with a deliberately unreachable URL and
confirm: it logs once, the working camera keeps working, and the
gateway does not fall over.

- [ ] **Step 8: Commit**

```bash
git add Hermes/plugins/samantha_vision/ widget/
git commit -m "feat(vision): cameras with names, one thread each"
```

---

## Task 4: The rules learn there is more than one camera

**Files:**
- Modify: `Hermes/plugins/samantha_vision/vision.py` (`Watcher` only)
- Modify: `Hermes/plugins/samantha_vision/tests/test_vision.py`

**Interfaces:**
- Produces: `Watcher.worth_saying(detections, now, hour, *, camera: str)`
  — the keyword argument is new and required. `_last_said` is keyed
  `(camera, label)`.

- [ ] **Step 1: Write the failing tests**

```python
# appended to tests/test_vision.py
from Hermes.plugins.samantha_vision.vision import Detection, Watcher


def _person(score: float = 0.9) -> Detection:
    return Detection(label="persona", score=score)


def test_anti_spam_is_per_camera():
    """Somebody walking from one camera to the other is two events."""
    w = Watcher()
    assert w.worth_saying([_person()], now=0.0, hour=12, camera="fuera")
    # Same label, same second, different camera: still worth saying.
    assert w.worth_saying([_person()], now=0.0, hour=12, camera="entrada")


def test_anti_spam_still_silences_the_same_camera():
    w = Watcher()
    assert w.worth_saying([_person()], now=0.0, hour=12, camera="fuera")
    assert not w.worth_saying([_person()], now=10.0, hour=12, camera="fuera")


def test_the_same_camera_speaks_again_after_the_window():
    w = Watcher()
    w.worth_saying([_person()], now=0.0, hour=12, camera="fuera")
    assert w.worth_saying([_person()], now=181.0, hour=12, camera="fuera")


def test_a_person_at_night_beats_the_anti_spam_per_camera():
    w = Watcher()
    assert w.worth_saying([_person()], now=0.0, hour=3, camera="fuera")
    assert w.worth_saying([_person()], now=1.0, hour=3, camera="fuera")


def test_a_car_at_night_does_not():
    w = Watcher()
    car = Detection(label="coche", score=0.9)
    assert w.worth_saying([car], now=0.0, hour=3, camera="fuera")
    assert not w.worth_saying([car], now=1.0, hour=3, camera="fuera")
```

> If `Detection` takes more fields than `label` and `score`, adapt
> `_person()` to the real constructor — read the dataclass at the top of
> `vision.py` rather than guessing. Do not change `Detection` itself.

- [ ] **Step 2: Run them and watch them fail**

Expected: `TypeError: worth_saying() got an unexpected keyword argument
'camera'`.

- [ ] **Step 3: Make the key a pair**

In `Watcher`:

```python
    def __init__(self, anti_spam_seconds: float = ANTI_SPAM_SECONDS) -> None:
        self.anti_spam_seconds = anti_spam_seconds
        # Keyed (camera, label), not label: two cameras seeing a person
        # are two events, and collapsing them would mean somebody could
        # cross the whole property in silence after the first sighting.
        self._last_said: dict[tuple[str, str], float] = {}

    def worth_saying(
        self, detections: list[Detection], now: float, hour: int, *, camera: str
    ) -> list[Detection]:
        out: list[Detection] = []
        for item in detections:
            key = (camera, item.label)
            previous = self._last_said.get(key)
            recent = previous is not None and (now - previous) < self.anti_spam_seconds
            urgent = item.label == "persona" and is_quiet_hours(hour)
            if recent and not urgent:
                continue
            self._last_said[key] = now
            out.append(item)
        return out
```

Leave `forget()` as it is — `clear()` on the new dict still does the
right thing.

- [ ] **Step 4: Run the whole vision suite**

```bash
cd /home/nexus/git/os1-samantha
PYTHONNOUSERSITE=1 ./widget/.venv/bin/python -m pytest \
  Hermes/plugins/samantha_vision/tests/ -v
```

Expected: everything passes, including the tests that moved in Task 3.
Any pre-existing test calling `worth_saying` without `camera=` must be
updated — that is the point of making the argument required.

- [ ] **Step 5: Commit**

```bash
git add Hermes/plugins/samantha_vision/
git commit -m "feat(vision): the quiet rules count cameras, not just labels"
```

---

## Task 5: The knock — a detection becomes a turn

> Written against `PROBE.md` from Task 1. If the probe found that
> delivery takes a **finished assistant message** rather than a user
> turn, stop and re-read: this task assumes the first, and the whole
> "he is told, not made to recite" rule depends on it.

**Files:**
- Create: `Hermes/plugins/samantha_vision/alert.py`
- Create: `Hermes/plugins/samantha_vision/tests/test_alert.py`
- Modify: `Hermes/plugins/samantha_vision/cameras.py` (wire `on_detections`)

**Interfaces:**
- Produces: `build_prompt(camera: str, phrase: str) -> str` — pure, and
  the only thing that decides what he is asked. `deliver(prompt: str)`
  — the side-effecting half, whatever Task 1 found.

- [ ] **Step 1: Write the failing tests for the prompt**

The prompt is the whole design of this feature, so it is what gets
tested. `deliver()` is a thin wrapper around the gateway and is proved
by hand, not by a unit test.

```python
# Hermes/plugins/samantha_vision/tests/test_alert.py
from Hermes.plugins.samantha_vision.alert import build_prompt


def test_the_prompt_carries_what_was_seen_and_where():
    p = build_prompt(camera="entrada", phrase="alguien")
    assert "entrada" in p
    assert "alguien" in p


def test_the_prompt_forbids_naming_the_machinery():
    p = build_prompt(camera="fuera", phrase="alguien").lower()
    # He must never say these out loud. The prompt has to say so,
    # because the model will otherwise narrate where it got the fact.
    for banned in ("cámara", "detección", "detectado", "yolo", "sensor"):
        assert banned in p, f"the prompt must forbid {banned!r} explicitly"


def test_the_prompt_asks_for_one_short_line():
    p = build_prompt(camera="fuera", phrase="alguien").lower()
    assert "una frase" in p or "una línea" in p
    assert "corta" in p


def test_the_phrase_is_inserted_verbatim():
    # describe() already produces Spanish; the prompt must not re-word it.
    p = build_prompt(camera="fuera", phrase="2 personas y un perro")
    assert "2 personas y un perro" in p
```

- [ ] **Step 2: Run them and watch them fail**

```bash
cd /home/nexus/git/os1-samantha
PYTHONNOUSERSITE=1 ./widget/.venv/bin/python -m pytest \
  Hermes/plugins/samantha_vision/tests/test_alert.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Write `alert.py`**

```python
"""A detection becomes a turn, not a sentence.

CLAUDE.md §1: he never performs using his tools. "Persona detectada en
exterior" is a machine talking. So what the camera produces is a
*prompt*, and what reaches the user is his answer to it — in his voice,
with the conversation still in mind.

This costs one model call per event. It is affordable precisely because
the Watcher makes events rare.
"""

from __future__ import annotations

_TEMPLATE = (
    "Acabas de fijarte en algo en la {camera} de casa: {phrase}. "
    "Coméntalo en una frase corta, con tus palabras, como quien levanta "
    "la vista y lo menciona. "
    "No digas nunca la palabra cámara, ni detección, ni detectado, ni "
    "yolo, ni sensor, ni expliques cómo lo sabes."
)


def build_prompt(camera: str, phrase: str) -> str:
    """What he is asked when a camera sees something worth mentioning."""
    return _TEMPLATE.format(camera=camera, phrase=phrase)
```

- [ ] **Step 4: Run the tests**

Expected: 4 passed.

- [ ] **Step 5: Wire it to the fleet, and strip the scaffolding**

In `cameras.py`, `on_detections` becomes: run the Watcher for that
camera, and if anything survives, `describe()` it and deliver
`build_prompt(...)`.

**The delivery arrives wrapped.** Measured on the reminders (2026-08-23):
a job id, a row of dashes, and an English footer about managing the job.
`widget/samantha_widget/speech.py:unwrap_delivery()` already strips
exactly that shape — confirm the alert goes through the same treatment,
or he reads furniture out loud. Write down in the report which side does
the stripping.

- [ ] **Step 6: Hear it**

Point one camera at a recording that contains a person, with the gateway
up and the widget running:

```bash
cd /home/nexus/git/os1-samantha/widget
timeout 90 env DISPLAY=:1 PYTHONUNBUFFERED=1 PYTHONNOUSERSITE=1 \
  PYTHONPATH=/home/nexus/git/os1-samantha \
  SAMANTHA_WIDGET_NO_MIC=1 \
  ./.venv/bin/python -m samantha_widget > /tmp/vision-t5.log 2>&1
grep -E '←|cámara|camera' /tmp/vision-t5.log
```

Expected: something like `← Oye. Hay alguien fuera de casa.` — his
words, no job id, no dashes, and **no mention of a camera**. If he says
"he detectado una persona", the prompt lost: report it verbatim rather
than tuning it silently.

- [ ] **Step 7: Commit**

```bash
git add Hermes/plugins/samantha_vision/
git commit -m "feat(vision): the cameras knock, and he answers in his own words"
```

---

## Task 6: The widget stops watching

> **The two halves of this task ship in ONE commit.** Turning the plugin
> on while the widget still watches means every event is announced
> twice; turning the widget off first means a window with no eyes at
> all. Do both, verify, then commit once.

**Files:**
- Delete: `widget/samantha_widget/vision.py` (already moved in Task 3 —
  confirm it is gone, not copied)
- Modify: `widget/samantha_widget/__main__.py` (remove `_watch_camera`,
  its thread, and the camera env switches)
- Modify: `widget/README.md` (the camera section and its switches)
- Modify: `Hermes/samantha-config.yaml` (enable the plugin, configure
  the real cameras)

- [ ] **Step 1: Confirm the module already left**

```bash
cd /home/nexus/git/os1-samantha
ls widget/samantha_widget/vision.py 2>&1   # expect: No such file
grep -rn 'from .vision\|import vision' widget/
```

Expected: no output from the grep. Task 3's `git mv` should have taken
it; if a copy came back, delete it now.

- [ ] **Step 2: Remove the camera thread from `__main__.py`**

Delete `_watch_camera` and the block that starts its thread (around
`__main__.py:239`). Also remove the reads of `SAMANTHA_WIDGET_CAMERA`,
`SAMANTHA_WIDGET_CAMERA_RETRY` and `SAMANTHA_YOLO_MODEL`.

Leave `SAMANTHA_WIDGET_FAKE_MIC`, `SAMANTHA_WIDGET_SAY`,
`SAMANTHA_WIDGET_NO_MIC`, `SAMANTHA_WIDGET_STATE` and
`SAMANTHA_WIDGET_DUMP` alone — none of them is about vision, and all
five are how this project debugs itself.

- [ ] **Step 3: Configure the real cameras and enable the plugin**

In `Hermes/samantha-config.yaml`, add the plugin entry with the two
real cameras (the URLs are in the git history of
`widget/README.md`, or on the cameras themselves):

```yaml
plugins:
  entries:
    samantha-vision:
      allow_tool_override: false
      cameras:
        - name: fuera
          url: rtsp://…@192.168.100.142:554/h264Preview_01_sub
        - name: entrada
          url: rtsp://…@192.168.100.143:554/h264Preview_01_sub
```

**This file is git-ignored.** Whatever you put here must also be
written down in the plugin's README, or the next machine has no cameras
and no way to know why.

- [ ] **Step 4: Verify nothing announces twice**

Restart both, point a camera at a recording with a person in it, and
watch for exactly one mention:

```bash
systemctl --user restart samantha-hermes.service
sleep 5
cd widget && timeout 90 env DISPLAY=:1 PYTHONUNBUFFERED=1 \
  PYTHONNOUSERSITE=1 PYTHONPATH=/home/nexus/git/os1-samantha \
  SAMANTHA_WIDGET_NO_MIC=1 \
  ./.venv/bin/python -m samantha_widget > /tmp/vision-t6.log 2>&1
grep -c '←' /tmp/vision-t6.log
```

Expected: one reply per event, not two.

- [ ] **Step 5: Run every test that exists**

```bash
cd /home/nexus/git/os1-samantha/widget
PYTHONNOUSERSITE=1 ./.venv/bin/python -m pytest -q
cd .. && PYTHONNOUSERSITE=1 ./widget/.venv/bin/python -m pytest \
  Hermes/plugins/samantha_vision/tests/ -q
```

Expected: both green. The widget's count drops by the vision tests that
moved out in Task 3.

- [ ] **Step 6: Commit — both halves together**

```bash
git add widget/ Hermes/
git commit -m "refactor(vision): the strip stops watching, the gateway starts

Both halves in one commit on purpose: with the plugin on and the widget
still watching, every event is announced twice; with the widget off
first, nothing watches at all."
```

---

## Task 7: Write it down

**Files:**
- Create: `Hermes/plugins/samantha_vision/README.md`
- Modify: `CLAUDE.md` (§0 stack line, §9 critical files, §12)
- Modify: `widget/README.md`
- Modify: `PROGRESS.md`
- Delete: `Hermes/plugins/samantha_vision/PROBE.md` (fold into the spec)

- [ ] **Step 1: The plugin's README**

For the operator, not for the model. It must carry: how to configure
cameras (with the shape of the config), where the YOLO model comes from
and that it is not in the repo, that a recording works as a camera and
that this is how the whole thing is tested, the quiet rules and their
numbers, and — first, because it is what breaks — that
`Hermes/samantha-config.yaml` is git-ignored, so the cameras must be
re-configured on any new machine.

- [ ] **Step 2: CLAUDE.md**

- §0's stack line for Vision: it is a Hermes plugin now, not part of the
  widget.
- §9: the critical-files rows for vision point at
  `Hermes/plugins/samantha_vision/`.
- §12: the three entries the spec's §11 lists — vision moves into a
  plugin, cameras become plural and named, and (when plan 2 lands) he
  remembers what he saw. Write the first two now; the third belongs to
  plan 2 and must not be claimed early.

- [ ] **Step 3: widget/README.md**

Delete "## The cameras" and the three camera environment switches.
Add one line saying where vision went, so a reader who remembers it
being here is not left hunting.

- [ ] **Step 4: Fold the probe into the spec**

`PROBE.md` answered how a plugin speaks first. That answer belongs in
the spec's §3, where the next person looks — not in a scratch file next
to the code. Move it there and delete the file.

- [ ] **Step 5: PROGRESS.md**

The usual shape: dated heading, summary, **Changed files**, **Tests**,
**Notes**. The notes are the part worth writing — what the probe found,
what the prompt needed before he stopped naming the machinery, and
anything about running camera threads inside the gateway that only
showed up once it was real.

- [ ] **Step 6: Commit and push**

```bash
git add -A
git commit -m "docs(vision): where the cameras live now, and what it cost"
git push origin development
```

---

## What this plan deliberately does not do

- **No tools.** `mirar` and `revisar` are plan 2. This plan ends with a
  JARVIS who notices things and says so, and who still cannot be asked
  anything.
- **No detections table.** It belongs with the tool that reads it;
  writing a table nobody queries is how schemas rot.
- **No VLM, no scene description.** Eight labels is the ceiling (spec §2).
- **No faces, no identity, no recording.** Out of scope by design, not
  by omission.
- **`backend/` is not touched.** Its retirement is plan 3 of the widget,
  a different plan with a hardware lock on it.
