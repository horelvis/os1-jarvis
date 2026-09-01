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
