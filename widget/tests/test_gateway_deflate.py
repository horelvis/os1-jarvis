"""The defect that ate three of the owner's sentences, pinned.

Measured on the live machine, 2026-08-27. The strip connects and sits
idle; `websockets` sends its keepalive ping after twenty seconds; the
next thing the user says is destroyed on the wire and the socket dies
with it, `CLOSE 1002 (protocol error)` from the server. The strip
reconnects into exactly the same state, so it happens again on the next
turn, and again. Not a race — every turn that follows an idle gap of
twenty seconds or more.

The cause is `permessage-deflate`: with it negotiated, aiohttp — which
is what the jarvis adapter is — refuses the FIRST compressed data frame
of a connection when a control frame reached it first. Reproduced with
no Hermes in it at all, which is what this file is.

**aiohttp is deliberately not a declared dependency of the widget** —
the strip does not use it, the gateway does — so the reproduction skips
where it is absent. `test_the_client_asks_for_no_compression` carries
the regression on its own with no dependency at all, and is the one
that must never be deleted.
"""

import asyncio
import json

import pytest

from samantha_widget.gateway import CONNECT_OPTIONS, GatewayClient

aiohttp = pytest.importorskip(
    "aiohttp", reason="the gateway's library, not the strip's"
)

# Sentinel: "whatever the client itself asks for". The regression test
# must go through the client's OWN options, or reverting the fix would
# leave it passing.
_AS_BUILT = object()


def test_the_client_asks_for_no_compression() -> None:
    # The whole fix, and the only part of this file that needs nothing
    # installed. `permessage-deflate` on a loopback socket carrying
    # small JSON frames buys nothing and costs every turn that follows
    # a pause.
    assert CONNECT_OPTIONS["compression"] is None
    assert GatewayClient().connect_options["compression"] is None


async def _echo_server():
    """An aiohttp websocket that answers a chat the way the adapter does."""
    from aiohttp import web

    async def handler(request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        async for msg in ws:
            if msg.type is web.WSMsgType.TEXT:
                said = json.loads(msg.data).get("message", "")
                await ws.send_str(json.dumps({"type": "token", "token": said}))
                await ws.send_str(json.dumps({"type": "done", "thinking_ms": 1}))
        return ws

    app = web.Application()
    app.router.add_get("/ws", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    return runner, runner.addresses[0][1]


async def _turn_after_a_keepalive(compression=_AS_BUILT) -> list[str]:
    """One sentence sent after the keepalive ping. What came back."""
    runner, port = await _echo_server()
    heard: list[str] = []
    client = GatewayClient(f"ws://127.0.0.1:{port}/ws")
    client.retry_seconds = 30.0  # no reconnect inside the test's window
    client.on_token = heard.append
    # Only the keepalive is overridden — milliseconds instead of the
    # default twenty seconds. The ping is not what is broken, it is only
    # what has to arrive first. Compression is left as the CLIENT asks
    # for it unless a test says otherwise, so reverting the fix fails
    # the regression below instead of quietly still passing.
    client.connect_options = {
        **client.connect_options,
        "ping_interval": 0.05,
        "ping_timeout": 20.0,
    }
    if compression is not _AS_BUILT:
        client.connect_options["compression"] = compression
    task = asyncio.create_task(client.run())
    try:
        await client.wait_connected(timeout=5.0)
        await asyncio.sleep(0.3)  # long enough that the ping has gone
        await client.send_chat("¿me oyes?")
        for _ in range(40):  # bounded: 2 s, never a hang
            if heard:
                break
            await asyncio.sleep(0.05)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await runner.cleanup()
    return heard


@pytest.mark.asyncio
async def test_a_sentence_after_a_pause_reaches_the_gateway() -> None:
    # The regression. Against the code as it was on 2026-08-27 this is
    # the owner's failure exactly: nothing comes back, and the socket is
    # gone.
    assert await _turn_after_a_keepalive() == ["¿me oyes?"]


@pytest.mark.asyncio
async def test_and_with_deflate_it_is_lost_which_is_why_it_is_off() -> None:
    """The demonstration, and a tripwire.

    If this ever starts FAILING, aiohttp has fixed its side and
    `CONNECT_OPTIONS` can be revisited — that is the point of asserting
    it rather than only asserting the fix. Until then it is the reason
    the line above exists, kept next to it so nobody deletes one without
    reading the other.
    """
    assert await _turn_after_a_keepalive("deflate") == []
