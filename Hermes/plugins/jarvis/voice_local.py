"""Hermes-owned implementation pieces for ``jarvis.local-voice.v1``.

This module intentionally has no widget dependency.  Hermes has no local STT
worker yet, so the route using it fails closed at readiness rather than sending
phone audio to the widget or to a cloud provider.
"""

from __future__ import annotations

import asyncio
import json
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from aiohttp import WSMsgType, web

PROTOCOL = "jarvis.local-voice.v1"
MAX_TURN = 2**32 - 1
MAX_INPUT_PCM = 3200
MAX_OUTPUT_PCM = 48000
MAX_EVENTS = 256
RESERVED_EVENTS = 4
MAX_JSON_BYTES = 65536
RESERVED_JSON_BYTES = 2048
MAX_PCM_BYTES = 384000


class VoiceProtocolError(ValueError):
    """A local voice v1 frame violates its frozen wire contract."""


def _reject_constant(value: str) -> None:
    raise VoiceProtocolError("invalid JSON constant")


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise VoiceProtocolError("duplicate JSON key")
        result[key] = value
    return result


def decode_json(raw: str) -> dict[str, Any]:
    if len(raw.encode("utf-8")) > 16384:
        raise VoiceProtocolError("message too large")
    try:
        value = json.loads(raw, object_pairs_hook=_no_duplicates, parse_constant=_reject_constant)
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise VoiceProtocolError("invalid JSON") from exc
    if not isinstance(value, dict):
        raise VoiceProtocolError("message must be an object")
    return value


def validate_client(frame: dict[str, Any], *, ready: bool) -> None:
    kind = frame.get("type")
    allowed = {
        "hello": {"type", "protocol", "processing"},
        "microphone": {"type", "enabled"},
        "cancel": {"type", "turn"},
    }
    if kind not in allowed or set(frame) != allowed[kind]:
        raise VoiceProtocolError("invalid client message")
    if kind == "hello":
        if (
            ready
            or not isinstance(frame["protocol"], str)
            or not isinstance(frame["processing"], str)
        ):
            raise VoiceProtocolError("invalid hello")
    elif kind == "microphone":
        if not ready or type(frame["enabled"]) is not bool:
            raise VoiceProtocolError("invalid microphone")
    else:
        turn = frame["turn"]
        if not ready or type(turn) is not int or not 1 <= turn <= MAX_TURN:
            raise VoiceProtocolError("invalid turn")


def validate_input_pcm(data: bytes) -> None:
    if not 2 <= len(data) <= MAX_INPUT_PCM or len(data) % 2:
        raise VoiceProtocolError("invalid input PCM")


def encode_pcm(turn: int, pcm: bytes) -> bytes:
    if type(turn) is not int or not 1 <= turn <= MAX_TURN:
        raise VoiceProtocolError("invalid output turn")
    if not 2 <= len(pcm) <= MAX_OUTPUT_PCM or len(pcm) % 2:
        raise VoiceProtocolError("invalid output PCM")
    return turn.to_bytes(4, "big") + pcm


def ready_frame() -> dict[str, Any]:
    return {"type": "ready", "protocol": PROTOCOL, "processing": "local-only", "input_rate": 16000, "output_rate": 24000, "format": "pcm_s16le", "channels": 1}


def _server_frame(kind: str, turn: int | None = None, **fields: Any) -> dict[str, Any]:
    frame: dict[str, Any] = {"type": kind, **fields}
    if turn is not None:
        if type(turn) is not int or not 1 <= turn <= MAX_TURN:
            raise VoiceProtocolError("invalid server turn")
        frame["turn"] = turn
    return frame


@dataclass
class _Queued:
    payload: str | bytes
    json_bytes: int = 0
    pcm_bytes: int = 0


class OrderedWriter:
    """One bounded ordered JSON/binary writer, with terminal capacity reserved."""

    def __init__(self, ws: web.WebSocketResponse) -> None:
        self._ws = ws
        self._queue: deque[_Queued] = deque()
        self._events = self._json_bytes = self._pcm_bytes = 0
        self._wake = asyncio.Event()
        self._empty = asyncio.Event()
        self._empty.set()
        self._closed = False
        self._task = asyncio.create_task(self._run())

    async def send_json(self, frame: dict[str, Any], *, terminal: bool = False) -> bool:
        encoded = json.dumps(frame, separators=(",", ":"), ensure_ascii=False)
        size = len(encoded.encode("utf-8"))
        if size > 16384:
            raise VoiceProtocolError("output JSON too large")
        return await self._enqueue(_Queued(encoded, json_bytes=size), terminal=terminal)

    async def send_pcm(self, turn: int, pcm: bytes) -> bool:
        return await self._enqueue(_Queued(encode_pcm(turn, pcm), pcm_bytes=len(pcm)))

    async def _enqueue(self, item: _Queued, *, terminal: bool = False) -> bool:
        if self._closed:
            return False
        event_limit = MAX_EVENTS if terminal else MAX_EVENTS - RESERVED_EVENTS
        json_limit = MAX_JSON_BYTES if terminal else MAX_JSON_BYTES - RESERVED_JSON_BYTES
        if (
            self._events >= event_limit
            or self._json_bytes + item.json_bytes > json_limit
            or self._pcm_bytes + item.pcm_bytes > MAX_PCM_BYTES
        ):
            return False
        self._queue.append(item)
        self._empty.clear()
        self._events += 1
        self._json_bytes += item.json_bytes
        self._pcm_bytes += item.pcm_bytes
        self._wake.set()
        return True

    async def _run(self) -> None:
        while not self._closed:
            await self._wake.wait()
            # Clear before draining so a producer racing the last write cannot
            # lose its wakeup between an empty-queue check and clear().
            self._wake.clear()
            while self._queue and not self._closed:
                item = self._queue.popleft()
                self._events -= 1
                self._json_bytes -= item.json_bytes
                self._pcm_bytes -= item.pcm_bytes
                try:
                    if isinstance(item.payload, bytes):
                        await self._ws.send_bytes(item.payload)
                    else:
                        await self._ws.send_str(item.payload)
                except (ConnectionResetError, RuntimeError):
                    self._closed = True
            if not self._queue:
                self._empty.set()

    async def drain(self) -> None:
        await self._empty.wait()

    async def close(self) -> None:
        self._closed = True
        self._wake.set()
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass


