"""The one piece of wiring in `__main__.py` worth pinning on its own.

`__main__.py` is glue — GTK, threads, a websocket — and nothing else in
this suite imports it. `_apply_error_to_wake_window` is the exception:
it is the whole wake-window decision `on_error` makes (the predicate
AND the `wake.answered(...)` call), pulled out as a pure function that
takes a real `WakeWord` so the effect on the window — not just the
predicate that decides it — can be driven and asserted without a strip,
a socket or a display.
"""

from samantha_widget.__main__ import _apply_error_to_wake_window
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
