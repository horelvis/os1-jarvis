import asyncio
import json
from pathlib import Path

import pytest

aiohttp = pytest.importorskip("aiohttp")

from Hermes.plugins.jarvis.adapter import JarvisAdapter  # noqa: E402


def _cfg(tmp_path: Path) -> dict:
    # tmp_path is unused now that the adapter serves no files, but every
    # caller passes it — kept so this stays a one-line swap if a future
    # test needs a scratch directory again.
    del tmp_path
    return {"port": 0}


def test_websocket_round_trip(tmp_path, monkeypatch):
    # Since Task 4, _handle_chat no longer answers itself — it dispatches a
    # MessageEvent to handle_message(), which is Hermes' job in production.
    # Stand in for Hermes here to prove the wire still carries a reply back
    # to the browser once something calls send().
    async def fake_handle_message(self, event):
        await self.send(event.source.chat_id, f"echo: {event.text}")

    monkeypatch.setattr(
        JarvisAdapter, "handle_message", fake_handle_message, raising=False
    )

    async def go():
        a = JarvisAdapter(_cfg(tmp_path))
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
    import Hermes.plugins.jarvis.adapter as mod

    seen = []

    async def fake_handle_message(self, event):
        seen.append(event)

    monkeypatch.setattr(
        mod.JarvisAdapter, "handle_message", fake_handle_message, raising=False
    )

    async def go():
        a = mod.JarvisAdapter(_cfg(tmp_path))
        await a.connect()
        try:
            await a._handle_chat("hola", "primary")
        finally:
            await a.disconnect()

    asyncio.run(go())
    assert len(seen) == 1
    assert seen[0].text == "hola"
    assert seen[0].message_type.value == "text"
    # The session key vision and code target is built from these two
    # fields, not from get_chat_info() — a regression here would silence
    # both plugins without failing anywhere else (Finding 3, 2026-08-28).
    assert seen[0].source.chat_id == "jarvis"
    assert seen[0].source.chat_name == "JARVIS"


def test_malformed_message_gets_an_error_in_spanish_not_a_crash(tmp_path):
    async def go():
        a = JarvisAdapter(_cfg(tmp_path))
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
        a = JarvisAdapter(_cfg(tmp_path))
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
        a = JarvisAdapter(_cfg(tmp_path))
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
        a = JarvisAdapter(_cfg(tmp_path))
        await a.connect()
        port = a.port
        await a.disconnect()
        # Binding the same port again must succeed.
        b = JarvisAdapter({"port": port})
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
        a = JarvisAdapter(_cfg(tmp_path))
        await a.connect()
        b = JarvisAdapter({"port": a.port})
        try:
            ok = await b.connect()
            assert ok is False
            assert b._fatal_error_code == "jarvis_port_in_use"
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
    # False there and a non-retryable failure (a taken port) gets requeued
    # and retried forever instead of being dropped —
    # exactly the retry-forever shape connect()'s fatal path exists to
    # prevent. Clearing on disconnect() undoes the fix silently, because
    # no other test calls disconnect() after a fatal connect().
    async def go():
        a = JarvisAdapter(_cfg(tmp_path))
        await a.connect()
        try:
            b = JarvisAdapter({"port": a.port})
            assert await b.connect() is False
            assert b._fatal_error_code == "jarvis_port_in_use"

            await b.disconnect()

            assert b._fatal_error_code == "jarvis_port_in_use"
            assert b._fatal_error_message is not None
            assert b._fatal_error_retryable is False
        finally:
            await a.disconnect()

    asyncio.run(go())


def test_environment_variable_overrides_the_config_dict(tmp_path, monkeypatch):
    # SAMANTHA_KIOSK_PORT is no longer what the manifest declares — that is
    # JARVIS_PORT now (plugin.yaml). This test keeps SAMANTHA_KIOSK_PORT on
    # purpose: it is the legacy fallback _env() still honours (adapter.py's
    # _LEGACY_ENV) for a box nobody has re-exported the new name on yet, and
    # it must still win over the config dict.
    del tmp_path
    monkeypatch.setenv("SAMANTHA_KIOSK_PORT", "0")

    a = JarvisAdapter({"port": 9999})

    assert a.port == 0


