# samantha-voice — CosyVoice streaming provider for Hermes

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Hermes speak in Samantha's cloned voice, streaming
clause by clause, with no cloud TTS involved.

**Architecture:** A Hermes plugin registers a `StreamingTTSProvider`
subclass that wraps the existing `samantha.tts` CosyVoice client. Two
pieces sit between them: a clause guard that prevents Hermes' sentence
chunker from emitting text that crashes CosyVoice's vocoder or splits
an expression marker, and a thread bridge that turns our async byte
stream into the synchronous iterator Hermes expects.

**Tech Stack:** Python 3.12, Hermes plugin API (`plugins/*/plugin.yaml`
+ `register(ctx)`), `httpx` (already a dependency), pytest.

**Spec:** `docs/superpowers/specs/2026-08-22-samantha-on-hermes-design.md`
(§3 is this plan; read §1–2 for why).

## Global Constraints

- This is **plan 1 of 3**. Plans for `samantha-memory` and
  `samantha-kiosk` are written after this one lands, because their
  detail depends on contracts Task 1 reads from source.
- Hermes is **not installed on this machine** today. Task 1 installs it
  and pins the version. Every later task assumes that pin.
- The provider must yield **raw int16 little-endian mono PCM at
  24000 Hz** — matching `samantha.tts.OUTPUT_SAMPLE_RATE`. No
  resampling anywhere.
- Synthesis uses `/inference_zero_shot` with the reference WAV **and**
  its transcript. Never `cross_lingual` — it strips prosody.
- Expression markers are exactly `[laughter]`, `[breath]`, `[sigh]`
  and `<laughter>…</laughter>` (`backend/samantha/personality.py:58-61`).
- Nothing in this plan may block the gateway's event loop.
- Comments and identifiers in English; any user-facing string in
  Spanish (CLAUDE.md §2.9).
- `ruff check` and `ruff format` must pass before every commit.
- New top-level directory `plugins/` — **requires the user's approval
  under CLAUDE.md §3 before Task 2.** If refused, use
  `backend/plugins/` and adjust every path below.

---

## File Structure

- `plugins/samantha_voice/plugin.yaml` — manifest. Metadata only.
- `plugins/samantha_voice/__init__.py` — `register(ctx)` entry point,
  mirroring `plugins/platforms/irc/__init__.py` upstream.
- `plugins/samantha_voice/chunking.py` — the clause guard. Pure
  functions, no I/O, no Hermes imports. Owns every rule about what text
  is safe to hand CosyVoice.
- `plugins/samantha_voice/bridge.py` — async→sync PCM bridge. Owns the
  worker thread and its loop. No CosyVoice knowledge.
- `plugins/samantha_voice/provider.py` — the `StreamingTTSProvider`
  subclass. Wires chunking + bridge + `samantha.tts`. The only file
  that imports Hermes.
- `plugins/samantha_voice/tests/test_chunking.py`
- `plugins/samantha_voice/tests/test_bridge.py`
- `plugins/samantha_voice/tests/test_provider.py`
- `docs/superpowers/specs/hermes-contracts-v<version>.md` — created by
  Task 1; the verbatim contracts plans 2 and 3 are written against.

Split rationale: `chunking.py` and `bridge.py` are the parts with real
logic and they are testable without Hermes installed, which keeps the
test suite runnable on any machine. `provider.py` is thin glue.

---

### Task 1: Install Hermes locally and capture its contracts

No production code. The deliverable is a pinned install and a document
of verbatim signatures, because plans 2 and 3 cannot be written
accurately from web documentation.

**Files:**
- Create: `docs/superpowers/specs/hermes-contracts-v<version>.md`
- Modify: `docs/running-real-mode.md` (add the Hermes install section)

**Interfaces:**
- Consumes: nothing.
- Produces: a documented, pinned Hermes version; verbatim source of
  `StreamingTTSProvider`, `MemoryProvider`, `BasePlatformAdapter`,
  `MessageType`, `MessageEvent`, and `PluginContext.register_platform`.

