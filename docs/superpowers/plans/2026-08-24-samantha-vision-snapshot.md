# The photo on demand — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** You ask "enséñame la entrada" and the photo appears above the
strip for a few seconds; clicking it makes it bigger.

**Architecture:** A new `mirar` tool in the `samantha_vision` plugin takes
the next frame off the stream the watcher thread already has open, writes
a JPEG, and answers in words. The photo itself does **not** travel in that
answer: it is pushed on a separate frame over the kiosk WebSocket, so it
reaches the strip and nothing else. The widget draws it above the wave by
growing the window with the EWMH code that already places the strip.

**Tech Stack:** Python 3.12, Pillow (JPEG encode), PyAV (already open
streams), Hermes plugin API (`register_tool`), aiohttp WebSocket, GTK4 /
GSK, pytest.

**Spec:** `docs/superpowers/specs/2026-08-24-samantha-vision-snapshot-design.md`
— read §3 (why the photo is strip-only), §3.1 (the alert never shows one)
and §4 (components) before Task 1.

**Depends on:** `2026-08-24-samantha-vision-plugin.md`, complete and
merged at `5d0ddd1`. The watcher, `CameraFleet`, `Watcher` and the kiosk
adapter all exist and run.

## Global Constraints

- **The photo never leaves this box.** The tool's return value is a
  sentence and nothing else — no `MEDIA:` line, ever. Spec §3: a privacy
  property held by convention is not held. If a task finds itself adding
  `MEDIA:` to a tool result, stop and report.
- **The spoken text never contains a filesystem path.** CosyVoice will
  read it aloud. This is a test, not a care.
- **Nothing may let an exception reach the gateway.** It owns the cameras
  now; if it dies, everything dies.
- **`grab()` never substitutes an older frame.** A timeout is answered
  honestly. The watcher's last analysed frame can be 40 s old and calling
  that "ahora" is a lie.
- **Do not open a second RTSP connection.** Some cameras cap concurrent
  sessions and the failure is intermittent under load.
- **Do not re-derive or tune the calibrated constants:** `DEFAULT_THRESHOLD`
  0.7, `ANTI_SPAM_SECONDS` 180, `QUIET_START_HOUR` 23, `QUIET_END_HOUR` 7,
  `NIGHT_FLOOR_SECONDS` 30.
- **Nothing that needs a camera, a GPU or a network runs in a unit test.**
- Identifiers and comments in **English**, user-facing strings in
  **Spanish** (CLAUDE.md §2.9).
- Lint with `widget/.venv/bin/ruff` (run it from `widget/`, which is where
  the project's config lives — from the repo root it resolves an ambient
  ruleset with ~11 pre-existing findings that are not yours).
- The gateway is **live and watching the real house**. Restarting
  `samantha-hermes.service` is expected; leaving it broken is not.

## What has already been measured — do not re-derive

- `PIL` **12.3.0 is already installed** in `.hermes/src/.venv`, alongside
  `av` 18.1.0 and `numpy` 2.4.3. It is there because Hermes brought it,
  so `pillow` must still be declared (Task 2).
- PyAV's `image2` muxer **ignores a `BytesIO` target** and writes a file
  named `<none>` into the cwd. Do not try to encode JPEG through PyAV.
- `widget/samantha_widget/gateway.py:51` **raises `ProtocolError` on any
  unknown server frame type.** That is why Task 1 exists and comes first.
- The strip is `900 × 96` (`theme.STRIP_MAX_WIDTH`, `theme.STRIP_HEIGHT`),
  centred on the bottom edge. Camera sub-streams are `640 × 360`.
- `Ewmh.move_resize(xid, x, y, w, h)` exists and is called once from
  `StripWindow._on_map`. The xid is currently a local there.
- `samantha_kiosk/adapter.py` owns `self._ws` and `async def _push(payload)
  -> bool`, which already swallows a closed socket.

## File Structure

| File | Responsibility |
|---|---|
| `widget/samantha_widget/gateway.py` | Modify: tolerate unknown server frames; dispatch `photo`. |
| `Hermes/plugins/samantha_vision/snapshot.py` | Create: ndarray → JPEG on disk, and pruning. |
| `Hermes/plugins/samantha_vision/cameras.py` | Modify: `CameraFleet.grab()` and the watcher's hand-off slot. |
| `Hermes/plugins/samantha_kiosk/protocol.py` | Modify: the `photo` server frame. |
| `Hermes/plugins/samantha_kiosk/adapter.py` | Modify: `push_photo()`, and a registry entry so another plugin can reach it. |
| `Hermes/plugins/samantha_vision/tool.py` | Create: `mirar` — registration, handler, the sentence. |
| `Hermes/plugins/samantha_vision/__init__.py` | Modify: register the tool, hand it the fleet. |
| `widget/samantha_widget/photo.py` | Create: the thumbnail, the click, the fade timer. |
| `widget/samantha_widget/window.py` | Modify: keep the xid; `grow_to(height)` / `shrink()`. |

