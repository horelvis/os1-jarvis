"""Nucleo local y verificable para turnos de voz tipo realtime.

Este modulo no implementa STT, LLM ni TTS. Solo modela el contrato que
Jarvis necesita antes de integrar motores locales: identidad de sesion,
turno, persona y destino capturados una vez, cola lossless con backpressure,
y terminales exactamente una vez.
"""

from __future__ import annotations

import asyncio
import itertools
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Literal

EventType = Literal[
    "session.opened",
    "session.disconnected",
    "turn.started",
    "input.accepted",
    "response.text",
    "response.audio",
    "response.audio.discarded",
    "response.done",
    "response.error",
    "response.cancelled",
]


class TurnState(str, Enum):
    RECORDING = "recording"
    THINKING = "thinking"
    STREAMING = "streaming"
    CLOSING = "closing"
    DONE = "done"
    ERROR = "error"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class Destination:
    kind: Literal["room", "remote"]
    endpoint_id: str | None = None


@dataclass(frozen=True)
class Event:
    type: EventType
    session_id: str
    turn_id: str | None = None
    persona: str | None = None
    destination: Destination | None = None
    text: str = ""
    audio: bytes = b""
    reason: str = ""
    count: int = 0


@dataclass
class Session:
    session_id: str
    persona: str
    destination: Destination
    connected: bool = True
    current_turn_id: str | None = None


@dataclass
class PendingTerminal:
    event_type: EventType
    final_state: TurnState
    reason: str


@dataclass
class Turn:
    turn_id: str
    session_id: str
    persona: str
    destination: Destination
    state: TurnState = TurnState.RECORDING
    transcript: str = ""
    slow_task: asyncio.Task[object] | None = None
    pending_terminal: PendingTerminal | None = None
    terminal_emitted: bool = False


