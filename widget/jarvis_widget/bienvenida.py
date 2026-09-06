"""Whether the strip is showing the passphrase, as pure state.

`bienvenida_area.py` is the GTK half, the way `photo_area.py` sits over
`photo.py`. This is deliberately its own pair rather than a third thing
bolted onto either of those: a photo fades on a clock and a card pages
and expires, and this has none of that — it shows exactly what it was
last told to, until it is told something else or told nothing. Nothing
here knows why. `casa.Registro` is what actually decides whether the
pairing flow is running at all — an amo, once founded, does not go away
for this box to reconsider (`casa.py`'s founding write) — and this
module does not import it: whoever wires the two together (`__main__`'s
unpaired seam) is the one who reads `registro.amo` and drives `mostrar`
/ `ocultar` from each `encuentro.Respuesta.lectura`.

**Both directions run more than once per pairing**, which the first
version of this file assumed they would not: the band carries the
passphrase, then the wipe confirmation, then each reading passage in
turn, then NOTHING while a name is being asked for, then the candidate
name — so a `mostrar` after an `ocultar` is ordinary, not a mistake.

**`height` is summed from real measurements, not guessed** (fix round,
2026-09-06). The first version fitted `ALTO` to one screenshot; a
review measured real Pango metrics for the actual font stack over
20,000 generated passphrases and found ~0.2% wrap onto a second line —
one in five hundred, which is not rare when the event happens once per
installation. A fixed height clipped that second line: the one string
a stranger has to read aloud correctly for any of this to work,
clipped at the worst possible place. `bienvenida_area.py` is the only
place that can measure a real rendered height (it has Pango; this file
still does not), so it hands `mostrar` the two numbers that matter —
how tall the fixed instruction block rendered, and how tall THIS
phrase rendered, wrapped at the band's real width — and this file only
ever sums what it was told.
"""

from __future__ import annotations

# Vertical gap between the instruction block and the phrase. Also the
# `spacing=` `bienvenida_area.py` builds its `Gtk.Box` with — imported
# from there rather than duplicated, so the arithmetic here and the
# actual layout can never drift apart.
ESPACIADO = 6

# Room around the whole block, top and bottom together — a deliberate
# aesthetic choice, the way `ficha.py`'s COMPACTA/AMPLIA are, never a
# measurement: without it the band would be exactly as tall as its text
# and read as cramped rather than a panel. Calibrated once against the
# real, measured heights on this box (2026-09-06 fix round) so an
# ordinary phrase keeps a comfortable margin above and below the block
# — screenshotted and reviewed as legible and well-proportioned at the
# total this produces, not because 49 means anything on its own. A box
# whose fallback font resolves differently will get a different total
# from the same RELLENO, which is the point: the number that has to
# stay right is the content's real height, not this one.
RELLENO = 49

# What a box with no amo says, in the order it reads: a greeting to a
# stranger, then the one fact that matters — nothing happens here until
# the phrase below is said — and only then the phrase itself, which
# stays the largest thing on the band (`bienvenida_area.py`) and the
# last line read. Neither of these two says anything about what saying
# the phrase actually does (founding the house, erasing what came
# before it): that belongs to the spoken confirmation later in the
# flow, not to a strip nobody has spoken to yet.
BIENVENIDA = "Buenas. Aún no sé quién es usted."
NECESIDAD = "Hasta que no la diga, no puedo hacer nada."


class BienvenidaModel:
    """The passphrase on the band, or nothing.

    Two pieces of state travel together — the phrase, and how tall it
    and the fixed block above it actually rendered — because there is
    nothing else to track: no fade, no batch, no page. `mostrar` and
    `ocultar` each report whether the strip's height changed, the way
    every other model on the band does, so a caller knows whether an
    EWMH round-trip is needed.
    """

    def __init__(self) -> None:
        self._frase: str | None = None
        # Real Pango heights, in pixels, of the fixed instruction block
        # and of the current phrase — set from measurements handed in by
        # `bienvenida_area.py.mostrar`, never computed here. These
        # defaults are only what a caller sees before the first real
        # measurement arrives (a test with no display, or the instant
        # between construction and the first `mostrar`): small,
        # single-line-sized numbers, not zero — zero would silently
        # reproduce the exact bug this file exists to fix the moment
        # anyone forgot to pass a real one in.
        self._alto_instruccion = 20
        self._alto_frase = 40

    # ── what the widget asks ──────────────────────────────────────────

    @property
    def visible(self) -> bool:
        return self._frase is not None

    @property
    def frase(self) -> str | None:
        return self._frase

    @property
    def height(self) -> int:
        """Extra pixels the strip needs above the wave, right now.

        Summed from what was actually measured to render — the fixed
        instruction block, the spacing next to it, and the phrase —
        rather than a single constant fitted to one example phrase.
        The phrase is the one part of this sum that changes shape from
        one installation to the next, since it is the one text here
        nobody wrote by hand.
        """
        if self._frase is None:
            return 0
        return RELLENO + self._alto_instruccion + ESPACIADO + self._alto_frase

    # ── what the world does to it ─────────────────────────────────────

    def mostrar(
        self,
        frase: str,
        *,
        alto_instruccion: int | None = None,
        alto_frase: int | None = None,
    ) -> bool:
        """The phrase to show. True when the strip has to change size.

        `alto_instruccion`/`alto_frase` are the real Pango pixel
        heights `bienvenida_area.py` measured for the fixed block and
        for THIS phrase, wrapped at the band's actual width — this
        method never estimates either on its own. Omitting one (a test
        exercising this model with no display at all) keeps whatever
        was already recorded, starting from the small defaults set in
        `__init__`.
        """
        before = self.height
        self._frase = frase
        if alto_instruccion is not None:
            self._alto_instruccion = alto_instruccion
        if alto_frase is not None:
            self._alto_frase = alto_frase
        return self.height != before

    def ocultar(self) -> bool:
        """Nothing to show right now. True when the strip has to change size.

        Idempotent: calling this with nothing showing is not an error,
        it is what the box that has always had an amo does at boot. Nor
        is it final — mid-pairing there is one moment with genuinely
        nothing to look at (he is asking for a name), and the band comes
        back a turn later with the name he heard.
        """
        before = self.height
        self._frase = None
        return self.height != before
