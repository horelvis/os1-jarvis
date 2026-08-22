# samantha-kiosk — the platform adapter, text only

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Open the OS1 interface in a browser, type a sentence, and have
Samantha answer — served by, and routed through, Hermes. No audio.

**Architecture:** A `kind: platform` Hermes plugin whose `connect()` starts
an aiohttp server inside the gateway process. It serves `frontend/dist` and
hosts a WebSocket that speaks **the protocol the existing frontend already
uses**, so no frontend change is needed. Text arrives as
`MessageEvent(MessageType.TEXT)`; Hermes' reply comes back through the
adapter's `send()`.

**Tech Stack:** Python 3.12, aiohttp, the Hermes plugin API
(`ctx.register_platform`), pytest.

**Spec:** `docs/superpowers/specs/2026-08-22-samantha-on-hermes-design.md`
§5 (read §2 for the topology and §1 for why).

## Global Constraints

- This is **plan 3a of three**. 3b adds audio in both directions,
  interruption and the §6 trim. 3c does onboarding, the frontend cleanup and
  the deletion of the FastAPI app. Each is written after the previous lands.
- **Do not change the WebSocket protocol.** `frontend/src/core/types.ts:37-45`
  defines it and the adapter must match it exactly. Inventing the design's
  §5.1 protocol here would force a frontend rewrite into a task whose whole
  point is proving the plumbing.
- **`aiohttp` is NOT in Hermes' virtualenv.** Hermes' own listening adapter
  treats it as optional and guards on it. Declare it in `python_dependencies`
  and install it explicitly — Hermes never installs declared dependencies.
- Comments and identifiers in English; every user-facing string in Spanish
  and in her voice (`backend/samantha/personality.py`) — no "ERROR:", nothing
  robotic (CLAUDE.md §2.9).
- `backend/.venv/bin/ruff check` and `ruff format --check` must pass over
  `Hermes/plugins/samantha_kiosk`, run from the repo root.
- Tests run from the repo root: `backend/.venv/bin/python -m pytest ... -v`.
- Single user, single kiosk. A second WebSocket connection replaces the first.
- The existing FastAPI backend keeps running and is not touched by this plan.
  There is a working Samantha throughout.
- Hermes source to read: `~/hermes-src` (v0.20.5). Never guess a signature —
  this branch has been bitten three times by guessed signatures. The captured
  contracts are in `docs/superpowers/specs/hermes-contracts-v0.20.5.md`.

---

## File Structure

A new sibling package to `samantha_voice`, following its layout:

- `Hermes/plugins/samantha_kiosk/plugin.yaml` — manifest, `kind: platform`.
- `Hermes/plugins/samantha_kiosk/__init__.py` — `register(ctx)` calling
  `ctx.register_platform(...)`.
- `Hermes/plugins/samantha_kiosk/adapter.py` — the `BasePlatformAdapter`
  subclass. Owns the aiohttp app, the runner and the single WebSocket.
- `Hermes/plugins/samantha_kiosk/protocol.py` — encode/decode of the wire
  messages. Pure functions, no I/O, no Hermes imports, so its tests run
  anywhere. This is where the frontend contract is pinned.
- `Hermes/plugins/samantha_kiosk/tests/test_protocol.py`
- `Hermes/plugins/samantha_kiosk/tests/test_adapter.py`

Split rationale: `protocol.py` is the only part with rules worth testing
independently, and keeping it Hermes-free means the suite runs on a machine
with no Hermes — the same property that made `samantha_voice`'s tests useful.
`adapter.py` is I/O and glue.

---

### Task 1: The wire protocol

The frontend already speaks this. This task pins it in Python so a later
change to either side breaks a test rather than the kiosk.

**Files:**
- Create: `Hermes/plugins/samantha_kiosk/protocol.py`
- Create: `Hermes/plugins/samantha_kiosk/tests/test_protocol.py`
- Create: `Hermes/plugins/samantha_kiosk/__init__.py` (empty for now; Task 4
  fills it), `Hermes/plugins/samantha_kiosk/tests/__init__.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `decode_client(raw: str) -> dict`, raising `ProtocolError` on
  anything malformed; and the encoders `token(text: str) -> str`,
  `done(thinking_ms: int) -> str`, `error(message: str) -> str`. Task 3 and
  Task 4 call only these.

- [ ] **Step 1: Create the package layout and write the failing tests**

```bash
mkdir -p Hermes/plugins/samantha_kiosk/tests
touch Hermes/plugins/samantha_kiosk/__init__.py \
      Hermes/plugins/samantha_kiosk/tests/__init__.py
