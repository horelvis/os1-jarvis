"""The state machine, with every I/O boundary faked.

What is being tested is the sequence a person sees: the line answers
their voice, goes quiet while she thinks, moves while she talks, and
settles. Getting that wrong is not a crash — it is a strip that looks
broken.

The `done` rule is not what the plan first assumed. The gateway sends
its own system messages as token frames, each followed by its own
`done`; one turn produced six (docs/…-widget-gateway-probe.md §4). A
`done` therefore only ends a turn if a real token arrived since the
last one.
"""

from jarvis_widget.turn import TurnMachine
from jarvis_widget.wave_model import WaveState


def _machine() -> tuple[TurnMachine, list[WaveState]]:
    seen: list[WaveState] = []
    machine = TurnMachine(on_state=seen.append, on_level=lambda _level: None)
    return machine, seen


def _up_to_thinking(machine: TurnMachine) -> None:
    machine.speech_started()
    machine.heard(b"\x00\x00" * 16000)


def test_it_starts_idle() -> None:
    machine, _ = _machine()

    assert machine.state is WaveState.IDLE


def test_hearing_speech_moves_to_listening() -> None:
    machine, _ = _machine()
    machine.speech_started()

    assert machine.state is WaveState.LISTENING


def test_a_finished_utterance_moves_to_thinking() -> None:
    machine, _ = _machine()
    _up_to_thinking(machine)

    assert machine.state is WaveState.THINKING


def test_the_first_token_moves_to_speaking() -> None:
    machine, _ = _machine()
    _up_to_thinking(machine)
    machine.token("Hola, ")

    assert machine.state is WaveState.SPEAKING


def test_done_after_a_real_token_returns_to_idle() -> None:
    machine, _ = _machine()
    _up_to_thinking(machine)
    machine.token("Hola, me alegro de oírte.")
    machine.done()

    assert machine.state is WaveState.IDLE


def test_done_with_no_token_does_not_end_the_turn() -> None:
    """The gateway's system messages each carry their own `done`.

    Settling here would drop the wave out of `thinking` while the model
    is still composing, and flush the clause buffer mid-reply.
    """
    machine, _ = _machine()
    _up_to_thinking(machine)
    machine.done()  # the `done` that followed "📬 No home channel…"

    assert machine.state is WaveState.THINKING


def test_a_turn_survives_several_system_dones_before_the_real_one() -> None:
    """Exactly the six-done turn that was measured."""
    machine, _ = _machine()
    _up_to_thinking(machine)
    for _ in range(3):
        machine.done()
    assert machine.state is WaveState.THINKING

    machine.token("La lluvia no pide permiso.")
    machine.done()

    assert machine.state is WaveState.IDLE


def test_done_with_no_token_reports_that_it_did_not_settle() -> None:
    """The return value now decides only the WAVE (see `done`'s own
    docstring, final review 2026-09-06): a caller must not drop the
    wave out of `thinking` on a `done` that belongs to one of the
    gateway's own system messages, which this reports by returning
    `False`.
    """
    machine, _ = _machine()
    _up_to_thinking(machine)

    assert machine.done() is False
    assert machine.state is WaveState.THINKING


def test_done_after_a_real_token_reports_that_it_settled() -> None:
    machine, _ = _machine()
    _up_to_thinking(machine)
    machine.token("Hola, me alegro de oírte.")

    assert machine.done() is True
    assert machine.state is WaveState.IDLE


def test_a_second_reply_still_needs_its_own_token() -> None:
    """The flag resets on settle, so the next stray `done` is ignored too."""
    machine, _ = _machine()
    _up_to_thinking(machine)
    machine.token("Primero esto.")
    machine.done()
    machine.done()  # ⚠️ Couldn't deliver the audio attachment.

    assert machine.state is WaveState.IDLE  # unchanged, and no crash


def test_an_error_returns_to_idle_even_with_no_token() -> None:
    """A turn that failed must not leave the line stuck in `thinking`."""
    machine, _ = _machine()
    _up_to_thinking(machine)
    machine.error("algo se ha quedado a medias")

    assert machine.state is WaveState.IDLE


def test_speaking_while_she_speaks_interrupts_her() -> None:
    machine, _ = _machine()
    _up_to_thinking(machine)
    machine.token("Estaba diciendo algo bastante largo.")
    machine.speech_started()  # the user cuts in

    assert machine.state is WaveState.LISTENING
    assert machine.interrupted is True


def test_every_state_change_is_announced_once() -> None:
    machine, seen = _machine()
    machine.speech_started()
    machine.speech_started()  # same state again

    assert seen.count(WaveState.LISTENING) == 1


def test_an_utterance_reaches_the_caller() -> None:
    heard: list[tuple[bytes, object | None]] = []
    machine = TurnMachine(
        on_state=lambda _s: None,
        on_level=lambda _level: None,
        on_utterance=lambda pcm, endpoint: heard.append((pcm, endpoint)),
    )
    machine.speech_started()
    machine.heard(b"\x01\x02" * 100)

    assert heard == [(b"\x01\x02" * 100, None)]


