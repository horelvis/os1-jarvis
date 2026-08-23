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
        client.on_done = lambda _ms: finished.set()

        task = asyncio.create_task(client.run())
        await client.wait_connected(timeout=5)
        await client.send_chat("hola")
        await asyncio.wait_for(finished.wait(), timeout=5)
        task.cancel()

    assert "".join(tokens) == "Hola."


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


async def test_sending_with_no_connection_says_so_instead_of_raising() -> None:
    """The gateway is down. She has to say something, not throw."""
    client = GatewayClient(uri="ws://127.0.0.1:1")  # nothing listens there
    said: list[str] = []
    client.on_error = said.append

    await client.send_chat("hola")

    assert len(said) == 1
    assert said[0]  # in Spanish, in her voice — content is a judgement call