```

```python
# Hermes/plugins/samantha_kiosk/tests/test_protocol.py
import json

import pytest

from Hermes.plugins.samantha_kiosk.protocol import (
    ProtocolError,
    decode_client,
    done,
    error,
    token,
)


def test_decodes_a_chat_message():
    raw = '{"type": "chat", "message": "hola", "user_id": "primary"}'
    assert decode_client(raw) == {
        "type": "chat",
        "message": "hola",
        "user_id": "primary",
    }


def test_rejects_unknown_type():
    with pytest.raises(ProtocolError):
        decode_client('{"type": "shutdown"}')


def test_rejects_malformed_json():
    with pytest.raises(ProtocolError):
        decode_client("not json at all")


def test_rejects_chat_without_a_message():
    with pytest.raises(ProtocolError):
        decode_client('{"type": "chat", "user_id": "primary"}')


def test_rejects_a_blank_message():
    # An empty turn would reach the model as an empty prompt.
    with pytest.raises(ProtocolError):
        decode_client('{"type": "chat", "message": "   ", "user_id": "x"}')


def test_listen_needs_no_fields():
    assert decode_client('{"type": "listen"}') == {"type": "listen"}


def test_encoders_match_the_frontend_contract():
    # frontend/src/core/types.ts:41-45 — field names are load-bearing.
    assert json.loads(token("hola")) == {"type": "token", "token": "hola"}
    assert json.loads(done(1200)) == {"type": "done", "thinking_ms": 1200}
    assert json.loads(error("se me ha ido el hilo")) == {
        "type": "error",
        "error": "se me ha ido el hilo",
    }
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (from the repo root):
`backend/.venv/bin/python -m pytest Hermes/plugins/samantha_kiosk/tests/test_protocol.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named
'Hermes.plugins.samantha_kiosk.protocol'`

- [ ] **Step 3: Implement the protocol**

```python
# Hermes/plugins/samantha_kiosk/protocol.py
"""The kiosk WebSocket wire format.

This is NOT a new protocol. It is the one the OS1 frontend already speaks,
defined in `frontend/src/core/types.ts:37-45`, pinned here so that a change
on either side fails a test instead of the kiosk. Field names are part of
the contract: the frontend reads `msg.token`, `msg.thinking_ms`, `msg.error`.

Audio frames are not here. They arrive in plan 3b as binary WebSocket
frames alongside these text ones, and do not change this format.
"""

from __future__ import annotations

import json
from typing import Any, Dict

_CLIENT_TYPES = {"chat", "listen"}


class ProtocolError(ValueError):
    """Raised for anything the kiosk should not have sent."""


def decode_client(raw: str) -> Dict[str, Any]:
    """Parse and validate one client message. Raises ProtocolError."""
    try:
        msg = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise ProtocolError(f"not JSON: {exc}") from exc

    if not isinstance(msg, dict):
        raise ProtocolError(f"expected an object, got {type(msg).__name__}")

    kind = msg.get("type")
    if kind not in _CLIENT_TYPES:
        raise ProtocolError(f"unknown type: {kind!r}")

    if kind == "chat":
        message = msg.get("message")
        if not isinstance(message, str) or not message.strip():
            # An empty turn would reach the model as an empty prompt.
            raise ProtocolError("chat needs a non-blank message")

    return msg


def token(text: str) -> str:
    return json.dumps({"type": "token", "token": text})


def done(thinking_ms: int) -> str:
    return json.dumps({"type": "done", "thinking_ms": thinking_ms})


def error(message: str) -> str:
    """`message` is shown to the user, so it is Spanish and in her voice."""
    return json.dumps({"type": "error", "error": message})
```

- [ ] **Step 4: Run the tests to verify they pass**

Run (from the repo root):
`backend/.venv/bin/python -m pytest Hermes/plugins/samantha_kiosk/tests/test_protocol.py -v`
Expected: PASS, 7 tests.

- [ ] **Step 5: Lint and commit**

