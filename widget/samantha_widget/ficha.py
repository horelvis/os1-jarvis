"""The card on the band, as pure state. No GTK in here, on purpose.

`ficha_area.py` is the GTK half, the way `photo_area.py` sits over
`photo.py`. What it decides and nothing else: whether there is a card,
how tall the strip must be for it, and when it goes away.

The three lifetimes are the whole of the behaviour, and they differ
because the WAITING differs: a question and a syllabus are waiting for
the user, and an explanation is not.
"""

from __future__ import annotations

import math

# A question or a plan waits this long and then gives up. There has to
# be a way out that costs nothing: a strip left at four times its height
# because nobody answered is worse than one that closes while you were
# still reading, since the question can be asked again and the desktop
# underneath cannot. The live view's own ceiling is 120 s; a person
# thinking about an answer deserves more than a camera does.
ESPERA_S = 300.0
# An explanation is not waiting for anything, so it behaves like a photo.
EXPLICACION_S = 60.0
# How long the corrected card stays once it has been answered.
CORREGIDA_S = 6.0

# Room above the wave, in pixels: the frame, and one line.
PADDING = 36
LINEA = 22
ENCABEZADO = 34
IMAGEN = 169
# The same ceiling the live camera takes. Beyond this the strip stops
# being a strip.
MAX_ALTO = 480

# Characters that fit on one line of body text in the card.
# Estimated from the strip's 900 px width, minus side margins and padding,
# at the card's body font size. This is an estimate: this file has no GTK
# in it and cannot measure text. Headings are counted at this rate too and
# are therefore slightly under-measured (they are bigger, so fewer characters
# fit). The trade-off keeps the code simple and the underestimate is small
# relative to the full card height.
CHARS_PER_LINEA = 90


class FichaModel:
    """What card the strip is showing, how tall it must be, and until when."""

    def __init__(self) -> None:
        self.md = ""
        self.tipo = ""
        self.fuente = ""
        self.correcta: str | None = None
        self.elegida: str | None = None
        self._since = 0.0

    @property
    def visible(self) -> bool:
        return bool(self.md)

    @property
    def height(self) -> int:
        """Extra pixels the strip needs for this card, right now."""
        if not self.md:
            return 0
        alto = PADDING
        for linea in self.md.splitlines():
            desnuda = linea.strip()
            if not desnuda:
                continue
            if desnuda.startswith("!["):
                alto += IMAGEN
            elif desnuda.startswith("#"):
                # Headings: count wrapped lines at the body text rate.
                wrapped_lines = max(1, math.ceil(len(desnuda) / CHARS_PER_LINEA))
                alto += wrapped_lines * ENCABEZADO
            else:
                # Body text: account for wrapping over multiple lines.
                wrapped_lines = max(1, math.ceil(len(desnuda) / CHARS_PER_LINEA))
                alto += wrapped_lines * LINEA
        if self.fuente:
            alto += LINEA
        return min(MAX_ALTO, alto)

    def mostrar(
        self,
        md: str,
        tipo: str,
        fuente: str,
        correcta: str | None,
        elegida: str | None,
        *,
        now: float,
    ) -> bool:
        """A card arrived. True when the strip has to change size."""
        before = self.height
        self.md = md
        self.tipo = tipo
        self.fuente = fuente
        self.correcta = correcta
        self.elegida = elegida
        self._since = now
        return self.height != before

    def click(self, *, now: float) -> bool:
        """A press puts it away — the gesture a photo has had since August."""
        if not self.md:
            return False
        return self._cerrar()

    def tick(self, *, now: float) -> bool:
        """Let time pass. True when the strip has to change size."""
        if not self.md:
            return False
        if self.correcta is not None:
            limite = CORREGIDA_S
        elif self.tipo == "explicacion":
            limite = EXPLICACION_S
        else:
            limite = ESPERA_S
        if now - self._since < limite:
            return False
        return self._cerrar()

    def _cerrar(self) -> bool:
        before = self.height
        self.md = ""
        self.tipo = ""
        self.fuente = ""
        self.correcta = None
        self.elegida = None
        return self.height != before
