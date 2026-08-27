"""The one piece of wiring in `__main__.py` worth pinning on its own.

`__main__.py` is glue — GTK, threads, a websocket — and nothing else in
this suite imports it. `_settles_a_held_question` is the exception: a
one-line decision with a real consequence (whether the wake window is
extended after the gateway's `silence()`), pulled out as a pure
function so it can be tested without a strip, a socket or a display.
"""

from samantha_widget.__main__ import _settles_a_held_question


def test_an_empty_error_settles_a_held_question():
    # adapter.py's silence() — the user's own sentence, diverted to the
    # code assistant as the answer to a gate or held question.
    assert _settles_a_held_question("") is True


def test_a_real_error_is_not_an_answer():
    # _TURN_LOST, _BAD_FRAME and every other error() carry Spanish text.
    assert _settles_a_held_question("Algo se ha quedado a medias.") is False
