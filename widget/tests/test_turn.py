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

from samantha_widget.turn import TurnMachine
from samantha_widget.wave_model import WaveState


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
    heard: list[bytes] = []
    machine = TurnMachine(
        on_state=lambda _s: None,
        on_level=lambda _level: None,
        on_utterance=heard.append,
    )
    machine.speech_started()
    machine.heard(b"\x01\x02" * 100)

    assert heard == [b"\x01\x02" * 100]


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
