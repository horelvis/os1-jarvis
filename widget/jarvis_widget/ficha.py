"""The card on the band, as pure state. No GTK in here, on purpose.

`ficha_area.py` is the GTK half, the way `photo_area.py` sits over
`photo.py`. What it decides and nothing else: whether there is a card,
how tall the strip must be for it, and when it goes away.

The three lifetimes are the whole of the behaviour, and they differ
because the WAITING differs: a question and a syllabus are waiting for
the user, and an explanation is not.
"""

from __future__ import annotations


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
# How tall the band is, and it is a product decision rather than a
# measurement now. WebKitGTK cannot report its content height without
# JavaScript, and JavaScript is switched off (`ficha_area.py`), so the
# card takes one of two sizes and scrolls inside it.
#
# That is the point, not a limitation grudgingly accepted: the estimate
# this replaced was pixel arithmetic that tracked `theme.CSS` by hand,
# it drifted the first time the CSS changed, and an eleven-point
# syllabus asked for 334 px of a 430 px window — squeezing the wave,
# which is what he IS, out of the strip. A band that cannot exceed its
# own size cannot do that.
COMPACTA = 200
# A full page — a heading, five points and the footer — measured on the
# strip at 334 px. Rounded up by two, because a band two pixels too tall
# shows a sliver of desktop and a band two pixels too short clips the
# footer, and only one of those is recoverable by looking again.
AMPLIA = 336
# Beyond this the strip stops being a strip. The live camera's ceiling.
MAX_ALTO = 480
# Blocks above which a card gets the taller band. Counted, not measured:
# a heading, a paragraph, a list item, an image.
BLOQUES_COMPACTOS = 5


class FichaModel:
    """What card the strip is showing, how tall it must be, and until when."""

    def __init__(self) -> None:
        self.md = ""
        self.tipo = ""
        self.fuente = ""
        self.correcta: str | None = None
        self.elegida: str | None = None
        self._since = 0.0
        # Which page is up, and how many there are. A card of eleven
        # syllabus points does not fit the band, and scrolling inside a
        # strip is something nobody discovers, so it pages instead: a
        # press advances, the last one puts it away.
        self.pagina = 0
        self._paginas: list[str] = []

    @property
    def visible(self) -> bool:
        return bool(self.md)

    @property
    def paginas(self) -> int:
        return max(1, len(self._paginas))

    @property
    def md_pagina(self) -> str:
        """The Markdown of the page that is up. What gets drawn."""
        if not self._paginas:
            return self.md
        return self._paginas[min(self.pagina, len(self._paginas) - 1)]

    @property
    def height(self) -> int:
        """Extra pixels the strip needs for this card, right now.

        Two sizes, chosen by counting the card's blocks. Nothing here
        knows what the CSS says, which is the whole improvement: the
        previous version multiplied characters by hand-tuned constants
        and had to be re-calibrated every time the card was restyled.
        """
        if not self.md:
            return 0
        bloques = sum(1 for linea in self.md_pagina.splitlines() if linea.strip())
        alto = COMPACTA if bloques <= BLOQUES_COMPACTOS else AMPLIA
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
        from .ficha_html import paginar

        before = self.height
        self.md = md
        # A correction goes back to the first page: the options are
        # there, and only a syllabus is long enough to page at all.
        self._paginas = paginar(md) if md else []
        self.pagina = 0
        self.tipo = tipo
        self.fuente = fuente
        self.correcta = correcta
        self.elegida = elegida
        self._since = now
        return self.height != before

    def click(self, *, now: float) -> bool:
        """A press: the next page, or away if this was the last one.

        True when the strip has to change size — which a page turn can
        do, since a short last page needs a smaller band than a full
        one. Turning a page restarts the clock: reading is interest,
        and a card should not expire under somebody's eyes.
        """
        if not self.md:
            return False
        if self.pagina + 1 < self.paginas:
            before = self.height
            self.pagina += 1
            self._since = now
            return self.height != before
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
        self._paginas = []
        self.pagina = 0
        self.md = ""
        self.tipo = ""
        self.fuente = ""
        self.correcta = None
        self.elegida = None
        return self.height != before
