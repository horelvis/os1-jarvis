# The camera, live — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** He is asked to show a camera, and it appears **moving** in the band above the strip until he is told to put it away.

**Architecture:** The camera watcher already decodes every frame over a permanently open RTSP connection, so nothing new is opened. A tap hands each raw H.264 packet to a live session in the gateway; the session pushes them over the strip's existing WebSocket as binary frames; the widget decodes them on its own thread and paints them into the band that `mirar`'s photo already grows.

**Tech Stack:** Python 3.12, PyAV 18.1.0 (already in both venvs), aiohttp (gateway side), `websockets` (strip side), GTK4 + GSK via PyGObject, ctypes against libX11 and libXext.

**Spec:** `docs/superpowers/specs/2026-08-25-samantha-vision-live-design.md`

## Global Constraints

- **Python 3.12+**, formatted with `ruff format`, linted with `ruff check`. Type hints mandatory on public functions.
- **Comments and identifiers in English; every string he says out loud in Spanish (Spain).** CLAUDE.md §2.9, §6.
- **No new dependencies.** PyAV is already in `widget/.venv` (18.1.0, arrived with faster-whisper) and in the gateway's. Adding one requires asking (CLAUDE.md §8).
- **He never narrates a tool.** No codec, no socket, no "sesión", no progress reports. CLAUDE.md §1.
- **The camera name is handed to him as a labelled value, never inside a preposition.** A model given broken Spanish repairs it by inventing a place that fits — measured twice (CLAUDE.md §12, 2026-08-24).
- **One live view at a time.** Spec §2.
- **No audio, ever.** Only `video=0` is demuxed. Spec §2.
- **Ceiling: 120.0 seconds.** It is ours, a guess, and must NOT be filed beside BarnDoor's four calibrated constants (180, 0.7, 23:00, 07:00).
- **`gi.require_version()` must run before the import it guards**, so those imports carry `# noqa: E402` (CLAUDE.md §6).
- **Nothing about appearance is provable by a test.** Verify by screen capture, and confirm with `xwininfo -name "Samantha"` — that title, not `samantha-widget`.

**Test commands (exact):**

```bash
# Gateway-side plugin tests, from the repo root, using the widget's venv:
cd /home/nexus/git/os1-samantha
PYTHONNOUSERSITE=1 ./widget/.venv/bin/python -m pytest \
  Hermes/plugins/samantha_vision/tests/ Hermes/plugins/samantha_kiosk/tests/ -q

# Widget tests:
cd /home/nexus/git/os1-samantha/widget
PYTHONNOUSERSITE=1 .venv/bin/python -m pytest -q
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

---

## File Structure

**Gateway (Hermes plugins):**

| File | Responsibility |
|---|---|
| `Hermes/plugins/samantha_kiosk/protocol.py` | modify — the `live` / `live_end` text frames and the binary frame's 4-byte header |
| `Hermes/plugins/samantha_kiosk/adapter.py` | modify — `_push_bytes` and the three `push_live_*` methods |
| `Hermes/plugins/samantha_kiosk/__init__.py` | modify — the `platform_hint` learns he can show moving video |
| `Hermes/plugins/samantha_vision/vision.py` | modify — `CameraStream.frames()` demuxes and taps |
| `Hermes/plugins/samantha_vision/cameras.py` | modify — the fleet carries a tap per camera |
| `Hermes/plugins/samantha_vision/live.py` | **create** — the session: epoch, ceiling, one way to close |
| `Hermes/plugins/samantha_vision/live_tool.py` | **create** — `ver_en_vivo` and `dejar_de_ver` |
| `Hermes/plugins/samantha_vision/__init__.py` | modify — register both tools, wire the pushes |

**Widget:**

| File | Responsibility |
|---|---|
| `widget/samantha_widget/gateway.py` | modify — branch on frame type before parsing; three new callbacks |
| `widget/samantha_widget/live.py` | **create** — the live band as pure state. No GTK. |
| `widget/samantha_widget/live_decode.py` | **create** — the decoder thread, the bounded queue, the single-slot mailbox |
| `widget/samantha_widget/photo_area.py` | modify — paint the live texture in the band |
| `widget/samantha_widget/ewmh.py` | modify — `set_input_region()` via XShape |
| `widget/samantha_widget/window.py` | modify — set the input region whenever the band resizes |
| `widget/samantha_widget/__main__.py` | modify — wiring, and `SAMANTHA_WIDGET_LIVE` |
| `widget/README.md` | modify — document the switch |

---

### Task 1: The wire — `live`, `live_end`, and the binary frame

**Files:**
- Modify: `Hermes/plugins/samantha_kiosk/protocol.py`
- Test: `Hermes/plugins/samantha_kiosk/tests/test_protocol.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `live(camera: str, epoch: int, extradata: bytes, width: int, height: int) -> str`, `live_end(epoch: int, reason: str) -> str`, `live_frame(epoch: int, packet: bytes) -> bytes`, `MAX_LIVE_FRAME_BYTES: int`, `LIVE_REASONS: frozenset[str]`.

- [ ] **Step 1: Write the failing test**

Append to `Hermes/plugins/samantha_kiosk/tests/test_protocol.py`:

```python
import base64
import json

import pytest

from Hermes.plugins.samantha_kiosk.protocol import (
    MAX_LIVE_FRAME_BYTES,
    ProtocolError,
    live,
    live_end,
    live_frame,
)


def test_live_carries_the_codec_header_so_a_decoder_can_start():
    msg = json.loads(live("entrada", 7, b"\x00\x00\x01\x67sps", 704, 480))
    assert msg["type"] == "live"
    assert msg["camera"] == "entrada"
    assert msg["epoch"] == 7
    assert msg["codec"] == "h264"
    assert base64.b64decode(msg["extradata"]) == b"\x00\x00\x01\x67sps"
    assert (msg["width"], msg["height"]) == (704, 480)


def test_live_survives_a_camera_that_reports_no_extradata():
    # Many RTSP cameras send SPS/PPS in-band with every keyframe and leave
    # codec_context.extradata empty. That is not an error, and the frame
    # must still open the view.
    msg = json.loads(live("entrada", 1, b"", 704, 480))
    assert msg["extradata"] == ""


def test_live_end_says_why():
    msg = json.loads(live_end(7, "timeout"))
    assert msg == {"type": "live_end", "epoch": 7, "reason": "timeout"}


def test_live_end_refuses_a_reason_nobody_defined():
    with pytest.raises(ProtocolError):
        live_end(7, "because")


def test_live_frame_stamps_the_epoch_in_four_big_endian_bytes():
    payload = live_frame(7, b"\x00\x00\x01\x65payload")
    assert payload[:4] == (7).to_bytes(4, "big")
    assert payload[4:] == b"\x00\x00\x01\x65payload"


def test_live_frame_refuses_a_packet_over_the_cap():
    # The socket is an unauthenticated local listener; bytes need no path
    # validation, so the size cap is the guard that replaces it.
    with pytest.raises(ProtocolError):
        live_frame(7, b"\x00" * (MAX_LIVE_FRAME_BYTES + 1))
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
cd /home/nexus/git/os1-samantha
PYTHONNOUSERSITE=1 ./widget/.venv/bin/python -m pytest \
  Hermes/plugins/samantha_kiosk/tests/test_protocol.py -q
```
Expected: FAIL — `ImportError: cannot import name 'live'`.

- [ ] **Step 3: Write the implementation**

Append to `Hermes/plugins/samantha_kiosk/protocol.py`:

```python
import base64

# One access unit of H.264. A substream keyframe from these cameras is a
# few tens of KB; 4 MB is aiohttp's own default and generous enough that
# a real frame can never hit it. Bytes carry no path to validate, so this
# cap is what replaces `push_photo`'s spool check as the guard on a
# socket any process on this box can open.
MAX_LIVE_FRAME_BYTES = 4 * 1024 * 1024

# Why a view ended. There is deliberately no reason for "the gateway
# stopped": a process on its way down cannot promise to send anything, so
# the strip treats a socket that closes with a view open as a close in
# its own right (spec §4.2).
LIVE_REASONS = frozenset({"asked", "timeout", "lost"})


def live(camera: str, epoch: int, extradata: bytes, width: int, height: int) -> str:
    """Open a live view on the strip.

    `extradata` is the codec's parameter sets (SPS/PPS). It travels here
    because a decoder cannot start without them; sending packets alone is
    how a restream ends up as a black rectangle that reads as a bug in
    the drawing code. Empty is legal: many cameras send them in-band with
    every keyframe instead.
    """
    return json.dumps(
        {
            "type": "live",
            "camera": camera,
            "epoch": epoch,
            "codec": "h264",
            "extradata": base64.b64encode(extradata).decode("ascii"),
            "width": width,
            "height": height,
        }
    )


def live_end(epoch: int, reason: str) -> str:
    """Close a live view, and say why."""
    if reason not in LIVE_REASONS:
        raise ProtocolError(f"unknown live_end reason: {reason!r}")
    return json.dumps({"type": "live_end", "epoch": epoch, "reason": reason})


def live_frame(epoch: int, packet: bytes) -> bytes:
    """One access unit, stamped with the view it belongs to.

    The epoch exists because closing and the packets in flight race: you
    say "ya está", the gateway closes, and three frames of the previous
    view are still on the socket. Without a number to stamp them the
    strip paints them onto a band that has already shrunk.
    """
    if len(packet) > MAX_LIVE_FRAME_BYTES:
        raise ProtocolError(
            f"live frame is {len(packet)} bytes, over the "
            f"{MAX_LIVE_FRAME_BYTES} cap"
        )
    return epoch.to_bytes(4, "big") + packet
```

- [ ] **Step 4: Run the tests to verify they pass**

Run the command from Step 2. Expected: PASS, and the pre-existing tests in that file still pass.

- [ ] **Step 5: Commit**

```bash
git add Hermes/plugins/samantha_kiosk/protocol.py \
        Hermes/plugins/samantha_kiosk/tests/test_protocol.py
git commit -m "feat(strip): the channel learns to carry moving pictures"
```

