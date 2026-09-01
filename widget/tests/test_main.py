"""The one piece of wiring in `__main__.py` worth pinning on its own.

`__main__.py` is glue — GTK, threads, a websocket — and nothing else in
this suite imports it. The two `_apply_*_to_wake*` functions are the
exception: each is a whole wake-window decision a gateway callback
makes (the predicate AND the call on `WakeWord`), pulled out as a pure
function that takes a real `WakeWord` so the effect on the window — not
just the predicate that decides it — can be driven and asserted without
a strip, a socket or a display.
"""

from samantha_widget.__main__ import (
    _apply_asking_to_wake,
    _apply_error_to_wake_window,
)
from samantha_widget.wake import WakeWord


def test_an_empty_error_extends_the_window():
    # adapter.py's silence() — the user's own sentence, diverted to the
    # code assistant as the answer to a gate or held question. He did
    # not speak, but the user did, and is plainly still in the
    # conversation.
    w = WakeWord("jarvis")
    _apply_error_to_wake_window(w, "", now=10.0)

    # Inside the extended window: no name needed.
    assert w.heard("y mañana", now=39.9) == "y mañana"
    # Past it: the window really was 30s from `now`, not open forever.
    assert w.heard("y el jueves", now=41.0) is None


def test_a_real_error_does_not_extend_the_window():
    # _TURN_LOST, _BAD_FRAME and every other error() carry Spanish text
    # and are genuine faults, not an answer to anything.
    w = WakeWord("jarvis")
    _apply_error_to_wake_window(w, "Algo se ha quedado a medias.", now=10.0)

    assert w.heard("y mañana", now=15.0) is None


def test_a_question_opening_holds_the_window_past_thirty_seconds():
    # The gateway's `asking` frame. Without it the answer to a gate the
    # user thought about for forty seconds is dropped by the strip and
    # never reaches `_should_divert` — see the function's docstring.
    w = WakeWord("jarvis")
    _apply_asking_to_wake(w, True, now=0.0)

    assert w.heard("sí, adelante", now=45.0) == "sí, adelante"


def test_the_question_resolving_shuts_it_again():
    w = WakeWord("jarvis")
    _apply_asking_to_wake(w, True, now=0.0)
    _apply_asking_to_wake(w, False, now=50.0)

    assert w.heard("y otra cosa", now=51.0) is None


def test_endpointing_is_wired_only_when_the_model_loaded(monkeypatch) -> None:
    """The two states this must have, and no third one.

    With a model: the detector is asked. Without: it is not, and nothing
    anywhere raises — which is the property that keeps a missing 39 MB
    file from costing a voice turn.
    """
    from samantha_widget.__main__ import build_may_close
    from samantha_widget.endpoint import CompletionRule

    assert build_may_close(None, CompletionRule())() is False

    class FakeStream:
        def __init__(self, text: str) -> None:
            self.text = text

        def partial(self) -> str:
            return self.text

    assert (
        build_may_close(FakeStream("enciendeme la luz del salon"), CompletionRule())()
        is True
    )
    assert (
        build_may_close(FakeStream("enciendeme la luz del"), CompletionRule())()
        is False
    )


def test_a_broken_partials_object_never_closes_a_turn() -> None:
    """Vosk throwing mid-turn must not end somebody's sentence."""
    from samantha_widget.__main__ import build_may_close
    from samantha_widget.endpoint import CompletionRule

    class Exploding:
        def partial(self) -> str:
            raise RuntimeError("boom")

    assert build_may_close(Exploding(), CompletionRule())() is False


def test_his_own_words_coming_back_are_not_an_interruption() -> None:
    """The measurement this replaces, from CLAUDE.md §2.8:

        the user's voice          RMS 0.054-0.088
        his echo, speakers away   RMS 0.027-0.035
        his echo, speakers beside RMS 0.178   ← louder than the person

    A single scalar cannot separate the last row from the first, and the
    file said so in its own comment. The widget knows what it just said,
    so this is decided on words instead: `EchoFilter` already returns ""
    when everything it was handed was his.
    """
    from samantha_widget.__main__ import build_is_a_person
    from samantha_widget.echo import EchoFilter

    echo = EchoFilter()
    echo.spoke("Buenas tardes, señor. Le cuento algo un poco más largo.", 100.0)

    class HisEcho:
        def partial(self) -> str:
            return "buenas tardes senor le cuento algo un poco mas largo"

    assert build_is_a_person(HisEcho(), echo)(101.0) is False


def test_somebody_talking_over_him_is_an_interruption() -> None:
    from samantha_widget.__main__ import build_is_a_person
    from samantha_widget.echo import EchoFilter

    echo = EchoFilter()
    echo.spoke("Buenas tardes, señor. Le cuento algo un poco más largo.", 100.0)

    class APerson:
        def partial(self) -> str:
            return "para jarvis no me interesa eso ahora mismo"

    assert build_is_a_person(APerson(), echo)(101.0) is True