- [ ] **Step 1: Install Hermes as a tool**

```bash
uv tool install hermes-agent --with mcp
hermes --version
```

Expected: a version at or above `0.20.5`. Record the exact string; it
is the pin for everything that follows.

- [ ] **Step 2: Locate the installed package**

```bash
python3 -c "import importlib.util, pathlib; \
spec = importlib.util.find_spec('tools.tts_streaming'); \
print(pathlib.Path(spec.origin).parent.parent)"
```

If that fails because the tool install is isolated, find it directly:

```bash
find ~/.local/share/uv/tools/hermes-agent -name tts_streaming.py
```

Expected: a path ending in `tools/tts_streaming.py`. Export its parent
parent as `$HERMES` for the remaining steps.

- [ ] **Step 3: Capture the four contracts verbatim**

Read and copy into the new doc, unedited:

```bash
sed -n '1,80p' "$HERMES/tools/tts_streaming.py"
sed -n '1,120p' "$HERMES/agent/memory_provider.py"
grep -n "class MessageType" -A 15 "$HERMES/gateway/platforms/base.py"
grep -n "class MessageEvent" -A 40 "$HERMES/gateway/platforms/base.py"
grep -n "def register_platform" -A 40 "$HERMES"/hermes_cli/plugins.py
grep -rn "streaming_tts" "$HERMES/gateway/platforms/base.py"
```

Write `docs/superpowers/specs/hermes-contracts-v<version>.md` with one
section per contract, each quoting the source exactly and naming the
file and line range it came from.

- [ ] **Step 4: Note every discrepancy against the capability map**

Compare what you read against
`docs/superpowers/specs/2026-08-21-hermes-herald-capability-map.md`.
Add a "Corrections" section listing anything that differs. The map was
built from documentation and web-fetched summaries; treat source as
authoritative and say so where they disagree.

- [ ] **Step 5: Confirm the plugin directory is discovered**

```bash
mkdir -p ~/.hermes/plugins
hermes plugins
```

Expected: the command runs and lists plugins (bundled ones at minimum).
Record the exact command that lists them — later tasks use it to verify
registration.

- [ ] **Step 6: Commit**

```bash
git add docs/superpowers/specs/hermes-contracts-v*.md docs/running-real-mode.md
git commit -m "docs(hermes): pin the local install and capture its contracts from source"
```

---

### Task 2: The clause guard

Hermes' `SentenceChunker` emits short clauses. CosyVoice's hifigan
crashes when `tts_text` is much shorter than `prompt_text`, returning
`200` with an empty body — `backend/samantha/tts.py:213-217` already
detects this and raises. A clause boundary landing inside
`<laughter>…</laughter>` produces the same silent failure. This task
prevents both.

The guard buffers with one-clause lookahead so the tail always merges
into the final emission rather than trailing as a too-short fragment.

**Files:**
- Create: `plugins/samantha_voice/chunking.py`
- Create: `plugins/samantha_voice/tests/test_chunking.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `safe_clauses(clauses: Iterable[str], min_chars: int = 40)
  -> Iterator[str]`. Later tasks call only this.

- [ ] **Step 1: Write the failing tests**

```python
# plugins/samantha_voice/tests/test_chunking.py
from plugins.samantha_voice.chunking import safe_clauses


def test_long_clauses_pass_through_unchanged():
    clauses = ["Hoy he estado pensando en lo que me contaste ayer.",
               "Y creo que te entiendo mejor de lo que creía."]
    assert list(safe_clauses(clauses, min_chars=10)) == clauses


def test_short_clauses_merge_forward():
    clauses = ["Ya.", "Claro.", "Te entiendo perfectamente y me alegra."]
    out = list(safe_clauses(clauses, min_chars=20))
    assert out == ["Ya. Claro. Te entiendo perfectamente y me alegra."]