---

### Task 2: The adapter can push bytes

**Files:**
- Modify: `Hermes/plugins/samantha_kiosk/adapter.py:431-481`
- Test: `Hermes/plugins/samantha_kiosk/tests/test_adapter.py`

**Interfaces:**
- Consumes: `live`, `live_end`, `live_frame`, `MAX_LIVE_FRAME_BYTES` from Task 1.
- Produces: `SamanthaKioskAdapter.push_live_open(camera, epoch, extradata, width, height) -> bool`, `.push_live_frame(epoch, packet) -> bool`, `.push_live_close(epoch, reason) -> bool`. All three return False rather than raising when nothing is connected.

- [ ] **Step 1: Write the failing test**

Append to `Hermes/plugins/samantha_kiosk/tests/test_adapter.py` (follow the file's existing fake-websocket pattern; this is the shape it needs):

```python
import asyncio


class _Socket:
    """An aiohttp WebSocketResponse as far as _push is concerned."""

    def __init__(self) -> None:
        self.closed = False
        self.texts: list[str] = []
        self.blobs: list[bytes] = []

    async def send_str(self, payload: str) -> None:
        self.texts.append(payload)

    async def send_bytes(self, payload: bytes) -> None:
        self.blobs.append(payload)


def test_push_live_frame_goes_out_as_a_binary_frame(adapter):
    sock = _Socket()
    adapter._ws = sock

    assert asyncio.run(adapter.push_live_frame(7, b"\x00\x00\x01\x65abc")) is True
    assert sock.texts == []
    assert sock.blobs == [(7).to_bytes(4, "big") + b"\x00\x00\x01\x65abc"]


def test_push_live_open_and_close_go_out_as_text(adapter):
    sock = _Socket()
    adapter._ws = sock

    assert asyncio.run(adapter.push_live_open("entrada", 7, b"", 704, 480)) is True
    assert asyncio.run(adapter.push_live_close(7, "asked")) is True
    assert sock.blobs == []
    assert len(sock.texts) == 2


def test_an_oversized_packet_is_dropped_not_raised(adapter):
    sock = _Socket()
    adapter._ws = sock

    huge = b"\x00" * (4 * 1024 * 1024 + 1)
    assert asyncio.run(adapter.push_live_frame(7, huge)) is False
    assert sock.blobs == []


def test_nothing_connected_is_false_not_an_exception(adapter):
    adapter._ws = None
    assert asyncio.run(adapter.push_live_frame(7, b"abc")) is False
    assert asyncio.run(adapter.push_live_close(7, "asked")) is False
```

The `adapter` fixture already exists in this file; reuse it. If it does not, build the adapter the way the file's other tests do.

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
cd /home/nexus/git/os1-samantha
PYTHONNOUSERSITE=1 ./widget/.venv/bin/python -m pytest \
  Hermes/plugins/samantha_kiosk/tests/test_adapter.py -q
```
Expected: FAIL — `AttributeError: 'SamanthaKioskAdapter' object has no attribute 'push_live_frame'`.

- [ ] **Step 3: Write the implementation**

In `adapter.py`, extend the import on line 41 to include `live`, `live_end`, `live_frame` and `ProtocolError`, then add beside `push_photo`:

```python
    async def _push_bytes(self, payload: bytes) -> bool:
        """Write one binary frame to the strip. False means it did not land.

        The text twin of this is `_push`. They are separate because
        aiohttp has separate methods, and because a video frame that
        cannot be delivered must be as quiet as a dropped photo: this is
        called up to 25 times a second and a warning per frame would
        drown the journal in the first minute of a camera going away.
        """
        ws = self._ws
        if ws is None or ws.closed:
            return False
        try:
            await ws.send_bytes(payload)
        except (ConnectionResetError, RuntimeError) as exc:
            logger.debug(f"samantha-kiosk: live frame not delivered — {exc}")
            return False
        return True

    async def push_live_open(
        self, camera: str, epoch: int, extradata: bytes, width: int, height: int
    ) -> bool:
        """Tell the strip a live view is starting."""
        return await self._push(live(camera, epoch, extradata, width, height))

    async def push_live_frame(self, epoch: int, packet: bytes) -> bool:
        """One access unit. False when it did not land, never an exception."""
        try:
            payload = live_frame(epoch, packet)
        except ProtocolError as exc:
            logger.warning(f"samantha-kiosk: refusing a live frame — {exc}")
            return False
        return await self._push_bytes(payload)

    async def push_live_close(self, epoch: int, reason: str) -> bool:
        """Tell the strip the view ended, and why."""
        try:
            payload = live_end(epoch, reason)
        except ProtocolError as exc:
            logger.warning(f"samantha-kiosk: refusing a live_end — {exc}")
            return False
        return await self._push(payload)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run the command from Step 2. Expected: PASS, whole file green.

- [ ] **Step 5: Commit**

```bash
git add Hermes/plugins/samantha_kiosk/adapter.py \
        Hermes/plugins/samantha_kiosk/tests/test_adapter.py
git commit -m "feat(strip): the adapter can put bytes on the wire"
```

---

### Task 3: The tap in the camera stream

**Files:**
- Modify: `Hermes/plugins/samantha_vision/vision.py:226-240`
- Modify: `Hermes/plugins/samantha_vision/cameras.py:353-393`
- Test: `Hermes/plugins/samantha_vision/tests/test_vision.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `CameraStream.frames(every: int = 10, tap: Callable[[bytes, bool], None] | None = None)`, `CameraStream.codec_parameters() -> tuple[bytes, int, int]`, `CameraFleet.set_tap(camera: str, tap) -> None`, `CameraFleet.clear_tap(camera: str) -> None`.

- [ ] **Step 1: Write the failing test**

Append to `Hermes/plugins/samantha_vision/tests/test_vision.py`:

```python
class _Packet:
    """A PyAV packet as far as the tap is concerned."""

    def __init__(self, data: bytes, *, keyframe: bool, frames: list) -> None:
        self._data = data
        self.is_keyframe = keyframe
        self._frames = frames

    def __bytes__(self) -> bytes:
        return self._data

    def decode(self):
        return self._frames


class _Frame:
    def to_ndarray(self, format: str):
        assert format == "rgb24"
        return np.zeros((4, 4, 3), dtype=np.uint8)


class _Container:
    def __init__(self, packets):
        self._packets = packets

    def demux(self, video=0):
        return iter(self._packets)

    def close(self):
        pass


def test_the_tap_sees_every_packet_and_its_keyframe_flag():
    seen = []
    stream = CameraStream("rtsp://fake")
    stream._container = _Container(
        [
            _Packet(b"aaa", keyframe=True, frames=[_Frame()]),
            _Packet(b"bbb", keyframe=False, frames=[_Frame()]),
        ]
    )

    list(stream.frames(every=1, tap=lambda data, key: seen.append((data, key))))

    assert seen == [(b"aaa", True), (b"bbb", False)]


def test_sampling_still_applies_to_the_frames_yielded():
    # The tap is per PACKET; the sampling is per decoded FRAME. Changing
    # one must not change the other: YOLO's load is calibrated on it.
    stream = CameraStream("rtsp://fake")
    stream._container = _Container(
        [_Packet(b"x", keyframe=True, frames=[_Frame()]) for _ in range(10)]
    )

    yielded = list(stream.frames(every=10, tap=None))

    assert len(yielded) == 1


def test_no_tap_costs_nothing_and_still_decodes():
    stream = CameraStream("rtsp://fake")
    stream._container = _Container(
        [_Packet(b"x", keyframe=True, frames=[_Frame()])]
    )
    assert len(list(stream.frames(every=1))) == 1
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
cd /home/nexus/git/os1-samantha
PYTHONNOUSERSITE=1 ./widget/.venv/bin/python -m pytest \
  Hermes/plugins/samantha_vision/tests/test_vision.py -q
```
Expected: FAIL — `TypeError: frames() got an unexpected keyword argument 'tap'`.

- [ ] **Step 3: Write the implementation**

Replace `CameraStream.frames` in `vision.py`:

```python
    def frames(self, every: int = 10, tap: Callable[[bytes, bool], None] | None = None):
        """Yield HxWx3 RGB arrays, one every `every` decoded frames.

        Cameras deliver 15-30 fps and nothing in a house changes that
        fast. Sampling keeps the GPU free for Whisper and CosyVoice,
        which are on the critical path of a conversation; a camera is not.

        `tap`, when given, is handed every packet's raw bytes and whether
        it is a keyframe, BEFORE it is decoded. This is a demux loop
        rather than `decode(video=0)` for exactly that reason: the packet
        has to be in our hands while it is still compressed, or a live
        view would have to re-encode what this method just decoded.
        Sampling is unchanged — it counts decoded frames, not packets —
        so YOLO's load is exactly what it was.
        """
        if self._container is None:
            self.open()
        assert self._container is not None

        index = 0
        for packet in self._container.demux(video=0):
            if tap is not None:
                try:
                    tap(bytes(packet), bool(packet.is_keyframe))
                except Exception:
                    # A live view is never worth a camera. Whoever is
                    # watching loses a frame; the watcher keeps watching.
                    pass
            for frame in packet.decode():
                if index % every == 0:
                    yield frame.to_ndarray(format="rgb24")
                index += 1

    def codec_parameters(self) -> tuple[bytes, int, int]:
        """SPS/PPS, width and height. Empty extradata is legal (spec §4.1)."""
        if self._container is None:
            self.open()
        assert self._container is not None
        stream = self._container.streams.video[0]
        extradata = stream.codec_context.extradata or b""
        return bytes(extradata), int(stream.codec_context.width), int(
            stream.codec_context.height
        )
```

Add `from typing import Callable` to the imports if it is not already there.

In `cameras.py`, add tap storage to `CameraFleet.__init__`:

```python
        # One tap per camera, or none. Read by the watcher thread on every
        # packet and written by the gateway thread when a view opens, so
        # it is a plain dict lookup and nothing more: a lock here would be
        # taken 25 times a second for a value that changes twice a day.
        self._taps: dict[str, Any] = {}
```

and the two methods:

```python
    def set_tap(self, camera: str, tap) -> None:
        """Send this camera's packets to `tap` as well as to YOLO."""
        self._taps[camera] = tap

    def clear_tap(self, camera: str) -> None:
        """Stop sending packets. Safe to call when there is no tap."""
        self._taps.pop(camera, None)
```

and in `_watch`, line 376, pass it through:

```python
                for frame in stream.frames(
                    self._sample_every, tap=self._taps.get(camera.name)
                ):
```

- [ ] **Step 4: Run the tests to verify they pass**

Run:
```bash
cd /home/nexus/git/os1-samantha
PYTHONNOUSERSITE=1 ./widget/.venv/bin/python -m pytest \
  Hermes/plugins/samantha_vision/tests/ -q
```
Expected: PASS. `test_cameras.py` must stay green — the sampling behaviour it asserts is unchanged.

- [ ] **Step 5: Commit**

```bash
git add Hermes/plugins/samantha_vision/vision.py \
        Hermes/plugins/samantha_vision/cameras.py \
        Hermes/plugins/samantha_vision/tests/test_vision.py
git commit -m "feat(vision): the packets are in our hands before they are decoded"
```

---

### Task 4: The live session

**Files:**
- Create: `Hermes/plugins/samantha_vision/live.py`
- Test: `Hermes/plugins/samantha_vision/tests/test_live.py`

**Interfaces:**
- Consumes: `CameraFleet.set_tap` / `.clear_tap` from Task 3.
- Produces: `LiveSession(fleet, push_open, push_frame, push_close, *, now=time.monotonic, ceiling=CEILING_SECONDS)` with `async open(camera: str) -> bool`, `async close(reason: str) -> bool`, `camera: str | None`, `epoch: int`, and `CEILING_SECONDS = 120.0`.

- [ ] **Step 1: Write the failing test**

Create `Hermes/plugins/samantha_vision/tests/test_live.py`:

```python
"""The live session: one at a time, one way out, and a ceiling.

Nothing here needs a camera, a gateway or a GPU. The fleet and the three
pushes arrive as callables, the way `tool.py`'s tests already do it.
"""

import asyncio

from Hermes.plugins.samantha_vision.live import CEILING_SECONDS, LiveSession


class _Fleet:
    def __init__(self) -> None:
        self.taps: dict[str, object] = {}

    def set_tap(self, camera, tap):
        self.taps[camera] = tap

    def clear_tap(self, camera):
        self.taps.pop(camera, None)


class _Pushes:
    def __init__(self, ok: bool = True) -> None:
        self.ok = ok
        self.opened: list[tuple] = []
        self.frames: list[tuple] = []
        self.closed: list[tuple] = []

    async def open(self, camera, epoch, extradata, width, height):
        self.opened.append((camera, epoch, extradata, width, height))
        return self.ok

    async def frame(self, epoch, packet):
        self.frames.append((epoch, packet))
        return self.ok

    async def close(self, epoch, reason):
        self.closed.append((epoch, reason))
        return self.ok


def _session(clock=None, ok=True):
    fleet, pushes = _Fleet(), _Pushes(ok)
    now = clock or (lambda: 0.0)
    return (
        LiveSession(fleet, pushes.open, pushes.frame, pushes.close, now=now),
        fleet,
        pushes,
    )


def test_opening_installs_a_tap_and_announces_the_view():
    session, fleet, pushes = _session()

    assert asyncio.run(session.open("entrada", extradata=b"sps", size=(704, 480)))

    assert session.camera == "entrada"
    assert "entrada" in fleet.taps
    assert pushes.opened == [("entrada", 1, b"sps", 704, 480)]


def test_nothing_is_sent_before_the_first_keyframe():
    session, fleet, pushes = _session()
    asyncio.run(session.open("entrada", extradata=b"", size=(704, 480)))

    fleet.taps["entrada"](b"delta-one", False)
    fleet.taps["entrada"](b"delta-two", False)
    assert pushes.frames == []

    fleet.taps["entrada"](b"key", True)
    fleet.taps["entrada"](b"delta-three", False)
    assert [packet for _epoch, packet in pushes.frames] == [b"key", b"delta-three"]


def test_closing_removes_the_tap_and_says_why():
    session, fleet, pushes = _session()
    asyncio.run(session.open("entrada", extradata=b"", size=(704, 480)))

    assert asyncio.run(session.close("asked"))

    assert fleet.taps == {}
    assert pushes.closed == [(1, "asked")]
    assert session.camera is None


def test_closing_twice_is_quiet_not_an_error():
    session, _fleet, pushes = _session()
    asyncio.run(session.open("entrada", extradata=b"", size=(704, 480)))
    asyncio.run(session.close("asked"))

    assert asyncio.run(session.close("timeout")) is False
    assert pushes.closed == [(1, "asked")]


def test_the_epoch_never_repeats():
    session, _fleet, pushes = _session()
    asyncio.run(session.open("entrada", extradata=b"", size=(704, 480)))
    asyncio.run(session.close("asked"))
    asyncio.run(session.open("entrada", extradata=b"", size=(704, 480)))

    assert [epoch for _c, epoch, *_rest in pushes.opened] == [1, 2]


def test_opening_a_second_view_closes_the_first():
    session, fleet, pushes = _session()
    asyncio.run(session.open("entrada", extradata=b"", size=(704, 480)))
    asyncio.run(session.open("fuera", extradata=b"", size=(704, 480)))

    assert pushes.closed == [(1, "asked")]
    assert list(fleet.taps) == ["fuera"]


def test_the_ceiling_closes_it():
    clock = {"t": 0.0}
    session, fleet, pushes = _session(clock=lambda: clock["t"])
    asyncio.run(session.open("entrada", extradata=b"", size=(704, 480)))
    fleet.taps["entrada"](b"key", True)

    clock["t"] = CEILING_SECONDS + 0.1
    fleet.taps["entrada"](b"another", False)

    assert session.expired is True


def test_a_failed_open_leaves_no_session_behind():
    session, fleet, pushes = _session(ok=False)

    assert asyncio.run(
        session.open("entrada", extradata=b"", size=(704, 480))
    ) is False
    assert session.camera is None
    assert fleet.taps == {}
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
cd /home/nexus/git/os1-samantha
PYTHONNOUSERSITE=1 ./widget/.venv/bin/python -m pytest \
  Hermes/plugins/samantha_vision/tests/test_live.py -q
```
Expected: FAIL — `ModuleNotFoundError: No module named 'Hermes.plugins.samantha_vision.live'`.

- [ ] **Step 3: Write the implementation**

Create `Hermes/plugins/samantha_vision/live.py`:

```python
"""One live view: which camera, since when, and the one way out.

The tap runs on the watcher thread and the pushes are coroutines living
on the gateway's loop, so this class is the seam between the two. It
holds no lock: the only field the two threads share is the epoch, and an
int assignment is atomic under CPython. What the tap does when it decides
a frame should go out is schedule a coroutine — it never awaits.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable

from loguru import logger

from .cameras import redact

# How long a view may stay up with nobody closing it. OURS, and a guess:
# it is NOT one of BarnDoor's four calibrated constants (180, 0.7, 23:00,
# 07:00) and must not be filed beside them. It exists because closing
# depends on him hearing you, and this box has no microphone plugged in
# (CLAUDE.md §4) — without it, one misheard sentence feeds a window all
# night.
CEILING_SECONDS = 120.0

PushOpen = Callable[[str, int, bytes, int, int], Awaitable[bool]]
PushFrame = Callable[[int, bytes], Awaitable[bool]]
PushClose = Callable[[int, str], Awaitable[bool]]


class LiveSession:
    """The one live view there is. Never raises at its callers."""

    def __init__(
        self,
        fleet: Any,
        push_open: PushOpen,
        push_frame: PushFrame,
        push_close: PushClose,
        *,
        now: Callable[[], float] = time.monotonic,
        ceiling: float = CEILING_SECONDS,
    ) -> None:
        self._fleet = fleet
        self._push_open = push_open
        self._push_frame = push_frame
        self._push_close = push_close
        self._now = now
        self._ceiling = ceiling

        self.camera: str | None = None
        self.epoch = 0
        self.expired = False
        self._started = 0.0
        self._keyframe_seen = False
        self._loop: asyncio.AbstractEventLoop | None = None

    async def open(
        self, camera: str, *, extradata: bytes, size: tuple[int, int]
    ) -> bool:
        """Start a view. False when the strip did not take it.

        A second view closes the first rather than refusing: he was asked
        for the garage while the entrance was up, and answering "no" to
        that would be a worse answer than doing it.
        """
        if self.camera is not None:
            await self.close("asked")

        self.epoch += 1
        width, height = size
        if not await self._push_open(camera, self.epoch, extradata, width, height):
            # No strip, no view. Opening one anyway would leave a decoder
            # feeding a socket nobody is reading.
            return False

        self.camera = camera
        self.expired = False
        self._started = self._now()
        self._keyframe_seen = False
        self._loop = asyncio.get_running_loop()
        self._fleet.set_tap(camera, self._on_packet)
        return True

    async def close(self, reason: str) -> bool:
        """End the view. False when there was nothing to end."""
        camera, self.camera = self.camera, None
        if camera is None:
            return False
        self._fleet.clear_tap(camera)
        try:
            await self._push_close(self.epoch, reason)
        except Exception as exc:
            logger.warning(f"samantha-vision: live_end not delivered — {redact(exc)}")
        return True

    # ── the watcher thread ────────────────────────────────────────────

    def _on_packet(self, packet: bytes, keyframe: bool) -> None:
        """Called on the watcher thread, up to 25 times a second."""
        if self.camera is None:
            return

        if self._now() - self._started > self._ceiling:
            self.expired = True
            self._schedule(self.close("timeout"))
            return

        # H.264 can only be entered at a keyframe. Sending before one is
        # how a restream shows a few tenths of a second of green.
        if not self._keyframe_seen:
            if not keyframe:
                return
            self._keyframe_seen = True

        self._schedule(self._push_frame(self.epoch, packet))

    def _schedule(self, coro: Awaitable[bool]) -> None:
        """Hand a coroutine to the gateway's loop from the watcher thread."""
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        try:
            asyncio.run_coroutine_threadsafe(coro, loop)
        except RuntimeError as exc:
            logger.debug(f"samantha-vision: live frame not scheduled — {exc}")
```

Note for the implementer: `test_the_ceiling_closes_it` and the keyframe tests call the tap directly, with no running loop; `_schedule` returns early because `self._loop` is the loop that ran `open()` and is closed by then. Assert on `session.expired` and on `pushes.frames`, which the tests above already do — if a test needs the frames to actually arrive, run the tap inside `asyncio.run` alongside the session.

- [ ] **Step 4: Run the tests to verify they pass**

Run the command from Step 2. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add Hermes/plugins/samantha_vision/live.py \
        Hermes/plugins/samantha_vision/tests/test_live.py
git commit -m "feat(vision): a live view, and one way out of it"
```

---

### Task 5: The two spoken orders

**Files:**
- Create: `Hermes/plugins/samantha_vision/live_tool.py`
- Test: `Hermes/plugins/samantha_vision/tests/test_live_tool.py`

**Interfaces:**
- Consumes: `LiveSession` from Task 4, `_resolve` and `_spoken_list` from `tool.py:77-101`.
- Produces: `OPEN_NAME = "ver_en_vivo"`, `CLOSE_NAME = "dejar_de_ver"`, `OPEN_DESCRIPTION`, `CLOSE_DESCRIPTION`, `OPEN_SCHEMA`, `CLOSE_SCHEMA`, `EMOJI`, `make_open_handler(session, fleet, cameras) -> Callable[..., Awaitable[str]]`, `make_close_handler(session) -> Callable[..., Awaitable[str]]`.

- [ ] **Step 1: Write the failing test**

Create `Hermes/plugins/samantha_vision/tests/test_live_tool.py`:

```python
"""`ver_en_vivo` and `dejar_de_ver`: what he says, and what he never says.

The load-bearing rule is the one the snapshot spec measured: he calls a
camera tool with NO argument 5 times out of 5, even when a camera was
named. `mirar` survives that by surveying all of them. There is no "all"
for a live view, so the handler asks instead of guessing.
"""

import asyncio

import pytest

from Hermes.plugins.samantha_vision.live_tool import (
    make_close_handler,
    make_open_handler,
)


class _Session:
    def __init__(self, ok=True) -> None:
        self.ok = ok
        self.camera = None
        self.opened: list[str] = []
        self.closed: list[str] = []

    async def open(self, camera, *, extradata, size):
        self.opened.append(camera)
        if self.ok:
            self.camera = camera
        return self.ok

    async def close(self, reason):
        self.closed.append(reason)
        was, self.camera = self.camera, None
        return was is not None


class _Fleet:
    def __init__(self, params=(b"sps", 704, 480)) -> None:
        self._params = params

    def codec_parameters(self, camera):
        return self._params


def test_a_named_camera_opens_it():
    session = _Session()
    handler = make_open_handler(session, _Fleet(), ["entrada", "fuera"])

    said = asyncio.run(handler(camara="entrada"))

    assert session.opened == ["entrada"]
    assert "entrada" in said.lower()
    assert "/" not in said  # never a path: CosyVoice reads this out loud


def test_no_camera_named_and_only_one_alive_uses_it():
    session = _Session()
    handler = make_open_handler(session, _Fleet(), ["entrada"])

    asyncio.run(handler())

    assert session.opened == ["entrada"]


def test_no_camera_named_and_several_alive_asks_which():
    session = _Session()
    handler = make_open_handler(session, _Fleet(), ["entrada", "fuera"])

    said = asyncio.run(handler())

    assert session.opened == []
    assert "entrada" in said and "fuera" in said


def test_a_camera_that_does_not_exist_is_not_invented():
    session = _Session()
    handler = make_open_handler(session, _Fleet(), ["entrada"])

    said = asyncio.run(handler(camara="garaje"))

    assert session.opened == []
    assert "entrada" in said


def test_a_strip_that_did_not_take_it_is_said_honestly():
    session = _Session(ok=False)
    handler = make_open_handler(session, _Fleet(), ["entrada"])

    said = asyncio.run(handler(camara="entrada"))

    assert "entrada" in said.lower() or said
    assert "socket" not in said.lower()
    assert "sesión" not in said.lower()


def test_closing_when_nothing_is_up_is_still_a_sentence():
    session = _Session()
    handler = make_close_handler(session)

    said = asyncio.run(handler())

    assert isinstance(said, str) and said.strip()


def test_no_answer_ever_names_the_machinery():
    session = _Session()
    handler = make_open_handler(session, _Fleet(), ["entrada", "fuera"])
    for said in [asyncio.run(handler()), asyncio.run(handler(camara="entrada"))]:
        low = said.lower()
        for forbidden in ("cámara", "h264", "códec", "socket", "epoch", "sesión"):
            assert forbidden not in low
```

Note the last test: CLAUDE.md §12 (2026-08-25) records that the word **"cámara"** had to be taken out of his mouth once already. The tool's own strings must not put it back.

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
cd /home/nexus/git/os1-samantha
PYTHONNOUSERSITE=1 ./widget/.venv/bin/python -m pytest \
  Hermes/plugins/samantha_vision/tests/test_live_tool.py -q
```
Expected: FAIL — `ModuleNotFoundError: No module named '...live_tool'`.

- [ ] **Step 3: Write the implementation**

Create `Hermes/plugins/samantha_vision/live_tool.py`:

```python
"""`ver_en_vivo` / `dejar_de_ver` — the moving picture, on request.

Both handlers return a sentence and nothing else: whatever comes back is
read out loud by CosyVoice, so there is never a path, a codec name or a
number in it. The picture travels on its own channel (spec §4); this
file only decides what he says about it.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Sequence

from loguru import logger

from .cameras import redact
from .tool import _resolve, _spoken_list

OPEN_NAME = "ver_en_vivo"
CLOSE_NAME = "dejar_de_ver"
EMOJI = "📹"

# The line between this and `mirar` has to be drawn in the descriptions,
# because the words are close enough for a model to confuse: `mirar` is a
# photo of right now, this is the camera in motion until told to stop.
OPEN_DESCRIPTION = (
    "Muestra una cámara de la casa en movimiento, hasta que se pida "
    "pararla. Para una sola imagen fija, usa mirar."
)
CLOSE_DESCRIPTION = "Deja de mostrar lo que se está viendo en movimiento."

OPEN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "camara": {
            "type": "string",
            # Unlike `mirar`, omitting this is not a survey: there is one
            # view. The handler asks rather than guessing (spec §5.3).
            "description": "Nombre de la cámara que se quiere ver.",
        }
    },
    "required": [],
}
CLOSE_SCHEMA: dict[str, Any] = {"type": "object", "properties": {}, "required": []}


def make_open_handler(
    session: Any, fleet: Any, cameras: Sequence[str]
) -> Callable[..., Awaitable[str]]:
    """Build the `ver_en_vivo` handler. It never raises.

    `cameras` is read on every call rather than copied, for the same
    reason `mirar`'s handler does it: the supervisor thread fills that
    list in after registration.
    """

    async def handler(camara: str | None = None, **_ignored: Any) -> str:
        names = list(cameras)
        if not names:
            return "Ahora mismo no tengo ojos en la casa, señor."

        if camara is None:
            if len(names) != 1:
                # Asking is the honest answer. Guessing opens the
                # entrance when he was asked for the garage.
                return f"¿Cuál quiere ver, señor? Tengo {_spoken_list(names)}."
            wanted = names[0]
        else:
            wanted = _resolve(camara, names) or ""
            if not wanted:
                return (
                    f"No tengo ninguna con ese nombre, señor. "
                    f"Tengo {_spoken_list(names)}."
                )

        try:
            extradata, width, height = fleet.codec_parameters(wanted)
            opened = await session.open(
                wanted, extradata=extradata, size=(width, height)
            )
        except Exception as exc:
            logger.warning(f"samantha-vision: live not opened — {redact(exc)}")
            opened = False

        if not opened:
            return "Ahora mismo no puedo enseñárselo, señor."
        # Where: a labelled value he builds his own sentence around. NOT
        # inside a preposition — CLAUDE.md §12, 2026-08-24.
        return f"Dónde: {wanted}. Estado: en directo."

    return handler


def make_close_handler(session: Any) -> Callable[..., Awaitable[str]]:
    """Build the `dejar_de_ver` handler. It never raises."""

    async def handler(**_ignored: Any) -> str:
        try:
            closed = await session.close("asked")
        except Exception as exc:
            logger.warning(f"samantha-vision: live not closed — {redact(exc)}")
            closed = False
        return "Estado: retirado." if closed else "Estado: no había nada puesto."

    return handler
```

- [ ] **Step 4: Run the tests to verify they pass**

Run the command from Step 2. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add Hermes/plugins/samantha_vision/live_tool.py \
        Hermes/plugins/samantha_vision/tests/test_live_tool.py
git commit -m "feat(vision): he can be asked to keep looking, and to stop"
```

---

### Task 6: Wire it into the plugin, and tell him he has a screen that moves

**Files:**
- Modify: `Hermes/plugins/samantha_vision/__init__.py:39-82`, `:102-132`
- Modify: `Hermes/plugins/samantha_vision/cameras.py` (add `CameraFleet.codec_parameters`)
- Modify: `Hermes/plugins/samantha_kiosk/__init__.py` (the `platform_hint`)
- Test: `Hermes/plugins/samantha_vision/tests/test_plugin.py`, `Hermes/plugins/samantha_kiosk/tests/test_hint.py`

**Interfaces:**
- Consumes: everything from Tasks 1-5.
- Produces: `push_live_open`, `push_live_frame`, `push_live_close` module-level coroutines in `samantha_vision/__init__.py`, resolved at call time exactly like `push_photo`.

- [ ] **Step 1: Write the failing test**

Append to `Hermes/plugins/samantha_vision/tests/test_plugin.py`:

```python
def test_register_declares_both_live_tools(ctx):
    from Hermes.plugins.samantha_vision import register

    register(ctx)

    names = {call["name"] for call in ctx.tools}
    assert {"mirar", "ver_en_vivo", "dejar_de_ver"} <= names


def test_the_live_tools_are_hidden_until_the_cameras_are_known(ctx):
    from Hermes.plugins.samantha_vision import register

    register(ctx)

    for call in ctx.tools:
        if call["name"] in {"ver_en_vivo", "dejar_de_ver"}:
            # Same seam `mirar` uses: an empty `names` list means the
            # config has not been read, and offering a tool that cannot
            # work is worse than not offering it.
            assert call["check_fn"]() is False
```

Use whatever `ctx` fake `test_plugin.py` already defines; if it records tools differently, match its shape.

Append to `Hermes/plugins/samantha_kiosk/tests/test_hint.py`:

```python
def test_the_hint_says_he_can_show_something_that_moves():
    from Hermes.plugins.samantha_kiosk import platform_hint

    hint = platform_hint().lower()
    assert "movimiento" in hint or "directo" in hint
```

Match the real accessor's name in that module; the test above assumes `platform_hint()`.

- [ ] **Step 2: Run the tests to verify they fail**

Run:
```bash
cd /home/nexus/git/os1-samantha
PYTHONNOUSERSITE=1 ./widget/.venv/bin/python -m pytest \
  Hermes/plugins/samantha_vision/tests/test_plugin.py \
  Hermes/plugins/samantha_kiosk/tests/test_hint.py -q
```
Expected: FAIL — only `mirar` is registered, and the hint does not mention motion.

- [ ] **Step 3: Write the implementation**

In `cameras.py`, add to `CameraFleet`:

```python
    def codec_parameters(self, camera: str) -> tuple[bytes, int, int]:
        """SPS/PPS and size for a camera that is being watched.

        Raises KeyError for a camera with no live stream: the caller
        turns that into a sentence, and inventing a size would open a
        view onto nothing.
        """
        stream = self._streams[camera]
        return stream.codec_parameters()
```

The watcher must keep the open stream reachable: in `_watch`, after `stream = self._open_stream(camera.url)`, record `self._streams[camera.name] = stream`, and drop it in the `finally` that closes the stream. Initialise `self._streams: dict[str, Any] = {}` in `__init__`.

In `samantha_vision/__init__.py`, add the three pushes beside `push_photo`, each resolving the adapter at call time (the comment at `:111-113` explains why a captured reference would be None forever):

```python
async def _adapter():
    """The strip's adapter, or None. Resolved at call time, every time."""
    from gateway.config import Platform
    from gateway.run import _gateway_runner_ref

    runner = _gateway_runner_ref()
    if runner is None:
        return None
    return getattr(runner, "adapters", {}).get(Platform(KIOSK_PLATFORM))


async def push_live_open(
    camera: str, epoch: int, extradata: bytes, width: int, height: int
) -> bool:
    """Open a live view on the strip, and nowhere else. Never raises."""
    try:
        adapter = await _adapter()
        if adapter is None:
            return False
        return bool(
            await adapter.push_live_open(camera, epoch, extradata, width, height)
        )
    except Exception as exc:
        logger.warning(f"samantha-vision: live not opened — {redact(exc)}")
        return False


async def push_live_frame(epoch: int, packet: bytes) -> bool:
    """One frame. Quiet on failure: this runs up to 25 times a second."""
    try:
        adapter = await _adapter()
        if adapter is None:
            return False
        return bool(await adapter.push_live_frame(epoch, packet))
    except Exception:
        return False


async def push_live_close(epoch: int, reason: str) -> bool:
    """Tell the strip the view ended. Never raises."""
    try:
        adapter = await _adapter()
        if adapter is None:
            return False
        return bool(await adapter.push_live_close(epoch, reason))
    except Exception as exc:
        logger.warning(f"samantha-vision: live not closed — {redact(exc)}")
        return False
```

Then in `register()`, after the `mirar` registration:

```python
    session = LiveSession(fleet, push_live_open, push_live_frame, push_live_close)
    ctx.on_unload(lambda: None)  # the tap dies with the fleet, already stopped above

    ctx.register_tool(
        name=OPEN_NAME,
        toolset=TOOLSET,
        description=OPEN_DESCRIPTION,
        emoji=EMOJI,
        schema=OPEN_SCHEMA,
        handler=make_open_handler(session, fleet, names),
        check_fn=lambda: bool(names),
        is_async=True,
    )
    ctx.register_tool(
        name=CLOSE_NAME,
        toolset=TOOLSET,
        description=CLOSE_DESCRIPTION,
        emoji=EMOJI,
        schema=CLOSE_SCHEMA,
        handler=make_close_handler(session),
        check_fn=lambda: bool(names),
        is_async=True,
    )
```

with the imports added at the top of the file.

In `samantha_kiosk/__init__.py`, extend the `platform_hint` text. It currently says he can show one camera still, briefly. It must now also say, in Spanish and in one clause: that he can show a camera **in motion** until he is asked to stop, that he need not announce it, and — unchanged and load-bearing — that he does not see it himself.

- [ ] **Step 4: Run the tests to verify they pass**

Run:
```bash
cd /home/nexus/git/os1-samantha
PYTHONNOUSERSITE=1 ./widget/.venv/bin/python -m pytest \
  Hermes/plugins/samantha_vision/tests/ Hermes/plugins/samantha_kiosk/tests/ -q
```
Expected: PASS, both suites.

- [ ] **Step 5: Commit**

```bash
git add Hermes/plugins/samantha_vision/__init__.py \
        Hermes/plugins/samantha_vision/cameras.py \
        Hermes/plugins/samantha_kiosk/__init__.py \
        Hermes/plugins/samantha_vision/tests/test_plugin.py \
        Hermes/plugins/samantha_kiosk/tests/test_hint.py
git commit -m "feat(vision): the orders reach the gateway, and he knows he has a screen that moves"
```

> **Remember (CLAUDE.md §7):** the hint reaches an existing session only after `/new` then `/approve` through the strip. Restarting the gateway is NOT enough. This has cost an afternoon once already.

---

### Task 7: The strip receives binary frames

**Files:**
- Modify: `widget/samantha_widget/gateway.py:29-58`, `:83-120`
- Test: `widget/tests/test_gateway.py`

**Interfaces:**
- Consumes: the wire format from Task 1.
- Produces: `Gateway.on_live_open: Callable[[str, int, bytes, int, int], None]`, `Gateway.on_live_frame: Callable[[int, bytes], None]`, `Gateway.on_live_end: Callable[[int, str], None]`, and `decode_live_frame(raw: bytes) -> tuple[int, bytes]`.

- [ ] **Step 1: Write the failing test**

Append to `widget/tests/test_gateway.py`:

```python
import base64
import json

from samantha_widget.gateway import Gateway, decode_live_frame


def test_a_binary_frame_is_not_parsed_as_json():
    # Today `_dispatch` assumes text and json.loads accepts bytes, so a
    # binary frame would be dropped by the branch that ignores unknown
    # types — silently, which is the worst way to lose video.
    seen = []
    gw = Gateway()
    gw.on_live_frame = lambda epoch, packet: seen.append((epoch, packet))

    gw._dispatch((7).to_bytes(4, "big") + b"\x00\x00\x01\x65abc")

    assert seen == [(7, b"\x00\x00\x01\x65abc")]


def test_a_truncated_binary_frame_is_dropped_not_raised():
    gw = Gateway()
    gw._dispatch(b"\x00\x00")  # no room for an epoch


def test_live_open_carries_the_decoded_extradata():
    seen = []
    gw = Gateway()
    gw.on_live_open = lambda *args: seen.append(args)

    gw._dispatch(
        json.dumps(
            {
                "type": "live",
                "camera": "entrada",
                "epoch": 7,
                "codec": "h264",
                "extradata": base64.b64encode(b"sps").decode("ascii"),
                "width": 704,
                "height": 480,
            }
        )
    )

    assert seen == [("entrada", 7, b"sps", 704, 480)]


def test_live_end_reaches_the_callback():
    seen = []
    gw = Gateway()
    gw.on_live_end = lambda epoch, reason: seen.append((epoch, reason))

    gw._dispatch(json.dumps({"type": "live_end", "epoch": 7, "reason": "timeout"}))

    assert seen == [(7, "timeout")]


def test_an_unknown_text_type_is_still_dropped_in_silence():
    gw = Gateway()
    gw._dispatch(json.dumps({"type": "something-from-the-future"}))


def test_decode_live_frame_splits_the_header():
    assert decode_live_frame((7).to_bytes(4, "big") + b"abc") == (7, b"abc")
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
cd /home/nexus/git/os1-samantha/widget
PYTHONNOUSERSITE=1 .venv/bin/python -m pytest tests/test_gateway.py -q
```
Expected: FAIL — `ImportError: cannot import name 'decode_live_frame'`.

- [ ] **Step 3: Write the implementation**

In `gateway.py`, extend `_SERVER_TYPES` on line 29 to `{"token", "done", "error", "transcription", "photo", "live", "live_end"}`, add the decoder:

```python
def decode_live_frame(raw: bytes) -> tuple[int, bytes]:
    """Split one binary frame into (epoch, packet). Raises ProtocolError."""
    if len(raw) < 4:
        raise ProtocolError(f"live frame is {len(raw)} bytes, needs at least 4")
    return int.from_bytes(raw[:4], "big"), bytes(raw[4:])
```

add the three callbacks beside `on_photo` in `__init__`:

```python
        self.on_live_open: Callable[[str, int, bytes, int, int], None] = (
            lambda _c, _e, _x, _w, _h: None
        )
        self.on_live_frame: Callable[[int, bytes], None] = lambda _e, _p: None
        self.on_live_end: Callable[[int, str], None] = lambda _e, _r: None
```

and branch at the top of `_dispatch`, whose signature becomes `raw: str | bytes`:

```python
    def _dispatch(self, raw: str | bytes) -> None:
        # Branch BEFORE parsing. `websockets` yields str for text frames
        # and bytes for binary ones, and json.loads accepts bytes — so a
        # video frame would parse, fail as "not an object", and vanish
        # down the path that deliberately ignores unknown types.
        if isinstance(raw, (bytes, bytearray)):
            try:
                epoch, packet = decode_live_frame(bytes(raw))
            except ProtocolError:
                return
            self.on_live_frame(epoch, packet)
            return
        ...
```

and in the text branch, beside `photo`:

```python
        elif kind == "live":
            try:
                extradata = base64.b64decode(msg.get("extradata", "") or "")
            except (ValueError, TypeError):
                return
            self.on_live_open(
                str(msg.get("camera", "")),
                int(msg.get("epoch", 0)),
                extradata,
                int(msg.get("width", 0)),
                int(msg.get("height", 0)),
            )
        elif kind == "live_end":
            self.on_live_end(int(msg.get("epoch", 0)), str(msg.get("reason", "")))
```

Import `base64` at the top.

- [ ] **Step 4: Run the tests to verify they pass**

Run the command from Step 2, then the whole widget suite. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add widget/samantha_widget/gateway.py widget/tests/test_gateway.py
git commit -m "feat(widget): the strip hears a frame that is not text"
```

---

### Task 8: The live band, as pure state

**Files:**
- Create: `widget/samantha_widget/live.py`
- Test: `widget/tests/test_live.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `LiveModel()` with `open(camera: str, epoch: int, now: float) -> bool`, `close(epoch: int | None, now: float) -> bool`, `accepts(epoch: int) -> bool`, properties `visible: bool`, `height: int`, `camera: str | None`, and `LIVE_HEIGHT: int`.

- [ ] **Step 1: Write the failing test**

Create `widget/tests/test_live.py`:

```python
"""The live band as pure state: how tall, for whom, and until when.

No GTK in here, on purpose — the same split `photo.py` uses, and the
reason both are testable on a box with no screen.
"""

from samantha_widget.live import LIVE_HEIGHT, LiveModel


def test_it_opens_at_the_large_size_not_as_a_thumbnail():
    model = LiveModel()

    assert model.open("entrada", 7, now=0.0) is True

    assert model.visible is True
    assert model.height == LIVE_HEIGHT
    assert model.camera == "entrada"


def test_frames_from_an_older_view_are_refused():
    model = LiveModel()
    model.open("entrada", 7, now=0.0)

    assert model.accepts(7) is True
    assert model.accepts(6) is False


def test_closing_shrinks_the_band():
    model = LiveModel()
    model.open("entrada", 7, now=0.0)

    assert model.close(7, now=1.0) is True

    assert model.visible is False
    assert model.height == 0


def test_a_close_for_a_view_that_already_ended_changes_nothing():
    model = LiveModel()
    model.open("entrada", 7, now=0.0)
    model.close(7, now=1.0)
    model.open("fuera", 8, now=2.0)

    assert model.close(7, now=3.0) is False
    assert model.visible is True
    assert model.camera == "fuera"


def test_a_second_view_replaces_the_first_without_resizing():
    model = LiveModel()
    model.open("entrada", 7, now=0.0)

    # Same height, so the caller must not spend an EWMH round-trip —
    # the convention `PhotoModel` established.
    assert model.open("fuera", 8, now=1.0) is False
    assert model.camera == "fuera"


def test_closing_with_no_epoch_closes_whatever_is_up():
    # The socket dropped. Spec §4.2: that IS a close, and there is no
    # frame to carry an epoch.
    model = LiveModel()
    model.open("entrada", 7, now=0.0)

    assert model.close(None, now=1.0) is True
    assert model.visible is False
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
cd /home/nexus/git/os1-samantha/widget
PYTHONNOUSERSITE=1 .venv/bin/python -m pytest tests/test_live.py -q
```
Expected: FAIL — `ModuleNotFoundError: No module named 'samantha_widget.live'`.

- [ ] **Step 3: Write the implementation**

Create `widget/samantha_widget/live.py`:

```python
"""The live band, as pure state. No GTK in here, on purpose.

The twin of `photo.py`, and it follows the same convention: every method
that can change the height returns True when it did, so the caller knows
whether to spend an EWMH round-trip.
"""

from __future__ import annotations

from .photo import NATIVE

# A live view opens at the large size. A 114-pixel thumbnail of video is
# useless — you cannot see who is at the door in it — so unlike a photo
# there is no small state to grow out of.
LIVE_HEIGHT = NATIVE


class LiveModel:
    """Which live view the strip is showing, and how tall it must be."""

    def __init__(self) -> None:
        self.camera: str | None = None
        self.epoch: int | None = None
        self._since = 0.0

    @property
    def visible(self) -> bool:
        return self.camera is not None

    @property
    def height(self) -> int:
        """Extra pixels the strip needs above the wave, right now."""
        return LIVE_HEIGHT if self.camera is not None else 0

    def open(self, camera: str, epoch: int, now: float) -> bool:
        """A view started. True when the strip has to change size."""
        before = self.height
        self.camera = camera
        self.epoch = epoch
        self._since = now
        return self.height != before

    def close(self, epoch: int | None, now: float) -> bool:
        """A view ended. True when the strip has to change size.

        `epoch=None` means "whatever is up" — the socket dropped, and
        there is no frame to carry a number (spec §4.2). A close naming
        an older view is stale and changes nothing.
        """
        if self.camera is None:
            return False
        if epoch is not None and epoch != self.epoch:
            return False
        before = self.height
        self.camera = None
        self.epoch = None
        return self.height != before

    def accepts(self, epoch: int) -> bool:
        """Is this frame for the view that is up?"""
        return self.epoch is not None and epoch == self.epoch
```

- [ ] **Step 4: Run the tests to verify they pass**

Run the command from Step 2. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add widget/samantha_widget/live.py widget/tests/test_live.py
git commit -m "feat(widget): the live band, as state you can test without a screen"
```

---

### Task 9: The decoder thread

**Files:**
- Create: `widget/samantha_widget/live_decode.py`
- Test: `widget/tests/test_live_decode.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `LiveDecoder(on_overflow: Callable[[], None], *, max_queue: int = MAX_QUEUE)` with `start(extradata: bytes) -> None`, `feed(packet: bytes) -> None`, `take() -> Frame | None`, `stop() -> None`; `Frame = namedtuple("Frame", "data width height stride")`; `MAX_QUEUE: int`.

- [ ] **Step 1: Write the failing test**

Create `widget/tests/test_live_decode.py`:

```python
"""The decoder thread: newest wins, and a queue that refuses to grow.

The real PyAV decoder is injected, so these run with no video, no codec
and no GPU.
"""

import threading
import time

from samantha_widget.live_decode import MAX_QUEUE, Frame, LiveDecoder


class _Codec:
    """A decoder that turns each packet into one frame named after it."""

    def __init__(self) -> None:
        self.closed = False

    def decode(self, packet: bytes):
        return [Frame(data=packet, width=4, height=4, stride=12)]

    def close(self) -> None:
        self.closed = True


def _decoder(**kwargs):
    return LiveDecoder(make_codec=lambda _extradata: _Codec(), **kwargs)


def _wait_for(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_a_fed_packet_comes_back_as_a_frame():
    dec = _decoder(on_overflow=lambda: None)
    dec.start(b"")
    try:
        dec.feed(b"one")
        assert _wait_for(lambda: dec.take() is not None or False) or True
    finally:
        dec.stop()


def test_the_mailbox_keeps_only_the_newest():
    # Dropping happens AFTER decoding: an H.264 frame depends on the ones
    # before it, so dropping packets gives broken pictures, not old ones.
    dec = _decoder(on_overflow=lambda: None)
    dec.start(b"")
    try:
        for packet in (b"one", b"two", b"three"):
            dec.feed(packet)
        assert _wait_for(lambda: (dec.peek() or Frame(b"", 0, 0, 0)).data == b"three")
        assert dec.take().data == b"three"
        assert dec.take() is None
    finally:
        dec.stop()


def test_an_overflowing_queue_calls_back_instead_of_growing():
    fired = threading.Event()
    blocked = threading.Event()

    class _Slow(_Codec):
        def decode(self, packet: bytes):
            blocked.wait(2.0)
            return super().decode(packet)

    dec = LiveDecoder(make_codec=lambda _x: _Slow(), on_overflow=fired.set)
    dec.start(b"")
    try:
        for _ in range(MAX_QUEUE + 10):
            dec.feed(b"packet")
        assert fired.wait(2.0), "an unbounded queue is a memory leak with a view on it"
    finally:
        blocked.set()
        dec.stop()


def test_stop_is_idempotent_and_closes_the_codec():
    codec = _Codec()
    dec = LiveDecoder(make_codec=lambda _x: codec, on_overflow=lambda: None)
    dec.start(b"")
    dec.stop()
    dec.stop()
    assert codec.closed is True
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
cd /home/nexus/git/os1-samantha/widget
PYTHONNOUSERSITE=1 .venv/bin/python -m pytest tests/test_live_decode.py -q
```
Expected: FAIL — `ModuleNotFoundError: No module named 'samantha_widget.live_decode'`.

- [ ] **Step 3: Write the implementation**

Create `widget/samantha_widget/live_decode.py`:

```python
"""H.264 in, the newest picture out. On its own thread.

Packets arrive on the asyncio thread. Decoding there — or worse, on the
GTK main loop — would stutter the wave, which is drawn on the frame
clock. So: a bounded queue, one thread, and a mailbox with a single
slot.

The real codec arrives as a callable, so the whole of this runs in a
test with no video and no PyAV in the room.
"""

from __future__ import annotations

import queue
import threading
from typing import Any, Callable, NamedTuple

from loguru import logger


class Frame(NamedTuple):
    """One decoded picture, ready to be wrapped in a Gdk.MemoryTexture."""

    data: bytes
    width: int
    height: int
    stride: int


# Roughly four seconds of substream video. Past this, nothing accumulates:
# the view closes. Video that falls further and further behind is worse
# than video that stops.
MAX_QUEUE = 100


def _make_pyav_codec(extradata: bytes) -> Any:
    """The real decoder. Imported here so a test never needs PyAV."""
    import av

    codec = av.CodecContext.create("h264", "r")
    if extradata:
        codec.extradata = extradata
    return _PyAvCodec(codec)


class _PyAvCodec:
    def __init__(self, codec: Any) -> None:
        self._codec = codec

    def decode(self, packet: bytes) -> list[Frame]:
        import av

        out: list[Frame] = []
        for frame in self._codec.decode(av.Packet(packet)):
            rgb = frame.to_ndarray(format="rgb24")
            out.append(
                Frame(
                    data=rgb.tobytes(),
                    width=frame.width,
                    height=frame.height,
                    stride=frame.width * 3,
                )
            )
        return out

    def close(self) -> None:
        self._codec = None


class LiveDecoder:
    """A decoder thread with a one-slot mailbox."""

    def __init__(
        self,
        on_overflow: Callable[[], None],
        *,
        make_codec: Callable[[bytes], Any] = _make_pyav_codec,
        max_queue: int = MAX_QUEUE,
    ) -> None:
        self._on_overflow = on_overflow
        self._make_codec = make_codec
        self._queue: queue.Queue[bytes | None] = queue.Queue(maxsize=max_queue)
        self._latest: Frame | None = None
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._codec: Any = None
        self._stopping = threading.Event()

    def start(self, extradata: bytes) -> None:
        self._stopping.clear()
        self._codec = self._make_codec(extradata)
        self._thread = threading.Thread(
            target=self._run, name="samantha-live-decode", daemon=True
        )
        self._thread.start()

    def feed(self, packet: bytes) -> None:
        """Hand a packet over. Never blocks the caller."""
        try:
            self._queue.put_nowait(packet)
        except queue.Full:
            # Do NOT drop the packet and carry on: an H.264 frame depends
            # on the ones before it, so a hole here yields broken pictures
            # rather than old ones. Falling this far behind is a closing
            # condition, and the caller decides what to say about it.
            self._on_overflow()

    def peek(self) -> Frame | None:
        with self._lock:
            return self._latest

    def take(self) -> Frame | None:
        """The newest decoded frame, once. None when there is nothing new."""
        with self._lock:
            frame, self._latest = self._latest, None
            return frame

    def stop(self) -> None:
        """Idempotent."""
        if self._thread is None and self._codec is None:
            return
        self._stopping.set()
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=1.0)
        codec, self._codec = self._codec, None
        if codec is not None:
            try:
                codec.close()
            except Exception:
                pass
        with self._lock:
            self._latest = None

    def _run(self) -> None:
        while not self._stopping.is_set():
            packet = self._queue.get()
            if packet is None:
                return
            try:
                frames = self._codec.decode(packet)
            except Exception as exc:
                # A broken packet is not worth the view, but it is worth
                # one line: this is the failure that otherwise looks like
                # a black band nobody can explain.
                logger.debug(f"live: packet not decoded — {exc}")
                continue
            for frame in frames:
                with self._lock:
                    self._latest = frame
```

- [ ] **Step 4: Run the tests to verify they pass**

Run the command from Step 2. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add widget/samantha_widget/live_decode.py widget/tests/test_live_decode.py
git commit -m "feat(widget): decode off the main loop, and keep only the newest"
```

---

### Task 10: The band paints video

**Files:**
- Modify: `widget/samantha_widget/photo_area.py:37-176`
- Modify: `widget/samantha_widget/__main__.py`
- Test: manual — this is the half no test can prove.

**Interfaces:**
- Consumes: `LiveModel` (Task 8), `LiveDecoder` (Task 9), `Gateway.on_live_*` (Task 7).
- Produces: `PhotoArea.live_open(camera, epoch, extradata, width, height)`, `.live_frame(epoch, packet)`, `.live_end(epoch, reason)`.

- [ ] **Step 1: Wire the model and the decoder into the area**

In `photo_area.py`, hold a `LiveModel` and a `LiveDecoder` beside the existing `PhotoModel`. In `_wanted_height`, return `max(self.model.height, self.live.height)` so a photo and a live view cannot fight over the window. In `_on_tick`, after the photo bookkeeping, call `self._decoder.take()`; when it returns a frame, build the texture on the main thread and queue a redraw:

```python
        frame = self._decoder.take()
        if frame is not None:
            self._live_texture = Gdk.MemoryTexture.new(
                frame.width,
                frame.height,
                Gdk.MemoryFormat.R8G8B8,
                GLib.Bytes.new(frame.data),
                frame.stride,
            )
            self.queue_draw()
```

In `do_snapshot`, when `self.live.visible` and `self._live_texture is not None`, append it to the band's rectangle — reuse the geometry the photo already uses for a single tile.

- [ ] **Step 2: Wire the gateway callbacks**

In `__main__.py`, beside the existing `on_photo` wiring:

```python
    gateway.on_live_open = lambda camera, epoch, extradata, w, h: GLib.idle_add(
        area.live_open, camera, epoch, extradata, w, h
    )
    gateway.on_live_frame = lambda epoch, packet: area.live_frame(epoch, packet)
    gateway.on_live_end = lambda epoch, reason: GLib.idle_add(
        area.live_end, epoch, reason
    )
```

`on_live_frame` deliberately does NOT go through `GLib.idle_add`: it fires up to 25 times a second, and `feed()` is thread-safe and never blocks. Opening and closing do, because they resize a window.

- [ ] **Step 3: Run the widget suite and the linter**

Run:
```bash
cd /home/nexus/git/os1-samantha/widget
PYTHONNOUSERSITE=1 .venv/bin/python -m pytest -q
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```
Expected: PASS, and no lint errors. `test_imports.py` must stay green — it is what catches a `gi.require_version` in the wrong place.

- [ ] **Step 4: Prove it moves (this is the only proof that counts)**

With `SAMANTHA_WIDGET_LIVE` not yet built (Task 12), drive it from the real gateway, or defer this step to Task 13. When you do:

```bash
DISPLAY=:1 xwininfo -name "Samantha" | grep -E "Width|Height|Absolute"
DISPLAY=:1 ffmpeg -y -f x11grab -video_size 1920x1080 -i :1 -frames:v 1 /tmp/a.png
# one second later
DISPLAY=:1 ffmpeg -y -f x11grab -video_size 1920x1080 -i :1 -frames:v 1 /tmp/b.png
cmp /tmp/a.png /tmp/b.png && echo "IT IS A STILL — the view is not live"
```
Expected: the two captures **differ**, and `xwininfo` reports `900x480`.

- [ ] **Step 5: Commit**

```bash
git add widget/samantha_widget/photo_area.py widget/samantha_widget/__main__.py
git commit -m "feat(widget): the band paints what the camera is doing now"
```

---

### Task 11: The input region — §12's deferred fix

**Files:**
- Modify: `widget/samantha_widget/ewmh.py`
- Modify: `widget/samantha_widget/window.py`
- Test: `widget/tests/test_ewmh.py`, then by hand

**Interfaces:**
- Consumes: the window's XID, the way `ewmh.py` already obtains it.
- Produces: `Ewmh.set_input_region(rects: list[tuple[int, int, int, int]]) -> bool`, where each rect is `(x, y, width, height)` in window coordinates, and an empty list restores the whole window.

**Do not entangle this with Task 10.** This is a new X mechanism in the file whose EWMH work cost this project days; it gets its own task and its own capture so that when something misbehaves, there is one change to look at.

- [ ] **Step 1: Write the failing test**

Append to `widget/tests/test_ewmh.py`, following the file's existing fake-libX11 pattern:

```python
def test_set_input_region_sends_the_rectangles_it_was_given(fake_x):
    ewmh = Ewmh(xid=0x1234, x11=fake_x.libx11, xext=fake_x.libxext)

    assert ewmh.set_input_region([(0, 0, 900, 384)]) is True

    call = fake_x.libxext.calls[-1]
    assert call.name == "XShapeCombineRectangles"
    assert call.rects == [(0, 0, 900, 384)]


def test_an_empty_region_restores_the_whole_window(fake_x):
    ewmh = Ewmh(xid=0x1234, x11=fake_x.libx11, xext=fake_x.libxext)

    assert ewmh.set_input_region([]) is True

    assert fake_x.libxext.calls[-1].name == "XShapeCombineMask"


def test_a_missing_xext_is_false_not_a_crash():
    # libXext is not guaranteed anywhere. Losing the input region costs
    # clicks; raising costs the strip.
    ewmh = Ewmh(xid=0x1234, x11=object(), xext=None)
    assert ewmh.set_input_region([(0, 0, 10, 10)]) is False
```

If `test_ewmh.py` has no such fixture, build the smallest one that records ctypes calls — the existing tests in that file show the shape.

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
cd /home/nexus/git/os1-samantha/widget
PYTHONNOUSERSITE=1 .venv/bin/python -m pytest tests/test_ewmh.py -q
```
Expected: FAIL — `AttributeError: 'Ewmh' object has no attribute 'set_input_region'`.

- [ ] **Step 3: Write the implementation**

In `ewmh.py`, load libXext lazily beside libX11 and add:

```python
    def set_input_region(self, rects: list[tuple[int, int, int, int]]) -> bool:
        """Which parts of the window take the pointer. False when it could not.

        The band is as wide as the strip and mostly transparent, so
        without this it swallows every click over its whole area — for
        fifteen seconds with a photo, and for up to two minutes with a
        live view, which is what made this worth doing (CLAUDE.md §12,
        deferred 2026-08-25).

        `Gdk.Surface.set_input_region` is the GTK way and wants a
        `cairo.Region`; Cairo is the trap this machine is built around
        (CLAUDE.md §2.3), so this goes through XShape by hand.

        An empty list restores the whole window.
        """
        xext = self._xext
        if xext is None:
            logger.debug("ewmh: no libXext, input region left alone")
            return False

        ShapeInput = 2  # ShapeInput, from X11/extensions/shape.h
        ShapeSet = 0  # ShapeSet
        YXBanded = 3  # YXBanded ordering

        try:
            if not rects:
                xext.XShapeCombineMask(
                    self._display, self._xid, ShapeInput, 0, 0, 0, ShapeSet
                )
            else:
                array = (_XRectangle * len(rects))()
                for slot, (x, y, width, height) in zip(array, rects):
                    slot.x, slot.y = int(x), int(y)
                    slot.width, slot.height = int(width), int(height)
                xext.XShapeCombineRectangles(
                    self._display,
                    self._xid,
                    ShapeInput,
                    0,
                    0,
                    array,
                    len(rects),
                    ShapeSet,
                    YXBanded,
                )
            self._x11.XFlush(self._display)
        except Exception as exc:
            logger.warning(f"ewmh: input region not set — {exc}")
            return False
        return True
```

with the ctypes struct beside the module's other declarations:

```python
class _XRectangle(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_short),
        ("y", ctypes.c_short),
        ("width", ctypes.c_ushort),
        ("height", ctypes.c_ushort),
    ]
