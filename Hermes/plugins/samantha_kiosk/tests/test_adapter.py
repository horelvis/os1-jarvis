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


def test_concurrent_reconnects_dont_clobber_the_newest_socket(tmp_path, monkeypatch):
    # Task 3 review: `previous = self._ws; await previous.close(); self._ws = ws`
    # is not atomic. aiohttp's WebSocketResponse.close() marks `.closed` True
    # synchronously before it awaits anything (see web_ws.py: `if self._closed:
    # return False` / `self._set_closed()`, both ahead of the first await) —
    # so a handler that reads `previous` while an older close() is still in
    # flight sees `.closed` already True, skips its own close() entirely, and
    # writes `self._ws` immediately. The earlier handler then resumes and
    # overwrites `self._ws` unconditionally with ITS OWN (now-stale) socket,
    # clobbering the newer one that never got closed — just untracked.
    #
    # Reproduce deterministically by slowing close() down (so a third
    # connection reliably lands its swap while the second one's close is
    # still in flight) and by recording server-side socket creation order (so
    # "the newest socket" is verifiable by identity, not just by `.closed`ness
    # — both the clobbering (wrong) socket and the orphaned (right) one are
    # equally un-closed, so an open/closed check alone can't tell them apart).
    created = []
    real_init = aiohttp.web.WebSocketResponse.__init__

    def tracking_init(self, *args, **kwargs):
        real_init(self, *args, **kwargs)
        created.append(self)

    async def slow_close(self, *args, **kwargs):
        if self._closed:
            return False
        self._set_closed()
        await asyncio.sleep(0.05)
        return True

    monkeypatch.setattr(aiohttp.web.WebSocketResponse, "__init__", tracking_init)
    monkeypatch.setattr(aiohttp.web.WebSocketResponse, "close", slow_close)

    async def go():
        a = KioskAdapter(_cfg(tmp_path))
        await a.connect()
        try:
            async with aiohttp.ClientSession() as s:
                ws1 = await s.ws_connect(f"http://127.0.0.1:{a.port}/ws")
                # ws2's handler reads self._ws (= ws1's server peer) and
                # starts closing it; slow_close holds that "in flight" for
                # 50ms after marking it closed.
                ws2 = await s.ws_connect(f"http://127.0.0.1:{a.port}/ws")
                await asyncio.sleep(0.01)
                # ws3 arrives while ws2's close of ws1 is still sleeping.
                ws3 = await s.ws_connect(f"http://127.0.0.1:{a.port}/ws")

                # Let ws2's delayed close() finish (and, if the race is
                # present, clobber ws3's swap) before asserting.
                await asyncio.sleep(0.1)

                assert len(created) == 3
                assert a._ws is created[2], (
                    "self._ws must track the newest connection (ws3), not "
                    "an earlier one left over from the race"
                )
                assert not a._ws.closed

                await ws1.close()
                await ws2.close()
                await ws3.close()
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


def test_port_conflict_is_a_fatal_non_retryable_error(tmp_path):
    # A taken port is a configuration error, not a transient blip — another
    # process holds it for its lifetime. connect() must say so
    # non-retryably instead of a bare `False`, which the gateway's
    # reconnect watcher would otherwise retry forever at the backoff cap
    # (api_server.py hit exactly this leak in production).
    async def go():
        a = KioskAdapter(_cfg(tmp_path))
        await a.connect()
        b = KioskAdapter({"port": a.port, "static_root": str(tmp_path)})
        try:
            ok = await b.connect()
            assert ok is False
            assert b._fatal_error_code == "samantha_kiosk_port_in_use"
            assert b._fatal_error_retryable is False
            # No leaked runner/site from the failed attempt.
            assert b._runner is None
            assert b._site is None
        finally:
            if (
                b._runner is not None
            ):  # pragma: no cover - only if the assert above failed
                await b.disconnect()
            await a.disconnect()

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