---

## Task 1: The strip stops choking on frames it does not know

> First because it is the only ordering that is safe. Once the adapter can
> send a `photo` frame, any strip that does not understand it raises on
> every photo. Make the strip tolerant BEFORE anything can send one.

**Files:**
- Modify: `widget/samantha_widget/gateway.py`
- Test: `widget/tests/test_gateway.py`

**Interfaces:**
- Produces: `decode_server()` returns the message for a known type and
  raises `ProtocolError` only for malformed JSON or a non-object. An
  unknown `type` is returned unchanged and ignored by `_dispatch`.

- [ ] **Step 1: Write the failing tests**

```python
# appended to widget/tests/test_gateway.py
import json

import pytest

from samantha_widget.gateway import Gateway, ProtocolError, decode_server


def test_an_unknown_server_type_is_not_fatal():
    # The gateway ships new frame types before the strip learns them.
    # A strip that raises here goes silent for the whole turn.
    msg = decode_server(json.dumps({"type": "photo", "path": "/tmp/a.jpg"}))
    assert msg["type"] == "photo"


def test_malformed_json_is_still_an_error():
    with pytest.raises(ProtocolError):
        decode_server("{not json")


def test_a_non_object_is_still_an_error():
    with pytest.raises(ProtocolError):
        decode_server(json.dumps([1, 2, 3]))


def test_dispatch_ignores_an_unknown_type_without_calling_handlers():
    gw = Gateway()
    seen: list[str] = []
    gw.on_token = lambda t: seen.append("token")
    gw.on_error = lambda m: seen.append("error")
    gw._dispatch(json.dumps({"type": "nonesuch"}))
    assert seen == []
```

- [ ] **Step 2: Run them and watch them fail**

```bash
cd /home/nexus/git/os1-samantha/widget
PYTHONNOUSERSITE=1 ./.venv/bin/python -m pytest tests/test_gateway.py -v -k unknown
```

Expected: `test_an_unknown_server_type_is_not_fatal` fails with
`ProtocolError: unknown type: 'photo'`.

- [ ] **Step 3: Make unknown types survive**

In `gateway.py`, delete the `_SERVER_TYPES` membership check from
`decode_server` and let `_dispatch` decide. Keep the JSON and object
checks exactly as they are.

```python
def decode_server(raw: str) -> dict[str, Any]:
    try:
        msg = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise ProtocolError(f"not JSON: {exc}") from exc
    if not isinstance(msg, dict):
        raise ProtocolError(f"expected an object, got {type(msg).__name__}")
    # A type we do not know is not an error. The gateway is versioned
    # separately from the strip and will ship frames this build has never
    # heard of; refusing them turned one unknown frame into a dead turn.
    # `_dispatch` handles what it recognises and drops the rest.
    return msg
```

`_dispatch` already ends its `if/elif` chain without an `else`, so an
unknown type falls through silently. Leave `_SERVER_TYPES` in place as
documentation of what this build understands, and reference it in the
comment.

- [ ] **Step 4: Run the tests**

```bash
cd /home/nexus/git/os1-samantha/widget
PYTHONNOUSERSITE=1 ./.venv/bin/python -m pytest tests/test_gateway.py -v
```

Expected: all pass, including the four new ones.

- [ ] **Step 5: Run the whole widget suite**

```bash
cd /home/nexus/git/os1-samantha/widget
PYTHONNOUSERSITE=1 ./.venv/bin/python -m pytest -q
```

Expected: 110 + 4 passing, output pristine.

- [ ] **Step 6: Commit**

```bash
git add widget/samantha_widget/gateway.py widget/tests/test_gateway.py
git commit -m "fix(widget): a frame type the strip does not know is not an error"
```

---

## Task 2: A frame becomes a file

**Files:**
- Create: `Hermes/plugins/samantha_vision/snapshot.py`
- Create: `Hermes/plugins/samantha_vision/tests/test_snapshot.py`
- Modify: `Hermes/plugins/samantha_vision/plugin.yaml`
- Modify: `Hermes/setup-runtime.sh`

**Interfaces:**
- Produces: `snapshot_dir() -> Path`; `write_jpeg(frame: np.ndarray, camera:
  str, *, now: float) -> Path`; `prune(*, keep: int = 20, max_age_s: float =
  3600.0, now: float) -> int` (returns how many were deleted). Task 5
  consumes `write_jpeg`; Task 4 consumes `snapshot_dir` to validate paths.

- [ ] **Step 1: Write the failing tests**

