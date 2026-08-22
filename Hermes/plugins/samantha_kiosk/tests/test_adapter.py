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


def test_fatal_error_survives_disconnect(tmp_path):
    # The gateway's startup path calls disconnect() BEFORE reading
    # has_fatal_error (gateway/run.py:12985-12986): a fatal connect()
    # failure is disconnected, then the adapter is asked whether it was
    # fatal. If disconnect() clears the flags, has_fatal_error is always
    # False there and a non-retryable failure (bad port, missing static
    # root) gets requeued and retried forever instead of being dropped —
    # exactly the retry-forever shape connect()'s fatal path exists to
    # prevent. Clearing on disconnect() undoes the fix silently, because
    # no other test calls disconnect() after a fatal connect().
    async def go():
        a = KioskAdapter(_cfg(tmp_path))
        await a.connect()
        try:
            b = KioskAdapter({"port": a.port, "static_root": str(tmp_path)})
            assert await b.connect() is False
            assert b._fatal_error_code == "samantha_kiosk_port_in_use"

            await b.disconnect()

            assert b._fatal_error_code == "samantha_kiosk_port_in_use"
            assert b._fatal_error_message is not None
            assert b._fatal_error_retryable is False
        finally:
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
    assert a.static_root == env_root.resolve()


def test_send_returns_a_send_result_not_none(tmp_path):
    # BasePlatformAdapter.send is declared `-> SendResult` and
    # _send_with_retry reads `result.success` with no guard, so returning
    # None raises AttributeError inside Hermes on EVERY reply — aborting
    # _process_message_background, reporting FAILURE for turns that
    # succeeded, and pushing Hermes' English error text onto the OS1 screen.
    # This shipped once with a green suite because every test here runs
    # against the shim. Assert the contract, not the shim.
    async def go():
        a = KioskAdapter(_cfg(tmp_path))
        await a.connect()
        try:
            async with aiohttp.ClientSession() as s:
                async with s.ws_connect(f"http://127.0.0.1:{a.port}/ws"):
                    await asyncio.sleep(0.05)
                    result = await a.send("kiosk", "hola")
                    assert result is not None
                    assert result.success is True
        finally:
            await a.disconnect()

    asyncio.run(go())


def test_send_with_nobody_connected_is_a_retryable_failure(tmp_path):
    # A browser mid-refresh must cost a retry, not the reply. Reporting
    # success=True here would tell Hermes a message landed that went nowhere.
    async def go():
        a = KioskAdapter(_cfg(tmp_path))
        await a.connect()
        try:
            result = await a.send("kiosk", "hola")
            assert result.success is False
            assert result.retryable is True
        finally:
            await a.disconnect()

    asyncio.run(go())


def test_a_turn_that_never_comes_back_gets_an_error_frame(tmp_path, monkeypatch):
    # THE guarantee: every accepted `chat` frame ends in exactly one `done`
    # or one `error`. Without it the frontend's `busy` never clears (it is
    # only cleared in a `finally` on a promise that never settles), the wave
    # stays in `thinking`, and the STT commit — gated on `busy` — dies with
    # it. Only a page reload recovers.
    async def never_answers(self, event):
        return None

    monkeypatch.setattr(KioskAdapter, "handle_message", never_answers, raising=False)

    async def go():
        a = KioskAdapter({**_cfg(tmp_path), "turn_timeout": 0.2})
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
                    assert got["type"] == "error"
                    # Spanish, in her voice — this reaches the screen.
                    assert (
                        got["error"] == "Algo se ha quedado a medias. ¿Me lo repites?"
                    )
        finally:
            await a.disconnect()

    asyncio.run(go())


def test_a_reply_that_arrives_in_time_gets_no_watchdog_error(tmp_path, monkeypatch):
    # The watchdog must not double-send. A turn answered normally sees
    # exactly token+done and nothing after it.
    async def answers(self, event):
        await self.send(event.source.chat_id, "aquí estoy")

    monkeypatch.setattr(KioskAdapter, "handle_message", answers, raising=False)

    async def go():
        a = KioskAdapter({**_cfg(tmp_path), "turn_timeout": 0.2})
        await a.connect()
        try:
            async with aiohttp.ClientSession() as s:
                async with s.ws_connect(f"http://127.0.0.1:{a.port}/ws") as ws:
                    await ws.send_str(
                        json.dumps(
                            {"type": "chat", "message": "hola", "user_id": "primary"}
                        )
                    )
                    assert json.loads((await ws.receive(timeout=5)).data)["type"] == (
                        "token"
                    )
                    assert json.loads((await ws.receive(timeout=5)).data)["type"] == (
                        "done"
                    )
                    # Past the watchdog deadline: nothing more may arrive.
                    with pytest.raises(asyncio.TimeoutError):
                        await ws.receive(timeout=0.6)
                    assert a._turn is None
        finally:
            await a.disconnect()

    asyncio.run(go())


