"""The three switches on the strip: his ears, his voice, and the door.

Pure state and pure geometry — no GTK — the way `photo.py` sits under
`photo_area.py`. `wave.py` draws what this decides and asks it where a
press landed.

Asked for by the user on 2026-08-26: two buttons over the strip, one to
turn the microphone off and one to stop him speaking out loud, and later
the same day a third to close him. Until
then the strip had nothing to press at all, which CLAUDE.md §1.5 states
as a property ("no hay ventana que enfocar, ningún icono que pulsar").
It survives that in the way the photo already does: they are part of the
strip rather than a window, they are two, and they do nothing but turn
a sense off.

**Why they cannot be voice commands instead**, which is the obvious
objection: "deja de escucharme" has to be heard to be obeyed, and
"cállate" has to be heard over his own voice. Both are exactly the cases
where the voice path is what you want to interrupt. A switch you can
press is the only kind that works when the thing being switched is the
one that would have to listen.
"""

from __future__ import annotations

from dataclasses import dataclass

# Each switch's box, and the gap between them. Small: they sit on a
# 96-pixel strip beside a wave that is the actual subject, and anything
# bigger reads as a toolbar.
SIZE = 26.0
GAP = 10.0

# Distance from the strip's right edge to the last switch. The wave's own
# horizontal padding is 6 px; this is deliberately wider, so the row of
# bars visibly ends before the switches begin.
MARGIN = 16.0

MIC = "mic"
VOICE = "voice"
CLOSE = "close"

# A press on the close switch arms it; a second press within this many
# seconds shuts him down, and after it the first press is forgotten.
#
# Two presses rather than one because this is the only control on the
# strip that cannot be undone from the strip: the microphone and the
# voice come back with another press, and he comes back only from a
# terminal (`systemctl --user start samantha-widget`). A brush against
# the wrong pixel must not cost that.
ARM_SECONDS = 3.0


@dataclass(frozen=True)
class Box:
    """Where one switch is, in the strip's own coordinates."""

    name: str
    x: float
    y: float
    size: float

    def holds(self, px: float, py: float) -> bool:
        return self.x <= px <= self.x + self.size and self.y <= py <= self.y + self.size


class Switches:
    """Which senses are on, and where the three boxes are drawn."""

    def __init__(self) -> None:
        self.mic_on = True
        self.voice_on = True
        self._armed_until = 0.0

    # ── geometry ──────────────────────────────────────────────────────

    def boxes(self, width: float, height: float) -> list[Box]:
        """The three boxes, right-aligned and vertically centred.

        Right rather than left: the wave is drawn from the left and the
        eye follows it, so the switches sit where it ends. A strip too
        narrow to hold them without covering the wave gets none — the
        wave is what the strip is for.
        """
        if width < (SIZE + GAP) * 3 + MARGIN * 2:
            return []
        y = (height - SIZE) / 2.0
        right = width - MARGIN
        return [
            Box(MIC, right - SIZE * 3 - GAP * 2, y, SIZE),
            Box(VOICE, right - SIZE * 2 - GAP, y, SIZE),
            Box(CLOSE, right - SIZE, y, SIZE),
        ]

    def hit(self, px: float, py: float, width: float, height: float) -> str | None:
        """Which switch a press at (px, py) landed on, if any."""
        for box in self.boxes(width, height):
            if box.holds(px, py):
                return box.name
        return None

    # ── state ─────────────────────────────────────────────────────────

    def is_on(self, name: str) -> bool:
        return self.mic_on if name == MIC else self.voice_on

    def armed(self, now: float) -> bool:
        """Is the close switch waiting for its second press?"""
        return now < self._armed_until

    def toggle(self, name: str) -> bool:
        """Flip one switch and return its new state."""
        if name == MIC:
            self.mic_on = not self.mic_on
            return self.mic_on
        if name == VOICE:
            self.voice_on = not self.voice_on
            return self.voice_on
        return True

    def press(
        self, px: float, py: float, width: float, height: float, now: float
    ) -> str | None:
        """What a press at (px, py) means, and do it.

        Returns the switch that changed — `MIC` or `VOICE` — or `CLOSE`
        when the close switch has now been pressed twice and he really
        is to shut down. A first press on close returns None: it arms,
        and the drawing says so.
        """
        name = self.hit(px, py, width, height)
        if name is None:
            # Anything that is not one of the three arms nothing and
            # cancels what was armed: a press elsewhere is a change of
            # mind, not a confirmation.
            self._armed_until = 0.0
            return None
        if name == CLOSE:
            if self.armed(now):
                self._armed_until = 0.0
                return CLOSE
            self._armed_until = now + ARM_SECONDS
            return None
        self._armed_until = 0.0
        self.toggle(name)
        return name