```python
# Hermes/plugins/samantha_vision/tests/test_snapshot.py
import numpy as np
from PIL import Image

from Hermes.plugins.samantha_vision import snapshot


def _frame() -> np.ndarray:
    # HxWx3 RGB, the shape CameraStream.frames() yields.
    return (np.random.default_rng(0).random((360, 640, 3)) * 255).astype("uint8")


def test_it_writes_a_real_jpeg(tmp_path, monkeypatch):
    monkeypatch.setattr(snapshot, "_ROOT", tmp_path)
    path = snapshot.write_jpeg(_frame(), "entrada", now=1000.0)
    assert path.exists()
    with Image.open(path) as im:
        assert im.format == "JPEG"
        assert im.size == (640, 360)


def test_the_name_carries_the_camera_and_the_moment(tmp_path, monkeypatch):
    monkeypatch.setattr(snapshot, "_ROOT", tmp_path)
    path = snapshot.write_jpeg(_frame(), "entrada", now=1000.0)
    assert "entrada" in path.name
    assert "1000" in path.name


def test_a_camera_name_cannot_escape_the_directory(tmp_path, monkeypatch):
    # The name comes from config, and config is written by hand.
    monkeypatch.setattr(snapshot, "_ROOT", tmp_path)
    path = snapshot.write_jpeg(_frame(), "../../etc/passwd", now=1000.0)
    assert path.parent == tmp_path


def test_the_directory_is_private(tmp_path, monkeypatch):
    # It holds pictures of the inside of the house.
    monkeypatch.setattr(snapshot, "_ROOT", tmp_path / "vision")
    snapshot.write_jpeg(_frame(), "entrada", now=1000.0)
    assert (snapshot._ROOT.stat().st_mode & 0o777) == 0o700


def test_prune_keeps_the_newest_and_drops_the_rest(tmp_path, monkeypatch):
    monkeypatch.setattr(snapshot, "_ROOT", tmp_path)
    for i in range(5):
        snapshot.write_jpeg(_frame(), "entrada", now=1000.0 + i)
    deleted = snapshot.prune(keep=2, max_age_s=1e9, now=2000.0)
    assert deleted == 3
    assert len(list(tmp_path.glob("*.jpg"))) == 2


def test_prune_drops_anything_older_than_the_window(tmp_path, monkeypatch):
    monkeypatch.setattr(snapshot, "_ROOT", tmp_path)
    snapshot.write_jpeg(_frame(), "entrada", now=1000.0)
    deleted = snapshot.prune(keep=50, max_age_s=10.0, now=5000.0)
    assert deleted == 1
    assert list(tmp_path.glob("*.jpg")) == []
```

- [ ] **Step 2: Run them and watch them fail**

```bash
cd /home/nexus/git/os1-samantha
PYTHONNOUSERSITE=1 ./widget/.venv/bin/python -m pytest \
  Hermes/plugins/samantha_vision/tests/test_snapshot.py -v
```

Expected: `ModuleNotFoundError: No module named
'Hermes.plugins.samantha_vision.snapshot'`.

- [ ] **Step 3: Write `snapshot.py`**

```python
"""A decoded frame becomes a file on disk, and old ones go away.

This directory holds pictures of the inside and the outside of the house.
An unbounded one is a privacy leak as much as a disk leak, which is why
pruning happens on every write rather than on a timer somebody can forget
to start.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import numpy as np
from loguru import logger
from PIL import Image

# Hermes already designates `cache/images` for generated media; a
# subdirectory of our own keeps pruning unambiguous and keeps this out of
# the way of anything else that writes there.
_ROOT = Path(
    os.environ.get("HERMES_HOME", Path.home() / ".hermes")
) / "cache" / "images" / "vision"

# Camera names come from a config file written by hand. Anything that is
# not a plain name is flattened rather than rejected: a bad name should
# cost a strange filename, never a write outside this directory.
_UNSAFE = re.compile(r"[^A-Za-z0-9_-]+")


def snapshot_dir() -> Path:
    """The one directory snapshots live in. Created on first use, 0700."""
    _ROOT.mkdir(parents=True, exist_ok=True)
    _ROOT.chmod(0o700)
    return _ROOT


def write_jpeg(frame: np.ndarray, camera: str, *, now: float) -> Path:
    """Write one RGB frame as a JPEG and return its path.

    Pillow, not PyAV: PyAV's image2 muxer ignores an in-memory target and
    writes a file named `<none>` into the working directory. Measured
    2026-08-24.
    """
    directory = snapshot_dir()
    safe = _UNSAFE.sub("-", camera).strip("-") or "camara"
    path = directory / f"{safe}-{int(now)}.jpg"
    Image.fromarray(frame).save(path, "JPEG", quality=85)
    path.chmod(0o600)
    prune(now=now)
    return path


def prune(*, keep: int = 20, max_age_s: float = 3600.0, now: float) -> int:
    """Delete old snapshots. Returns how many went. Never raises."""
    try:
        files = sorted(
            snapshot_dir().glob("*.jpg"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
    except OSError as exc:
        logger.warning(f"samantha-vision: cannot list snapshots: {exc}")
        return 0

    deleted = 0
    for index, path in enumerate(files):
        try:
            too_many = index >= keep
            too_old = (now - path.stat().st_mtime) > max_age_s
            if too_many or too_old:
                path.unlink()
                deleted += 1
        except OSError as exc:
            logger.warning(f"samantha-vision: cannot prune {path.name}: {exc}")
    return deleted
```