def test_tail_never_trails_short():
    # "Sí." alone would crash hifigan; it must ride with the previous clause.
    clauses = ["Me parece una idea estupenda y deberíamos probarla.", "Sí."]
    out = list(safe_clauses(clauses, min_chars=20))
    assert len(out) == 1
    assert out[0].endswith("Sí.")


def test_marker_tag_is_never_split():
    clauses = ["Eso me hace gracia, <laughter>de verdad", "que sí</laughter>."]
    out = list(safe_clauses(clauses, min_chars=1))
    assert out == ["Eso me hace gracia, <laughter>de verdad que sí</laughter>."]


def test_bracket_marker_alone_merges():
    clauses = ["[laughter]", "No me lo puedo creer, en serio te lo digo."]
    out = list(safe_clauses(clauses, min_chars=20))
    assert out == ["[laughter] No me lo puedo creer, en serio te lo digo."]


def test_whole_reply_shorter_than_minimum_is_still_emitted():
    # Known pre-existing limitation: a reply this short may still fail
    # upstream. The guard must not swallow it silently.
    assert list(safe_clauses(["Sí."], min_chars=40)) == ["Sí."]


def test_empty_and_blank_clauses_are_dropped():
    assert list(safe_clauses(["", "   ", "Hola, ¿qué tal has dormido?"], min_chars=5)) == [
        "Hola, ¿qué tal has dormido?"
    ]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest ../plugins/samantha_voice/tests/test_chunking.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'plugins'`

- [ ] **Step 3: Implement the guard**

```python
# plugins/samantha_voice/chunking.py
"""Text safety rules between Hermes' sentence chunker and CosyVoice.

Two upstream failures this prevents, both of which surface as HTTP 200
with an empty body (see backend/samantha/tts.py:213-217):

  1. `tts_text` much shorter than `prompt_text` crashes hifigan.
  2. A clause boundary inside an expression marker.

Markers are exactly `[laughter]`, `[breath]`, `[sigh]` and
`<laughter>...</laughter>` (backend/samantha/personality.py:58-61).
"""

from __future__ import annotations

from typing import Iterable, Iterator

_OPEN_TAG = "<laughter>"
_CLOSE_TAG = "</laughter>"


def _has_unclosed_tag(text: str) -> bool:
    """True when an opened <laughter> has not been closed yet."""
    return text.count(_OPEN_TAG) > text.count(_CLOSE_TAG)


def safe_clauses(clauses: Iterable[str], min_chars: int = 40) -> Iterator[str]:
    """Merge clauses until each is safe to synthesise, then yield.

    One-clause lookahead: a buffer that already satisfies the rules is
    held in `ready` and only released once a further clause arrives, so
    a short final clause always merges into the last emission instead
    of trailing on its own and crashing the vocoder.
    """
    ready: str | None = None  # satisfies the rules, awaiting release
    pending: str | None = None  # still accumulating

    for raw in clauses:
        clause = raw.strip()
        if not clause:
            continue

        pending = clause if pending is None else f"{pending} {clause}"

        if len(pending) < min_chars or _has_unclosed_tag(pending):
            continue

        if ready is not None:
            yield ready
        ready, pending = pending, None

    if pending is not None:
        ready = pending if ready is None else f"{ready} {pending}"
    if ready is not None:
        yield ready
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest ../plugins/samantha_voice/tests/test_chunking.py -v`
Expected: PASS, 7 tests.

If `test_tail_never_trails_short` fails, the lookahead is wrong: a
clause that satisfies `min_chars` is being emitted before the next
clause is read, so the tail has nothing to merge into. Restructure to
hold one emission back.

- [ ] **Step 5: Lint and commit**

```bash
cd backend && .venv/bin/ruff check ../plugins/samantha_voice && .venv/bin/ruff format ../plugins/samantha_voice
cd .. && git add plugins/samantha_voice/chunking.py plugins/samantha_voice/tests/test_chunking.py
git commit -m "feat(voice): clause guard so CosyVoice never gets text that crashes it"
```

---

### Task 3: The async→sync PCM bridge

`StreamingTTSProvider.stream()` is a synchronous `Iterator[bytes]`.
`samantha.tts.stream()` is an async generator. This task bridges them
on a worker thread with its own event loop, and — critically —
terminates cleanly when the consumer stops early, which is what happens
on every barge-in.

**Files:**
- Create: `plugins/samantha_voice/bridge.py`
- Create: `plugins/samantha_voice/tests/test_bridge.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `iter_sync(agen_factory: Callable[[], AsyncIterator[bytes]],
  queue_size: int = 8) -> Iterator[bytes]`. Task 4 calls only this.