def test_send_returns_a_send_result_not_none(tmp_path):
    # BasePlatformAdapter.send is declared `-> SendResult` and
    # _send_with_retry reads `result.success` with no guard, so returning
    # None raises AttributeError inside Hermes on EVERY reply — aborting
    # _process_message_background, reporting FAILURE for turns that
    # succeeded, and pushing Hermes' English error text onto the OS1 screen.
    # This shipped once with a green suite because every test here runs
    # against the shim. Assert the contract, not the shim.
    async def go():
        a = JarvisAdapter(_cfg(tmp_path))
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
        a = JarvisAdapter(_cfg(tmp_path))
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

    monkeypatch.setattr(JarvisAdapter, "handle_message", never_answers, raising=False)

    async def go():
        a = JarvisAdapter({**_cfg(tmp_path), "turn_timeout": 0.2})
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

    monkeypatch.setattr(JarvisAdapter, "handle_message", answers, raising=False)

    async def go():
        a = JarvisAdapter({**_cfg(tmp_path), "turn_timeout": 0.2})
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

    monkeypatch.setattr(JarvisAdapter, "handle_message", never_answers, raising=False)

    async def go():
        a = JarvisAdapter({**_cfg(tmp_path), "turn_timeout": 0.2})
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

    monkeypatch.setattr(JarvisAdapter, "handle_message", answers, raising=False)

    async def go():
        a = JarvisAdapter(_cfg(tmp_path))
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

    monkeypatch.setattr(JarvisAdapter, "handle_message", never_answers, raising=False)

    async def go():
        a = JarvisAdapter({**_cfg(tmp_path), "turn_timeout": 30})
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

    monkeypatch.setattr(JarvisAdapter, "handle_message", blows_up, raising=False)

    async def go():
        a = JarvisAdapter(_cfg(tmp_path))
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


def test_a_foreign_origin_cannot_open_the_socket(tmp_path):
    # WebSockets are exempt from the same-origin policy, so without this any
    # local page could open ws://127.0.0.1/ws, assert a user_id, talk to an
    # agent with tool access — and, because the newest connection wins,
    # EVICT the real kiosk rather than merely eavesdrop.
    async def go():
        a = JarvisAdapter(_cfg(tmp_path))
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
        a = JarvisAdapter(_cfg(tmp_path))
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
    monkeypatch.delenv("JARVIS_PORT", raising=False)
    monkeypatch.delenv("JARVIS_TURN_TIMEOUT", raising=False)
    monkeypatch.delenv("SAMANTHA_KIOSK_PORT", raising=False)
    monkeypatch.delenv("SAMANTHA_KIOSK_TURN_TIMEOUT", raising=False)

    class FakePlatformConfig:
        """Shaped like gateway.config.PlatformConfig: settings live in .extra."""

        enabled = True
        extra = {"port": 0, "turn_timeout": 12}

    a = JarvisAdapter(FakePlatformConfig())
    assert a.port == 0
    assert a.turn_timeout == 12


def test_construction_survives_a_config_with_no_extra_at_all(monkeypatch):
    monkeypatch.delenv("JARVIS_PORT", raising=False)
    monkeypatch.delenv("JARVIS_TURN_TIMEOUT", raising=False)
    monkeypatch.delenv("SAMANTHA_KIOSK_PORT", raising=False)
    monkeypatch.delenv("SAMANTHA_KIOSK_TURN_TIMEOUT", raising=False)

    class Bare:
        enabled = True

    a = JarvisAdapter(Bare())
    assert a.port == 7777
    assert a.turn_timeout == 90.0


@pytest.fixture
def spool(tmp_path, monkeypatch):
    """A snapshot directory with one real file in it."""
    from Hermes.plugins.samantha_vision import snapshot

    monkeypatch.setattr(snapshot, "_ROOT", tmp_path)
    path = tmp_path / "entrada-1000.jpg"
    path.write_bytes(b"\xff\xd8\xff\xd9")  # shortest valid JPEG marker pair
    return path


@pytest.fixture
def adapter(tmp_path):
    """The adapter with no socket attached: _push returns False.

    Good for proving push_photo is False when nobody is listening, but
    USELESS for proving a bad path was rejected: _push(...) returns False
    the instant it sees `_ws is None`, before push_photo's own validation
    ever runs — so a rejection test built on this fixture alone passes
    whether or not the validation code exists. Use `connected_adapter`
    for anything that must prove the validation itself did the rejecting.
    """
    a = JarvisAdapter(_cfg(tmp_path))
    a._ws = None
    return a