```bash
backend/.venv/bin/ruff check Hermes/plugins/samantha_kiosk
backend/.venv/bin/ruff format Hermes/plugins/samantha_kiosk
git add Hermes/plugins/samantha_kiosk
git commit -m "feat(kiosk): pin the frontend's WebSocket protocol in Python"
```

---

### Task 2: Install aiohttp into Hermes' environment

No production code. This exists as its own task because the last plugin lost
half a day to a dependency that was declared but not installed, and because
the answer needs recording where the next person will find it.

**Files:**
- Modify: `docs/running-real-mode.md`

**Interfaces:**
- Consumes: nothing.
- Produces: a working `import aiohttp` inside Hermes' venv, and the recorded
  command.

- [ ] **Step 1: Confirm it is missing**

```bash
~/hermes-src/.venv/bin/python -c "import aiohttp" ; echo "exit=$?"
```

Expected: `ModuleNotFoundError` and a non-zero exit. If it imports, someone
installed it already — record that and skip to Step 3.

- [ ] **Step 2: Install it**

```bash
cd ~/hermes-src && uv pip install --python .venv/bin/python aiohttp
~/hermes-src/.venv/bin/python -c "import aiohttp; print(aiohttp.__version__)"
```

Expected: a version prints. Note it — Task 3's manifest pins a floor against
it.

- [ ] **Step 3: Record it where the next person looks**

Add to `docs/running-real-mode.md`, in the Hermes section, a line saying that
plugin dependencies must be installed into `~/hermes-src/.venv` explicitly
because Hermes only warns about `python_dependencies` and never acts on them,
with the `uv pip install --python .venv/bin/python` form and both packages
needed so far (`loguru`, `aiohttp`).

- [ ] **Step 4: Commit**

```bash
git add docs/running-real-mode.md
git commit -m "docs(hermes): record that plugin deps install into Hermes' venv by hand"
```

---

### Task 3: The adapter — serve the UI and hold one socket

The adapter with no agent behind it yet: it starts, serves `frontend/dist`,
accepts one WebSocket, and echoes back a fixed reply. Proving the server
lifecycle separately from the Hermes plumbing keeps the next task's failures
unambiguous.

**Files:**
- Create: `Hermes/plugins/samantha_kiosk/adapter.py`
- Create: `Hermes/plugins/samantha_kiosk/tests/test_adapter.py`

**Interfaces:**
- Consumes: `decode_client`, `token`, `done`, `error`, `ProtocolError` from
  Task 1.
- Produces: `KioskAdapter`, with `connect()`, `disconnect()`, `send()`, and
  the attributes `port: int`, `static_root: pathlib.Path`. Task 4 registers
  this class.

- [ ] **Step 1: Read the real base class before writing anything**

```bash
grep -n "class BasePlatformAdapter" -A 60 ~/hermes-src/gateway/platforms/base.py | head -80
sed -n '7436,7560p' ~/hermes-src/gateway/platforms/api_server.py
```

`api_server.py` is the only in-tree adapter that *listens* rather than
dialling out, so it is the template for the server lifecycle —
`web.Application`, `web.AppRunner`, `web.TCPSite`. `irc` is the template for
registration only. Note in your report anything the base class requires that
this plan does not mention.

- [ ] **Step 2: Write the failing tests**

