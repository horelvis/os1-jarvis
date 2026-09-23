"""A short word while he is still working, so a slow turn is not a silence.

§1 (2026-09-06): *"silence during a slow search reads as a hang rather than
as restraint"* — and the owner, 2026-09-23, asked for exactly this after a
tool-using turn sat quiet for seconds: *"debería decir algo previamente para
no dar la sensación de que se queda colgado"*.

It is a FILLER, not an answer: it fires only if the reply has not begun to
sound within `DELAY`, and it is cancelled by the reply starting, so a fast
turn says nothing at all. Pure state, no GTK and no audio — the same split
`wake.py` and `photo.py` make.
"""

from __future__ import annotations

import itertools
import os

# Short, in his voice, and over quickly: this plays under the wait, it does
# not add to it. No "estoy procesando" — that is machinery out loud (§1).
PHRASES: tuple[str, ...] = (
    "Mmm…",
    "Déjame ver…",
    "Un momento, señor.",
    "Voy a mirarlo…",
)

# How long a turn may stay silent before he says something. Long enough
# that a normal reply never triggers it, short enough that a tool round
# trip does. `JARVIS_WIDGET_FILLER_DELAY=0` disables the filler.
try:
    DELAY = float(os.environ.get("JARVIS_WIDGET_FILLER_DELAY", "1.6"))
except ValueError:
    DELAY = 1.6


class Filler:
    """Hands out one short phrase per slow turn, rotating through them."""

    def __init__(self, phrases: tuple[str, ...] = PHRASES) -> None:
        self._cycle = itertools.cycle(phrases or PHRASES)

    def phrase(self) -> str:
        return next(self._cycle)