def test_with_no_partials_everything_is_a_person() -> None:
    """No Vosk means falling back to the old world, where the RMS floor
    is the only gate. Refusing to interrupt would be worse than
    interrupting too easily: it is the bug being fixed."""
    from samantha_widget.__main__ import build_is_a_person
    from samantha_widget.echo import EchoFilter

    assert build_is_a_person(None, EchoFilter())(1.0) is True


def test_nothing_heard_yet_is_not_a_person() -> None:
    """Vosk has no words yet. Not an interruption, and not an error."""
    from samantha_widget.__main__ import build_is_a_person
    from samantha_widget.echo import EchoFilter

    class Nothing:
        def partial(self) -> str:
            return ""

    assert build_is_a_person(Nothing(), EchoFilter())(1.0) is False


def test_room_resets_once_per_reply_never_mid_reply() -> None:
    """Fix round 1, 2026-09-01: the first draft used `elif` on the
    busy-branch guard (`player.busy and not detector.speaking`), which is
    False for every frame of an interruption in progress — `player.busy`
    stays True until playback actually stops, while `detector.speaking`
    is already True. That fired the reset every frame throughout the
    interruption: ~31 KaldiRecognizer objects a second at the exact
    moment somebody is talking over him.

    Fix round 2's CRITICAL bug lived one level up, in the CALLER rather
    than in this decision: the assignment feeding the next `was_busy`
    back into `_busy["was"]` sat below the busy branch, which returns
    early on EVERY frame of an ordinary, uninterrupted reply (the quiet
    frame and the his-own-echo frame both return before reaching it) —
    so across a whole reply `_busy["was"]` was never actually updated and
    the reset never fired at all. `.room` then grew without bound past
    `EchoFilter`'s 45 s memory, which is worse than the bug this task
    exists to fix: he starts interrupting himself with nobody in the
    room.

    A truth table over two booleans (round 1's test) cannot catch that —
    it never exercises the CALLER's wiring, only the decision in
    isolation. This drives a whole SEQUENCE of frames through
    `_room_bookkeeping`, exactly as the callback does — one call per
    frame, always applying `next_was_busy` — and counts every reset.
    """
    from samantha_widget.__main__ import _room_bookkeeping

    # quiet, quiet — nothing has happened yet, nothing to reset
    # busy, busy, busy — one whole uninterrupted reply: never resets
    #     mid-reply, which is the frame-by-frame version of the CRITICAL
    #     bug (every one of these used to leave `was_busy` at False)
    # quiet, quiet — resets exactly once, on the frame busy ends, and
    #     not again on the quiet frame after it
    # busy — a second reply starts fresh: no leftover reset
    # quiet — resets again, once, when that one ends too
    frames = [False, False, True, True, True, False, False, True, False]

    was_busy = False
    resets = []
    for busy in frames:
        should_reset, was_busy = _room_bookkeeping(was_busy, busy)
        resets.append(should_reset)

    assert resets == [
        False,
        False,
        False,
        False,
        False,
        True,
        False,
        False,
        True,
    ]


def test_turn_resets_once_per_mic_off_toggle_never_while_it_holds() -> None:
    """Fix round 3, 2026-09-01: un-nesting `partials.turn.reset()` from
    `if detector.speaking:` (needed because `.turn` holds preroll from
    before the detector ever calls anything speech) removed a bound that
    had only ever existed by accident — `detector.reset()` on the same
    path cleared `detector.speaking`, so the branch stopped re-entering.
    Without that accident, nothing stopped the reset firing on EVERY
    frame the mic switch stayed off: ~31 `KaldiRecognizer` constructions
    a second, indefinitely, on the PortAudio thread.

    Same defect class as round 1's finding and round 2's Critical, so the
    same shape of test: a SEQUENCE of frames driven through
    `_turn_bookkeeping` exactly as the callback does — one call per
    frame, `next_was_on` always fed back — not a truth table over the
    pure function alone.
    """
    from samantha_widget.__main__ import _turn_bookkeeping

    # on, on — mic on, nothing to reset
    # off, off, off — switched off and left off for three frames: resets
    #     once, on the very first off frame, and never again while it
    #     stays off (this is exactly what round 3's bug got wrong)
    # on, on — switched back on: no reset, and no leftover state
    # off — switched off a second time: resets once more
    frames = [True, True, False, False, False, True, True, False]

    was_on = True
    resets = []
    for is_on in frames:
        should_reset, was_on = _turn_bookkeeping(was_on, is_on)
        resets.append(should_reset)

    assert resets == [
        False,
        False,
        True,
        False,
        False,
        False,
        False,
        True,
    ]
