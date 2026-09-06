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
        on_utterance: Callable[[bytes, object | None], None] = lambda _pcm, _e=None: (
            None
        ),
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
        # Whether a tool is outstanding, per the gateway's hooks. Only
        # ever cleared by `_settle` or by an explicit off — see
        # `working`.
        self._working = False

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

    def heard(self, pcm: bytes, endpoint: object | None = None) -> None:
        """A complete utterance. Transcription and dispatch follow.

        `endpoint` is a phone's, or `None` for the desk microphone — and
        it travels bound to THIS `pcm`, in this one synchronous call,
        never stored. Task 14 (round 2) removed a shared slot
        (`TurnOrigin.pending`) that used to carry a phone's endpoint
        from here into `dispatch` separately from its audio: written by
        one call and read by another, with two real scheduling hops in
        between (`loop.call_soon_threadsafe`, then the spawned task
        actually starting). Two phones are two concurrent handler tasks
        on the same loop, so a SECOND phone's `heard()` landing before
        the FIRST phone's audio had been taken out of that slot was
        ordinary rather than exotic, and it crossed their identities —
        the first phone's turn settled holding the second phone's
        claim. Passing `endpoint` straight through as an argument, paired
        with `pcm` in the same call and recaptured fresh in whatever
        closure schedules the next step, closes the race by
        construction: there is no gap between "receiving it" and
        "using it" for a second call to land in.
        """
        self._heard_token = False
        self._go(WaveState.THINKING)
        self._on_utterance(pcm, endpoint)

    def typed(self) -> None:
        """A line was typed at him on the strip (user, 2026-08-26).

        The sibling of `heard`, minus the audio: there is no utterance to
        transcribe, so nothing is dispatched from here — the caller has
        the text already and sends it. What this owns is the wave, which
        must show he is thinking about it exactly as if it had been said.
        """
        self._heard_token = False
        self._go(WaveState.THINKING)

    def working(self, on: bool) -> None:
        """He is doing something, or has stopped doing it.

        Driven from the gateway's `pre_tool_call` / `post_tool_call`
        hooks, not from anything the strip can see: looking at a camera,
        searching the web or filing a reminder are invisible from here,
        and until 2026-09-06 a turn that spent thirty seconds on two
        searches looked exactly like one that was slow to answer.

        `WORKING` has existed in `wave_model` since the widget was
        built — drawn, and its pulses tuned (`wave.py`) — and nothing
        had ever switched it on.

        **Off returns to THINKING, never to IDLE.** The tool finished;
        the turn did not, and he is about to answer. Dropping to IDLE
        here would say the exchange is over a second before he speaks.
        The guard on the current state matters for the same reason: a
        `post_tool_call` that lands after he has already started
        speaking must not drag the wave backwards.

        Nothing here trusts the count to come back. `_settle` clears
        this flag, so a lost `post_tool_call` on the gateway side costs
        a wave that pulses until the turn ends — not one that pulses
        for ever.
        """
        self._working = bool(on)
        if on:
            self._go(WaveState.WORKING)
        elif self.state is WaveState.WORKING:
            self._go(WaveState.THINKING)

    def token(self, text: str) -> None:
        """A real token — system frames are filtered before they get here."""
        del text
        self._heard_token = True
        self._go(WaveState.SPEAKING)

    def done(self) -> bool:
        """End the turn, but only if she actually said something.

        Returns whether the turn settled. This machine is shared by
        every conversation the house is having at once — it draws ONE
        wave, and `_heard_token` is one flag, not one per `chat_id` —
        so from 2026-09-06 (final review, CLAUDE.md) its return value
        is used ONLY to decide the WAVE. `__main__.on_done` used to
        also read it to decide whether to give a phone's claim back;
        that was wrong the moment two conversations could be open at
        once, because a `done` for one can consume this flag and make
        a DIFFERENT conversation's `done`, arriving after, report
        `False` for a reply that really did arrive. That decision is
        made per-`chat_id` now, from `TurnChunkers.has` — see its
        docstring — which shares nothing between conversations because
        nothing here does either.
        """
        if not self._heard_token:
            # A `done` belonging to a system message the filter dropped.
            # Settling here would drop the wave out of `thinking` while
            # the model is still composing.
            return False
        self._settle()
        return True

    def error(self, message: str) -> None:
        """Unlike `done`, this always settles: the turn is over either way."""
        del message  # the caller decides whether to say it out loud
        self._settle()

    def _settle(self) -> None:
        self.interrupted = False
        self._heard_token = False
        # The safety net for the whole feature: whatever the gateway
        # last said about a tool, a turn that has ended is not working.
        # A dropped `post_tool_call` must cost one turn, never the wave.
        self._working = False
        self._go(WaveState.IDLE)
