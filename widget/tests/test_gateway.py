"""The wire format, and the client's behaviour against a real socket.

The frame shapes are not ours to choose: they are pinned in
Hermes/plugins/jarvis/protocol.py, which in turn pins what the
old frontend spoke. A change on either side has to fail here rather
than on the strip.
"""

import asyncio
import base64
import json

import pytest
import websockets

from jarvis_widget.gateway import (
    GatewayClient,
    ProtocolError,
    decode_live_frame,
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


def test_unknown_type_is_not_a_protocol_error() -> None:
    """The gateway is versioned separately from the strip; a frame type
    this build has never heard of is dropped, not fatal."""
    msg = decode_server('{"type":"sing"}')
    assert msg["type"] == "sing"


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


def test_an_unknown_server_type_is_not_fatal() -> None:
    # The gateway ships new frame types before the strip learns them.
    # A strip that raises here goes silent for the whole turn. `photo`
    # was the example here until the strip learned it (2026-08-24),
    # which is exactly the sequence this test exists to survive.
    msg = decode_server(json.dumps({"type": "hologram", "path": "/tmp/a.jpg"}))
    assert msg["type"] == "hologram"


def test_a_photo_frame_reaches_the_photo_handler() -> None:
    gw = GatewayClient()
    seen: list[tuple[str, str]] = []
    gw.on_photo = lambda path, camera: seen.append((path, camera))
    gw._dispatch(
        json.dumps({"type": "photo", "path": "/tmp/vision/a.jpg", "camera": "entrada"})
    )
    assert seen == [("/tmp/vision/a.jpg", "entrada")]


def test_a_photo_frame_never_reaches_the_voice() -> None:
    # It is a picture, not something she says. A photo that arrived as a
    # token would be read out as a file path by CosyVoice.
    gw = GatewayClient()
    spoken: list[str] = []
    gw.on_token = lambda t: spoken.append(t)
    gw.on_error = lambda m: spoken.append(m)
    gw._dispatch(json.dumps({"type": "photo", "path": "/tmp/a.jpg", "camera": "fuera"}))
    assert spoken == []


def test_a_photo_with_no_path_is_dropped() -> None:
    # An empty path can only end as a failed texture load; there is
    # nothing to show and nothing to grow the strip for.
    gw = GatewayClient()
    seen: list[tuple[str, str]] = []
    gw.on_photo = lambda path, camera: seen.append((path, camera))
    gw._dispatch(json.dumps({"type": "photo", "camera": "entrada"}))
    gw._dispatch(json.dumps({"type": "photo", "path": "", "camera": "entrada"}))
    assert seen == []


def test_a_ficha_frame_reaches_its_callback() -> None:
    cliente = GatewayClient("ws://x")
    recogido: list = []
    cliente.on_ficha = lambda md, tipo, fuente, correcta, elegida: recogido.append(
        (md, tipo, fuente, correcta, elegida)
    )
    cliente._dispatch(
        json.dumps(
            {
                "type": "ficha",
                "tipo": "pregunta",
                "md": "- a\n- b\n",
                "fuente": "Cambridge",
                "correcta": None,
                "elegida": None,
            }
        )
    )
    assert recogido == [("- a\n- b\n", "pregunta", "Cambridge", None, None)]


def test_a_ficha_with_an_unknown_tipo_is_dropped_not_fatal() -> None:
    """The gateway and the widget are versioned separately and always
    will be: an unknown kind must cost the card, not the turn."""
    cliente = GatewayClient("ws://x")
    llamado: list = []
    cliente.on_ficha = lambda *a: llamado.append(a)
    cliente._dispatch(json.dumps({"type": "ficha", "tipo": "examen", "md": "x"}))
    assert llamado == []


def test_malformed_json_is_still_an_error() -> None:
    with pytest.raises(ProtocolError):
        decode_server("{not json")


def test_a_non_object_is_still_an_error() -> None:
    with pytest.raises(ProtocolError):
        decode_server(json.dumps([1, 2, 3]))


def test_dispatch_ignores_an_unknown_type_without_calling_handlers() -> None:
    gw = GatewayClient()
    seen: list[str] = []
    gw.on_token = lambda t: seen.append("token")
    gw.on_error = lambda m: seen.append("error")
    gw._dispatch(json.dumps({"type": "nonesuch"}))
    assert seen == []


def test_a_binary_frame_is_not_parsed_as_json():
    # Today `_dispatch` assumes text and json.loads accepts bytes, so a
    # binary frame would be dropped by the branch that ignores unknown
    # types — silently, which is the worst way to lose video.
    seen = []
    gw = GatewayClient()
    gw.on_live_frame = lambda epoch, packet: seen.append((epoch, packet))

    gw._dispatch((7).to_bytes(4, "big") + b"\x00\x00\x01\x65abc")

    assert seen == [(7, b"\x00\x00\x01\x65abc")]


def test_a_truncated_binary_frame_is_dropped_not_raised():
    gw = GatewayClient()
    gw._dispatch(b"\x00\x00")  # no room for an epoch


def test_live_open_carries_the_decoded_extradata():
    seen = []
    gw = GatewayClient()
    gw.on_live_open = lambda *args: seen.append(args)

    gw._dispatch(
        json.dumps(
            {
                "type": "live",
                "camera": "entrada",
                "epoch": 7,
                "codec": "h264",
                "extradata": base64.b64encode(b"sps").decode("ascii"),
                "width": 704,
                "height": 480,
            }
        )
    )

    assert seen == [("entrada", 7, b"sps", 704, 480)]


def test_live_end_reaches_the_callback():
    seen = []
    gw = GatewayClient()
    gw.on_live_end = lambda epoch, reason: seen.append((epoch, reason))

    gw._dispatch(json.dumps({"type": "live_end", "epoch": 7, "reason": "timeout"}))

    assert seen == [(7, "timeout")]


def test_an_unknown_text_type_is_still_dropped_in_silence():
    gw = GatewayClient()
    gw._dispatch(json.dumps({"type": "something-from-the-future"}))


def test_decode_live_frame_splits_the_header():
    assert decode_live_frame((7).to_bytes(4, "big") + b"abc") == (7, b"abc")


def test_console_lines_reach_the_console_and_do_not_end_it() -> None:
    gw = GatewayClient()
    lines: list[str] = []
    ended: list[bool] = []
    gw.on_console = lines.append
    gw.on_console_done = lambda: ended.append(True)
    gw._dispatch(json.dumps({"type": "console", "text": "compilando"}))
    assert lines == ["compilando"]
    assert ended == []


def test_the_end_of_the_work_reaches_the_console_with_no_text() -> None:
    """An empty frame with `done` is how the run says it is over.

    The console is the one thing on the band with no end of its own — a
    photo fades, a live view hits a ceiling — so it has to be told.
    """
    gw = GatewayClient()
    lines: list[str] = []
    ended: list[bool] = []
    gw.on_console = lines.append
    gw.on_console_done = lambda: ended.append(True)
    gw._dispatch(json.dumps({"type": "console", "text": "", "done": True}))
    assert lines == []
    assert ended == [True]


def test_a_last_line_and_the_end_can_arrive_together() -> None:
    gw = GatewayClient()
    lines: list[str] = []
    ended: list[bool] = []
    gw.on_console = lines.append
    gw.on_console_done = lambda: ended.append(True)
    gw._dispatch(json.dumps({"type": "console", "text": "— terminado", "done": True}))
    assert lines == ["— terminado"]
    assert ended == [True]


def test_a_new_run_empties_the_console_first() -> None:
    """The box is sized by the model, so wiping only the terminal widget
    left a short run sitting in a hole made for the long one before it."""
    gw = GatewayClient()
    order: list[str] = []
    gw.on_console_reset = lambda: order.append("reset")
    gw.on_console = lambda t: order.append(f"line:{t}")
    gw._dispatch(json.dumps({"type": "console", "text": "", "reset": True}))
    gw._dispatch(json.dumps({"type": "console", "text": "primera"}))
    assert order == ["reset", "line:primera"]


def test_a_reset_can_carry_its_first_line() -> None:
    gw = GatewayClient()
    order: list[str] = []
    gw.on_console_reset = lambda: order.append("reset")
    gw.on_console = lambda t: order.append(f"line:{t}")
    gw._dispatch(json.dumps({"type": "console", "text": "arrancando", "reset": True}))
    assert order == ["reset", "line:arrancando"]


class _FakeWs:
    """Stands in for the `websockets` connection `send_chat` writes to."""

    def __init__(self, sent: list[str]) -> None:
        self._sent = sent

    async def send(self, raw: str) -> None:
        self._sent.append(raw)


def test_send_chat_marks_named_turns_and_only_those():
    sent: list[str] = []
    gw = GatewayClient()
    gw._ws = _FakeWs(sent)
    asyncio.run(gw.send_chat("hola"))
    asyncio.run(gw.send_chat("hola", wake=True))
    first, second = (json.loads(s) for s in sent)
    assert "wake" not in first
    assert second["wake"] is True


def test_a_question_waiting_reaches_the_asking_handler() -> None:
    client = GatewayClient()
    seen: list[bool] = []
    client.on_asking = seen.append

    client._dispatch(json.dumps({"type": "asking", "open": True}))
    client._dispatch(json.dumps({"type": "asking", "open": False}))

    assert seen == [True, False]


def test_an_asking_frame_is_never_spoken() -> None:
    # It changes what the strip DOES, not what he says. A frame that
    # leaked into the voice would have him read "asking true" aloud.
    client = GatewayClient()
    said: list[str] = []
    client.on_token = said.append
    client.on_error = said.append

    client._dispatch(json.dumps({"type": "asking", "open": True}))

    assert said == []


# ── The reconnect says so. It used to be `except Exception: pass`. ────


@pytest.fixture
def captured_logs():
    """Everything loguru writes during one test."""
    import io

    from loguru import logger

    sink = io.StringIO()
    handler = logger.add(sink, level="DEBUG")
    try:
        yield sink
    finally:
        logger.remove(handler)


@pytest.mark.asyncio
async def test_a_gateway_that_is_down_says_so_once_not_once_per_retry(
    captured_logs,
) -> None:
    # Until 2026-08-27 every failure here was swallowed with no log at
    # any level. The owner watched JARVIS not answer three times in nine
    # minutes with nothing anywhere on the machine to read.
    #
    # Once, though, not once per attempt: a gateway that is simply down
    # would otherwise write a line every `retry_seconds` for as long as
    # it is down.
    client = GatewayClient("ws://127.0.0.1:1/ws")
    client.retry_seconds = 0.02
    task = asyncio.create_task(client.run())
    await asyncio.sleep(0.3)  # bounded: ~10 attempts at 0.02 s
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    logged = captured_logs.getvalue()
    assert logged.count("no puedo conectar") == 1
    assert "WARNING" in logged
    # The rest are there, quietly, for whoever turns the level down.
    assert "sigo sin conectar" in logged


@pytest.mark.asyncio
async def test_a_dropped_connection_is_a_warning_and_the_reconnect_is_logged(
    captured_logs,
) -> None:
    # "dropped at 11:25:18, back at 11:25:20" — the two lines a reader
    # needs, and neither existed.
    async def handler(ws):
        await ws.close()

    async with websockets.serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        client = GatewayClient(f"ws://127.0.0.1:{port}/ws")
        client.retry_seconds = 0.05
        task = asyncio.create_task(client.run())
        await asyncio.sleep(0.3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    logged = captured_logs.getvalue()
    assert "conexión perdida" in logged
    assert logged.count("conectado a") >= 2  # it came back, and said so


@pytest.mark.asyncio
async def test_a_send_on_a_dead_socket_settles_the_turn_instead_of_raising() -> None:
    # The other half of a silent loss: an exception out of `send_chat`
    # escapes into the task `__main__` spawned for the turn, which dies
    # with no log and leaves the wave in `thinking` for as long as the
    # strip is up.
    class _Dead:
        async def send(self, _payload):
            raise ConnectionResetError("socket ya cerrado")

    client = GatewayClient()
    said: list[str] = []
    client.on_error = said.append
    client._ws = _Dead()

    await client.send_chat("¿me oyes?")  # must not raise

    assert said and said[0]  # he says something rather than going quiet