- [ ] **Step 4: Run the tests**

Expected: 6 passed.

- [ ] **Step 5: Declare Pillow**

Pillow is present only because Hermes brought it. Add it where the other
four are declared — `Hermes/plugins/samantha_vision/plugin.yaml`'s
`python_dependencies`, and the `PLUGIN_DEPS` array in
`Hermes/setup-runtime.sh`. Match the existing style of both exactly.

Verify without executing the script:

```bash
cd /home/nexus/git/os1-samantha
bash -n Hermes/setup-runtime.sh
grep -n "pillow" Hermes/setup-runtime.sh Hermes/plugins/samantha_vision/plugin.yaml
```

- [ ] **Step 6: Commit**

```bash
git add Hermes/plugins/samantha_vision/ Hermes/setup-runtime.sh
git commit -m "feat(vision): a frame becomes a file, and old ones go away"
```

---

## Task 3: The watcher hands over its next frame

**Files:**
- Modify: `Hermes/plugins/samantha_vision/cameras.py`
- Modify: `Hermes/plugins/samantha_vision/tests/test_cameras.py`

**Interfaces:**
- Produces: `CameraFleet.grab(camera: str, timeout: float = 2.0) ->
  np.ndarray | None`. Task 5 consumes it. Returns `None` for an unknown
  camera and for a timeout — the caller cannot tell them apart and does
  not need to; Task 5 checks the name separately.

- [ ] **Step 1: Write the failing tests**

```python
# appended to Hermes/plugins/samantha_vision/tests/test_cameras.py
import numpy as np


def _fleet() -> CameraFleet:
    """A fleet with nothing running: grab/_offer never touch a thread.

    Build it the way the existing tests in this file do — the injected
    detector and stream factories are what keep every test hardware-free.
    """
    return CameraFleet(detector_factory=lambda: None, open_stream=lambda url: None)


def test_grab_returns_the_next_frame_the_watcher_decodes():
    fleet = _fleet()
    # Drive one frame through the watcher's hand-off and assert grab sees it.
    fleet._offer("entrada", np.zeros((4, 4, 3), dtype="uint8"))
    got = fleet.grab("entrada", timeout=0.1)
    assert got is not None
    assert got.shape == (4, 4, 3)


def test_grab_times_out_rather_than_hanging():
    fleet = _fleet()
    assert fleet.grab("entrada", timeout=0.05) is None


def test_grab_on_an_unknown_camera_is_none_not_an_error():
    fleet = _fleet()
    assert fleet.grab("nonesuch", timeout=0.05) is None


def test_the_watcher_pays_nothing_when_nobody_is_waiting():
    # `_offer` must not copy or store a frame unless somebody asked.
    fleet = _fleet()
    fleet._offer("entrada", np.zeros((4, 4, 3), dtype="uint8"))
    assert fleet._pending.get("entrada") is None


def test_grab_never_returns_a_frame_the_watcher_already_analysed():
    # The slot is filled only AFTER a request arrives, so a frame offered
    # before the request can never satisfy it. This is the "no stale
    # frames" constraint, as a test.
    fleet = _fleet()
    stale = np.zeros((4, 4, 3), dtype="uint8")
    fleet._offer("entrada", stale)          # nobody waiting: dropped
    assert fleet.grab("entrada", timeout=0.05) is None
```

> `_fleet()` above mirrors how `test_cameras.py` already builds one. If the
> real constructor's parameter names differ, follow the file — do not
> invent a second convention, and fix the helper rather than the tests.

- [ ] **Step 2: Run them and watch them fail**

```bash
cd /home/nexus/git/os1-samantha
PYTHONNOUSERSITE=1 ./widget/.venv/bin/python -m pytest \
  Hermes/plugins/samantha_vision/tests/test_cameras.py -v -k grab
```

Expected: `AttributeError: 'CameraFleet' object has no attribute 'grab'`.

- [ ] **Step 3: Add the hand-off**

In `CameraFleet.__init__`:

```python
        # One slot per camera, filled by the watcher thread ONLY while a
        # caller is waiting. A request arriving mid-frame therefore gets
        # the NEXT frame, never the one already analysed — "ahora" has to
        # mean now, and the watcher samples one frame in ten, so its last
        # frame can be 40 s old.
        self._pending: dict[str, np.ndarray | None] = {}
        self._wanted: dict[str, threading.Event] = {}
        self._grab_lock = threading.Lock()
```

Add the two methods:

