# samantha-widget (plan 2) — the voice turn

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** You speak to the strip and it answers out loud, in Samantha's
cloned voice, with no wake word and no button.

**Architecture:** The microphone is always open. A local Silero VAD cuts
it into utterances; faster-whisper turns one into text; the text goes up
the WebSocket the `samantha-kiosk` plugin already serves; the reply comes
back as tokens, is cut into clauses, and each clause is synthesised by
CosyVoice and played as it arrives. GTK's main loop, one asyncio thread
and PortAudio's callback thread never touch each other's objects —
everything crossing into the UI goes through `GLib.idle_add`.

**Tech Stack:** Python 3.12, `sounddevice` (PortAudio), `onnxruntime`
(Silero VAD), `faster-whisper` on CUDA, `websockets`, `httpx` via
`samantha.tts`, pytest.

**Spec:** `docs/superpowers/specs/2026-08-23-samantha-widget-gtk4-design.md`
§5 (the turn), §9 (risks). Read §5.1 before Task 1 — it names the
failure this plan is most likely to hit.

**Depends on:** plan 1 (`…-samantha-widget-strip.md`) landed. The window,
`WaveArea` and `WaveState` exist and are on screen.

## Global Constraints

- **24 kHz for output, 16 kHz for input. No resampling anywhere.**
  `samantha.tts.OUTPUT_SAMPLE_RATE` is 24000 and every chunk it yields
  is raw mono int16 little-endian with no header. Silero and Whisper
  both take 16 kHz mono. Two rates, two streams, no conversion.
- **`samantha.tts` is imported, not reimplemented.** It needs only
  `httpx` and `loguru` (verified: `tts.py` imports those plus stdlib;
  `config.py` is a plain dataclass). Reach it with
  `PYTHONPATH=<repo>/backend`, the same mechanism `Hermes/run-gateway.sh`
  uses. Do **not** `pip install -e ../backend` — that drags in FastAPI
  and ChromaDB for two functions.
- **Pass `samantha.tts.new_client()` explicitly.** An `httpx.AsyncClient`
  may only be used on the loop that created it, and the widget's loop is
  not uvicorn's. Omitting it is a runtime error at first speech, not at
  import.
- **`user_id` is exactly `"primary"`.** The kiosk adapter defaults its
  allowlist to that id (`samantha_kiosk/__init__.py`). Any other value is
  dropped with a log warning and **nothing on screen**.