def test_an_utterance_carries_its_own_endpoint() -> None:
    """The desk microphone has none — `None` — and a phone's travels
    bound to its OWN pcm, passed straight through in the same call
    (task 14, round 2: this replaces a shared slot a second utterance
    could overwrite before the first had been read)."""
    heard: list[tuple[bytes, object | None]] = []
    machine = TurnMachine(
        on_state=lambda _s: None,
        on_level=lambda _level: None,
        on_utterance=lambda pcm, endpoint: heard.append((pcm, endpoint)),
    )
    marta, lucia = object(), object()

    machine.heard(b"audio-de-marta", marta)
    machine.heard(b"audio-de-lucia", lucia)

    assert heard == [(b"audio-de-marta", marta), (b"audio-de-lucia", lucia)]


def test_done_is_one_flag_for_every_conversation_and_must_not_gate_a_settle() -> None:
    """`TurnMachine` is the one piece of state left in `__main__.py`
    that is shared across every conversation (final review, 2026-09-06,
    CLAUDE.md) — `_heard_token` is a single flag, not one per
    `chat_id`. This characterises exactly why: a `done` for one
    conversation consumes the flag, so a SECOND conversation's `done`
    — for a real reply of its own — can find nothing left to consume
    and report it did not settle. `__main__.on_done` no longer reads
    this return value to decide whether to release a claim (see
    `TurnChunkers.has` and `test_main.py`'s
    `test_two_conversations_dones_interleaved_release_both_claims`);
    `done()` still drives the wave, and this is why it may not drive
    anything else.
    """
    machine, _ = _machine()
    _up_to_thinking(machine)

    machine.token("Hola, marta.")  # marta's real reply
    machine.token("Hola, lucía.")  # lucía's, interleaved before either `done`

    assert machine.done() is True  # marta's `done` — consumes the flag
    assert machine.done() is False  # lucía's `done` — swallowed


def test_two_utterances_scheduled_out_of_order_do_not_cross() -> None:
    """The exact race task 14 (round 2) closes, reproduced at the shape
    it actually happens in: in production, `__main__.py`'s own
    `on_utterance` closure hands `(pcm, endpoint)` to
    `loop.call_soon_threadsafe`, a real gap between `heard()` returning
    and the scheduled call actually running — and two phones are two
    concurrent handler tasks on that same loop, so their two `heard()`
    calls can be scheduled in either order relative to when each
    scheduled callback is actually RUN. The removed `TurnOrigin.pending`
    was a single slot written by the first call and read by whichever
    scheduled callback ran next — so reordering crossed identities.
    Nothing is shared here: each scheduled callback closes over its OWN
    `pcm`/`endpoint`, captured at `heard()`-time, so running them in the
    OPPOSITE order they were produced still pairs each correctly."""
    scheduled: list = []
    dispatched: list[tuple[bytes, object | None]] = []

    def on_utterance(pcm: bytes, endpoint: object | None) -> None:
        # Mimics `loop.call_soon_threadsafe(lambda: self._spawn(dispatch(pcm, endpoint)))`:
        # a fresh closure per call, queued to run later, in whatever
        # order the loop gets to it.
        scheduled.append(lambda: dispatched.append((pcm, endpoint)))

    machine = TurnMachine(
        on_state=lambda _s: None,
        on_level=lambda _level: None,
        on_utterance=on_utterance,
    )
    marta, lucia = object(), object()

    machine.heard(b"audio-de-marta", marta)
    machine.heard(b"audio-de-lucia", lucia)

    # Lucía's scheduled dispatch actually runs FIRST — the reordering
    # two concurrent handler tasks on the same loop can produce.
    for call in reversed(scheduled):
        call()

    assert dispatched == [(b"audio-de-lucia", lucia), (b"audio-de-marta", marta)]


def test_a_typed_line_shows_him_thinking() -> None:
    # The sibling of `heard`, minus the audio: nothing is dispatched,
    # because the caller already has the text (user, 2026-08-26).
    states, utterances = [], []
    m = TurnMachine(
        on_state=states.append,
        on_level=lambda _v: None,
        on_utterance=utterances.append,
        on_interrupt=lambda: None,
    )
    m.typed()
    assert states[-1] is WaveState.THINKING
    assert utterances == []


def test_an_empty_error_settles_the_line_with_nothing_said() -> None:
    """The frame a diverted turn ends on, pinned here because the
    gateway now depends on it.

    When the user answers the code assistant, the jarvis adapter opens no
    turn and pushes `protocol.silence()` — an `error` frame with an
    empty message. Two halves make that work and both are already here:
    `error` always settles (unlike `done`, which needs a token), and
    `__main__.on_error` only speaks when the message is non-blank. The
    same idiom the widget already uses itself for an empty
    transcription, his own echo, and a sentence not addressed to him.
    """
    machine, states = _machine()
    _up_to_thinking(machine)
    machine.error("")

    assert machine.state is WaveState.IDLE
    assert states[-1] is WaveState.IDLE
