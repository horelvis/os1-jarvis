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


def test_websocket_round_trip(tmp_path, monkeypatch):
    # Since Task 4, _handle_chat no longer answers itself — it dispatches a
    # MessageEvent to handle_message(), which is Hermes' job in production.
    # Stand in for Hermes here to prove the wire still carries a reply back
    # to the browser once something calls send().
    async def fake_handle_message(self, event):
        await self.send(event.source.chat_id, f"echo: {event.text}")

    monkeypatch.setattr(
        KioskAdapter, "handle_message", fake_handle_message, raising=False
    )

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


def test_chat_becomes_a_message_event(tmp_path, monkeypatch):
    # The adapter must hand Hermes a TEXT MessageEvent, not answer itself.
    import Hermes.plugins.samantha_kiosk.adapter as mod

    seen = []

    async def fake_handle_message(self, event):
        seen.append(event)

    monkeypatch.setattr(
        mod.KioskAdapter, "handle_message", fake_handle_message, raising=False
    )

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


def test_environment_variable_overrides_the_config_dict(tmp_path, monkeypatch):
    # SAMANTHA_KIOSK_PORT / SAMANTHA_KIOSK_STATIC_ROOT (declared in Task 4's
    # manifest, exported by Task 5's manual test) must win over whatever the
    # config dict says — otherwise the documented env vars are ignored and
    # the kiosk silently serves the wrong directory on the wrong port.
    env_root = tmp_path / "env-root"
    env_root.mkdir()
    monkeypatch.setenv("SAMANTHA_KIOSK_PORT", "0")
    monkeypatch.setenv("SAMANTHA_KIOSK_STATIC_ROOT", str(env_root))

    a = KioskAdapter({"port": 9999, "static_root": str(tmp_path / "config-root")})

    assert a.port == 0
    assert a.static_root == env_root