class _RecordingWs:
    """A stand-in for aiohttp's WebSocketResponse that records frames sent.

    `_push` only checks `ws is None or ws.closed`, so this needs nothing
    else to look "connected" to it. What it buys: `sent` makes it possible
    to tell "push_photo's validation rejected this" apart from "nothing
    was listening" — both return False from push_photo, but only the first
    leaves `sent` empty when the path SHOULD have been rejected, and only
    the second leaves it empty when the path was fine. A test asserting
    `push_photo(...) is False` alone cannot make that distinction; a test
    asserting `sent == []` on a definitely-open socket can.
    """

    def __init__(self) -> None:
        self.closed = False
        self.sent: list[str] = []

    async def send_str(self, payload: str) -> None:
        self.sent.append(payload)


@pytest.fixture
def connected_adapter(tmp_path):
    """The adapter with a fake, definitely-open socket attached.

    Recovered from a review finding: the `adapter` fixture's `_ws = None`
    made `test_push_photo_refuses_a_path_outside_the_snapshot_directory`
    and its symlink sibling pass regardless of whether the path validation
    in push_photo ran at all — `_push` returns False on a None socket
    before the frame content is ever inspected. This fixture's socket is
    "open" (`closed = False`), so if validation ever let a bad path
    through, `_RecordingWs.sent` would show it.
    """
    a = JarvisAdapter(_cfg(tmp_path))
    a._ws = _RecordingWs()
    return a


@pytest.mark.asyncio
async def test_push_photo_refuses_a_path_outside_the_snapshot_directory(
    connected_adapter,
):
    ok = await connected_adapter.push_photo("/etc/shadow", "entrada")
    assert ok is False
    # The socket is open; an empty `sent` is what proves validation refused
    # the path BEFORE _push was ever called — not that nobody was listening.
    assert connected_adapter._ws.sent == []


@pytest.mark.asyncio
async def test_push_photo_with_no_strip_connected_is_false_not_an_error(adapter, spool):
    adapter._ws = None
    ok = await adapter.push_photo(str(spool), "entrada")
    assert ok is False


@pytest.mark.asyncio
async def test_push_photo_refuses_a_symlink_that_escapes_the_snapshot_directory(
    connected_adapter, spool, tmp_path
):
    # A symlink INSIDE the spool that resolves to a file OUTSIDE it must be
    # refused too — this is what proves the check follows realpath rather
    # than just string-matching the given path.
    outside = tmp_path.parent / "outside-secret.jpg"
    outside.write_bytes(b"\xff\xd8\xff\xd9")
    escape = spool.parent / "escape.jpg"
    escape.symlink_to(outside)

    ok = await connected_adapter.push_photo(str(escape), "entrada")
    assert ok is False
    assert connected_adapter._ws.sent == []


@pytest.mark.asyncio
async def test_push_photo_refuses_a_symlink_loop_rather_than_raising(
    connected_adapter, tmp_path, monkeypatch
):
    # Path.resolve(strict=True) raises RuntimeError (not OSError) on a
    # symlink cycle on CPython. A cycle reachable inside the spool is our
    # own bug, not an attacker's input, but push_photo must never raise —
    # the gateway owns the cameras, and an exception here reaches it.
    from Hermes.plugins.samantha_vision import snapshot

    monkeypatch.setattr(snapshot, "_ROOT", tmp_path)
    loop_a = tmp_path / "loop_a"
    loop_b = tmp_path / "loop_b"
    loop_a.symlink_to(loop_b)
    loop_b.symlink_to(loop_a)

    ok = await connected_adapter.push_photo(str(loop_a), "entrada")

    assert ok is False
    assert connected_adapter._ws.sent == []


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


# ── The divert: while the code assistant waits, the next unnamed word
#    is its answer and never opens a turn. ────────────────────────────


def test_divert_consumes_unnamed_input_when_someone_waits(adapter):
    taken = []
    adapter.divert_chat = lambda text: taken.append(text) or True
    assert (
        adapter._should_divert({"type": "chat", "message": "sí", "user_id": "u"})
        is True
    )
    assert taken == ["sí"]


