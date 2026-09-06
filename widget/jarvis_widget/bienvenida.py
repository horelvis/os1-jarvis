"""Whether the strip is showing the passphrase, as pure state.

`bienvenida_area.py` is the GTK half, the way `photo_area.py` sits over
`photo.py`. This is deliberately its own pair rather than a third thing
bolted onto either of those: a photo fades on a clock and a card pages
and expires, and this has none of that — it shows until it is told not
to, once, and never again. Nothing here knows why. `casa.Registro` is
what actually decides — an amo, once founded, does not go away for this
box to reconsider showing the phrase again (`casa.py`'s founding write)
— and this module does not import it: whoever wires the two together
(task 9) is the one who reads `registro.amo` and calls `mostrar` or
`ocultar` accordingly.
"""

from __future__ import annotations

# Room above the wave: two lines of centred text and the padding around
# them. A product decision, the way `ficha.py`'s COMPACTA/AMPLIA are —
# fixed rather than measured, because a label's natural height depends
# on Pango's font metrics, which nothing here has any business knowing.
ALTO = 140

# The sentence is the whole of the instruction (CLAUDE.md, this plan):
# there is no second screen and no settings for it to point at, so it
# has to stand on its own.
INSTRUCCION = "Dígame esta frase para que sepa quién es usted."


class BienvenidaModel:
    """The passphrase on the band, or nothing.

    One piece of state, because there is nothing else to track: no
    fade, no batch, no page. `mostrar` and `ocultar` each report whether
    the strip's height changed, the way every other model on the band
    does, so a caller knows whether an EWMH round-trip is needed.
    """

    def __init__(self) -> None:
        self._frase: str | None = None

    # ── what the widget asks ──────────────────────────────────────────

    @property
    def visible(self) -> bool:
        return self._frase is not None

    @property
    def frase(self) -> str | None:
        return self._frase

    @property
    def height(self) -> int:
        """Extra pixels the strip needs above the wave, right now."""
        return ALTO if self._frase is not None else 0

    # ── what the world does to it ─────────────────────────────────────

    def mostrar(self, frase: str) -> bool:
        """The phrase to show. True when the strip has to change size."""
        before = self.height
        self._frase = frase
        return self.height != before

    def ocultar(self) -> bool:
        """Nothing left to show. True when the strip has to change size.

        Idempotent: calling this with nothing showing is not an error,
        it is what the box that has always had an amo does at boot.
        """
        before = self.height
        self._frase = None
        return self.height != before