- [ ] **Step 1: Write the failing tests**

```python
# plugins/samantha_voice/tests/test_bridge.py
import asyncio
import threading

import pytest

from plugins.samantha_voice.bridge import iter_sync


def _agen_factory(chunks, delay=0.0):
    async def agen():
        for c in chunks:
            if delay:
                await asyncio.sleep(delay)
            yield c
    return agen


def test_yields_every_chunk_in_order():
    out = list(iter_sync(_agen_factory([b"a", b"b", b"c"])))
    assert out == [b"a", b"b", b"c"]


def test_empty_stream_yields_nothing():
    assert list(iter_sync(_agen_factory([]))) == []


def test_exception_propagates_to_caller():
    async def agen():
        yield b"a"
        raise RuntimeError("cosyvoice exploded")

    with pytest.raises(RuntimeError, match="cosyvoice exploded"):
        list(iter_sync(lambda: agen()))


def test_early_stop_joins_the_worker_thread():
    # Barge-in: the consumer stops after one chunk. No thread may leak.
    before = threading.active_count()
    it = iter_sync(_agen_factory([b"a"] * 100, delay=0.001))
    assert next(it) == b"a"
    it.close()
    deadline = threading.active_count()
    assert deadline <= before + 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest ../plugins/samantha_voice/tests/test_bridge.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'plugins.samantha_voice.bridge'`

- [ ] **Step 3: Implement the bridge**

```python
# plugins/samantha_voice/bridge.py
"""Run an async byte generator on a worker loop and yield synchronously.

Hermes' StreamingTTSProvider.stream() is a sync Iterator[bytes]; our
CosyVoice client is async. This must never touch the gateway's event
loop, and must shut the worker down when the consumer stops early —
which is what a barge-in looks like from here.
"""

from __future__ import annotations

import asyncio
import queue
import threading
from typing import AsyncIterator, Callable, Iterator

_SENTINEL = object()


def iter_sync(
    agen_factory: Callable[[], AsyncIterator[bytes]],
    queue_size: int = 8,
) -> Iterator[bytes]:
    """Yield the bytes produced by `agen_factory()` on a worker thread.

    The bounded queue applies backpressure so synthesis does not race
    ahead of playback. Exceptions raised inside the generator are
    re-raised in the consumer's thread.
    """
    out: queue.Queue = queue.Queue(maxsize=queue_size)
    stop = threading.Event()

    def runner() -> None:
        async def pump() -> None:
            agen = agen_factory()
            async for chunk in agen:
                if stop.is_set():
                    break
                # Block until the consumer drains, but wake up to check
                # `stop` so an abandoned generator cannot pin the thread.
                while True:
                    if stop.is_set():
                        return
                    try:
                        out.put(chunk, timeout=0.1)
                        break
                    except queue.Full:
                        continue

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(pump())
        except BaseException as exc:  # surfaced to the consumer below
            out.put(exc)
        finally:
            try:
                loop.close()
            finally:
                out.put(_SENTINEL)

    thread = threading.Thread(target=runner, name="samantha-tts", daemon=True)
    thread.start()

    try:
        while True:
            item = out.get()
            if item is _SENTINEL:
                return
            if isinstance(item, BaseException):
                raise item
            yield item
    finally:
        stop.set()
        thread.join(timeout=2.0)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest ../plugins/samantha_voice/tests/test_bridge.py -v`
Expected: PASS, 4 tests.

- [ ] **Step 5: Run the whole suite to check nothing regressed**

