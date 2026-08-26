"""The two switches on the strip: his ears, and his voice.

Pure state and pure geometry — no GTK — the way `photo.py` sits under
`photo_area.py`. `wave.py` draws what this decides and asks it where a
press landed.

Asked for by the user on 2026-08-26: two buttons over the strip, one to
turn the microphone off and one to stop him speaking out loud. Until
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
    """Which senses are on, and where the two boxes are drawn."""

    def __init__(self) -> None:
        self.mic_on = True
        self.voice_on = True

    # ── geometry ──────────────────────────────────────────────────────

    def boxes(self, width: float, height: float) -> list[Box]:
        """The two boxes, right-aligned and vertically centred.

        Right rather than left: the wave is drawn from the left and the
        eye follows it, so the switches sit where it ends. A strip too
        narrow to hold them without covering the wave gets none — the
        wave is what the strip is for.
        """
        if width < (SIZE + GAP) * 2 + MARGIN * 2:
            return []
        y = (height - SIZE) / 2.0
        right = width - MARGIN
        return [
            Box(MIC, right - SIZE * 2 - GAP, y, SIZE),
            Box(VOICE, right - SIZE, y, SIZE),
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

    def toggle(self, name: str) -> bool:
        """Flip one switch and return its new state."""
        if name == MIC:
            self.mic_on = not self.mic_on
            return self.mic_on
        if name == VOICE:
            self.voice_on = not self.voice_on
            return self.voice_on
        return True