def test_a_late_reply_is_dropped_rather_than_landing_on_the_next_turn(
    tmp_path, monkeypatch
):
    # Once the watchdog has apologised, the late reply must NOT be pushed:
    # the frontend may already have re-armed its handlers for the next turn,
    # where a stray token would be appended to the wrong bubble and its
    # `done` would resolve the wrong promise with the wrong text.
    async def never_answers(self, event):
        return None

    monkeypatch.setattr(KioskAdapter, "handle_message", never_answers, raising=False)

    async def go():
        a = KioskAdapter({**_cfg(tmp_path), "turn_timeout": 0.2})
        await a.connect()
        try:
            async with aiohttp.ClientSession() as s:
                async with s.ws_connect(f"http://127.0.0.1:{a.port}/ws") as ws:
                    await ws.send_str(
                        json.dumps(
                            {"type": "chat", "message": "hola", "user_id": "primary"}
                        )
                    )
                    assert json.loads((await ws.receive(timeout=5)).data)["type"] == (
                        "error"
                    )
                    result = await a.send("kiosk", "llego tarde")
                    assert result.success is False
                    assert result.retryable is False
                    # The error text must read as a timeout to Hermes'
                    # BasePlatformAdapter._send_with_retry — that's the only
                    # branch that returns the failure as-is instead of
                    # retrying or falling back to a plain-text resend, which
                    # would call send() again and land a stray English
                    # message on the kiosk after this drop.
                    assert "timed out" in result.error
                    with pytest.raises(asyncio.TimeoutError):
                        await ws.receive(timeout=0.3)
        finally:
            await a.disconnect()

    asyncio.run(go())


def test_the_watchdog_leaves_no_task_behind(tmp_path, monkeypatch):
    # One task per turn, cancelled when the turn settles. Over weeks of
    # uptime nothing here may accumulate.
    async def answers(self, event):
        await self.send(event.source.chat_id, "vale")

    monkeypatch.setattr(KioskAdapter, "handle_message", answers, raising=False)

    async def go():
        a = KioskAdapter(_cfg(tmp_path))
        await a.connect()
        try:
            async with aiohttp.ClientSession() as s:
                async with s.ws_connect(f"http://127.0.0.1:{a.port}/ws"):
                    await asyncio.sleep(0.05)
                    before = len(asyncio.all_tasks())
                    for _ in range(5):
                        await a._handle_chat("hola", "primary")
                    await asyncio.sleep(0.05)
                    assert a._turn is None
                    assert len(asyncio.all_tasks()) <= before
        finally:
            await a.disconnect()

    asyncio.run(go())


def test_disconnect_cancels_a_pending_watchdog(tmp_path, monkeypatch):
    async def never_answers(self, event):
        return None

    monkeypatch.setattr(KioskAdapter, "handle_message", never_answers, raising=False)

    async def go():
        a = KioskAdapter({**_cfg(tmp_path), "turn_timeout": 30})
        await a.connect()
        async with aiohttp.ClientSession() as s:
            async with s.ws_connect(f"http://127.0.0.1:{a.port}/ws"):
                await asyncio.sleep(0.05)
                await a._handle_chat("hola", "primary")
                turn = a._turn
                assert turn is not None
                await a.disconnect()
                assert a._turn is None
                assert turn.watchdog.cancelled() or turn.watchdog.cancelling()

    asyncio.run(go())


def test_a_dispatch_failure_reaches_the_screen(tmp_path, monkeypatch):
    # An exception raised while dispatching used to kill the WebSocket
    # handler mid-loop: no error frame, no `self._ws` reset, socket closed
    # with nothing to show for it.
    async def blows_up(self, event):
        raise RuntimeError("boom")

    monkeypatch.setattr(KioskAdapter, "handle_message", blows_up, raising=False)

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
                    assert got["type"] == "error"
                    # And the socket survives it — the kiosk stays usable.
                    assert not ws.closed
        finally:
            await a.disconnect()

    asyncio.run(go())