def test_named_input_always_reaches_jarvis(adapter):
    adapter.divert_chat = lambda text: True
    assert (
        adapter._should_divert(
            {"type": "chat", "message": "qué hora es", "user_id": "u", "wake": True}
        )
        is False
    )


def test_no_divert_hook_means_nothing_changes(adapter):
    assert (
        adapter._should_divert({"type": "chat", "message": "hola", "user_id": "u"})
        is False
    )


def test_a_divert_that_declines_leaves_the_turn_alone(adapter):
    # Nothing is waiting any more: the hook says so and the words are a
    # turn like any other.
    adapter.divert_chat = lambda text: False
    assert (
        adapter._should_divert({"type": "chat", "message": "hola", "user_id": "u"})
        is False
    )


def test_a_divert_that_raises_does_not_eat_the_turn(adapter):
    def boom(text):
        raise RuntimeError("x")

    adapter.divert_chat = boom
    assert (
        adapter._should_divert({"type": "chat", "message": "hola", "user_id": "u"})
        is False
    )


def test_a_diverted_frame_never_becomes_a_turn(tmp_path, monkeypatch):
    # The seam that matters, through a real socket: the answer goes to
    # the bridge and Hermes is never asked to think about it.
    import Hermes.plugins.jarvis.adapter as mod

    seen = []
    taken = []

    async def fake_handle_message(self, event):
        seen.append(event)
        # Answer, so the test can wait on something instead of sleeping.
        await self.send(event.source.chat_id, "vale")

    monkeypatch.setattr(
        mod.JarvisAdapter, "handle_message", fake_handle_message, raising=False
    )

    async def go():
        a = mod.JarvisAdapter(_cfg(tmp_path))
        a.divert_chat = lambda text: taken.append(text) or True
        await a.connect()
        try:
            async with aiohttp.ClientSession() as s:
                async with s.ws_connect(f"http://127.0.0.1:{a.port}/ws") as ws:
                    await ws.send_str(
                        json.dumps(
                            {"type": "chat", "message": "sí", "user_id": "primary"}
                        )
                    )
                    # Then a named one, which must get through — and its
                    # arrival is what proves the first was consumed
                    # rather than merely slow.
                    await ws.send_str(
                        json.dumps(
                            {
                                "type": "chat",
                                "message": "qué hora es",
                                "user_id": "primary",
                                "wake": True,
                            }
                        )
                    )
                    frames = [
                        json.loads((await ws.receive(timeout=5)).data) for _ in range(2)
                    ]
                    return frames
        finally:
            await a.disconnect()

    frames = asyncio.run(go())
    # The diverted frame settles the wave silently; the named one is a
    # turn like any other.
    assert frames[0] == {"type": "error", "error": ""}
    assert frames[1]["type"] == "token"
    assert taken == ["sí"]
    assert [e.text for e in seen] == ["qué hora es"]


def test_a_diverted_frame_settles_the_wave_without_a_word(tmp_path, monkeypatch):
    # The turn guarantee: every accepted chat frame ends in exactly one
    # `done` or one `error`. A divert opens no turn, so nothing arms the
    # watchdog — without this frame the strip sits in `thinking` for as
    # long as the build runs.
    import Hermes.plugins.jarvis.adapter as mod

    seen = []

    async def fake_handle_message(self, event):
        seen.append(event)

    monkeypatch.setattr(
        mod.JarvisAdapter, "handle_message", fake_handle_message, raising=False
    )

    async def go():
        a = mod.JarvisAdapter(_cfg(tmp_path))
        a.divert_chat = lambda text: True
        await a.connect()
        try:
            async with aiohttp.ClientSession() as s:
                async with s.ws_connect(f"http://127.0.0.1:{a.port}/ws") as ws:
                    await ws.send_str(
                        json.dumps(
                            {"type": "chat", "message": "sí", "user_id": "primary"}
                        )
                    )
                    return json.loads((await ws.receive(timeout=5)).data)
        finally:
            await a.disconnect()

    got = asyncio.run(go())
    assert got == {"type": "error", "error": ""}
    assert seen == []


