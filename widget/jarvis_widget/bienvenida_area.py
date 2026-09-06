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
"""

from __future__ import annotations

from typing import Callable

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import Gtk  # noqa: E402

from .bienvenida import BIENVENIDA, NECESIDAD, BienvenidaModel  # noqa: E402


class BienvenidaArea(Gtk.Box):
    """The band above the wave, showing the passphrase or nothing.

    Zero pixels tall until `mostrar` is called, and gone for good once
    `ocultar` is — there is no third state and no way back in from here.
    """

    def __init__(self, on_resize: Callable[[int], None]) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
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
        """The phrase to put on the strip, while there is still no amo."""
        self._frase.set_text(frase)
        self._apply(self.model.mostrar(frase))

    def ocultar(self) -> None:
        """An amo now exists: the phrase is consumed and stays gone."""
        self._apply(self.model.ocultar())

    def _apply(self, changed: bool) -> None:
        height = self.model.height
        self.set_size_request(-1, height)
        self.set_visible(self.model.visible)
        if changed:
            self._on_resize(height)