```python
    def _offer(self, camera: str, frame: np.ndarray) -> None:
        """Called by the watcher thread for every sampled frame.

        Costs one dict lookup when nobody is waiting, which is the normal
        case: this must not slow the detection loop down.
        """
        event = self._wanted.get(camera)
        if event is None or event.is_set():
            return
        with self._grab_lock:
            self._pending[camera] = frame
        event.set()

    def grab(self, camera: str, timeout: float = 2.0) -> np.ndarray | None:
        """The next frame this camera decodes, or None.

        None covers both "no such camera" and "it did not answer in time".
        A question that hangs is worse than one answered honestly, because
        he simply goes quiet (spec §4.1).
        """
        event = threading.Event()
        with self._grab_lock:
            self._wanted[camera] = event
            self._pending[camera] = None
        try:
            if not event.wait(timeout):
                return None
            with self._grab_lock:
                return self._pending.get(camera)
        finally:
            with self._grab_lock:
                self._wanted.pop(camera, None)
                self._pending.pop(camera, None)
```

In `_watch`, call `self._offer(camera.name, frame)` immediately after the
frame is yielded and before detection runs, so a waiting caller is served
even when the detector is slow.

- [ ] **Step 4: Run the tests**

Expected: the 5 new ones pass, and the existing camera tests still do.

- [ ] **Step 5: Run the plugin suite**

```bash
cd /home/nexus/git/os1-samantha
PYTHONNOUSERSITE=1 ./widget/.venv/bin/python -m pytest \
  Hermes/plugins/samantha_vision/tests/ -q
```

- [ ] **Step 6: Commit**

```bash
git add Hermes/plugins/samantha_vision/
git commit -m "feat(vision): the watcher hands over its next frame, never its last"
```

---

## Task 4: The kiosk learns to carry a photo

> The contract change the user approved on 2026-08-24. Server-to-client
> only; `decode_client` is untouched.

**Files:**
- Modify: `Hermes/plugins/samantha_kiosk/protocol.py`
- Modify: `Hermes/plugins/samantha_kiosk/adapter.py`
- Modify: `Hermes/plugins/samantha_kiosk/tests/` (follow the existing file)

**Interfaces:**
- Produces: `protocol.photo(path: str, camera: str) -> str`, and
  `KioskAdapter.push_photo(path: str, camera: str) -> bool` (async).
  Task 5 consumes `push_photo`.

- [ ] **Step 1: Write the failing tests**

```python
import json
from pathlib import Path

import pytest

from Hermes.plugins.samantha_kiosk import protocol
from Hermes.plugins.samantha_kiosk.protocol import ProtocolError


@pytest.fixture
def spool(tmp_path, monkeypatch):
    """A snapshot directory with one real file in it."""
    from Hermes.plugins.samantha_vision import snapshot

    monkeypatch.setattr(snapshot, "_ROOT", tmp_path)
    path = tmp_path / "entrada-1000.jpg"
    path.write_bytes(b"\xff\xd8\xff\xd9")   # shortest valid JPEG marker pair
    return path


@pytest.fixture
def adapter():
    """The adapter with no socket attached: _push returns False."""
    a = KioskAdapter(...)          # follow the construction in the file's other tests
    a._ws = None
    return a


def test_photo_frame_carries_the_path_and_the_camera():
    raw = protocol.photo("/tmp/vision/entrada-1000.jpg", "entrada")
    msg = json.loads(raw)
    assert msg == {
        "type": "photo",
        "path": "/tmp/vision/entrada-1000.jpg",
        "camera": "entrada",
    }


def test_photo_is_server_to_client_only():
    # A client must never be able to make the strip open a file.
    with pytest.raises(ProtocolError):
        protocol.decode_client(json.dumps({"type": "photo", "path": "/etc/shadow"}))


@pytest.mark.asyncio
async def test_push_photo_refuses_a_path_outside_the_snapshot_directory(adapter):
    assert await adapter.push_photo("/etc/shadow", "entrada") is False


@pytest.mark.asyncio
async def test_push_photo_with_no_strip_connected_is_false_not_an_error(adapter, spool):
    adapter._ws = None
    ok = await adapter.push_photo(str(spool), "entrada")
    assert ok is False
```

- [ ] **Step 2: Run them and watch them fail**

Expected: `AttributeError: module ... has no attribute 'photo'`.

- [ ] **Step 3: Add the frame and the push**

In `protocol.py`, beside `token`/`done`/`error`:

```python
def photo(path: str, camera: str) -> str:
    """A picture for the strip, and only for the strip.

    This frame exists because the photo must not travel in the model's
    answer: an answer goes wherever the turn goes, and `MEDIA:` would put
    a picture of the house on any platform that turn was routed to. See
    the snapshot spec §3.
    """
    return json.dumps({"type": "photo", "path": path, "camera": camera})
```

`_CLIENT_TYPES` is unchanged, which is what makes the second test pass.

In `adapter.py`:

```python
    async def push_photo(self, path: str, camera: str) -> bool:
        """Show a photo on the strip. False when it could not be shown.

        The path is validated against the snapshot directory before it is
        sent: the strip opens whatever it is handed, and this socket is an
        unauthenticated local listener.
        """
        from Hermes.plugins.samantha_vision.snapshot import snapshot_dir

        try:
            resolved = Path(path).resolve(strict=True)
            resolved.relative_to(snapshot_dir().resolve())
        except (OSError, ValueError):
            logger.warning(f"samantha-kiosk: refusing photo outside the spool: {path!r}")
            return False
        return await self._push(protocol.photo(str(resolved), camera))
```