def test_a_declined_divert_still_opens_an_ordinary_turn(tmp_path, monkeypatch):
    # The silence must belong to the divert, not to every chat frame.
    import Hermes.plugins.jarvis.adapter as mod

    async def fake_handle_message(self, event):
        await self.send(event.source.chat_id, "vale")

    monkeypatch.setattr(
        mod.JarvisAdapter, "handle_message", fake_handle_message, raising=False
    )

    async def go():
        a = mod.JarvisAdapter(_cfg(tmp_path))
        a.divert_chat = lambda text: False
        await a.connect()
        try:
            async with aiohttp.ClientSession() as s:
                async with s.ws_connect(f"http://127.0.0.1:{a.port}/ws") as ws:
                    await ws.send_str(
                        json.dumps(
                            {"type": "chat", "message": "hola", "user_id": "primary"}
                        )
                    )
                    return json.loads((await ws.receive(timeout=5)).data)
        finally:
            await a.disconnect()

    assert asyncio.run(go())["type"] == "token"


def test_push_asking_goes_out_as_text(adapter):
    # The frame that keeps the strip's wake window open while the code
    # assistant waits. Without it a spoken answer that took more than 30
    # seconds is dropped by the strip and never reaches `_should_divert`.
    sock = _Socket()
    adapter._ws = sock

    assert asyncio.run(adapter.push_asking(True)) is True
    assert asyncio.run(adapter.push_asking(False)) is True
    assert sock.blobs == []
    assert [json.loads(t) for t in sock.texts] == [
        {"type": "asking", "open": True},
        {"type": "asking", "open": False},
    ]


def test_push_asking_with_no_strip_connected_is_false_not_an_error(adapter):
    adapter._ws = None
    assert asyncio.run(adapter.push_asking(True)) is False


def test_the_platform_is_called_jarvis():
    """The name the gateway registers, the session key, and the chat.

    None of the three was pinned before 2026-08-28, which is why the
    rename had to start here: `samantha_kiosk` could have been changed
    in one of them and left in the other two with every test green.
    """
    adapter = JarvisAdapter(config={})
    assert JarvisAdapter.name == "jarvis"
    assert adapter.platform.value == "jarvis"


def test_the_chat_is_called_jarvis():
    import asyncio

    adapter = JarvisAdapter(config={})
    info = asyncio.run(adapter.get_chat_info("ignored"))
    assert info == {"name": "JARVIS", "type": "dm"}


def test_the_port_comes_from_the_new_variable(monkeypatch):
    monkeypatch.setenv("JARVIS_PORT", "7801")
    assert JarvisAdapter(config={})._configured_port == 7801


def test_the_old_variable_still_works(monkeypatch):
    """A box that set SAMANTHA_KIOSK_PORT before 2026-08-28 keeps it.

    Nothing on this machine sets any of the four (verified 2026-08-28:
    no unit, no drop-in), so this protects a box we cannot see rather
    than this one.
    """
    monkeypatch.delenv("JARVIS_PORT", raising=False)
    monkeypatch.setenv("SAMANTHA_KIOSK_PORT", "7802")
    assert JarvisAdapter(config={})._configured_port == 7802


def test_the_new_variable_wins_over_the_old(monkeypatch):
    monkeypatch.setenv("JARVIS_PORT", "7803")
    monkeypatch.setenv("SAMANTHA_KIOSK_PORT", "7804")
    assert JarvisAdapter(config={})._configured_port == 7803


@pytest.fixture
def teacher_spool(tmp_path, monkeypatch):
    """A teacher image spool with one real file in it, isolated to tmp_path.

    Mirrors the `spool` fixture above, but for `jarvis_teacher.imagen`,
    which is configured by an environment variable rather than a module
    attribute — `monkeypatch.setenv` is the equivalent of that fixture's
    `monkeypatch.setattr(snapshot, "_ROOT", tmp_path)`.
    """
    monkeypatch.setenv("JARVIS_TEACHER_HOME", str(tmp_path))
    from Hermes.plugins.jarvis_teacher.imagen import spool_dir

    path = spool_dir() / "leccion.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n")
    return path


@pytest.mark.asyncio
async def test_push_ficha_without_an_image_is_sent(connected_adapter):
    ok = await connected_adapter.push_ficha("## Hola\n\n- a\n- b\n", "pregunta")
    assert ok is True
    assert connected_adapter._ws.sent