```python
# Hermes/plugins/samantha_kiosk/tests/test_adapter.py
import asyncio
import json
from pathlib import Path

import pytest

aiohttp = pytest.importorskip("aiohttp")

from Hermes.plugins.samantha_kiosk.adapter import KioskAdapter  # noqa: E402


def _cfg(tmp_path: Path) -> dict:
    # Mirrors a real Vite build: index.html plus an assets/ directory.
    (tmp_path / "index.html").write_text("<html>os1</html>", encoding="utf-8")
    (tmp_path / "assets").mkdir(exist_ok=True)
    (tmp_path / "assets" / "app.js").write_text("// os1", encoding="utf-8")
    return {"port": 0, "static_root": str(tmp_path)}


def test_serves_index_html(tmp_path):
    async def go():
        a = KioskAdapter(_cfg(tmp_path))
        assert await a.connect() is True
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(f"http://127.0.0.1:{a.port}/") as r:
                    assert r.status == 200
                    assert "os1" in await r.text()
        finally:
            await a.disconnect()

    asyncio.run(go())


def test_serves_the_assets_directory(tmp_path):
    # index.html references /assets/... — if this 404s the screen is blank.
    async def go():
        a = KioskAdapter(_cfg(tmp_path))
        await a.connect()
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(f"http://127.0.0.1:{a.port}/assets/app.js") as r:
                    assert r.status == 200
        finally:
            await a.disconnect()

    asyncio.run(go())


def test_websocket_round_trip(tmp_path):
    async def go():
        a = KioskAdapter(_cfg(tmp_path))
        await a.connect()
        try:
            async with aiohttp.ClientSession() as s:
                async with s.ws_connect(f"http://127.0.0.1:{a.port}/ws") as ws:
                    await ws.send_str(
                        json.dumps(
                            {"type": "chat", "message": "hola", "user_id": "primary"}
                        )
                    )
                    got = json.loads((await ws.receive(timeout=5)).data)
                    assert got["type"] == "token"
        finally:
            await a.disconnect()

    asyncio.run(go())


def test_malformed_message_gets_an_error_in_spanish_not_a_crash(tmp_path):
    async def go():
        a = KioskAdapter(_cfg(tmp_path))
        await a.connect()
        try:
            async with aiohttp.ClientSession() as s:
                async with s.ws_connect(f"http://127.0.0.1:{a.port}/ws") as ws:
                    await ws.send_str("no json")
                    got = json.loads((await ws.receive(timeout=5)).data)
                    assert got["type"] == "error"
                    assert got["error"]
                    # The socket must survive a bad frame.
                    assert not ws.closed
        finally:
            await a.disconnect()

    asyncio.run(go())


def test_second_connection_replaces_the_first(tmp_path):
    # One kiosk. A reconnect after a browser refresh must not leave two.
    async def go():
        a = KioskAdapter(_cfg(tmp_path))
        await a.connect()
        try:
            async with aiohttp.ClientSession() as s:
                ws1 = await s.ws_connect(f"http://127.0.0.1:{a.port}/ws")
                ws2 = await s.ws_connect(f"http://127.0.0.1:{a.port}/ws")
                msg = await ws1.receive(timeout=5)
                assert msg.type in (
                    aiohttp.WSMsgType.CLOSE,
                    aiohttp.WSMsgType.CLOSED,
                    aiohttp.WSMsgType.CLOSING,
                )
                assert not ws2.closed
                await ws2.close()
        finally:
            await a.disconnect()

    asyncio.run(go())


def test_disconnect_releases_the_port(tmp_path):
    async def go():
        a = KioskAdapter(_cfg(tmp_path))
        await a.connect()
        port = a.port
        await a.disconnect()
        # Binding the same port again must succeed.
        b = KioskAdapter({"port": port, "static_root": str(tmp_path)})
        assert await b.connect() is True
        await b.disconnect()

    asyncio.run(go())
```

- [ ] **Step 3: Run the tests to verify they fail**