Run: `cd backend && .venv/bin/python -m pytest -q`
Expected: PASS. Record the count; it is the new baseline.

- [ ] **Step 6: Lint and commit**

```bash
cd backend && .venv/bin/ruff check ../plugins/samantha_voice && .venv/bin/ruff format ../plugins/samantha_voice
cd .. && git add plugins/samantha_voice/bridge.py plugins/samantha_voice/tests/test_bridge.py
git commit -m "feat(voice): async-to-sync PCM bridge that shuts down on early stop"
```

---

### Task 4: The provider and its manifest

**Files:**
- Create: `plugins/samantha_voice/provider.py`
- Create: `plugins/samantha_voice/__init__.py`
- Create: `plugins/samantha_voice/plugin.yaml`
- Create: `plugins/samantha_voice/tests/test_provider.py`

**Interfaces:**
- Consumes: `safe_clauses(clauses, min_chars)` from Task 2;
  `iter_sync(agen_factory, queue_size)` from Task 3;
  `samantha.tts.stream(text)` yielding `(bytes, str)` tuples,
  `samantha.tts.is_available()`, `samantha.tts.OUTPUT_SAMPLE_RATE`.
- Produces: `CosyVoiceStreamingProvider`, registered under the name
  `cosyvoice`. Plan 3 (`samantha-kiosk`) reads its
  `bytes_yielded_per_clause` accounting to implement the trim rule in
  spec §6.

- [ ] **Step 1: Write the failing tests**

```python
# plugins/samantha_voice/tests/test_provider.py
import pytest

from plugins.samantha_voice import provider as prov


class _FakeTTS:
    OUTPUT_SAMPLE_RATE = 24000

    def __init__(self, available=True, chunks=(b"\x00\x01" * 100,)):
        self._available = available
        self._chunks = chunks
        self.calls: list[str] = []

    def is_available(self):
        return self._available

    async def stream(self, text):
        self.calls.append(text)
        for c in self._chunks:
            yield c, "cosyvoice"


def test_declares_the_format_cosyvoice_actually_emits():
    p = prov.CosyVoiceStreamingProvider()
    assert p.sample_rate == 24000
    assert p.channels == 1
    assert p.sample_width == 2


def test_available_follows_the_tts_module(monkeypatch):
    monkeypatch.setattr(prov, "tts", _FakeTTS(available=False))
    assert prov.CosyVoiceStreamingProvider.available() is False
    monkeypatch.setattr(prov, "tts", _FakeTTS(available=True))
    assert prov.CosyVoiceStreamingProvider.available() is True


def test_stream_yields_pcm_bytes_not_tuples(monkeypatch):
    fake = _FakeTTS(chunks=(b"aa", b"bb"))
    monkeypatch.setattr(prov, "tts", fake)
    out = list(prov.CosyVoiceStreamingProvider().stream("Hola, ¿qué tal estás hoy?"))
    assert out == [b"aa", b"bb"]


def test_short_text_is_not_sent_raw(monkeypatch):
    # A single tiny clause must still reach CosyVoice as one call, not
    # be split further. The guard's job is merging, never splitting.
    fake = _FakeTTS()
    monkeypatch.setattr(prov, "tts", fake)
    list(prov.CosyVoiceStreamingProvider().stream("Sí."))
    assert fake.calls == ["Sí."]


def test_empty_text_makes_no_call(monkeypatch):
    fake = _FakeTTS()
    monkeypatch.setattr(prov, "tts", fake)
    assert list(prov.CosyVoiceStreamingProvider().stream("   ")) == []
    assert fake.calls == []


def test_records_bytes_yielded_per_clause(monkeypatch):
    # Plan 3 needs this to trim an interrupted reply to what was heard.
    monkeypatch.setattr(prov, "tts", _FakeTTS(chunks=(b"a" * 10,)))
    p = prov.CosyVoiceStreamingProvider()
    list(p.stream("Una frase lo bastante larga como para pasar el guardia."))
    assert p.bytes_yielded_per_clause == [
        ("Una frase lo bastante larga como para pasar el guardia.", 10)
    ]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest ../plugins/samantha_voice/tests/test_provider.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'plugins.samantha_voice.provider'`

