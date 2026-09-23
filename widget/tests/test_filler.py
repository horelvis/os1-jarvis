"""The filler: a short word while a slow turn is still working.

Pure state, like `wake.py` — no GTK, no audio. What it decides: which short
phrase to say, and that it is worth saying at all (the timing lives in
`__main__.py`, which owns the loop).
"""

import importlib

from jarvis_widget import filler as filler_module
from jarvis_widget.filler import PHRASES, Filler


def test_rotates_through_the_phrases():
    f = Filler()
    assert [f.phrase() for _ in range(len(PHRASES))] == list(PHRASES)


def test_it_keeps_going_round():
    f = Filler()
    for _ in range(len(PHRASES)):
        f.phrase()
    assert f.phrase() == PHRASES[0]


def test_the_default_delay_is_short_and_on():
    # Short enough that a tool round trip triggers it, long enough that a
    # normal reply does not. Zero would disable it, so it must not be zero.
    assert 0 < filler_module.DELAY <= 3.0


def test_the_delay_can_be_overridden_and_disabled(monkeypatch):
    monkeypatch.setenv("JARVIS_WIDGET_FILLER_DELAY", "0")
    reloaded = importlib.reload(filler_module)
    try:
        assert reloaded.DELAY == 0
    finally:
        monkeypatch.delenv("JARVIS_WIDGET_FILLER_DELAY", raising=False)
        importlib.reload(filler_module)
