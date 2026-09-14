import asyncio
import json
import ssl
import subprocess

import aiohttp
import pytest

from Hermes.plugins.jarvis.adapter import JarvisAdapter


def _context(tmp_path):
    cert = tmp_path / "cert.pem"
    key = tmp_path / "key.pem"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-keyout",
            str(key),
            "-out",
            str(cert),
            "-days",
            "1",
            "-nodes",
            "-subj",
            "/CN=127.0.0.1",
        ],
        check=True,
        capture_output=True,
    )
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    return context


def _cfg(tmp_path):
    roster = tmp_path / "personas.json"
    roster.write_text(
        json.dumps(
            {
                "orelvis": "orelvis-secret",
                "casa": "casa-secret",
                "marta": "marta-secret",
            }
        )
    )
    return {
        "port": 0,
        "mobile": {
            "host": "127.0.0.1",
            "port": 0,
            "origins": ["https://127.0.0.1:0"],
            "ssl_context": _context(tmp_path),
            "roster_path": roster,
            "token_path": tmp_path / "remote.token",
        },
        "policy": {
            "local_provider": {
                "provider": "custom:local",
                "model": "gemma-4-26b-a4b-it",
                "base_url": "http://127.0.0.1:8000/v1",
            }
        },
    }


async def _mobile(session, adapter, token, *, origin=True):
    headers = {"Authorization": f"Bearer {token}"}
    if origin:
        headers["Origin"] = "https://127.0.0.1:0"
    return await session.ws_connect(
        f"https://127.0.0.1:{adapter.mobile_port}/ws", headers=headers, ssl=False
    )


async def _mobile_voice(session, adapter, token):
    return await session.ws_connect(
        f"https://127.0.0.1:{adapter.mobile_port}/voice/local",
        headers={
            "Authorization": f"Bearer {token}",
            "Origin": "https://127.0.0.1:0",
        },
        ssl=False,
    )


def test_mobile_does_not_replace_desktop_and_requires_auth_before_upgrade(tmp_path):
    async def go():
        adapter = JarvisAdapter(_cfg(tmp_path))
        await adapter.connect()
        try:
            async with aiohttp.ClientSession() as session:
                desktop = await session.ws_connect(
                    f"http://127.0.0.1:{adapter.port}/ws"
                )
                with pytest.raises(aiohttp.WSServerHandshakeError) as denied:
                    await _mobile(session, adapter, "wrong")
                assert denied.value.status == 403
                mobile = await _mobile(session, adapter, "casa-secret")
                assert not desktop.closed
                await mobile.close()
                await desktop.close()
        finally:
            await adapter.disconnect()

    asyncio.run(go())


def test_local_voice_is_tls_authenticated_and_fails_closed_without_hermes_stt(tmp_path):
    async def go():
        adapter = JarvisAdapter(_cfg(tmp_path))
        await adapter.connect()
        try:
            async with aiohttp.ClientSession() as session:
                with pytest.raises(aiohttp.WSServerHandshakeError) as denied:
                    await session.ws_connect(
                        f"https://127.0.0.1:{adapter.mobile_port}/voice/local",
                        ssl=False,
                    )
                assert denied.value.status == 403
                ws = await _mobile_voice(session, adapter, "casa-secret")
                await ws.send_json(
                    {
                        "type": "hello",
                        "protocol": "jarvis.local-voice.v1",
                        "processing": "local-only",
                    }
                )
                assert await ws.receive_json(timeout=2) == {
                    "type": "error",
                    "code": "provider_unavailable",
                }
                assert (await ws.receive(timeout=2)).type is aiohttp.WSMsgType.CLOSE
        finally:
            await adapter.disconnect()

    asyncio.run(go())