- [ ] **Step 3: Implement the provider**

Import the Hermes base class defensively so the tests above run on a
machine without Hermes installed.

```python
# plugins/samantha_voice/provider.py
"""CosyVoice as a Hermes StreamingTTSProvider.

Yields raw int16 little-endian mono PCM at 24 kHz — the format
CosyVoice already emits, so nothing is resampled.
"""

from __future__ import annotations

from typing import Iterator

from loguru import logger

from samantha import tts

from .bridge import iter_sync
from .chunking import safe_clauses

try:  # Hermes is absent on dev machines that only run the unit tests.
    from tools.tts_streaming import StreamingTTSProvider, register
except ImportError:  # pragma: no cover - exercised only without Hermes
    StreamingTTSProvider = object

    def register(_name):
        return lambda cls: cls


MIN_CLAUSE_CHARS = 40


class CosyVoiceStreamingProvider(StreamingTTSProvider):
    sample_rate: int = tts.OUTPUT_SAMPLE_RATE
    channels: int = 1
    sample_width: int = 2

    def __init__(self) -> None:
        # (clause_text, pcm_bytes_yielded) in emission order. Plan 3
        # turns this into milliseconds to trim an interrupted reply.
        self.bytes_yielded_per_clause: list[tuple[str, int]] = []

    @staticmethod
    def available() -> bool:
        return tts.is_available()

    def stream(self, text: str) -> Iterator[bytes]:
        for clause in safe_clauses([text], min_chars=MIN_CLAUSE_CHARS):
            emitted = 0
            try:
                for chunk in iter_sync(lambda c=clause: _pcm_only(c)):
                    emitted += len(chunk)
                    yield chunk
            except RuntimeError as exc:
                # tts.py raises this when CosyVoice returns 200 with no
                # audio. Losing one clause beats losing the whole reply.
                logger.warning(f"samantha-voice: clause failed, skipping — {exc}")
            finally:
                self.bytes_yielded_per_clause.append((clause, emitted))


async def _pcm_only(clause: str):
    """Drop tts.stream()'s backend label; the provider only wants bytes."""
    async for chunk, _backend in tts.stream(clause):
        yield chunk


CosyVoiceStreamingProvider = register("cosyvoice")(CosyVoiceStreamingProvider)
```

- [ ] **Step 4: Write the entry point**

```python
# plugins/samantha_voice/__init__.py
"""samantha-voice — CosyVoice streaming TTS for Hermes."""

from .provider import CosyVoiceStreamingProvider

__all__ = ["CosyVoiceStreamingProvider"]


def register(ctx):
    """Importing .provider performs the @register('cosyvoice') side effect."""
    del ctx
    return CosyVoiceStreamingProvider
```

- [ ] **Step 5: Write the manifest**

Field names follow `plugins/platforms/irc/plugin.yaml` upstream. If
Task 1's contract capture shows different required fields for a TTS
provider, match what it recorded and note the difference in the commit
message.

```yaml
# plugins/samantha_voice/plugin.yaml
name: samantha-voice
label: Samantha (CosyVoice)
kind: standalone
version: 1.0.0
description: >
  Streaming TTS provider for Samantha's cloned voice. Synthesises via
  CosyVoice 3 zero-shot on the 4090, emitting 24 kHz mono int16 PCM
  clause by clause. No audio leaves the house.
author: Horelvis Castillo
optional_env:
  - name: TTS_COSYVOICE_URL
    description: "CosyVoice 3 server base URL (default http://192.168.100.58:8093)"
    prompt: "CosyVoice URL"
    password: false
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest ../plugins/samantha_voice/tests/ -v`
Expected: PASS, 17 tests across the three files.

- [ ] **Step 7: Lint and commit**