class VoiceLocalSession:
    """Per-peer state. A connection generation is captured by the adapter."""

    def __init__(
        self,
        ws: web.WebSocketResponse,
        *,
        provider_ready: Callable[[], bool],
        on_pcm: Callable[[bytes], Awaitable[None]] | None = None,
    ) -> None:
        self.ws = ws
        self.writer = OrderedWriter(ws)
        self._provider_ready = provider_ready
        self._on_pcm = on_pcm
        self.ready = False
        self.microphone = False
        self._next_turn = 1
        self._open_turn: int | None = None
        self._terminal: set[int] = set()

    async def run(self) -> None:
        try:
            async for message in self.ws:
                if message.type is WSMsgType.TEXT:
                    await self._text(message.data)
                elif message.type is WSMsgType.BINARY:
                    await self._pcm(message.data)
                elif message.type is WSMsgType.ERROR:
                    break
        finally:
            await self.writer.close()

    async def _text(self, raw: str) -> None:
        try:
            frame = decode_json(raw)
            validate_client(frame, ready=self.ready)
        except VoiceProtocolError:
            await self._session_error("invalid_message", 1008)
            return
        kind = frame["type"]
        if kind == "hello":
            if frame["protocol"] != PROTOCOL:
                await self._session_error("protocol_mismatch", 1008)
            elif frame["processing"] != "local-only":
                await self._session_error("local_only_required", 1008)
            elif not self._provider_ready():
                await self._session_error("provider_unavailable", 1013)
            else:
                self.ready = True
                await self.writer.send_json(ready_frame())
        elif kind == "microphone":
            self.microphone = frame["enabled"]
            if not self.microphone and self._open_turn is not None:
                await self.finish(self._open_turn, "cancelled", work_state="stopped")
        else:
            turn = frame["turn"]
            if turn > self._next_turn - 1:
                await self._session_error("invalid_turn", 1008)
            elif turn not in self._terminal:
                await self.finish(turn, "cancelled", work_state="stopped")

    async def _pcm(self, data: bytes) -> None:
        try:
            validate_input_pcm(data)
        except VoiceProtocolError:
            await self._session_error("invalid_message", 1008)
            return
        if not self.ready or not self.microphone:
            await self._session_error("audio_disabled", 1008)
            return
        if self._on_pcm is None:
            # This cannot happen after a truthful readiness check, but protects
            # a provider disappearing between hello and the first microphone frame.
            await self._session_error("provider_unavailable", 1013)
            return
        if self._open_turn is None:
            if self._next_turn > MAX_TURN:
                await self._session_error("turn_exhausted", 1000)
                return
            self._open_turn = self._next_turn
            self._next_turn += 1
            await self.writer.send_json(_server_frame("turn_started", self._open_turn))
        await self._on_pcm(data)

    async def transcript(self, turn: int, text: str) -> bool:
        if turn != self._open_turn or turn in self._terminal or len(text) > 2048:
            return False
        await self.writer.send_json(_server_frame("speech_stopped", turn))
        return await self.writer.send_json(_server_frame("transcript", turn, text=text))

    async def response(self, turn: int, text: str, pcm: list[bytes] | None = None) -> bool:
        if turn != self._open_turn or turn in self._terminal or not text or len(text) > 2048:
            return False
        if not await self.writer.send_json(_server_frame("text", turn, delta=text)):
            return False
        for chunk in pcm or []:
            if not await self.writer.send_pcm(turn, chunk):
                return False
        return await self.finish(turn, "completed")

    async def finish(self, turn: int, status: str, *, work_state: str | None = None) -> bool:
        if turn in self._terminal:
            return True
        frame = _server_frame("turn_done", turn, status=status)
        if status == "cancelled" and work_state is not None:
            frame["work_state"] = work_state
        sent = await self.writer.send_json(frame, terminal=True)
        self._terminal.add(turn)
        if self._open_turn == turn:
            self._open_turn = None
        return sent

    async def _session_error(self, code: str, close_code: int) -> None:
        await self.writer.send_json(_server_frame("error", code=code), terminal=True)
        await self.writer.drain()
        await self.ws.close(code=close_code)