Run (from the repo root):
`backend/.venv/bin/python -m pytest Hermes/plugins/samantha_kiosk/tests/test_adapter.py -v`
Expected: FAIL — no module `adapter`. (If aiohttp is missing from
`backend/.venv`, the tests skip instead; install it there too with
`backend/.venv/bin/python -m pip install aiohttp` and re-run. Task 2 covered
Hermes' venv; the test venv is separate.)

- [ ] **Step 4: Implement the adapter**

For this task, `_handle_chat` returns a fixed reply. Task 4 replaces its body
with the real dispatch, and that is the only line that changes.

Import `BasePlatformAdapter` defensively so the tests run without Hermes,
exactly as `samantha_voice/provider.py` does — read that file for the shape
before writing this one.

```python
# Hermes/plugins/samantha_kiosk/adapter.py
"""The OS1 kiosk as a Hermes platform adapter.

Unlike every other in-tree adapter except `api_server`, this one LISTENS: it
starts an aiohttp server inside the gateway process, serves the built OS1
frontend, and holds one WebSocket to it. There is exactly one kiosk, so a
second connection replaces the first rather than being refused — a browser
refresh must not lock the user out of their own house.

The wire format is the frontend's existing one; see protocol.py.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, Optional

from aiohttp import WSMsgType, web
from loguru import logger

from .protocol import ProtocolError, decode_client, done, error, token

try:
    from gateway.platforms.base import BasePlatformAdapter
except ImportError:  # pragma: no cover - only without Hermes installed
    class BasePlatformAdapter:  # type: ignore[no-redef]
        """Stand-in so these tests run on a machine with no Hermes."""

        def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
            self.config = config or {}


# Spanish, in her voice — this reaches the screen.
_BAD_FRAME = "No te he entendido. ¿Me lo dices otra vez?"


class KioskAdapter(BasePlatformAdapter):
    name = "samantha_kiosk"

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(config)
        cfg = config or {}
        self.static_root = Path(cfg.get("static_root", "frontend/dist")).expanduser()
        self._configured_port = int(cfg.get("port", 7777))
        self.port = self._configured_port
        self._runner: Optional[web.AppRunner] = None
        self._site: Optional[web.TCPSite] = None
        self._ws: Optional[web.WebSocketResponse] = None

    async def connect(self, *, is_reconnect: bool = False) -> bool:
        app = web.Application()
        app.router.add_get("/ws", self._ws_handler)
        # Vite's build emits index.html plus assets/, and index.html
        # references /assets/... — so three explicit routes, and no
        # catch-all static mount on "/" that would shadow /ws.
        app.router.add_static("/assets", str(self.static_root / "assets"))
        app.router.add_get("/", self._index)

        self._runner = web.AppRunner(app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, "127.0.0.1", self._configured_port)
        await self._site.start()
        self.port = self._actual_port()
        logger.info(f"samantha-kiosk: serving {self.static_root} on :{self.port}")
        return True

    def _actual_port(self) -> int:
        # port 0 means "any free port"; the tests rely on discovering it.
        sockets = getattr(self._site, "_server", None)
        if sockets is not None and sockets.sockets:
            return int(sockets.sockets[0].getsockname()[1])
        return self._configured_port

    async def _index(self, _request: web.Request) -> web.FileResponse:
        return web.FileResponse(self.static_root / "index.html")

    async def disconnect(self) -> None:
        if self._ws is not None and not self._ws.closed:
            await self._ws.close()
        self._ws = None
        if self._runner is not None:
            await self._runner.cleanup()
        self._runner = None
        self._site = None

    async def send(self, chat_id: str, content: str, **_kwargs: Any) -> None:
        """Hermes' reply, on its way to the screen."""
        del chat_id
        await self._push(token(content))
        await self._push(done(0))

    async def _push(self, payload: str) -> None:
        ws = self._ws
        if ws is None or ws.closed:
            logger.warning("samantha-kiosk: nothing connected, dropping a frame")
            return
        await ws.send_str(payload)

    async def _ws_handler(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)

        previous, self._ws = self._ws, ws
        if previous is not None and not previous.closed:
            # One kiosk. A refresh replaces, never queues.
            await previous.close()

        async for msg in ws:
            if msg.type is not WSMsgType.TEXT:
                continue
            try:
                decoded = decode_client(msg.data)
            except ProtocolError as exc:
                logger.warning(f"samantha-kiosk: bad frame — {exc}")
                await ws.send_str(error(_BAD_FRAME))
                continue
            if decoded["type"] == "chat":
                await self._handle_chat(decoded["message"], decoded["user_id"])

        if self._ws is ws:
            self._ws = None
        return ws

    async def _handle_chat(self, message: str, user_id: str) -> None:
        # Task 4 replaces this body with the real Hermes dispatch.
        del user_id
        await self.send("kiosk", f"He recibido: {message}")
```

- [ ] **Step 5: Run the tests to verify they pass**

Run (from the repo root):
`backend/.venv/bin/python -m pytest Hermes/plugins/samantha_kiosk/tests/ -v`
Expected: PASS, 13 tests.

If `test_second_connection_replaces_the_first` hangs rather than failing,
the close is happening while `_ws_handler`'s `async for` still owns the old
socket — close the previous one before reassigning `self._ws`, not after.

- [ ] **Step 6: Lint and commit**

```bash
backend/.venv/bin/ruff check Hermes/plugins/samantha_kiosk
backend/.venv/bin/ruff format Hermes/plugins/samantha_kiosk
git add Hermes/plugins/samantha_kiosk
git commit -m "feat(kiosk): adapter that serves the OS1 build and holds one socket"
```

---

### Task 4: Register it, and route text through Hermes

The task that makes it real: registration, and replacing the echo with a
`MessageEvent` so the answer comes from the model.

**Files:**
- Create: `Hermes/plugins/samantha_kiosk/plugin.yaml`
- Modify: `Hermes/plugins/samantha_kiosk/__init__.py`
- Modify: `Hermes/plugins/samantha_kiosk/adapter.py` (`_handle_chat` only)
- Modify: `Hermes/plugins/samantha_kiosk/tests/test_adapter.py`

**Interfaces:**
- Consumes: `KioskAdapter` from Task 3.
- Produces: a plugin Hermes loads and lists, registering the platform under
  the name `samantha_kiosk`.

- [ ] **Step 1: Read how inbound dispatch actually works**

```bash
grep -n "def build_source" -A 25 ~/hermes-src/gateway/platforms/base.py
grep -n "async def handle_message" -A 20 ~/hermes-src/gateway/platforms/base.py
sed -n '/def register(ctx)/,/^$/p' ~/hermes-src/plugins/platforms/irc/adapter.py
```

`docs/superpowers/specs/hermes-contracts-v0.20.5.md` Contract 3 has
`MessageEvent` and `MessageType` verbatim, and Contract 4 has
`register_platform`. Follow the source where the plan and the source
disagree, and say so in your report.

- [ ] **Step 2: Write the failing test**

```python
def test_chat_becomes_a_message_event(tmp_path, monkeypatch):
    # The adapter must hand Hermes a TEXT MessageEvent, not answer itself.
    import Hermes.plugins.samantha_kiosk.adapter as mod

    seen = []

    async def fake_handle_message(self, event):
        seen.append(event)

    monkeypatch.setattr(mod.KioskAdapter, "handle_message", fake_handle_message,
                        raising=False)

    async def go():
        a = mod.KioskAdapter(_cfg(tmp_path))
        await a.connect()
        try:
            await a._handle_chat("hola", "primary")
        finally:
            await a.disconnect()

    asyncio.run(go())
    assert len(seen) == 1
    assert seen[0].text == "hola"
    assert seen[0].message_type.value == "text"
```

- [ ] **Step 3: Run it to verify it fails**

Run: `backend/.venv/bin/python -m pytest Hermes/plugins/samantha_kiosk/tests/test_adapter.py::test_chat_becomes_a_message_event -v`
Expected: FAIL — `seen` is empty, because `_handle_chat` still echoes.

- [ ] **Step 4: Replace the echo with a real dispatch**

```python
    async def _handle_chat(self, message: str, user_id: str) -> None:
        source = self.build_source(
            chat_id="kiosk",
            chat_name="Kiosk",
            chat_type="dm",
            user_id=user_id,
            user_name=user_id,
        )
        event = MessageEvent(
            text=message,
            message_type=MessageType.TEXT,
            source=source,
            message_id=str(uuid.uuid4()),
        )
        await self.handle_message(event)
```

Add `import uuid` and, to the defensive import block, `MessageEvent` and
`MessageType` from `gateway.platforms.base` with test stand-ins alongside the
`BasePlatformAdapter` fallback.

- [ ] **Step 5: Write the manifest**

Field names follow `~/hermes-src/plugins/platforms/irc/plugin.yaml`. Use the
aiohttp version Task 2 recorded as the floor.

```yaml
# Hermes/plugins/samantha_kiosk/plugin.yaml
manifest_version: 2
api_version: 1
name: samantha-kiosk
label: Samantha (kiosk)
kind: platform
version: 1.0.0
description: >
  Serves the OS1 interface and holds the single WebSocket the kiosk talks
  over. Text only in this version; audio arrives in plan 3b.
author: Horelvis Castillo

# Declaration only — Hermes never installs these. See docs/running-real-mode.md.
python_dependencies:
  - aiohttp>=3.9

optional_env:
  - name: SAMANTHA_KIOSK_PORT
    description: "Puerto donde se sirve la interfaz (por defecto 7777)"
    prompt: "Puerto del kiosko"
    password: false
  - name: SAMANTHA_KIOSK_STATIC_ROOT
    description: "Ruta al frontend construido (por defecto frontend/dist)"
    prompt: "Ruta de frontend/dist"
    password: false
```

- [ ] **Step 6: Write the entry point**

```python
# Hermes/plugins/samantha_kiosk/__init__.py
"""samantha-kiosk — the OS1 interface as a Hermes platform."""

from .adapter import KioskAdapter

__all__ = ["KioskAdapter", "register"]


def register(ctx):
    ctx.register_platform(
        name="samantha_kiosk",
        label="Samantha (kiosk)",
        adapter_factory=lambda cfg: KioskAdapter(cfg),
        required_env=[],
        install_hint="uv pip install --python ~/hermes-src/.venv/bin/python aiohttp",
        max_message_length=600,
        emoji="🟠",
        pii_safe=True,
        platform_hint=(
            "Estás hablando en voz alta con la persona que vive aquí, a "
            "través de una pantalla sin teclado a mano. Frases cortas, "
            "nada de listas ni markdown."
        ),
    )
```

If `register_platform` rejects any of these arguments, follow the source and
record the difference — Contract 4 was captured from v0.20.5 and the
signature may have moved.

- [ ] **Step 7: Run every test**

Run (from the repo root):
`backend/.venv/bin/python -m pytest Hermes/plugins/samantha_kiosk/tests/ -v`
Expected: PASS, 14 tests.

- [ ] **Step 8: Confirm Hermes loads it**

```bash
ln -sfn "$(pwd)/Hermes/plugins/samantha_kiosk" ~/.hermes/plugins/samantha_kiosk
~/hermes-src/.venv/bin/hermes plugins list | grep -i samantha
~/hermes-src/.venv/bin/hermes plugins doctor 2>&1 | tail -20
```

Expected: `samantha-kiosk` listed as enabled, and `doctor` reporting no load
error. A plugin listed as enabled proves only that the manifest parsed —
`doctor` is what proves the module imported. Both are required.

- [ ] **Step 9: Commit**

```bash
git add Hermes/plugins/samantha_kiosk
git commit -m "feat(kiosk): register the platform and route text through Hermes"
```

---

### Task 5: Type to her through the kiosk

The acceptance test. Manual, because the deliverable is a working screen.

**Files:**
- Modify: `docs/running-real-mode.md`

**Interfaces:**
- Consumes: everything above.
- Produces: a documented way to run the kiosk.

- [ ] **Step 1: Build the frontend**

```bash
cd frontend && pnpm install && pnpm build && cd ..
ls frontend/dist/index.html
```

Never `npm` here — the project uses pnpm deliberately (CLAUDE.md §5).

- [ ] **Step 2: Point the plugin at the build and start the gateway**

```bash
export SAMANTHA_KIOSK_STATIC_ROOT="$(pwd)/frontend/dist"
export SAMANTHA_KIOSK_PORT=7777
export PYTHONPATH="$(pwd)/backend:$(pwd)"
~/hermes-src/.venv/bin/hermes gateway
```

Expected in the log: `samantha-kiosk: serving … on :7777`. If the port is
taken, the existing FastAPI backend is still running on it — stop it, or use
a different port; this plan does not remove it.

- [ ] **Step 3: Open it and type**

Open `http://localhost:7777/` in a browser. Type: `Hola, ¿qué tal estás?`

Expected: her reply appears in the interface. Three failure signatures and
what each means:
- the interface loads but nothing comes back → the WebSocket connected and
  the dispatch did not; check the gateway log for `handle_message`.
- a blank page → `SAMANTHA_KIOSK_STATIC_ROOT` is wrong, or `pnpm build` was
  not run.
- her reply arrives all at once rather than streaming → expected in this
  plan. `send()` delivers the finished reply; token streaming is plan 3b.

- [ ] **Step 4: Confirm a refresh does not lock you out**

Refresh the browser twice, then type again. Expected: it still answers. If it
does not, the replaced-socket logic from Task 3 is wrong in the real path.

- [ ] **Step 5: Document it**

Add a "Kiosk" section to `docs/running-real-mode.md`: the build step, both
environment variables, the start command, and the three failure signatures
above with what each means.

- [ ] **Step 6: Commit**

```bash
git add docs/running-real-mode.md
git commit -m "docs(kiosk): how to run the OS1 interface through the gateway"
```

---

## Done when

`http://localhost:7777/` shows the OS1 interface, served by Hermes, and
typing a sentence gets an answer from the model — with the existing FastAPI
backend untouched and still working.

At that point the plumbing is proven and plan 3b can add audio to a transport
that already exists, rather than building both at once.