```bash
cd backend && .venv/bin/ruff check ../plugins/samantha_voice && .venv/bin/ruff format ../plugins/samantha_voice
cd .. && git add plugins/samantha_voice
git commit -m "feat(voice): register CosyVoice as a Hermes streaming TTS provider"
```

---

### Task 5: Hear her through Hermes

The acceptance test for this plan, and the moment the riskiest
assumption in the whole migration is confirmed or killed. Manual by
necessity — the deliverable is a voice.

**Files:**
- Modify: `plugins/samantha_voice/provider.py` (only if tuning is
  needed — see Step 4)
- Modify: `docs/running-real-mode.md`

**Interfaces:**
- Consumes: everything above.
- Produces: a documented, working `hermes` voice configuration.

- [ ] **Step 1: Check CosyVoice is reachable**

```bash
curl -sS -o /dev/null -w '%{http_code}\n' http://192.168.100.58:8093/ --max-time 5
```

Expected: any HTTP response. A hang or connection refused means the
container is down on the 4090 — start it there before continuing;
nothing below can work without it.

- [ ] **Step 2: Install the plugin and select it**

```bash
ln -sfn "$(pwd)/plugins/samantha_voice" ~/.hermes/plugins/samantha_voice
hermes plugins
```

Expected: `samantha-voice` appears in the listing.

Then set the provider in `~/.hermes/config.yaml`:

```yaml
tts:
  provider: "cosyvoice"
  streaming:
    provider: "cosyvoice"
```

- [ ] **Step 3: Speak one long sentence**

```bash
hermes
```

Type: `Cuéntame en dos frases qué te parece el otoño.`

Expected: her voice, in Spanish, starting before the reply has finished
generating. Listen for three specific failures:
- silence, then an error about 200-with-no-audio → the clause guard's
  `MIN_CLAUSE_CHARS` is too low. Go to Step 4.
- audible seams or clipped syllables between clauses → chunk boundaries
  are landing badly; raise `MIN_CLAUSE_CHARS`.
- a wrong voice → `tts.provider` is not resolving to `cosyvoice`;
  re-check the config block, not the code.

- [ ] **Step 4: Tune the minimum clause length**

Compare against the actual reference transcript, since the crash
condition is relative to it:

```bash
wc -m ~/.samantha/voices/ref/samantha.txt
```

Set `MIN_CLAUSE_CHARS` in `provider.py` to at least half that count,
re-run Step 3, and repeat until no clause fails. Record the final value
and the transcript length together in the commit message — the number
is meaningless without it.

- [ ] **Step 5: Test a deliberately short reply**

Type: `Contéstame solo "sí".`

Expected: either her saying it, or exactly one warning line in the log
and the turn continuing. A crash, a hang, or a silent turn is a
failure — the guard must degrade, not break.

- [ ] **Step 6: Test an interruption**

Ask for something long, and press `Ctrl+C` while she is speaking.

Expected: playback stops promptly and the process stays healthy. Then
confirm no thread leaked:

```bash
hermes  # start a fresh session in the same shell and repeat twice
```

Expected: no growth in memory or thread count across three
interrupted turns. A leak here means `iter_sync`'s `finally` is not
being reached.

- [ ] **Step 7: Document the setup**

Add a "Hermes voice" section to `docs/running-real-mode.md` covering
the install from Task 1, the symlink, the config block, the tuned
`MIN_CLAUSE_CHARS` with its rationale, and the three failure signatures
from Step 3 with what each one means.

- [ ] **Step 8: Commit**

```bash
git add plugins/samantha_voice/provider.py docs/running-real-mode.md
git commit -m "feat(voice): tune clause minimum against the reference transcript, document setup"
```

---

## Done when

`hermes` in a terminal answers in Samantha's voice, in Spanish,
streaming, with CosyVoice on the 4090 and nothing leaving the house —
and an interruption stops her cleanly without leaking a thread.

At that point the riskiest piece of
`2026-08-22-samantha-on-hermes-design.md` is proven, and plan 2
(`samantha-memory`) can be written against the contracts Task 1
captured.