- [ ] **Step 4: Run the tests**

Expected: 4 passed, and the existing kiosk tests still pass.

- [ ] **Step 5: Commit**

```bash
git add Hermes/plugins/samantha_kiosk/
git commit -m "feat(kiosk): a frame that carries a photo, and only to the strip"
```

---

## Task 5: `mirar`

**Files:**
- Create: `Hermes/plugins/samantha_vision/tool.py`
- Create: `Hermes/plugins/samantha_vision/tests/test_tool.py`
- Modify: `Hermes/plugins/samantha_vision/__init__.py`

**Interfaces:**
- Produces: `make_handler(fleet, cameras, push_photo, *, now=time.time) ->
  Callable[[dict], str]` and `register(ctx, fleet, cameras)`.
- Consumes: `CameraFleet.grab` (Task 3), `snapshot.write_jpeg` (Task 2),
  `KioskAdapter.push_photo` (Task 4), and `vision.describe`.

- [ ] **Step 1: Write the failing tests**

```python
# Hermes/plugins/samantha_vision/tests/test_tool.py
import numpy as np
import pytest

from Hermes.plugins.samantha_vision.tool import make_handler


class _Fleet:
    """A fleet that answers grab() with a canned frame, or with None."""

    def __init__(self, frame: np.ndarray | None) -> None:
        self._frame = frame

    def grab(self, camera: str, timeout: float = 2.0):
        return self._frame


class _Spy:
    """Stands in for KioskAdapter.push_photo. Records, never fails."""

    def __init__(self, result: bool = True) -> None:
        self.calls: list[tuple[str, str]] = []
        self._result = result

    def __call__(self, path: str, camera: str) -> bool:
        self.calls.append((path, camera))
        return self._result


def _raise_oserror(*_a, **_kw):
    raise OSError("disk full")


@pytest.fixture
def fake_fleet():
    return _Fleet(np.zeros((360, 640, 3), dtype="uint8"))


@pytest.fixture
def empty_fleet():
    # A frame with nothing YOLO recognises in it.
    return _Fleet(np.zeros((360, 640, 3), dtype="uint8"))


def SilentFleet():
    """A camera that never answers within the timeout."""
    return _Fleet(None)


@pytest.fixture
def spy_push():
    return _Spy()


@pytest.fixture
def failing_push():
    return _Spy(result=False)


def test_the_answer_is_a_sentence_with_no_path_in_it(fake_fleet, spy_push):
    handler = make_handler(fake_fleet, ["entrada"], spy_push)
    answer = handler({"camara": "entrada"})
    assert "/" not in answer          # a path read aloud is the failure
    assert "MEDIA:" not in answer     # spec §3: never, on any platform
    assert "entrada" in answer


def test_the_photo_is_pushed_to_the_strip(fake_fleet, spy_push):
    handler = make_handler(fake_fleet, ["entrada"], spy_push)
    handler({"camara": "entrada"})
    assert len(spy_push.calls) == 1
    assert spy_push.calls[0][1] == "entrada"


def test_a_camera_that_does_not_answer_says_so_and_pushes_nothing(spy_push):
    handler = make_handler(SilentFleet(), ["entrada"], spy_push)
    answer = handler({"camara": "entrada"})
    assert "no responde" in answer.lower()
    assert spy_push.calls == []


def test_an_unknown_camera_names_the_ones_that_exist(fake_fleet, spy_push):
    handler = make_handler(fake_fleet, ["entrada", "fuera"], spy_push)
    answer = handler({"camara": "garaje"})
    assert "entrada" in answer and "fuera" in answer


def test_omitting_the_camera_looks_at_all_of_them(fake_fleet, spy_push):
    handler = make_handler(fake_fleet, ["entrada", "fuera"], spy_push)
    handler({})
    assert len(spy_push.calls) == 2


def test_a_failed_push_still_answers(fake_fleet, failing_push):
    # The strip may not be running. The words are not conditional on it.
    handler = make_handler(fake_fleet, ["entrada"], failing_push)
    assert handler({"camara": "entrada"})


def test_a_failed_write_still_answers(fake_fleet, spy_push, monkeypatch):
    monkeypatch.setattr(
        "Hermes.plugins.samantha_vision.tool.write_jpeg",
        _raise_oserror,
    )
    handler = make_handler(fake_fleet, ["entrada"], spy_push)
    answer = handler({"camara": "entrada"})
    assert "entrada" in answer
    assert spy_push.calls == []


def test_nothing_seen_is_an_answer_not_an_error(empty_fleet, spy_push):
    # `describe([])` is what produces the 'no hay nadie' branch.
    handler = make_handler(empty_fleet, ["entrada"], spy_push)
    assert "no hay nadie" in handler({"camara": "entrada"}).lower()
```