- **The WebSocket is `ws://127.0.0.1:7777/ws`** — `SAMANTHA_KIOSK_PORT`,
  default 7777. Not 8642 (that is Hermes' API-server daemon).
- **Send no `Origin` header.** The adapter allows an absent one on
  purpose (`adapter.py:565-570`, "a future native shell"); a browser-ish
  Origin on the wrong port is a 403.
- **Nothing outside the GTK main thread touches a widget.**
  `GLib.idle_add` is the only bridge. This rule has no exceptions.
- **Nothing that needs the GPU, a microphone or a network runs in a unit
  test.** Every such boundary is behind a small interface with a fake.
- Identifiers and comments in **English**, user-facing strings in
  **Spanish** (CLAUDE.md §2.9).
- `ruff check` / `ruff format` and the full `pytest` gate every commit.
- **Nothing here removes anything.** The kiosk still works throughout.

## What has already been run

Written 2026-08-23. The hardware-free code here was extracted and
executed against its own tests before the plan was committed:
`vad.py`'s `UtteranceDetector` (11 tests), `speech.py`'s `ClauseChunker`
(9), `stt.py`'s `clean` plus `Transcriber`'s not-ready path (6) and
`turn.py` (8) — **34 passed**.

That run earned its keep: the first version of `_MIN_UTTERANCE_SECONDS`
measured the *buffer*, which always contains the 0.7 s of trailing
silence, so the minimum could never reject anything. Two tests in Task 3
now pin the fix.

**Not run:** `gateway.py` (needs `websockets`), `SileroDetector` (needs
the model), `Transcriber.load` (needs the GPU), `audio.py` and
`Speaker` (need PortAudio and a live CosyVoice). Each has a hand-run
probe step instead, and those are where this plan can still surprise
you.

---

## File Structure

| File | Responsibility |
|---|---|
| `widget/samantha_widget/gateway.py` | The WebSocket client and the frame format. |
| `widget/samantha_widget/vad.py` | `UtteranceDetector` (pure) + `SileroDetector` (onnxruntime). |
| `widget/samantha_widget/audio.py` | `sounddevice` input and output streams. |
| `widget/samantha_widget/stt.py` | faster-whisper, loaded off the main thread. |
| `widget/samantha_widget/speech.py` | `ClauseChunker` (pure) + `Speaker` (synthesise + play). |
| `widget/samantha_widget/turn.py` | The state machine; the only place the pieces meet. |
| `widget/samantha_widget/__main__.py` | Wiring, replacing plan 1's demo keys. |

---

## Task 1: Find out whether the gateway also speaks ✅ done 2026-08-23

> **Answered. Full findings:**
> `docs/superpowers/specs/2026-08-23-widget-gateway-probe.md`
>
> The short version, and what it changes downstream:
>
> - **Yes, it speaks** — through the agent's own `text_to_speech` tool,
>   not `voice.auto_tts` (which is off by default and was never on).
>   It was synthesising through **Edge TTS, Microsoft's cloud**: the
>   cache file was MP3 48 kbps, and CosyVoice yields WAV/PCM. Fixed by
>   setting `tts.provider: cosyvoice` in the repo's
>   `.hermes/home/config.yaml`, and verified — the next file was
>   `WAVE audio, Microsoft PCM, 16 bit, mono 24000 Hz`. **That config is
>   git-ignored, so it has to be redone on the appliance.**
> - **Hermes answers as "Hermes, tu asistente"**, offering `/help` to a
>   person with no keyboard. Known (spec §9), still true, plan 3's to fix
>   — and the likeliest reason the widget fails to convince.
> - **NEW, and it changes Task 6:** the gateway emits its own system
>   messages as ordinary `token` frames, in English, with emoji —
>   `📬 No home channel…`, `↪ Redirected current run…`,
>   `💡 First-time tip…`, `⚠️ Couldn't deliver the audio attachment.`,
>   `⚡ Interrupting current task…`. Spoken aloud they are gibberish.
>   Task 6 must filter a frame whose text starts with one of
>   `📬 ↪ 💡 ⚠️ ⚡` before it reaches the chunker.
> - **NEW, and it changes Task 7:** every system message carries its own
>   `done`, so one turn produced **six** of them, all with
>   `thinking_ms: 0`. `done` is not a turn boundary. Rule that matches
>   what was measured: a `done` settles the turn only if at least one
>   *unfiltered* token has arrived since the last settle.
> - **NEW:** tokens arrive as whole messages, not word by word. The
>   chunker still earns its place, but the latency win is smaller than
>   §5.2 assumed.

## Task 1 (as originally written): Find out whether the gateway also speaks

**Files:**
- Create: `widget/tools/probe_gateway.py`
- Create: `docs/superpowers/specs/2026-08-23-widget-gateway-probe.md`

**Interfaces:**
- Consumes: a running Hermes gateway with `samantha-kiosk` enabled.
- Produces: a written answer to "does anything other than the widget
  produce audio for a kiosk turn?", plus a proven-good WebSocket
  round trip that Task 2 is written against.

No code that matters gets written until this is answered. Spec §5.1
calls this the most likely way the design fails on first run: if the
gateway's auto-TTS also fires, Samantha says everything twice, and that
is a confusing bug to meet for the first time with six other new
modules in the room.

- [ ] **Step 1: Confirm the gateway is up and the plugin is enabled**

```bash
cd /home/nexus/git/os1-samantha
systemctl --user status samantha-hermes.service --no-pager | head -5
Hermes/run-gateway.sh plugins list | grep -i samantha
```

Expected: the service is active; `samantha-kiosk` and `samantha-voice`
both listed and **enabled**. "not enabled" is not an error message but
it does mean nothing will answer — enable it before continuing.

- [ ] **Step 2: Write the probe**

```python
# widget/tools/probe_gateway.py
"""Ask the kiosk socket one question and print everything it says back.

Not a test — a thing you run by hand, once, to find out what the
gateway actually does with a turn before writing code that assumes it.
"""

import asyncio
import json
import sys

import websockets

URI = "ws://127.0.0.1:7777/ws"


async def main() -> None:
    text = sys.argv[1] if len(sys.argv) > 1 else "Hola, ¿me oyes?"
    async with websockets.connect(URI) as ws:
        await ws.send(json.dumps({"type": "chat", "message": text, "user_id": "primary"}))
        reply = []
        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=120)
            msg = json.loads(raw)
            print(f"  <- {msg}")
            if msg["type"] == "token":
                reply.append(msg["token"])
            elif msg["type"] in {"done", "error"}:
                break
        print("\nFULL REPLY:", "".join(reply))


asyncio.run(main())
```

- [ ] **Step 3: Install the client and run it, with the speakers ON**

```bash
cd widget
.venv/bin/pip install "websockets>=12"
.venv/bin/python tools/probe_gateway.py "Hola, ¿me oyes?"
```

Watch two things at once:
1. **The frames** printed. Confirm `token`* then `done`.
2. **The speakers.** Did anything come out of them? The widget is not
   running, so any sound at all came from the gateway.

- [ ] **Step 4: Check the log for a TTS path**

```bash
journalctl --user -u samantha-hermes --since "2 minutes ago" | grep -iE "tts|cosyvoice|speech|edge"
```

- [ ] **Step 5: Write down what you found**

Create `docs/superpowers/specs/2026-08-23-widget-gateway-probe.md` with:
the exact frames observed, whether audio played, what the log said, and
— if the gateway does speak — the config key that turns it off and
where it lives. Copy the full reply text too: it is the first evidence
of the §9 risk that Hermes answers in its own `SOUL.md` persona rather
than `backend/samantha/personality.py`.

**If the gateway speaks:** disable its auto-TTS for this platform now,
re-run the probe, and confirm silence before continuing. Two voices is
not a bug to defer.

- [ ] **Step 6: Commit**

```bash
cd .. && git add widget/tools docs/ && git commit -m "docs(widget): what the gateway does with a turn, measured"
```

---

## Task 2: The WebSocket client

**Files:**
- Create: `widget/samantha_widget/gateway.py`
- Create: `widget/tests/test_gateway.py`

**Interfaces:**
- Consumes: `websockets`.
- Produces:
  - `class GatewayClient` with
    `__init__(self, uri: str = DEFAULT_URI, user_id: str = "primary")`,
    `async def run(self) -> None` (connect-and-read loop, reconnects),
    `async def wait_connected(self, timeout: float = 10.0) -> None`,
    `async def send_chat(self, text: str) -> None`,
    `retry_seconds: float` (settable; the tests shorten it),
    and three callbacks assigned by the caller:
    `on_token: Callable[[str], None]`,
    `on_done: Callable[[int], None]`,
    `on_error: Callable[[str], None]`.
  - `encode_chat(text: str, user_id: str) -> str`
  - `decode_server(raw: str) -> dict` (raises `ProtocolError`)
  - `DEFAULT_URI = "ws://127.0.0.1:7777/ws"`

- [ ] **Step 1: Write the failing tests**

```python
# widget/tests/test_gateway.py
"""The wire format, and the client's behaviour against a real socket.

The frame shapes are not ours to choose: they are pinned in
Hermes/plugins/samantha_kiosk/protocol.py, which in turn pins what the
old frontend spoke. A change on either side has to fail here rather
than on the strip.
"""

import asyncio
import json

import pytest
import websockets

from samantha_widget.gateway import (
    GatewayClient,
    ProtocolError,
    decode_server,
    encode_chat,
)


def test_chat_frame_matches_the_adapter() -> None:
    frame = json.loads(encode_chat("hola", "primary"))

    assert frame == {"type": "chat", "message": "hola", "user_id": "primary"}


def test_token_frame_reads_the_token_field() -> None:
    assert decode_server('{"type":"token","token":"ho"}')["token"] == "ho"


def test_done_carries_thinking_ms() -> None:
    assert decode_server('{"type":"done","thinking_ms":1200}')["thinking_ms"] == 1200


def test_error_frame_is_decoded_not_raised() -> None:
    """An `error` frame is a message from her, not a transport failure."""
    msg = decode_server('{"type":"error","error":"algo se ha quedado a medias"}')

    assert msg["type"] == "error"


def test_garbage_is_a_protocol_error() -> None:
    with pytest.raises(ProtocolError):
        decode_server("not json at all")


def test_unknown_type_is_a_protocol_error() -> None:
    with pytest.raises(ProtocolError):
        decode_server('{"type":"sing"}')


@pytest.mark.asyncio
async def test_a_full_turn_against_a_real_socket() -> None:
    """Three tokens and a done, over an actual WebSocket."""

    async def handler(ws) -> None:
        request = json.loads(await ws.recv())
        assert request["message"] == "hola"
        for tok in ("Ho", "la", "."):
            await ws.send(json.dumps({"type": "token", "token": tok}))
        await ws.send(json.dumps({"type": "done", "thinking_ms": 42}))

    async with websockets.serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        client = GatewayClient(uri=f"ws://127.0.0.1:{port}")

        tokens: list[str] = []
        finished = asyncio.Event()
        client.on_token = tokens.append
        client.on_done = lambda ms: finished.set()

        task = asyncio.create_task(client.run())
        await client.wait_connected(timeout=5)
        await client.send_chat("hola")
        await asyncio.wait_for(finished.wait(), timeout=5)
        task.cancel()

    assert "".join(tokens) == "Hola."


@pytest.mark.asyncio
async def test_it_reconnects_after_the_server_drops_it() -> None:
    """The gateway restarts. The strip must come back on its own."""
    connections = 0

    async def handler(ws) -> None:
        nonlocal connections
        connections += 1
        if connections == 1:
            await ws.close()
            return
        await asyncio.sleep(5)

    async with websockets.serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        client = GatewayClient(uri=f"ws://127.0.0.1:{port}")
        client.retry_seconds = 0.05
        task = asyncio.create_task(client.run())
        await asyncio.sleep(1.0)
        task.cancel()

    assert connections >= 2
```

- [ ] **Step 2: Install the test dependency and run them**

```bash
cd widget
.venv/bin/pip install pytest-asyncio
```

Add to `pyproject.toml` under `[tool.pytest.ini_options]`:

```toml
asyncio_mode = "auto"
```

Run: `.venv/bin/python -m pytest tests/test_gateway.py -v`
Expected: FAIL — no module `samantha_widget.gateway`.

- [ ] **Step 3: Write `gateway.py`**

```python
# widget/samantha_widget/gateway.py
"""The client half of the kiosk WebSocket.

The server half is Hermes/plugins/samantha_kiosk/adapter.py, and the
frame format is pinned in its protocol.py — `chat` up, `token` /
`done` / `error` down. Nothing here invents a protocol; the whole point
of talking to the existing adapter is that there is nothing to invent.

Two details that are not obvious and are load-bearing:

- No `Origin` header. The adapter refuses a browser Origin that does
  not match its own port, and explicitly allows a client that sends
  none — "a future native shell", says the comment. That is us.
- `user_id` must be "primary". The adapter's allowlist defaults to
  exactly that id, and an unauthorized turn is dropped with a log line
  and NOTHING on the screen.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Callable

import websockets

DEFAULT_URI = "ws://127.0.0.1:7777/ws"
DEFAULT_USER_ID = "primary"

_SERVER_TYPES = {"token", "done", "error", "transcription"}


class ProtocolError(ValueError):
    """Raised for anything the gateway should not have sent."""


def encode_chat(text: str, user_id: str = DEFAULT_USER_ID) -> str:
    return json.dumps({"type": "chat", "message": text, "user_id": user_id})


def decode_server(raw: str) -> dict[str, Any]:
    try:
        msg = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise ProtocolError(f"not JSON: {exc}") from exc
    if not isinstance(msg, dict):
        raise ProtocolError(f"expected an object, got {type(msg).__name__}")
    if msg.get("type") not in _SERVER_TYPES:
        raise ProtocolError(f"unknown type: {msg.get('type')!r}")
    return msg


class GatewayClient:
    def __init__(
        self, uri: str = DEFAULT_URI, user_id: str = DEFAULT_USER_ID
    ) -> None:
        self.uri = uri
        self.user_id = user_id
        self.retry_seconds = 2.0
        self.on_token: Callable[[str], None] = lambda _t: None
        self.on_done: Callable[[int], None] = lambda _ms: None
        self.on_error: Callable[[str], None] = lambda _m: None
        self._ws: Any = None
        self._connected = asyncio.Event()

    async def wait_connected(self, timeout: float = 10.0) -> None:
        await asyncio.wait_for(self._connected.wait(), timeout=timeout)

    async def send_chat(self, text: str) -> None:
        if self._ws is None:
            # The gateway is down. Silence would leave the user talking
            # to a wall, so this is one of the few Spanish strings here.
            self.on_error("No te oigo bien ahora mismo. Dame un momento.")
            return
        await self._ws.send(encode_chat(text, self.user_id))

    async def run(self) -> None:
        """Connect, read, and reconnect forever. Cancel to stop."""
        while True:
            try:
                async with websockets.connect(self.uri) as ws:
                    self._ws = ws
                    self._connected.set()
                    async for raw in ws:
                        self._dispatch(raw)
            except asyncio.CancelledError:
                raise
            except Exception:
                # Every failure mode here — gateway down, gateway
                # restarting, socket dropped mid-turn — has the same
                # answer: wait and try again. A strip that gives up is
                # a strip that has to be restarted by hand.
                pass
            finally:
                self._ws = None
                self._connected.clear()
            await asyncio.sleep(self.retry_seconds)

    def _dispatch(self, raw: str) -> None:
        try:
            msg = decode_server(raw)
        except ProtocolError:
            return
        kind = msg["type"]
        if kind == "token":
            self.on_token(msg.get("token", ""))
        elif kind == "done":
            self.on_done(int(msg.get("thinking_ms", 0)))
        elif kind == "error":
            self.on_error(msg.get("error", ""))
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_gateway.py -v`
Expected: 8 passed.

- [ ] **Step 5: Prove it against the real gateway**

```bash
.venv/bin/python -c "
import asyncio
from samantha_widget.gateway import GatewayClient
async def main():
    c = GatewayClient()
    c.on_token = lambda t: print(t, end='', flush=True)
    c.on_done = lambda ms: print(f'\n[done in {ms} ms]')
    task = asyncio.create_task(c.run())
    await c.wait_connected()
    await c.send_chat('Hola, ¿qué tal?')
    await asyncio.sleep(60)
asyncio.run(main())
"
```

Expected: her reply, token by token, then `[done]`.

- [ ] **Step 6: Commit**

```bash
cd .. && git add widget/ && git commit -m "feat(widget): speak the kiosk protocol from a native client"
```

---

## Task 3: Utterance boundaries

**Files:**
- Create: `widget/samantha_widget/vad.py`
- Create: `widget/tests/test_vad.py`

**Interfaces:**
- Consumes: nothing (the real model arrives in Task 4).
- Produces:
  - `FRAME_SAMPLES = 512`, `INPUT_RATE = 16000` (32 ms per frame).
  - `class SpeechProbe(Protocol)`: `def speech_probability(self, frame: bytes) -> float`
  - `class UtteranceDetector` with
    `__init__(self, probe: SpeechProbe)`,
    `def push(self, frame: bytes) -> bytes | None` — returns the
    complete utterance PCM when one ends, else `None`,
    `def reset(self) -> None`, and `speaking: bool`.
  - Tunables as module constants: `_START_FRAMES = 3`,
    `_SILENCE_SECONDS = 0.7`, `_MIN_UTTERANCE_SECONDS = 0.4`,
    `_MAX_UTTERANCE_SECONDS = 30.0`, `_THRESHOLD = 0.5`.

- [ ] **Step 1: Write the failing tests**

```python
# widget/tests/test_vad.py
"""Turn boundaries, with a scripted VAD instead of a real one.

Silero's job is one number per frame. Deciding what a *turn* is — how
much speech starts one, how much silence ends one, what is too short to
bother transcribing — is ours, and it is the part that decides whether
she interrupts people or ignores them. So it is tested here, exactly,
with no model and no microphone in the room.
"""

from samantha_widget.vad import FRAME_SAMPLES, UtteranceDetector

FRAME = b"\x00\x00" * FRAME_SAMPLES  # 512 int16 samples = 32 ms
FRAME_SECONDS = FRAME_SAMPLES / 16000


class ScriptedProbe:
    """Speech probability read off a list, one per frame."""

    def __init__(self, script: list[float]) -> None:
        self.script = list(script)

    def speech_probability(self, frame: bytes) -> float:
        del frame
        return self.script.pop(0) if self.script else 0.0


def _frames(*runs: tuple[float, float]) -> list[float]:
    """(probability, seconds) pairs → a per-frame probability script."""
    out: list[float] = []
    for probability, seconds in runs:
        out += [probability] * max(1, round(seconds / FRAME_SECONDS))
    return out


def _run(script: list[float]) -> list[bytes]:
    detector = UtteranceDetector(ScriptedProbe(script))
    return [u for _ in script if (u := detector.push(FRAME)) is not None]


def test_silence_alone_produces_nothing() -> None:
    assert _run(_frames((0.0, 5.0))) == []


def test_a_normal_utterance_is_emitted_once() -> None:
    utterances = _run(_frames((0.0, 0.5), (0.9, 2.0), (0.0, 2.0)))

    assert len(utterances) == 1


def test_the_utterance_holds_roughly_the_speech() -> None:
    utterances = _run(_frames((0.0, 0.5), (0.9, 2.0), (0.0, 2.0)))
    seconds = len(utterances[0]) / 2 / 16000

    # The 0.7 s of trailing silence is inside the utterance by design —
    # Whisper does better with a little room than with a hard cut.
    assert 2.0 <= seconds <= 3.0


def test_a_single_loud_frame_does_not_start_a_turn() -> None:
    """A door, a keyboard, a cough. Three frames are required."""
    assert _run(_frames((0.0, 0.5), (0.95, 0.032), (0.0, 3.0))) == []


def test_a_gap_shorter_than_the_silence_window_does_not_split_a_turn() -> None:
    """Someone pausing to think mid-sentence is still one turn."""
    utterances = _run(
        _frames((0.9, 1.0), (0.0, 0.3), (0.9, 1.0), (0.0, 2.0))
    )

    assert len(utterances) == 1


def test_a_gap_longer_than_the_silence_window_splits_it() -> None:
    utterances = _run(
        _frames((0.9, 1.0), (0.0, 1.5), (0.9, 1.0), (0.0, 1.5))
    )

    assert len(utterances) == 2


def test_a_too_short_utterance_is_discarded() -> None:
    """"Eh." is not a turn."""
    assert _run(_frames((0.9, 0.2), (0.0, 2.0))) == []


def test_a_stuck_vad_cannot_grow_the_buffer_forever() -> None:
    """Speech that never ends is cut at the cap rather than eating RAM."""
    utterances = _run(_frames((0.99, 45.0)))

    assert len(utterances) >= 1
    assert len(utterances[0]) / 2 / 16000 <= 31.0


def test_speaking_flag_tracks_the_turn() -> None:
    detector = UtteranceDetector(ScriptedProbe(_frames((0.9, 1.0), (0.0, 2.0))))

    detector.push(FRAME)
    assert detector.speaking is False  # one frame is not enough
    for _ in range(4):
        detector.push(FRAME)
    assert detector.speaking is True


def test_the_minimum_measures_speech_not_the_buffer() -> None:
    """The one that caught a real bug while this plan was being written.

    0.3 s of speech makes a ~1 s buffer once the 0.7 s of trailing
    silence is inside it. A minimum measured against the BUFFER is
    therefore never reached from below — every cough gets through and
    the check does nothing at all. It has to count speech frames.
    """
    assert _run(_frames((0.9, 0.3), (0.0, 2.0))) == []


def test_scattered_pre_roll_frames_do_not_count_towards_the_minimum() -> None:
    """A ticking clock before someone speaks must not top up the tally."""
    script: list[float] = []
    for _ in range(40):  # ~2.5 s of alternating tick / silence
        script += [0.9, 0.0]
    script += _frames((0.9, 0.2), (0.0, 2.0))

    assert _run(script) == []
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd widget && .venv/bin/python -m pytest tests/test_vad.py -v`
Expected: FAIL — no module `samantha_widget.vad`.

- [ ] **Step 3: Write the detector half of `vad.py`**

```python
# widget/samantha_widget/vad.py
"""Where a turn starts and stops.

Two halves, deliberately separate: `UtteranceDetector` is the policy —
hysteresis, minimum length, the cap — and is pure enough to be tested
frame by frame with a scripted probe. `SileroDetector` is the model,
and is the only part that needs a file on disk and onnxruntime.
"""

from __future__ import annotations

from typing import Protocol

INPUT_RATE = 16000
FRAME_SAMPLES = 512  # 32 ms at 16 kHz — Silero's native frame at this rate
_FRAME_SECONDS = FRAME_SAMPLES / INPUT_RATE

_THRESHOLD = 0.5
# Three frames (~96 ms) of speech to start: enough to reject a keyboard
# click, short enough that the first syllable is still in the buffer,
# because the buffer starts collecting before the turn is confirmed.
_START_FRAMES = 3
_SILENCE_SECONDS = 0.7
_MIN_UTTERANCE_SECONDS = 0.4
_MAX_UTTERANCE_SECONDS = 30.0


class SpeechProbe(Protocol):
    def speech_probability(self, frame: bytes) -> float: ...


class UtteranceDetector:
    def __init__(self, probe: SpeechProbe) -> None:
        self._probe = probe
        self._buffer = bytearray()
        self._speech_run = 0
        self._silence_seconds = 0.0
        # Speech only, NOT the buffer's length. The buffer always ends
        # with 0.7 s of silence and usually starts with some pre-roll, so
        # a minimum measured against it is never reached from below and
        # the check silently does nothing.
        self._speech_seconds = 0.0
        self.speaking = False

    def reset(self) -> None:
        self._buffer.clear()
        self._speech_run = 0
        self._silence_seconds = 0.0
        self._speech_seconds = 0.0
        self.speaking = False

    def push(self, frame: bytes) -> bytes | None:
        """Feed one 32 ms frame. Returns a finished utterance, or None."""
        is_speech = self._probe.speech_probability(frame) >= _THRESHOLD
        if is_speech:
            self._speech_seconds += _FRAME_SECONDS

        if not self.speaking:
            # Collect while unconfirmed: by the time three frames prove
            # someone is talking, their first syllable is already 96 ms
            # in the past, and dropping it costs the first word.
            self._buffer += frame
            if is_speech:
                self._speech_run += 1
                if self._speech_run >= _START_FRAMES:
                    self.speaking = True
                    self._silence_seconds = 0.0
            else:
                self._speech_run = 0
                # A ticking clock is a speech frame every second or so.
                # Without this reset the tally creeps up all day and the
                # minimum stops rejecting anything.
                self._speech_seconds = 0.0
                self._buffer.clear()
            return None

        self._buffer += frame
        self._silence_seconds = 0.0 if is_speech else self._silence_seconds + _FRAME_SECONDS

        if len(self._buffer) / 2 / INPUT_RATE >= _MAX_UTTERANCE_SECONDS:
            return self._emit(force=True)
        if self._silence_seconds >= _SILENCE_SECONDS:
            return self._emit()
        return None

    def _emit(self, *, force: bool = False) -> bytes | None:
        pcm = bytes(self._buffer)
        speech_seconds = self._speech_seconds
        self.reset()
        if not force and speech_seconds < _MIN_UTTERANCE_SECONDS:
            # Too short to be a sentence. Transcribing it wastes a GPU
            # pass and usually produces a hallucinated "Gracias".
            return None
        return pcm
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_vad.py -v`
Expected: 11 passed. These eleven were run against this exact
implementation while the plan was written — a failure here means the
code was mistyped, not that the tests need loosening.

- [ ] **Step 5: Commit**

```bash
cd .. && git add widget/ && git commit -m "feat(widget): decide where a turn starts and stops"
```

---

## Task 4: Silero, for real

**Files:**
- Modify: `widget/samantha_widget/vad.py` (add `SileroDetector`)
- Create: `widget/tools/probe_silero.py`

**Interfaces:**
- Consumes: `UtteranceDetector`, `SpeechProbe`.
- Produces: `class SileroDetector` implementing `SpeechProbe`, with
  `__init__(self, model_path: str | None = None)`.

The ONNX model's input names and state shape changed between Silero
versions, and guessing them produces a detector that returns plausible
numbers for the wrong reason. Read them off the file before writing the
wrapper.

- [ ] **Step 1: Get the model and read its signature**

```bash
cd widget
.venv/bin/pip install onnxruntime numpy
.venv/bin/pip download silero-vad --no-deps -d /tmp/silero
# The wheel carries silero_vad/data/silero_vad.onnx (~2 MB).
cd /tmp/silero && unzip -o silero_vad*.whl -d unpacked
find unpacked -name "*.onnx"
```

```bash
cd /home/nexus/git/os1-samantha/widget
.venv/bin/python -c "
import onnxruntime as ort
s = ort.InferenceSession('/tmp/silero/unpacked/silero_vad/data/silero_vad.onnx')
for i in s.get_inputs():  print('IN ', i.name, i.shape, i.type)
for o in s.get_outputs(): print('OUT', o.name, o.shape, o.type)
"
```

Write the printed signature into the docstring of `SileroDetector`.
**The code below assumes the v5 signature** — inputs `input`
`[1, N] float32`, `state` `[2, 1, 128] float32`, `sr` `int64`; outputs
`output` and `stateN`. If what you printed differs, adapt the wrapper
to what you printed, not the other way round.

- [ ] **Step 2: Copy the model somewhere permanent**

```bash
mkdir -p ~/.samantha/models
cp /tmp/silero/unpacked/silero_vad/data/silero_vad.onnx ~/.samantha/models/
```

`~/.samantha/` is where this project already keeps voices and memory,
so the model lives beside them rather than inside the repo.

- [ ] **Step 3: Add `SileroDetector` to `vad.py`**

```python
# widget/samantha_widget/vad.py  — appended

import os
from pathlib import Path

DEFAULT_MODEL_PATH = Path.home() / ".samantha" / "models" / "silero_vad.onnx"


class SileroDetector:
    """Silero VAD over onnxruntime, on the CPU.

    ONNX rather than the `silero-vad` package's default path: that one
    reaches for torch, which is ~2 GB of dependency for a 2 MB model
    that runs in well under a millisecond per frame on a CPU core.

    Model signature, read off the file (Step 1) — v5:
      IN   input [1, N] float32 · state [2, 1, 128] float32 · sr int64
      OUT  output [1, 1] float32 · stateN [2, 1, 128] float32

    The state is carried between frames. Dropping it makes every frame
    a fresh start, which reads as "constant maybe-speech" and is a
    plausible-looking failure with no error attached.
    """

    def __init__(self, model_path: str | os.PathLike[str] | None = None) -> None:
        import numpy as np
        import onnxruntime as ort

        self._np = np
        path = Path(model_path or os.getenv("SAMANTHA_VAD_MODEL") or DEFAULT_MODEL_PATH)
        if not path.is_file():
            raise FileNotFoundError(
                f"Silero VAD model not at {path} — see widget/README.md"
            )
        options = ort.SessionOptions()
        # One thread: this runs every 32 ms forever, and letting ORT
        # spawn a pool per session costs more in scheduling than the
        # model costs to run.
        options.inter_op_num_threads = 1
        options.intra_op_num_threads = 1
        self._session = ort.InferenceSession(str(path), sess_options=options)
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._sr = np.array(INPUT_RATE, dtype=np.int64)

    def reset(self) -> None:
        self._state = self._np.zeros((2, 1, 128), dtype=self._np.float32)

    def speech_probability(self, frame: bytes) -> float:
        audio = self._np.frombuffer(frame, dtype=self._np.int16)
        audio = (audio.astype(self._np.float32) / 32768.0).reshape(1, -1)
        out, self._state = self._session.run(
            None, {"input": audio, "state": self._state, "sr": self._sr}
        )
        return float(out[0][0])
```

- [ ] **Step 4: Write a probe that proves it hears you**

```python
# widget/tools/probe_silero.py
"""Print a live speech probability. Talk, and watch it move."""

import sounddevice as sd

from samantha_widget.vad import FRAME_SAMPLES, INPUT_RATE, SileroDetector

detector = SileroDetector()
print(f"device: {sd.query_devices(kind='input')['name']}")

with sd.RawInputStream(
    samplerate=INPUT_RATE, blocksize=FRAME_SAMPLES, channels=1, dtype="int16"
) as stream:
    while True:
        frame, _overflowed = stream.read(FRAME_SAMPLES)
        p = detector.speech_probability(bytes(frame))
        print(f"\r{p:0.2f} {'█' * int(p * 40):<40}", end="", flush=True)
```

- [ ] **Step 5: Run it and talk**

```bash
.venv/bin/pip install sounddevice
.venv/bin/python tools/probe_silero.py
```

Expected: near 0.0 in a quiet room, jumping above 0.5 within a syllable
of you speaking, and falling back when you stop. If it sits at a
constant middling value, the state is not being carried — re-read
Step 3's docstring. If it never moves, PortAudio picked the wrong input
device; the printed device name is the first thing to check.

- [ ] **Step 6: Commit**

```bash
cd .. && git add widget/ && git commit -m "feat(widget): Silero VAD over onnxruntime, no torch"
```

---

## Task 5: Transcription

**Files:**
- Create: `widget/samantha_widget/stt.py`
- Create: `widget/tests/test_stt.py`

**Interfaces:**
- Consumes: `vad.INPUT_RATE`.
- Produces:
  - `class Transcriber` with `__init__(self, model_name: str = "large-v3-turbo")`,
    `def load(self) -> None` (blocking; call off the main thread),
    `def transcribe(self, pcm: bytes) -> str`, and `ready: bool`.
  - `def clean(text: str) -> str` — pure, and what the tests exercise.

- [ ] **Step 1: Write the failing tests**

```python
# widget/tests/test_stt.py
"""What we do with what Whisper says.

The model itself is not tested here — it needs a GPU and 1.5 GB of
weights. What IS tested is the part that bites: Whisper hallucinates
politeness into silence, and a strip that is always listening meets
that failure hundreds of times a day.
"""

from samantha_widget.stt import Transcriber, clean


def test_whitespace_is_trimmed() -> None:
    assert clean("  hola  ") == "hola"


def test_a_hallucinated_thank_you_is_dropped() -> None:
    """Whisper's favourite output for near-silence, in Spanish and English."""
    for phrase in (
        "Gracias.",
        "gracias por ver el video",
        "Subtítulos realizados por la comunidad de Amara.org",
        "Thank you.",
        "¡Suscríbete al canal!",
    ):
        assert clean(phrase) == ""


def test_a_real_sentence_containing_gracias_survives() -> None:
    assert clean("Gracias, pero prefiero quedarme en casa") != ""


def test_an_empty_transcription_stays_empty() -> None:
    assert clean("") == ""
    assert clean("   ") == ""


def test_transcriber_is_not_ready_before_load() -> None:
    """The strip appears immediately and simply cannot hear for a while."""
    assert Transcriber().ready is False


def test_transcribing_before_load_returns_nothing_rather_than_raising() -> None:
    """A turn during startup is lost, not fatal."""
    assert Transcriber().transcribe(b"\x00\x00" * 16000) == ""
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd widget && .venv/bin/python -m pytest tests/test_stt.py -v`
Expected: FAIL — no module `samantha_widget.stt`.

- [ ] **Step 3: Write `stt.py`**

```python
# widget/samantha_widget/stt.py
"""faster-whisper, loaded late and asked in Spanish.

CLAUDE.md §2.6 named large-v3-turbo back when STT was going to be
local; the 2026-05-13 decision moved it into the browser's Web Speech
API instead. With the browser gone, that decision goes with it and the
original one comes back.

Measured headroom on this box: the 4090 has 24564 MiB with ~5355 MiB
taken by CosyVoice. large-v3-turbo in float16 needs roughly 1.5-2 GB.

Loading takes seconds, so it happens on a background thread and the
strip is simply deaf until `ready`. An appliance does not show a
progress bar.
"""

from __future__ import annotations

import re

from .vad import INPUT_RATE

DEFAULT_MODEL = "large-v3-turbo"

# Whisper fills silence with the politeness it was trained on: video
# outros, subtitle credits, "gracias". A strip that listens all day
# meets these constantly, and each one would otherwise become a turn.
_HALLUCINATIONS = re.compile(
    r"^\W*(gracias(\s+por\s+ver.*)?|thank you|thanks for watching"
    r"|subt[ií]tulos?.*|¡?suscr[ií]bete.*|amara\.org.*)\W*$",
    re.IGNORECASE,
)


def clean(text: str) -> str:
    """Trim, and drop the phrases Whisper invents out of silence."""
    stripped = text.strip()
    if not stripped:
        return ""
    return "" if _HALLUCINATIONS.match(stripped) else stripped


class Transcriber:
    def __init__(self, model_name: str = DEFAULT_MODEL) -> None:
        self.model_name = model_name
        self._model = None

    @property
    def ready(self) -> bool:
        return self._model is not None

    def load(self) -> None:
        """Blocking. Call from a worker thread, never the GTK one."""
        from faster_whisper import WhisperModel

        self._model = WhisperModel(
            self.model_name, device="cuda", compute_type="float16"
        )

    def transcribe(self, pcm: bytes) -> str:
        """16 kHz mono int16 PCM in, Spanish text out. "" if not ready."""
        if self._model is None:
            return ""
        import numpy as np

        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        segments, _info = self._model.transcribe(
            audio,
            language="es",  # never auto-detect: she lives in Spanish
            beam_size=1,  # latency over correctness (CLAUDE.md §1.4)
            vad_filter=False,  # Silero already cut this to one utterance
        )
        return clean(" ".join(segment.text for segment in segments))


del INPUT_RATE  # imported for the docstring's sake only
```

Drop that last line if ruff objects — it is there to make the rate's
provenance obvious, not to do work.

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_stt.py -v`
Expected: 6 passed.

- [ ] **Step 5: Load the real model once, and time it**

```bash
.venv/bin/pip install faster-whisper
.venv/bin/python -c "
import time
from samantha_widget.stt import Transcriber
t = Transcriber(); start = time.time(); t.load()
print(f'loaded in {time.time()-start:.1f}s')
"
nvidia-smi --query-gpu=memory.used --format=csv
```

Expected: loads (first run downloads ~1.5 GB), and VRAM in use rises
by roughly 1.5–2 GB over the 5.3 GB CosyVoice already holds. If it
OOMs, drop to `compute_type="int8_float16"` and note it in the README.

- [ ] **Step 6: Transcribe your own voice**

```bash
.venv/bin/python -c "
import sounddevice as sd
from samantha_widget.stt import Transcriber
t = Transcriber(); t.load()
print('habla durante 4 segundos...')
pcm = sd.rec(int(4*16000), samplerate=16000, channels=1, dtype='int16')
sd.wait()
print(repr(t.transcribe(pcm.tobytes())))
"
```

Expected: your words, in Spanish.

- [ ] **Step 7: Commit**

```bash
cd .. && git add widget/ && git commit -m "feat(widget): local transcription, and the politeness Whisper invents"
```

---

## Task 6: Clauses, synthesis, and playback

**Files:**
- Create: `widget/samantha_widget/audio.py`
- Create: `widget/samantha_widget/speech.py`
- Create: `widget/tests/test_speech.py`

**Interfaces:**
- Consumes: `samantha.tts.stream`, `samantha.tts.new_client`,
  `Hermes.plugins.samantha_voice.markers.has_unclosed_tag`.
- Produces:
  - `class ClauseChunker` with `def push(self, token: str) -> list[str]`
    and `def flush(self) -> list[str]`.
  - `audio.Player` with `def start(self)`, `def write(self, pcm: bytes)`,
    `def stop(self)` (drops everything queued), and `level: float`.
  - `class Speaker` with `async def say(self, clause: str) -> None`
    and `def interrupt(self) -> None`.

- [ ] **Step 1: Write the failing tests for the chunker**

```python
# widget/tests/test_speech.py
"""Where to cut her reply so CosyVoice sounds like a person.

The numbers come from what samantha-voice already measured against the
live server (docs/…-samantha-on-hermes-design.md §3.1): very short
clauses are synthesised badly, and a clause cut inside an expression
marker hands CosyVoice an opening tag with no close.
"""

from samantha_widget.speech import ClauseChunker


def _feed(text: str) -> list[str]:
    chunker = ClauseChunker()
    out: list[str] = []
    for char in text:  # one token per character: the worst case
        out += chunker.push(char)
    return out + chunker.flush()


def test_a_sentence_is_emitted_at_the_full_stop() -> None:
    assert _feed("Hola, me alegro de oírte de nuevo.") == [
        "Hola, me alegro de oírte de nuevo."
    ]


def test_two_sentences_become_two_clauses() -> None:
    assert len(_feed("Claro que sí. ¿Y tú qué tal estás hoy?")) == 2


def test_a_short_fragment_is_held_and_merged_forward() -> None:
    """"Ya." alone makes CosyVoice clip. It waits for company."""
    clauses = _feed("Ya. Entiendo perfectamente lo que quieres decir.")

    assert clauses[0].startswith("Ya.")
    assert len(clauses[0]) >= 12


def test_a_comma_only_cuts_when_there_is_enough_behind_it() -> None:
    long_enough = _feed("Estuve pensando en lo que dijiste ayer, y creo que sí.")
    too_short = _feed("Sí, claro que te entiendo perfectamente.")

    assert len(long_enough) == 2
    assert len(too_short) == 1


def test_an_open_laughter_tag_is_never_cut() -> None:
    """<laughter>Ya. Claro</laughter> must not split at the full stop."""
    clauses = _feed("<laughter>Ya. Claro</laughter> te entiendo del todo.")

    for clause in clauses:
        assert clause.count("<laughter>") == clause.count("</laughter>")


def test_inline_markers_survive_intact() -> None:
    clauses = _feed("Vale [breath] lo pensaré con calma esta noche.")

    assert "[breath]" in " ".join(clauses)


def test_flush_releases_a_reply_with_no_final_punctuation() -> None:
    """Models end mid-thought. It still has to be said out loud."""
    assert _feed("Creo que sí aunque no estoy del todo segura") != []


def test_nothing_in_produces_nothing_out() -> None:
    assert _feed("") == []


def test_newline_ends_a_clause() -> None:
    assert len(_feed("Primero esto que ya es bastante largo\ny luego lo otro\n")) == 2
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd widget && .venv/bin/python -m pytest tests/test_speech.py -v`
Expected: FAIL — no module `samantha_widget.speech`.

- [ ] **Step 3: Make `markers.py` reachable**

`Hermes/plugins/samantha_voice/markers.py` is already the answer to
"is this tag closed?", and reimplementing it means two copies that
drift. `Hermes/run-gateway.sh` puts the repo root on `PYTHONPATH`;
`speech.py` imports it the same way, with a local fallback so a
`widget/`-only checkout still runs:

```python
try:
    from Hermes.plugins.samantha_voice.markers import has_unclosed_tag
except ImportError:  # repo root not on PYTHONPATH
    def has_unclosed_tag(text: str) -> bool:
        return text.count("<laughter>") > text.count("</laughter>")
```

- [ ] **Step 4: Write `speech.py`**

```python
# widget/samantha_widget/speech.py
"""Cut the reply into clauses, synthesise each, play it as it arrives.

Waiting for `done` before speaking makes her feel dead; synthesising
every token makes CosyVoice stutter. The rule in between comes from
what samantha-voice measured against the live server.

The widget synthesises rather than waiting for the gateway to send
audio (spec §5.1). It is a Python process on the same machine as
CosyVoice, so the binary WebSocket protocol that a browser would have
needed is never written.
"""

from __future__ import annotations

import asyncio

try:
    from Hermes.plugins.samantha_voice.markers import has_unclosed_tag
except ImportError:  # repo root not on PYTHONPATH
    def has_unclosed_tag(text: str) -> bool:
        return text.count("<laughter>") > text.count("</laughter>")

_HARD_STOPS = ".?!…\n"
_SOFT_STOPS = ",;:"
# Below this CosyVoice clips the clause; hold it and let it merge forward.
_MIN_CLAUSE_CHARS = 12
# A comma only earns a cut when there is a real phrase behind it.
_MIN_SOFT_CLAUSE_CHARS = 25


class ClauseChunker:
    def __init__(self) -> None:
        self._buffer = ""

    def push(self, token: str) -> list[str]:
        out: list[str] = []
        for char in token:
            self._buffer += char
            if self._ready(char):
                out.append(self._buffer.strip())
                self._buffer = ""
        return [c for c in out if c]

    def flush(self) -> list[str]:
        """Release whatever is left — a reply that ended mid-thought."""
        rest, self._buffer = self._buffer.strip(), ""
        return [rest] if rest else []

    def _ready(self, char: str) -> bool:
        if has_unclosed_tag(self._buffer):
            # Cutting here would hand CosyVoice "<laughter>Ya." — an
            # opening tag with no close.
            return False
        text = self._buffer.strip()
        if char in _HARD_STOPS:
            return len(text) >= _MIN_CLAUSE_CHARS
        if char in _SOFT_STOPS:
            return len(text) >= _MIN_SOFT_CLAUSE_CHARS
        return False


class Speaker:
    """Synthesise one clause and hand the PCM to the player."""

    def __init__(self, player) -> None:
        self._player = player
        self._client = None
        self._generation = 0

    def interrupt(self) -> None:
        """Stop talking, now. Called when the user starts speaking.

        The generation counter is what makes it stick: a synthesis
        already in flight cannot be cancelled mid-HTTP-response, so it
        finishes and then finds its generation stale and throws its
        audio away instead of playing over the user.
        """
        self._generation += 1
        self._player.stop()

    async def say(self, clause: str) -> None:
        from samantha import tts

        if self._client is None:
            # An httpx.AsyncClient may only be used on the loop that
            # created it, and this loop is not uvicorn's.
            self._client = tts.new_client()

        generation = self._generation
        async for chunk, _backend in tts.stream(clause, client=self._client):
            if generation != self._generation:
                return  # interrupted while this clause was synthesising
            self._player.write(chunk)
            await asyncio.sleep(0)  # let the loop breathe between chunks
```

- [ ] **Step 5: Write `audio.py`**

```python
# widget/samantha_widget/audio.py
"""PortAudio in and out. Two rates, no resampling.

In:  16 kHz mono int16, 512-sample frames — what Silero and Whisper want.
Out: 24 kHz mono int16 — samantha.tts.OUTPUT_SAMPLE_RATE, exactly.

PipeWire (with pipewire-pulse) is what is running on this box, so
PortAudio reaches it through the Pulse compatibility layer. The device
name is logged once at startup because the failure mode of picking the
wrong one is silence with no error.
"""

from __future__ import annotations

import queue
import threading

import sounddevice as sd

from .vad import FRAME_SAMPLES, INPUT_RATE

OUTPUT_RATE = 24000


class Microphone:
    """Always open. Calls `on_frame` from PortAudio's own thread."""

    def __init__(self, on_frame) -> None:
        self._on_frame = on_frame
        self._stream: sd.RawInputStream | None = None

    def start(self) -> None:
        def callback(indata, _frames, _time, status) -> None:
            del status  # overruns are logged by PortAudio itself
            self._on_frame(bytes(indata))

        self._stream = sd.RawInputStream(
            samplerate=INPUT_RATE,
            blocksize=FRAME_SAMPLES,
            channels=1,
            dtype="int16",
            callback=callback,
        )
        self._stream.start()

    def stop(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None


class Player:
    """A queue feeding one output stream, with a level for the wave."""

    def __init__(self) -> None:
        self._queue: queue.Queue[bytes | None] = queue.Queue()
        self._stream: sd.RawOutputStream | None = None
        self._thread: threading.Thread | None = None
        self._running = False
        self.level = 0.0

    def start(self) -> None:
        self._stream = sd.RawOutputStream(
            samplerate=OUTPUT_RATE, channels=1, dtype="int16"
        )
        self._stream.start()
        self._running = True
        self._thread = threading.Thread(target=self._pump, daemon=True)
        self._thread.start()

    def write(self, pcm: bytes) -> None:
        self._queue.put(pcm)

    def stop(self) -> None:
        """Drop everything queued. This is what barge-in feels like."""
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
        self.level = 0.0

    def close(self) -> None:
        self._running = False
        self._queue.put(None)
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()

    @property
    def busy(self) -> bool:
        return not self._queue.empty()

    def _pump(self) -> None:
        import numpy as np

        while self._running:
            chunk = self._queue.get()
            if chunk is None:
                return
            samples = np.frombuffer(chunk, dtype=np.int16).astype(np.float32)
            if samples.size:
                self.level = float(np.sqrt(np.mean((samples / 32768.0) ** 2)))
            if self._stream is not None:
                self._stream.write(chunk)
        self.level = 0.0
```

- [ ] **Step 6: Run the chunker tests**

Run: `.venv/bin/python -m pytest tests/test_speech.py -v`
Expected: 9 passed.

- [ ] **Step 7: Hear her say one sentence**

```bash
cd /home/nexus/git/os1-samantha/widget
PYTHONPATH=/home/nexus/git/os1-samantha/backend:/home/nexus/git/os1-samantha \
  .venv/bin/pip install httpx loguru
PYTHONPATH=/home/nexus/git/os1-samantha/backend:/home/nexus/git/os1-samantha \
  .venv/bin/python -c "
import asyncio, time
from samantha_widget.audio import Player
from samantha_widget.speech import Speaker
p = Player(); p.start()
asyncio.run(Speaker(p).say('Hola. Soy yo, y esta vez no estoy en una pantalla.'))
while p.busy: time.sleep(0.1)
time.sleep(1); p.close()
"
```

Expected: her cloned voice, out of the speakers. If it is silent, check
CosyVoice is up on :8093 and that the reference WAV exists — that is
what `samantha.tts.is_available()` probes.

- [ ] **Step 8: Commit**

```bash
cd .. && git add widget/ && git commit -m "feat(widget): cut her reply into clauses and say them as they arrive"
```

---

## Task 7: The turn, assembled

**Files:**
- Create: `widget/samantha_widget/turn.py`
- Modify: `widget/samantha_widget/__main__.py`
- Create: `widget/tests/test_turn.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `class TurnMachine` with
  `__init__(self, *, on_state: Callable[[WaveState], None],
  on_level: Callable[[float], None],
  on_utterance: Callable[[bytes], None] = …,
  on_interrupt: Callable[[], None] = …)`,
  and the five transitions
  `def speech_started(self) -> None`, `def heard(self, pcm: bytes) -> None`,
  `def token(self, text: str) -> None`, `def done(self) -> None`,
  `def error(self, message: str) -> None`,
  plus `def level(self, value: float) -> None`,
  `state: WaveState` and `interrupted: bool`.
  The two `on_utterance` / `on_interrupt` callbacks default to no-ops so
  the tests can construct one with only the two it asserts on.

- [ ] **Step 1: Write the failing tests**

```python
# widget/tests/test_turn.py
"""The state machine, with every I/O boundary faked.

What is being tested is the sequence a person sees: the line answers
their voice, goes quiet while she thinks, moves while she talks, and
settles. Getting that wrong is not a crash — it is a strip that looks
broken.
"""

from samantha_widget.turn import TurnMachine
from samantha_widget.wave_model import WaveState


def _machine() -> tuple[TurnMachine, list[WaveState]]:
    seen: list[WaveState] = []
    machine = TurnMachine(on_state=seen.append, on_level=lambda _level: None)
    return machine, seen


def test_it_starts_idle() -> None:
    machine, _ = _machine()

    assert machine.state is WaveState.IDLE


def test_hearing_speech_moves_to_listening() -> None:
    machine, _ = _machine()
    machine.speech_started()

    assert machine.state is WaveState.LISTENING


def test_a_finished_utterance_moves_to_thinking() -> None:
    machine, _ = _machine()
    machine.speech_started()
    machine.heard(b"\x00\x00" * 16000)

    assert machine.state is WaveState.THINKING


def test_the_first_token_moves_to_speaking() -> None:
    machine, _ = _machine()
    machine.speech_started()
    machine.heard(b"\x00\x00" * 16000)
    machine.token("Hola, ")

    assert machine.state is WaveState.SPEAKING


def test_done_returns_to_idle() -> None:
    machine, _ = _machine()
    machine.speech_started()
    machine.heard(b"\x00\x00" * 16000)
    machine.token("Hola, me alegro de oírte.")
    machine.done()

    assert machine.state is WaveState.IDLE


def test_an_error_returns_to_idle_too() -> None:
    """A turn that failed must not leave the line stuck in `thinking`."""
    machine, _ = _machine()
    machine.speech_started()
    machine.heard(b"\x00\x00" * 16000)
    machine.error("algo se ha quedado a medias")

    assert machine.state is WaveState.IDLE


def test_speaking_while_she_speaks_interrupts_her() -> None:
    machine, _ = _machine()
    machine.speech_started()
    machine.heard(b"\x00\x00" * 16000)
    machine.token("Estaba diciendo algo bastante largo.")
    machine.speech_started()  # the user cuts in

    assert machine.state is WaveState.LISTENING
    assert machine.interrupted is True


def test_every_state_change_is_announced_once() -> None:
    machine, seen = _machine()
    machine.speech_started()
    machine.speech_started()  # same state again

    assert seen.count(WaveState.LISTENING) == 1
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd widget && .venv/bin/python -m pytest tests/test_turn.py -v`
Expected: FAIL — no module `samantha_widget.turn`.

- [ ] **Step 3: Write `turn.py`**

```python
# samantha_widget/turn.py
"""The sequence a person sees, and the only place the pieces meet.

Deliberately free of GTK, of PortAudio and of the network: it is handed
callbacks and calls them. That is what lets the sequence be tested, and
it is also what keeps the GLib.idle_add rule enforceable in one place —
`on_state` and `on_level` are the only things that reach the UI, and
whoever constructs a TurnMachine is responsible for making them safe to
call from another thread.
"""

from __future__ import annotations

from typing import Callable

from .wave_model import WaveState


class TurnMachine:
    def __init__(
        self,
        *,
        on_state: Callable[[WaveState], None],
        on_level: Callable[[float], None],
        on_utterance: Callable[[bytes], None] = lambda _pcm: None,
        on_interrupt: Callable[[], None] = lambda: None,
    ) -> None:
        self._on_state = on_state
        self._on_level = on_level
        self._on_utterance = on_utterance
        self._on_interrupt = on_interrupt
        self.state = WaveState.IDLE
        self.interrupted = False

    def _go(self, state: WaveState) -> None:
        if state is self.state:
            return
        self.state = state
        self._on_state(state)

    def level(self, value: float) -> None:
        self._on_level(value)

    def speech_started(self) -> None:
        """The VAD is confident someone is talking."""
        if self.state is WaveState.SPEAKING:
            # Barge-in. She stops mid-word; the alternative is two
            # people talking, which is what makes an assistant feel
            # like a machine.
            self.interrupted = True
            self._on_interrupt()
        self._go(WaveState.LISTENING)

    def heard(self, pcm: bytes) -> None:
        """A complete utterance. Transcription and dispatch follow."""
        self._go(WaveState.THINKING)
        self._on_utterance(pcm)

    def token(self, text: str) -> None:
        del text
        self._go(WaveState.SPEAKING)

    def done(self) -> None:
        self.interrupted = False
        self._go(WaveState.IDLE)

    def error(self, message: str) -> None:
        del message  # the caller decides whether to say it out loud
        self.interrupted = False
        self._go(WaveState.IDLE)
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_turn.py -v`
Expected: 8 passed.

- [ ] **Step 5: Wire it all together in `__main__.py`**

Replace plan 1's demo keys. The shape (the only bridge to the UI is
`GLib.idle_add`):

```python
    def do_activate(self) -> None:
        import asyncio
        import threading

        from gi.repository import GLib

        from .audio import Microphone, Player
        from .gateway import GatewayClient
        from .speech import ClauseChunker, Speaker
        from .stt import Transcriber
        from .turn import TurnMachine
        from .vad import SileroDetector, UtteranceDetector
        from .wave import WaveArea
        from .window import StripWindow

        window = StripWindow(self)
        wave = WaveArea()
        window.set_content(wave)
        window.present()

        loop = asyncio.new_event_loop()
        player = Player()
        player.start()
        speaker = Speaker(player)
        chunker = ClauseChunker()
        transcriber = Transcriber()
        client = GatewayClient()

        # ── the only bridge into the UI ──────────────────────────────
        def set_state(state) -> None:
            GLib.idle_add(wave.set_state, state)

        def set_level(level: float) -> None:
            GLib.idle_add(wave.model.set_level, level)

        machine = TurnMachine(
            on_state=set_state,
            on_level=set_level,
            on_utterance=lambda pcm: loop.call_soon_threadsafe(
                lambda: asyncio.ensure_future(dispatch(pcm))
            ),
            on_interrupt=speaker.interrupt,
        )

        async def dispatch(pcm: bytes) -> None:
            text = await asyncio.to_thread(transcriber.transcribe, pcm)
            if not text:
                machine.done()  # nothing was said; go back to idle quietly
                return
            await client.send_chat(text)

        # ── the gateway's replies ────────────────────────────────────
        def on_token(token: str) -> None:
            machine.token(token)
            for clause in chunker.push(token):
                asyncio.ensure_future(speaker.say(clause))

        def on_done(_ms: int) -> None:
            for clause in chunker.flush():
                asyncio.ensure_future(speaker.say(clause))
            machine.done()

        client.on_token = on_token
        client.on_done = on_done
        client.on_error = lambda message: machine.error(message)

        # ── the microphone, always open ──────────────────────────────
        detector = UtteranceDetector(SileroDetector())

        def on_frame(frame: bytes) -> None:
            was_speaking = detector.speaking
            utterance = detector.push(frame)
            if detector.speaking and not was_speaking:
                machine.speech_started()
            if detector.speaking:
                import numpy as np

                samples = np.frombuffer(frame, dtype=np.int16).astype(np.float32)
                set_level(float(np.sqrt(np.mean((samples / 32768.0) ** 2))) * 6)
            if utterance is not None:
                machine.heard(utterance)

        Microphone(on_frame).start()

        threading.Thread(target=loop.run_forever, daemon=True).start()
        loop.call_soon_threadsafe(lambda: asyncio.ensure_future(client.run()))
        threading.Thread(target=transcriber.load, daemon=True).start()
```

- [ ] **Step 6: Gate the microphone while she speaks**

The VAD hears the speakers. Without a gate she interrupts herself on
her own voice — spec §9. In `on_frame`, before anything else:

```python
            if player.busy and not detector.speaking:
                # She is talking and nobody has cut in. Do not let her
                # own voice, coming back through the room, start a turn.
                return
```

Barge-in still works: `detector.speaking` is only False before a turn
starts, and a user talking over her clears the queue via
`machine.speech_started()` → `speaker.interrupt()` → `player.stop()`,
after which `player.busy` is False and frames flow again.

- [ ] **Step 7: Run the whole suite**

Run: `.venv/bin/python -m pytest -v && .venv/bin/ruff check . && .venv/bin/ruff format --check .`
Expected: everything green.

- [ ] **Step 8: Commit**

```bash
cd .. && git add widget/ && git commit -m "feat(widget): the turn, from her ear to her voice"
```

---

## Task 8: Talk to her

**Files:**
- Modify: `systemd/samantha-widget.service`
- Modify: `widget/README.md`
- Modify: `PROGRESS.md`

- [ ] **Step 1: Give the unit what the new code needs**

```ini
Environment=PYTHONPATH=%h/git/os1-samantha/backend:%h/git/os1-samantha
```

Without it `samantha.tts` and `markers.py` are both unimportable — and
the failure is not a crash: `speech.py`'s fallback covers markers, so
the strip runs and is simply mute. Add it, then:

```bash
cp systemd/samantha-widget.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user restart samantha-widget.service
journalctl --user -u samantha-widget -f
```

- [ ] **Step 2: Have a conversation**

Say "Hola Samantha, ¿qué tal estás?" out loud and watch the strip.
Check each, and write down what actually happened:

1. The line answers your voice while you speak (`listening`).
2. It goes to a travelling packet when you stop (`thinking`).
3. She answers **out loud, in her cloned voice**, within a few seconds.
4. The line moves while she speaks (`speaking`).
5. It settles flat when she finishes (`idle`).
6. **She says it once.** Twice means the gateway is also speaking —
   Task 1's risk, and Task 1's answer.
7. Talking over her stops her mid-word.
8. Silence for a minute produces nothing at all.

- [ ] **Step 3: Time it**

From the end of your sentence to her first sound. Note the number. If
it is over ~4 s, the breakdown is what to measure next: Whisper
(logged), the gateway (`thinking_ms` in the `done` frame), CosyVoice
(the gap before the first PCM chunk). Do not optimise before measuring
which of the three it is.

- [ ] **Step 4: Note whose voice it is**

Spec §9: Hermes answers in its own `SOUL.md` persona, not
`backend/samantha/personality.py`. Write down whether she sounded like
Samantha. This is the input to plan 3 and the most likely reason the
widget does not convince.

- [ ] **Step 5: Update the README**

Document: the two extra system packages, the Silero model at
`~/.samantha/models/silero_vad.onnx`, the `PYTHONPATH` requirement, the
`SAMANTHA_VAD_MODEL` override, and the measured latency from Step 3.

- [ ] **Step 6: Update PROGRESS.md**

`## 2026-08-23 — Widget plan 2: the voice turn ✅`, house format, and in
Notes: the measured latency, whose persona answered, and anything from
Step 2's checklist that did not hold.

- [ ] **Step 7: Commit**

```bash
git add widget/ systemd/ PROGRESS.md
git commit -m "feat(widget): she listens and answers, with no wake word"
```

---

## Done when

- You speak; she answers out loud, once, in her voice, with no button.
- The line moves through four visibly distinct states in the right order.
- Talking over her stops her.
- Her own voice through the speakers does not start a turn.
- A minute of silence produces nothing.
- `systemctl --user restart samantha-widget` brings it all back.
- `pytest` is green in `widget/`; `backend/` is untouched.
- The Chromium kiosk still starts.

Plan 3 — barge-in polish, onboarding, and retiring the kiosk, the
frontend and the adapter's static half — is written once this has
convinced. That was decision 2's explicit rider and it still stands.
