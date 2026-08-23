"""The sequence a person sees, and the only place the pieces meet.

Deliberately free of GTK, of PortAudio and of the network: it is handed
callbacks and calls them. That is what lets the sequence be tested, and
it is also what keeps the GLib.idle_add rule enforceable in one place —
`on_state` and `on_level` are the only things that reach the UI, and
whoever constructs a TurnMachine is responsible for making them safe to
call from another thread.
"""

from __future__ import annotations

from typing import Callable

from .wave_model import WaveState


class TurnMachine:
    def __init__(
        self,
        *,
        on_state: Callable[[WaveState], None],
        on_level: Callable[[float], None],
        on_utterance: Callable[[bytes], None] = lambda _pcm: None,
        on_interrupt: Callable[[], None] = lambda: None,
    ) -> None:
        self._on_state = on_state
        self._on_level = on_level
        self._on_utterance = on_utterance
        self._on_interrupt = on_interrupt
        self.state = WaveState.IDLE
        self.interrupted = False
        # Whether a real token has arrived since the last settle. The
        # gateway emits a `done` after each of its own system messages —
        # one measured turn carried six — so `done` alone is not a turn
        # boundary. See docs/…-widget-gateway-probe.md §4.
        self._heard_token = False

    def _go(self, state: WaveState) -> None:
        if state is self.state:
            return
        self.state = state
        self._on_state(state)

    def level(self, value: float) -> None:
        self._on_level(value)

    def speech_started(self) -> None:
        """The VAD is confident someone is talking."""
        if self.state is WaveState.SPEAKING:
            # Barge-in. She stops mid-word; the alternative is two
            # people talking, which is what makes an assistant feel
            # like a machine.
            self.interrupted = True
            self._on_interrupt()
        self._go(WaveState.LISTENING)

    def heard(self, pcm: bytes) -> None:
        """A complete utterance. Transcription and dispatch follow."""
        self._heard_token = False
        self._go(WaveState.THINKING)
        self._on_utterance(pcm)

    def token(self, text: str) -> None:
        """A real token — system frames are filtered before they get here."""
        del text
        self._heard_token = True
        self._go(WaveState.SPEAKING)

    def done(self) -> None:
        """End the turn, but only if she actually said something."""
        if not self._heard_token:
            # A `done` belonging to a system message the filter dropped.
            # Settling here would drop the wave out of `thinking` while
            # the model is still composing.
            return
        self._settle()

    def error(self, message: str) -> None:
        """Unlike `done`, this always settles: the turn is over either way."""
        del message  # the caller decides whether to say it out loud
        self._settle()

    def _settle(self) -> None:
        self.interrupted = False
        self._heard_token = False
        self._go(WaveState.IDLE)