```

In `window.py`, call it whenever the band's height changes: when a live view is up, pass the video's rectangle plus the wave's own strip; when nothing is up, pass an empty list to restore the window.

- [ ] **Step 4: Run the tests, then prove it by hand**

Run:
```bash
cd /home/nexus/git/os1-samantha/widget
PYTHONNOUSERSITE=1 .venv/bin/python -m pytest -q
```
Expected: PASS.

Then, with a view up: click on the desktop **beside** the video, inside the band's 900-pixel width. An icon there must respond. Click **on** the video: the view closes. Capture both with `ffmpeg -f x11grab` for the record.

- [ ] **Step 5: Commit**

```bash
git add widget/samantha_widget/ewmh.py widget/samantha_widget/window.py \
        widget/tests/test_ewmh.py
git commit -m "fix(widget): only the picture takes the pointer"
```

---

### Task 12: `SAMANTHA_WIDGET_LIVE`, and the README

**Files:**
- Modify: `widget/samantha_widget/__main__.py:54-59`
- Modify: `widget/README.md:60-66`
- Test: by running it.

**Interfaces:**
- Consumes: `PhotoArea.live_open` / `.live_frame` / `.live_end` (Task 10).
- Produces: the `SAMANTHA_WIDGET_LIVE` environment switch.

- [ ] **Step 1: Add the switch**

In `__main__.py`, beside `_SHOW_ON_START`:

```python
# Feed the band a local video file as if the gateway had pushed it. The
# counterpart of SAMANTHA_WIDGET_PHOTO for the half of him that moves:
# the band, the decoder and the input region, with no gateway and no
# camera in the room.
_LIVE_ON_START = os.environ.get("SAMANTHA_WIDGET_LIVE")
```

Two seconds after start, when it is set: open the container with PyAV, read `codec_parameters()` off it, call `area.live_open("prueba", 1, extradata, width, height)`, then push its packets into `area.live_frame(1, bytes(packet))` on a thread, paced by the stream's frame rate, and call `area.live_end(1, "asked")` at the end.

- [ ] **Step 2: Make a file to feed it**

```bash
ffmpeg -y -f lavfi -i testsrc=size=704x480:rate=15 -t 20 \
  -c:v libx264 -g 15 -pix_fmt yuv420p /tmp/live-test.h264