def test_mobile_identity_and_reply_are_bound_to_authenticated_peer(
    tmp_path, monkeypatch
):
    seen = []

    async def answer(self, event):
        seen.append(event)
        await self.send(event.source.chat_id, "privado", reply_to=event.message_id)

    monkeypatch.setattr(JarvisAdapter, "handle_message", answer, raising=False)

    async def go():
        adapter = JarvisAdapter(_cfg(tmp_path))
        await adapter.connect()
        try:
            async with aiohttp.ClientSession() as session:
                casa = await _mobile(session, adapter, "casa-secret")
                orelvis = await _mobile(session, adapter, "orelvis-secret")
                await casa.send_json(
                    {
                        "type": "turn.submit",
                        "text": "hola",
                        "client_request_id": "one",
                        "chat_id": "orelvis",
                    }
                )
                accepted = await casa.receive_json(timeout=2)
                text = await casa.receive_json(timeout=2)
                done = await casa.receive_json(timeout=2)
                assert accepted["type"] == "turn.accepted"
                assert text == {
                    "type": "text",
                    "turn_id": accepted["turn_id"],
                    "text": "privado",
                }
                assert done == {"type": "done", "turn_id": accepted["turn_id"]}
                with pytest.raises(asyncio.TimeoutError):
                    await orelvis.receive(timeout=0.1)
                await casa.close()
                await orelvis.close()
        finally:
            await adapter.disconnect()

    asyncio.run(go())
    assert seen[0].source.chat_id == "casa"
    assert seen[0].source.user_id == "primary"
    assert seen[0].source.jarvis_policy.principal == "casa"
    assert seen[0].source.jarvis_policy.toolsets == ()


def test_mobile_reconnect_drops_late_reply(tmp_path, monkeypatch):
    async def pending(self, event):
        return None

    monkeypatch.setattr(JarvisAdapter, "handle_message", pending, raising=False)

    async def go():
        adapter = JarvisAdapter(_cfg(tmp_path))
        await adapter.connect()
        try:
            async with aiohttp.ClientSession() as session:
                old = await _mobile(session, adapter, "casa-secret")
                await old.send_json(
                    {"type": "turn.submit", "text": "hola", "client_request_id": "old"}
                )
                turn_id = (await old.receive_json(timeout=2))["turn_id"]
                await old.close()
                replacement = await _mobile(session, adapter, "casa-secret")
                result = await adapter.send("casa", "tarde", reply_to=turn_id)
                assert result.success is False
                assert result.retryable is False
                with pytest.raises(asyncio.TimeoutError):
                    await replacement.receive(timeout=0.1)
                await replacement.close()
        finally:
            await adapter.disconnect()

    asyncio.run(go())


def test_mobile_rejects_unapproved_roster_persona_before_upgrade(tmp_path):
    async def go():
        adapter = JarvisAdapter(_cfg(tmp_path))
        await adapter.connect()
        try:
            async with aiohttp.ClientSession() as session:
                with pytest.raises(aiohttp.WSServerHandshakeError) as denied:
                    await _mobile(session, adapter, "marta-secret")
                assert denied.value.status == 403
        finally:
            await adapter.disconnect()

    asyncio.run(go())


def test_mobile_orelvis_gets_the_full_frozen_policy_snapshot(tmp_path, monkeypatch):
    seen = []

    async def answer(self, event):
        seen.append((event.source.jarvis_policy, self._turns[event.message_id].policy))
        await self.send(event.source.chat_id, "vale", reply_to=event.message_id)

    monkeypatch.setattr(JarvisAdapter, "handle_message", answer, raising=False)

    async def go():
        adapter = JarvisAdapter(_cfg(tmp_path))
        await adapter.connect()
        try:
            async with aiohttp.ClientSession() as session:
                ws = await _mobile(session, adapter, "orelvis-secret")
                await ws.send_json(
                    {"type": "turn.submit", "text": "hola", "client_request_id": "one"}
                )
                await ws.receive_json(timeout=2)
                await ws.receive_json(timeout=2)
                await ws.receive_json(timeout=2)
                await ws.close()
        finally:
            await adapter.disconnect()

    asyncio.run(go())
    source_policy, turn_policy = seen[0]
    assert source_policy == turn_policy
    assert source_policy.principal == "orelvis"
    assert "terminal" in source_policy.toolsets
    assert "file" in source_policy.toolsets
    assert "camaras" in source_policy.toolsets