@pytest.mark.asyncio
async def test_push_ficha_drops_an_image_outside_the_teacher_spool_but_still_sends_the_card(
    connected_adapter, teacher_spool, tmp_path
):
    """The strip opens whatever it is handed, and this socket is local and
    unauthenticated — the same trust boundary `push_photo` guards.

    Unlike a photo, a bad reference here must not cost the whole card
    (push_ficha's own docstring): it is dropped from the document and the
    card is still drawn, so this asserts `ok is True` rather than False.
    """
    fuera = tmp_path / "fuera.png"
    fuera.write_bytes(b"x")

    ok = await connected_adapter.push_ficha(f"![]({fuera})", "pregunta")

    assert ok is True
    sent = json.loads(connected_adapter._ws.sent[0])
    assert str(fuera) not in sent["md"]


@pytest.mark.asyncio
async def test_push_ficha_keeps_an_image_inside_the_teacher_spool(
    connected_adapter, teacher_spool
):
    ok = await connected_adapter.push_ficha(f"![]({teacher_spool})", "explicacion")

    assert ok is True
    sent = json.loads(connected_adapter._ws.sent[0])
    assert str(teacher_spool) in sent["md"]


@pytest.mark.asyncio
async def test_push_ficha_keeps_the_good_image_when_a_second_one_is_refused(
    connected_adapter, teacher_spool, tmp_path
):
    """A card with two images must not lose the good one to the bad one."""
    fuera = tmp_path / "fuera.png"
    fuera.write_bytes(b"x")
    md = f"![]({teacher_spool})\n\n![]({fuera})\n"

    ok = await connected_adapter.push_ficha(md, "explicacion")

    assert ok is True
    sent = json.loads(connected_adapter._ws.sent[0])
    assert str(teacher_spool) in sent["md"]
    assert str(fuera) not in sent["md"]


@pytest.mark.asyncio
async def test_push_ficha_refuses_a_symlink_that_escapes_the_teacher_spool(
    connected_adapter, teacher_spool, tmp_path
):
    # A symlink INSIDE the spool that resolves to a file OUTSIDE it must be
    # dropped too — proves the check follows realpath, not string matching.
    outside = tmp_path.parent / "outside-secret.png"
    outside.write_bytes(b"x")
    escape = teacher_spool.parent / "escape.png"
    escape.symlink_to(outside)

    ok = await connected_adapter.push_ficha(f"![]({escape})", "explicacion")

    assert ok is True
    sent = json.loads(connected_adapter._ws.sent[0])
    assert str(escape) not in sent["md"]


@pytest.mark.asyncio
async def test_push_ficha_with_no_strip_connected_is_false_not_an_error(adapter):
    ok = await adapter.push_ficha("## Hola\n\n- a\n- b\n", "pregunta")
    assert ok is False


@pytest.mark.asyncio
async def test_push_ficha_with_an_unknown_tipo_is_false_not_an_error(connected_adapter):
    # ficha() raises ProtocolError on an unknown tipo — push_photo's rule
    # applies here too: this method must never raise into a turn.
    ok = await connected_adapter.push_ficha("## Hola\n\n- a\n- b\n", "examen")
    assert ok is False
    assert connected_adapter._ws.sent == []


@pytest.mark.asyncio
async def test_push_ficha_removes_a_refused_reference_rather_than_emptying_it(
    connected_adapter, teacher_spool, tmp_path
):
    """A refused image leaves no `![alt]()` behind.

    Pointing the reference at "" left the empty syntax in the document,
    which the strip draws as literal text and charges a picture's height
    for (`ficha.height` counts any line starting `![` as 169 px). The
    one visible outcome of this security check looked like a bug.
    """
    fuera = tmp_path / "fuera.png"
    fuera.write_bytes(b"x")

    ok = await connected_adapter.push_ficha(
        f"## Pregunta\n\n![un diagrama]({fuera})\n\n- a\n- b\n", "pregunta"
    )

    assert ok is True
    sent = json.loads(connected_adapter._ws.sent[0])
    assert "![" not in sent["md"]
    assert "]()" not in sent["md"]
    assert "- a" in sent["md"] and "## Pregunta" in sent["md"]