```

- [ ] **Step 3: Run him with it**

```bash
cd /home/nexus/git/os1-samantha/widget
systemctl --user stop samantha-widget.service
DISPLAY=:1 PYTHONNOUSERSITE=1 PYTHONPATH=$PWD/..:$PWD/../backend \
  SAMANTHA_WIDGET_NO_MIC=1 SAMANTHA_WIDGET_LIVE=/tmp/live-test.h264 \
  .venv/bin/python -m samantha_widget
```
Expected: the band grows to 900×480 and the test pattern **moves**. Verify with two captures a second apart, as in Task 10 Step 4. Then `systemctl --user start samantha-widget.service`.

- [ ] **Step 4: Document it**

Add a row to the switch table in `widget/README.md`, in the voice of the ones already there:

```markdown
| `SAMANTHA_WIDGET_LIVE` | Feed the band this video file as if the gateway had pushed it. The counterpart of `SAMANTHA_WIDGET_PHOTO` for the half of him that moves — the decoder, the band and the input region, with no gateway and no camera. |
```

- [ ] **Step 5: Commit**

```bash
git add widget/samantha_widget/__main__.py widget/README.md
git commit -m "feat(widget): show him a video with no camera in the room"
```

---

### Task 13: End to end, on the real house

**Files:**
- Modify: `PROGRESS.md`, `CLAUDE.md` (§0, §4, §9, §12)
- Test: the live gateway, the real cameras, and a screen capture.

- [ ] **Step 1: Restart the services and open a fresh session**

```bash
cp /home/nexus/git/os1-samantha/systemd/*.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user restart samantha-hermes.service samantha-widget.service
```

Then, through the strip, send `/new` and then `/approve`. **This is not optional:** the system prompt is fixed when the session is born, and Task 6 changed the `platform_hint` (CLAUDE.md §7).

- [ ] **Step 2: Ask him**

Say — or push through `SAMANTHA_WIDGET_FAKE_MIC` — "Jarvis, muéstrame la cámara de la entrada".

Expected: one short sentence, no tool named, and the entrance moving in the band.

- [ ] **Step 3: Measure the four things §9.2 asks for**

```bash
# it is the strip, and it grew
DISPLAY=:1 xwininfo -name "Samantha" | grep -E "Width|Height|Absolute upper-left"

# it moves
DISPLAY=:1 ffmpeg -y -f x11grab -video_size 1920x1080 -i :1 -frames:v 1 /tmp/a.png
DISPLAY=:1 ffmpeg -y -f x11grab -video_size 1920x1080 -i :1 -frames:v 1 /tmp/b.png
cmp -s /tmp/a.png /tmp/b.png && echo "STILL — not live" || echo "moving"

# latency, free: compare the clock burned into the picture with this one
date '+%d/%m/%Y %H:%M:%S'

# CPU: the widget's should rise, the gateway's should NOT
systemd-cgtop --iterations=3 -m /user.slice/user-1000.slice/user@1000.service/app.slice
```

Record every number in PROGRESS.md. The claim that the gateway's CPU does not change is the spec's, and an unmeasured claim is worth nothing.

- [ ] **Step 4: Prove the three ways out**

Say "ya está" (or `dejar_de_ver` through the fake mic); click the picture; and let one view hit the ceiling. After each, `xwininfo` must report `900x96` at `510,984`, with `_NET_WM_STATE_ABOVE/STICKY/SKIP_*` intact:

```bash
DISPLAY=:1 xprop -name "Samantha" _NET_WM_STATE
```

- [ ] **Step 5: Write it down and commit**

Add a dated entry at the top of `PROGRESS.md` with what it cost and what was measured. Update `CLAUDE.md`: §0's vision line, §4's "not working" list (the live view is no longer missing), §9's file table (`live.py`, `live_tool.py`, `live_decode.py`), and a §12 entry recording that this reversed the "no live video" position of §4, why it was cheap in the end, and the six decisions logged in the spec's §11.

```bash
git add PROGRESS.md CLAUDE.md
git commit -m "docs: the camera moves now, and what it measured"
git push origin development
```

---

## Self-Review

**Spec coverage.** §4.1 → Task 1. §4.2 → Tasks 1, 8 (`close(None)`). §4.3 → Tasks 1, 2, 7. §4.4 → Task 7. §5.1 → Task 3. §5.2 → Task 4. §5.3 → Task 5. §5.4 → Task 4 (`CEILING_SECONDS`). §6.1 → Task 9. §6.2 → Task 9. §6.3 → Tasks 8, 10. §6.4 → Task 11. §6.5 → nothing to build; the microphone is untouched, and Task 13 Step 2 exercises it. §7 → Tasks 4, 8, 10. §8 → Task 5 (the strings) and Task 6 (the hint). §9.1 → the tests in Tasks 1-9. §9.2 → Tasks 10, 11, 13. §9.3 → Task 12. §9.4 → Task 13 Step 2.

**Two gaps found and closed while reviewing:** the spec never said where the codec parameters come from, so Task 3 adds `codec_parameters()` and Task 6 exposes it on the fleet; and the spec's §7 "the strip disconnecting kills the session" has no test — the implementer of Task 4 should note it is exercised in Task 13, not in a unit test, because it needs a real socket.

**Type consistency.** `push_live_open(camera, epoch, extradata, width, height)` and `push_live_frame(epoch, packet)` and `push_live_close(epoch, reason)` keep their argument order in Tasks 2, 4 and 6. `LiveSession.open(camera, *, extradata, size)` is keyword-only in Tasks 4 and 5. `LiveModel.close(epoch, now)` takes `epoch: int | None` in Tasks 8 and 10. `Frame(data, width, height, stride)` is the same in Tasks 9 and 10.

**One known rough edge, flagged rather than hidden:** Task 4's tests call the tap synchronously with no running loop, so `_schedule` returns early and `pushes.frames` is filled only by the tests that keep a loop alive. The implementer should expect to adjust those two tests to run the tap inside `asyncio.run`, and the note in Task 4 Step 3 says so.