def test_missing_static_root_is_a_fatal_non_retryable_error(tmp_path):
    # aiohttp's add_static raises ValueError on a missing directory, which
    # would escape connect() into the gateway watcher's `except Exception`,
    # be logged at DEBUG, and retry forever on backoff — the exact shape the
    # port-conflict branch exists to prevent, reached by the likelier road.
    async def go():
        a = KioskAdapter({"port": 0, "static_root": str(tmp_path / "nope")})
        assert await a.connect() is False
        assert a._fatal_error_code == "samantha_kiosk_static_root_missing"
        assert a._fatal_error_retryable is False
        # The message must name the path, or it is unactionable.
        assert "nope" in a._fatal_error_message
        assert a._runner is None

    asyncio.run(go())


def test_missing_index_html_is_fatal_too(tmp_path):
    # assets/ present, index.html absent: aiohttp binds happily and serves a
    # bare 404 on "/", so the kiosk paints a blank page with nothing to
    # diagnose from. Same failure, same treatment.
    (tmp_path / "assets").mkdir()

    async def go():
        a = KioskAdapter({"port": 0, "static_root": str(tmp_path)})
        assert await a.connect() is False
        assert a._fatal_error_code == "samantha_kiosk_static_root_missing"
        assert "index.html" in a._fatal_error_message

    asyncio.run(go())


def test_a_foreign_origin_cannot_open_the_socket(tmp_path):
    # WebSockets are exempt from the same-origin policy, so without this any
    # local page could open ws://127.0.0.1/ws, assert a user_id, talk to an
    # agent with tool access — and, because the newest connection wins,
    # EVICT the real kiosk rather than merely eavesdrop.
    async def go():
        a = KioskAdapter(_cfg(tmp_path))
        await a.connect()
        try:
            async with aiohttp.ClientSession() as s:
                with pytest.raises(aiohttp.WSServerHandshakeError) as exc:
                    await s.ws_connect(
                        f"http://127.0.0.1:{a.port}/ws",
                        headers={"Origin": "http://evil.example"},
                    )
                assert exc.value.status == 403
                # The kiosk's own origin still gets in.
                async with s.ws_connect(
                    f"http://127.0.0.1:{a.port}/ws",
                    headers={"Origin": f"http://localhost:{a.port}"},
                ) as ws:
                    assert not ws.closed
        finally:
            await a.disconnect()

    asyncio.run(go())


def test_a_local_page_on_another_port_cannot_open_the_socket(tmp_path):
    # The dev box runs other things on loopback. "Local" is not enough —
    # the origin must be the kiosk's own.
    async def go():
        a = KioskAdapter(_cfg(tmp_path))
        await a.connect()
        try:
            async with aiohttp.ClientSession() as s:
                with pytest.raises(aiohttp.WSServerHandshakeError) as exc:
                    await s.ws_connect(
                        f"http://127.0.0.1:{a.port}/ws",
                        headers={"Origin": f"http://127.0.0.1:{a.port + 1}"},
                    )
                assert exc.value.status == 403
        finally:
            await a.disconnect()

    asyncio.run(go())


def test_construction_survives_a_real_platform_config(tmp_path, monkeypatch):
    # The gateway hands adapter_factory a PlatformConfig, not a dict
    # (platform_registry.py:685). Calling .get() on it raises inside
    # create_adapter's `except Exception`, which logs once and returns None —
    # the platform never comes up and the screen is blank with nothing on the
    # wire to explain it. Only the exported env vars were hiding this.
    monkeypatch.delenv("SAMANTHA_KIOSK_PORT", raising=False)
    monkeypatch.delenv("SAMANTHA_KIOSK_STATIC_ROOT", raising=False)
    monkeypatch.delenv("SAMANTHA_KIOSK_TURN_TIMEOUT", raising=False)

    class FakePlatformConfig:
        """Shaped like gateway.config.PlatformConfig: settings live in .extra."""

        enabled = True
        extra = {"port": 0, "static_root": "/tmp/os1", "turn_timeout": 12}

    a = KioskAdapter(FakePlatformConfig())
    assert a.port == 0
    assert a.turn_timeout == 12
    assert a.static_root == Path("/tmp/os1").resolve()


def test_construction_survives_a_config_with_no_extra_at_all(monkeypatch):
    monkeypatch.delenv("SAMANTHA_KIOSK_PORT", raising=False)
    monkeypatch.delenv("SAMANTHA_KIOSK_STATIC_ROOT", raising=False)
    monkeypatch.delenv("SAMANTHA_KIOSK_TURN_TIMEOUT", raising=False)

    class Bare:
        enabled = True

    a = KioskAdapter(Bare())
    assert a.port == 7777
    assert a.turn_timeout == 90.0