- [ ] **Step 2: Run them and watch them fail**

Expected: `ModuleNotFoundError: ... .tool`.

- [ ] **Step 3: Write `tool.py`**

The handler, per camera: `grab` → on `None`, say it did not answer and
stop; otherwise `write_jpeg`, `push_photo`, run the detector's `describe`
over what YOLO finds, and build the sentence. Wrap `write_jpeg` and
`push_photo` each in their own `try/except Exception` — the sentence is
never conditional on either — and let nothing propagate.

The Spanish it produces (CLAUDE.md §2.9 — these are the only user-facing
strings in this task):

| Case | Sentence |
|---|---|
| Something seen | `En {camara} hay {frase}.` |
| Nothing seen | `En {camara} no hay nadie.` |
| No answer in 2 s | `La cámara de {camara} no responde.` |
| Unknown name | `No tengo esa cámara. Tengo {lista}.` |

**No `MEDIA:` line, no path, in any of them.**

- [ ] **Step 4: Run the tests**

Expected: 8 passed.

- [ ] **Step 5: Register the tool**

In `__init__.py`, register `mirar` with the schema from the plugin spec
§6.2, `check_fn` returning False when no camera is configured, and the
handler built here. The tool must be registered from `register(ctx)` —
which stays pure: registering is not doing.

- [ ] **Step 6: Ask him, out loud**

```bash
systemctl --user restart samantha-hermes.service
sleep 5
cd /home/nexus/git/os1-samantha/widget && timeout 90 env DISPLAY=:1 \
  PYTHONUNBUFFERED=1 PYTHONNOUSERSITE=1 \
  PYTHONPATH=/home/nexus/git/os1-samantha/backend:/home/nexus/git/os1-samantha \
  SAMANTHA_WIDGET_FAKE_MIC="Enséñame la entrada" \
  ./.venv/bin/python -m samantha_widget > /tmp/snap-t5.log 2>&1
grep -E '→|←|photo' /tmp/snap-t5.log
```

Expected: he answers in words, and a `photo` frame is sent. The strip
cannot draw it yet — that is Task 6. **Report his line verbatim.** If he
reads a path aloud, report it and stop; do not tune the prompt.

- [ ] **Step 7: Commit**

```bash
git add Hermes/plugins/samantha_vision/
git commit -m "feat(vision): mirar — he looks now, and answers in words"
```

---

## Task 6: The strip shows it

**Files:**
- Create: `widget/samantha_widget/photo.py`
- Create: `widget/tests/test_photo.py`
- Modify: `widget/samantha_widget/window.py`
- Modify: `widget/samantha_widget/__main__.py`

**Interfaces:**
- Consumes: the `photo` frame (Task 4), `StripWindow.grow_to/shrink`.
- Produces: `PhotoModel` — pure state, no GTK, testable: `show(path,
  camera, now)`, `click(now)`, `tick(now) -> bool` (True when the strip
  must resize), `height`, `visible`.

- [ ] **Step 1: Write the failing tests for the model**

```python
from samantha_widget.photo import PhotoModel, THUMB, NATIVE

def test_it_starts_hidden():
    m = PhotoModel()
    assert not m.visible and m.height == 0

def test_showing_it_asks_for_the_thumbnail_height():
    m = PhotoModel()
    assert m.show("/tmp/a.jpg", "entrada", now=0.0) is True
    assert m.visible and m.height == THUMB

def test_it_fades_on_its_own():
    m = PhotoModel(); m.show("/tmp/a.jpg", "entrada", now=0.0)
    assert m.tick(now=14.0) is False
    assert m.tick(now=16.0) is True
    assert not m.visible and m.height == 0

def test_a_click_makes_it_native_and_resets_the_clock():
    m = PhotoModel(); m.show("/tmp/a.jpg", "entrada", now=0.0)
    assert m.click(now=10.0) is True
    assert m.height == NATIVE
    assert m.tick(now=20.0) is False      # the clock restarted at 10.0

def test_a_second_click_dismisses_it():
    m = PhotoModel(); m.show("/tmp/a.jpg", "entrada", now=0.0)
    m.click(now=1.0)
    assert m.click(now=2.0) is True
    assert not m.visible

def test_two_photos_sit_side_by_side_and_grow_the_strip_once():
    # Asking with no camera named looks at all of them (spec §4.3), so two
    # frames arrive milliseconds apart. Replacing would mean you only ever
    # see the last camera. Spec §5.
    m = PhotoModel()
    m.show("/tmp/a.jpg", "entrada", now=0.0)
    assert m.show("/tmp/b.jpg", "fuera", now=0.05) is False   # no resize
    assert [p.path for p in m.photos] == ["/tmp/a.jpg", "/tmp/b.jpg"]
    assert m.height == THUMB

def test_a_photo_after_the_batch_starts_a_new_one():
    # A separate question, not the second half of the same one.
    m = PhotoModel()
    m.show("/tmp/a.jpg", "entrada", now=0.0)
    m.show("/tmp/b.jpg", "fuera", now=30.0)
    assert [p.path for p in m.photos] == ["/tmp/b.jpg"]
```

