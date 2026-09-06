"""The GTK half of the passphrase band: two labels, centred.

State lives in `bienvenida.py`, which imports no `gi` and is therefore
testable. This is the part that cannot be: two `Gtk.Label`s, styled
through `theme.CSS` the same way the console's own label already is.
The top label carries two lines of text (`BIENVENIDA` and `NECESIDAD`,
joined by "\\n") rather than being a third `Gtk.Label` — the owner
asked for a welcome and a reason to bother, not a third weight or a
second colour (2026-09-06), so both share the one small style the
original instruction line already had.

No GSK snapshot and no Cairo context here, unlike `photo_area.py` (a
texture) or `ficha_area.py` (a webview): this band draws no pixels of
its own, only stock widgets, so CLAUDE.md §2.3's Cairo trap — a
`TypeError` swallowed inside a draw callback, the strip appearing and
never drawing again — has nothing to bite on.

**This is also the only place that can measure a real rendered height**
(fix round, 2026-09-06). `bienvenida.py`'s `height` used to be a single
constant fitted to one example phrase; a review measured real Pango
metrics for the actual font stack over 20,000 generated passphrases and
found ~0.2% wrap onto a second line the fixed height did not budget
for — clipped at the worst possible place, the phrase itself. `mostrar`
below measures the real thing, the way `window.py`'s console asks VTE
for `get_char_height()` instead of assuming a number, and hands both
numbers to the model rather than letting it guess.
"""

from __future__ import annotations

from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")

from gi.repository import Gtk, Pango, PangoCairo  # noqa: E402

from . import theme  # noqa: E402
from .bienvenida import ESPACIADO, BIENVENIDA, NECESIDAD, BienvenidaModel  # noqa: E402

# Font descriptions for measurement, built to match `theme.py`'s
# `.jarvis-bienvenida-instruccion` / `.jarvis-bienvenida-frase` CSS
# exactly — family list, weight, size. If either CSS rule changes,
# this must change with it, or the measurement below stops meaning
# anything; nothing enforces that automatically, which is the trade of
# measuring rather than trusting GTK's own (later, allocation-timed)
# layout of these same labels.
_FUENTE_INSTRUCCION = Pango.FontDescription()
_FUENTE_INSTRUCCION.set_family("Inter Tight,sans-serif")
_FUENTE_INSTRUCCION.set_absolute_size(Pango.units_from_double(15))

_FUENTE_FRASE = Pango.FontDescription()
_FUENTE_FRASE.set_family("Cormorant Garamond,Georgia,serif")
_FUENTE_FRASE.set_weight(Pango.Weight.SEMIBOLD)
_FUENTE_FRASE.set_absolute_size(Pango.units_from_double(32))


def _alto_renderizado(texto: str, fuente: Pango.FontDescription, ancho_max: int) -> int:
    """The real height `texto` takes, wrapped at `ancho_max` px, in `fuente`.

    A headless `Pango.Layout`, off a `Pango.Context` from the default
    `PangoCairo.FontMap` — despite the name, `FontMap.create_context()`
    returns a plain `Pango.Context` and touches no actual
    `cairo.Context` object, so `gi._gi_cairo` (missing on this machine,
    CLAUDE.md §2.3) is never involved and there is nothing for that
    trap — a `TypeError` a draw callback swallows, the strip never
    drawing again and logging nothing — to catch here. Whatever font
    fontconfig actually resolves "Cormorant Garamond,Georgia,serif" to
    on THIS box — the named font is not installed here (`fc-list`,
    2026-09-06) — is the font this measures, not an assumption about
    one that may not be present. Confirmed live (2026-09-06 fix round):
    on this box's actual fallback, `_FUENTE_FRASE` measures narrower
    than whatever font the review's own numbers came from, so this
    function's job is exactly to notice that difference rather than
    assume a number that was true somewhere else.
    """
    contexto = PangoCairo.FontMap.get_default().create_context()
    layout = Pango.Layout(contexto)
    layout.set_font_description(fuente)
    layout.set_width(Pango.units_from_double(ancho_max))
    layout.set_wrap(Pango.WrapMode.WORD)
    layout.set_text(texto, -1)
    return layout.get_pixel_size()[1]


class BienvenidaArea(Gtk.Box):
    """The band above the wave, showing the passphrase or nothing.

    Zero pixels tall until `mostrar` is called, and gone for good once
    `ocultar` is — there is no third state and no way back in from here.
    """

    def __init__(self, on_resize: Callable[[int], None]) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=ESPACIADO)
        self.model = BienvenidaModel()
        self._on_resize = on_resize
        self.set_hexpand(True)
        self.set_vexpand(False)
        self.set_halign(Gtk.Align.CENTER)
        self.set_valign(Gtk.Align.CENTER)
        self.set_visible(False)

        # The welcome and the reason to bother, in the two smaller lines
        # read before the phrase: one label, not two, so there is no
        # second weight or colour for either to carry.
        self._instruccion = Gtk.Label(label=f"{BIENVENIDA}\n{NECESIDAD}")
        self._instruccion.add_css_class("jarvis-bienvenida-instruccion")
        self._instruccion.set_justify(Gtk.Justification.CENTER)
        self._instruccion.set_wrap(True)
        self.append(self._instruccion)

        # The phrase itself: larger, because this is the one thing on
        # the strip a person actually has to read out loud.
        self._frase = Gtk.Label()
        self._frase.add_css_class("jarvis-bienvenida-frase")
        self._frase.set_justify(Gtk.Justification.CENTER)
        self._frase.set_wrap(True)
        self.append(self._frase)

        self.set_size_request(-1, 0)

    def mostrar(self, frase: str) -> None:
        """The phrase to put on the strip, while there is still no amo.

        Measures both blocks at the band's real width before asking the
        model for a height — `theme.STRIP_MAX_WIDTH`, the same 900px
        figure the strip itself is fixed to (`theme.py`), so what is
        measured here is what will actually be laid out, not a guess at
        it.
        """
        self._frase.set_text(frase)
        ancho = theme.STRIP_MAX_WIDTH
        alto_instruccion = _alto_renderizado(
            f"{BIENVENIDA}\n{NECESIDAD}", _FUENTE_INSTRUCCION, ancho
        )
        alto_frase = _alto_renderizado(frase, _FUENTE_FRASE, ancho)
        self._apply(
            self.model.mostrar(
                frase, alto_instruccion=alto_instruccion, alto_frase=alto_frase
            )
        )

    def ocultar(self) -> None:
        """An amo now exists: the phrase is consumed and stays gone."""
        self._apply(self.model.ocultar())

    def _apply(self, changed: bool) -> None:
        height = self.model.height
        self.set_size_request(-1, height)
        self.set_visible(self.model.visible)
        if changed:
            self._on_resize(height)