class LocalTurnEngine:
    """Turn registry with one bounded, lossless transport queue.

    The queue never drops normal output to make room for later output. When it
    is full, producers wait. The only discard policy is explicit: cancelling a
    turn removes queued audio for that same turn and emits a discard event.
    """

    def __init__(self, *, queue_size: int = 64) -> None:
        if queue_size < 1:
            raise ValueError("queue_size must be positive")
        self._queue_size = queue_size
        self._events: deque[Event] = deque()
        self._changed = asyncio.Condition()
        self._ids = itertools.count(1)
        self._sessions: dict[str, Session] = {}
        self._session_locks: dict[str, asyncio.Lock] = {}
        self._turns: dict[str, Turn] = {}
        self._active_by_session: dict[str, str] = {}

    async def open_session(self, persona: str, destination: Destination) -> str:
        session_id = f"s-{next(self._ids)}"
        session = Session(session_id, persona, destination)
        event = Event("session.opened", session_id, persona=persona)
        async with self._changed:
            await self._wait_for_queue_space_locked()
            self._sessions[session_id] = session
            self._session_locks[session_id] = asyncio.Lock()
            self._events.append(event)
            self._changed.notify_all()
        return session_id

    async def disconnect(self, session_id: str) -> None:
        async with self._changed:
            session = self._sessions.get(session_id)
            if session is None:
                return
            session.connected = False
            active_turn = self._active_by_session.get(session_id)
            self._changed.notify_all()
        if active_turn is not None:
            await self.cancel(active_turn, "session disconnected")
        await self._publish_system(Event("session.disconnected", session_id))

    async def start_turn(self, session_id: str) -> str:
        async with self._changed:
            session = self._require_session_locked(session_id)
            if not session.connected:
                raise RuntimeError("session is disconnected")
            session_lock = self._session_locks[session_id]

        async with session_lock:
            async with self._changed:
                session = self._require_session_locked(session_id)
                if not session.connected:
                    raise RuntimeError("session is disconnected")
                active_turn = self._active_by_session.get(session_id)
            if active_turn is not None:
                await self.cancel(active_turn, "superseded by new turn")

            turn_id = f"t-{next(self._ids)}"
            async with self._changed:
                session = self._require_session_locked(session_id)
                if not session.connected:
                    raise RuntimeError("session is disconnected")
                ready = await self._wait_for_queue_space_locked(
                    lambda: (
                        self._sessions.get(session_id) is session and session.connected
                    )
                )
                if not ready:
                    raise RuntimeError("session is disconnected")
                turn = Turn(
                    turn_id=turn_id,
                    session_id=session_id,
                    persona=session.persona,
                    destination=session.destination,
                )
                self._turns[turn_id] = turn
                self._active_by_session[session_id] = turn_id
                session.current_turn_id = turn_id
                self._events.append(
                    Event(
                        "turn.started",
                        session_id,
                        turn_id,
                        persona=turn.persona,
                        destination=turn.destination,
                    )
                )
                self._changed.notify_all()
            return turn_id

    async def accept_input(self, turn_id: str, transcript: str) -> bool:
        clean = transcript.strip()
        if not clean:
            await self.error(turn_id, "empty transcription")
            return False

        async with self._changed:
            turn = self._turns.get(turn_id)
            if not self._input_can_be_accepted_locked(turn):
                return False
            ready = await self._wait_for_queue_space_locked(
                lambda: self._input_can_be_accepted_locked(self._turns.get(turn_id))
            )
            if not ready:
                return False
            turn = self._require_turn_locked(turn_id)
            if not self._input_can_be_accepted_locked(turn):
                return False
            turn.transcript = clean
            turn.state = TurnState.THINKING
            self._events.append(
                Event(
                    "input.accepted",
                    turn.session_id,
                    turn.turn_id,
                    persona=turn.persona,
                    destination=turn.destination,
                    text=clean,
                )
            )
            self._changed.notify_all()
            return True

    async def stream_text(self, turn_id: str, text: str) -> bool:
        return await self._publish_response(
            turn_id,
            lambda turn: Event(
                "response.text",
                turn.session_id,
                turn.turn_id,
                persona=turn.persona,
                destination=turn.destination,
                text=text,
            ),
        )

    async def stream_audio(self, turn_id: str, chunk: bytes) -> bool:
        payload = bytes(chunk)
        return await self._publish_response(
            turn_id,
            lambda turn: Event(
                "response.audio",
                turn.session_id,
                turn.turn_id,
                persona=turn.persona,
                destination=turn.destination,
                audio=payload,
            ),
        )

    async def finish(self, turn_id: str) -> bool:
        return await self._publish_terminal(
            turn_id, PendingTerminal("response.done", TurnState.DONE, "")
        )

    async def error(self, turn_id: str, reason: str) -> bool:
        return await self._publish_terminal(
            turn_id, PendingTerminal("response.error", TurnState.ERROR, reason)
        )

    async def cancel(self, turn_id: str, reason: str = "cancelled") -> bool:
        return await self._publish_terminal(
            turn_id,
            PendingTerminal("response.cancelled", TurnState.CANCELLED, reason),
            cancel_slow_task=True,
            discard_pending_audio=True,
        )

    def attach_slow_task(self, turn_id: str, task: asyncio.Task[object]) -> None:
        turn = self._turns.get(turn_id)
        if turn is None:
            raise KeyError(turn_id)
        turn.slow_task = task

    async def recover_pending_terminals(self) -> int:
        """Try to deliver terminals reserved by cancelled publisher tasks."""

        async with self._changed:
            turn_ids = [
                turn.turn_id
                for turn in self._turns.values()
                if turn.pending_terminal is not None and not turn.terminal_emitted
            ]
        delivered = 0
        for turn_id in turn_ids:
            if await self._publish_terminal(turn_id, None):
                delivered += 1
        return delivered

    async def get_event(self) -> Event:
        async with self._changed:
            while not self._events:
                await self._changed.wait()
            event = self._events.popleft()
            self._changed.notify_all()
            return event

    async def drain_available(self) -> list[Event]:
        async with self._changed:
            drained = list(self._events)
            self._events.clear()
            self._changed.notify_all()
            return drained

    async def queued_count(self) -> int:
        async with self._changed:
            return len(self._events)

    async def turn_state(self, turn_id: str) -> TurnState:
        async with self._changed:
            return self._require_turn_locked(turn_id).state

    async def _publish_response(self, turn_id: str, make_event) -> bool:
        async with self._changed:
            turn = self._turns.get(turn_id)
            if not self._response_can_be_published_locked(turn):
                return False
            ready = await self._wait_for_queue_space_locked(
                lambda: self._response_can_be_published_locked(self._turns.get(turn_id))
            )
            if not ready:
                return False
            turn = self._require_turn_locked(turn_id)
            if not self._response_can_be_published_locked(turn):
                return False
            turn.state = TurnState.STREAMING
            self._events.append(make_event(turn))
            self._changed.notify_all()
            return True

    async def _publish_terminal(
        self,
        turn_id: str,
        terminal: PendingTerminal | None,
        *,
        cancel_slow_task: bool = False,
        discard_pending_audio: bool = False,
    ) -> bool:
        async with self._changed:
            turn = self._turns.get(turn_id)
            if turn is None or turn.terminal_emitted:
                return False

            if turn.pending_terminal is None:
                if terminal is None:
                    return False
                turn.pending_terminal = terminal
                turn.state = TurnState.CLOSING
                self._clear_active_turn_locked(turn)
                if cancel_slow_task and turn.slow_task is not None:
                    turn.slow_task.cancel()
                self._changed.notify_all()
                if discard_pending_audio:
                    discarded = self._discard_audio_locked(turn_id)
                    if discarded:
                        await self._wait_for_queue_space_locked()
                        self._events.append(
                            Event(
                                "response.audio.discarded",
                                turn.session_id,
                                turn.turn_id,
                                persona=turn.persona,
                                destination=turn.destination,
                                reason=terminal.reason,
                                count=discarded,
                            )
                        )
                        self._changed.notify_all()

            while len(self._events) >= self._queue_size:
                await self._changed.wait()
                turn = self._turns.get(turn_id)
                if turn is None or turn.terminal_emitted:
                    return False

            turn = self._require_turn_locked(turn_id)
            pending = turn.pending_terminal
            if pending is None or turn.terminal_emitted:
                return False
            self._events.append(
                Event(
                    pending.event_type,
                    turn.session_id,
                    turn.turn_id,
                    persona=turn.persona,
                    destination=turn.destination,
                    reason=pending.reason,
                )
            )
            turn.state = pending.final_state
            turn.terminal_emitted = True
            self._changed.notify_all()
            return True

    async def _publish_system(self, event: Event) -> None:
        async with self._changed:
            await self._wait_for_queue_space_locked()
            self._events.append(event)
            self._changed.notify_all()

    async def _wait_for_queue_space_locked(self, still_relevant=None) -> bool:
        while len(self._events) >= self._queue_size:
            if still_relevant is not None and not still_relevant():
                return False
            await self._changed.wait()
        return still_relevant is None or still_relevant()

    def _discard_audio_locked(self, turn_id: str) -> int:
        kept: deque[Event] = deque()
        discarded = 0
        while self._events:
            event = self._events.popleft()
            if event.turn_id == turn_id and event.type == "response.audio":
                discarded += 1
            else:
                kept.append(event)
        self._events = kept
        if discarded:
            self._changed.notify_all()
        return discarded

    def _clear_active_turn_locked(self, turn: Turn) -> None:
        if self._active_by_session.get(turn.session_id) == turn.turn_id:
            del self._active_by_session[turn.session_id]
            self._sessions[turn.session_id].current_turn_id = None

    def _require_session_locked(self, session_id: str) -> Session:
        session = self._sessions.get(session_id)
        if session is None:
            raise KeyError(session_id)
        return session

    def _require_turn_locked(self, turn_id: str) -> Turn:
        turn = self._turns.get(turn_id)
        if turn is None:
            raise KeyError(turn_id)
        return turn

    def _input_can_be_accepted_locked(self, turn: Turn | None) -> bool:
        if turn is None or turn.state is not TurnState.RECORDING:
            return False
        session = self._sessions.get(turn.session_id)
        return session is not None and session.connected

    def _response_can_be_published_locked(self, turn: Turn | None) -> bool:
        if turn is None or turn.state not in {TurnState.THINKING, TurnState.STREAMING}:
            return False
        session = self._sessions.get(turn.session_id)
        return session is not None and session.connected