- [ ] **Step 2: Run them and watch them fail**

- [ ] **Step 3: Write `PhotoModel`** — pure Python, no `gi` import, the
  same shape as `wave_model.py` and `bars_model.py`.

  - `THUMB = 114` (900×210 total, minus the 96 the wave keeps),
    `NATIVE = 384` (900×480), fade after 15 s.
  - It holds a **list** of photos, not one: `show()` appends when the last
    photo arrived within `BATCH_S = 2.0`, and starts a new list otherwise.
    Cap the list at 4 — beyond that they are too small to read, and four
    thumbnails at 320 wide already overflow 900, so thumbnails shrink to
    fit the row rather than the strip growing wider.
  - `show()` returns True only when the strip must resize, so the second
    photo of a batch does not trigger a second EWMH round-trip.
  - A click enlarges **the batch**, not one photo: with two visible, the
    row becomes two 640×360 side by side, which does not fit 900 — so
    clicking with more than one photo enlarges to the widest that fits and
    reports that in a comment. Do not add a per-photo selection gesture;
    that is a UI, and §1.5 says no.

- [ ] **Step 4: Run the tests.** Expected: 7 passed.

- [ ] **Step 5: Draw it, and grow the window**

`window.py` keeps the xid from `_on_map` and gains:

```python
    def resize_to(self, extra_height: int) -> None:
        """Grow the strip upward by `extra_height`, or back to the strip."""
```

It recomputes with `strip_rect` and calls `self._ewmh.move_resize(...)`
with `y` moved up and `h` increased, then flushes. Reuse the placement
code; do not open a second window.

`photo.py`'s widget half loads the file with
`Gdk.Texture.new_from_filename` and appends it with
`Gtk.Snapshot.append_texture`. Cairo does not work on this machine
(CLAUDE.md §2.3) — GSK only. A `Gtk.GestureClick` on the image drives
`PhotoModel.click`.

- [ ] **Step 6: See it**

```bash
cd /home/nexus/git/os1-samantha/widget && timeout 90 env DISPLAY=:1 \
  PYTHONUNBUFFERED=1 PYTHONNOUSERSITE=1 \
  PYTHONPATH=/home/nexus/git/os1-samantha/backend:/home/nexus/git/os1-samantha \
  SAMANTHA_WIDGET_FAKE_MIC="Enséñame la entrada" \
  ./.venv/bin/python -m samantha_widget > /tmp/snap-t6.log 2>&1 &
sleep 8
ffmpeg -y -f x11grab -video_size 1920x1080 -i :1 -frames:v 1 /tmp/strip-photo.png
xwininfo -name "Samantha"
```

Nothing about the appearance is provable from a test (CLAUDE.md §5).
Capture the screen, and confirm with `xwininfo` that you photographed the
strip and not a lock screen. Attach what you saw to the report.

- [ ] **Step 7: Run both suites, then commit**

```bash
git add widget/
git commit -m "feat(widget): the strip shows what he was asked to show"
```

---

## Task 7: Write it down

**Files:**
- Modify: `CLAUDE.md` (§9 critical files, §12 — two entries)
- Modify: `Hermes/plugins/samantha_vision/README.md`
- Modify: `widget/README.md`
- Modify: `PROGRESS.md`

- [ ] **Step 1: The two §12 entries** the spec's §8 owes: the photo
  reaching the strip and nothing else (with why `MEDIA:` was rejected
  despite fitting), and the kiosk contract gaining its first new frame.
  State the cost of each, as that log demands.

- [ ] **Step 2: The plugin README** — the `mirar` tool, the snapshot
  directory and what lives in it, and the pruning numbers.

- [ ] **Step 3: `widget/README.md`** — that the strip now grows, and the
  click.

- [ ] **Step 4: PROGRESS.md** — dated heading, summary, **Changed files**,
  **Tests**, **Notes**. The notes are the part worth writing.

- [ ] **Step 5: Work backwards.** Take the diff of Tasks 1-6 and list
  every sentence anywhere in the repo that describes those lines. Check
  each. This is not optional bookkeeping: on the previous plan, prose
  describing changed code went stale **four times**, once inside its own
  correction. Say in the report which sentences you checked, not only
  which you changed.

- [ ] **Step 6: Commit** (do not push; the controller pushes)

```bash
git add -A
git commit -m "docs(vision): the photo, where it goes and where it does not"
```

---

## What this plan deliberately does not do

- **No live video.** Spec §1.
- **No detections table, no `revisar`.** Plan 2 of the plugin spec.
- **No photo with the alert.** Spec §3.1 — a decision, not an oversight.
- **No camera grid.** CLAUDE.md §1.5.
- **Nothing that makes the LLM see.** It is text-only; a VLM does not fit
  in VRAM.
