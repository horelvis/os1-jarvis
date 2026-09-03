"""The card, drawn by WebKitGTK. The pure half is `ficha_html.py`.

**This file reverses CLAUDE.md §3 and §2.3's hardest rule** — "MUST NOT
introduce a browser / webview of any kind" — at the user's instruction
on 2026-09-03, after the previous approach had proved his point. That
one rendered a hand-written Markdown subset into GTK labels and
estimated the strip's height with pixel arithmetic that had to track
`theme.CSS` by hand. It drifted the first time the CSS changed: the
estimate came out at half the truth, an eleven-point syllabus asked for
334 px of a 430 px window, and the wave — which is what he IS — was
squeezed out of the strip entirely.

Three things this file does NOT do, and each is deliberate:

- **No JavaScript.** A card can carry text taken from a web page, which
  is the whole point of the teacher's documentary base. `ficha_html`
  escapes HTML on the way in; this switches the engine off as well,
  because one guard is not a guarantee.
- **No network, of any kind.** The document is self-contained — CSS
  inlined, images as `data:` URIs — and every navigation after the
  first load is refused. A renderer that fetches is a renderer that can
  be told what to fetch.
- **No measuring.** WebKit cannot report its content height without
  JavaScript, and JavaScript is exactly what is switched off. So the
  band takes one of two sizes and the content scrolls inside it, which
  is also what makes it impossible for a card to take the wave's
  pixels — the defect that caused all of this.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("WebKit", "6.0")
from gi.repository import Gtk, WebKit  # noqa: E402

from . import theme  # noqa: E402
from .ficha_html import a_html  # noqa: E402


class FichaArea(Gtk.Box):
    """A webview in a box, zero pixels tall until a card lands."""

    def __init__(self, on_resize) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.set_vexpand(False)
        self.set_visible(False)
        self._on_resize = on_resize

        ajustes = WebKit.Settings()
        ajustes.set_enable_javascript(False)
        for apagar in (
            "set_enable_javascript_markup",
            "set_enable_webgl",
            "set_enable_media",
            "set_enable_webaudio",
            "set_enable_html5_database",
            "set_enable_html5_local_storage",
        ):
            # Not every one of these exists on every WebKitGTK; a missing
            # switch must not stop the card being drawn.
            if hasattr(ajustes, apagar):
                getattr(ajustes, apagar)(False)

        self._vista = WebKit.WebView(settings=ajustes)
        self._vista.set_background_color(_TRANSPARENTE)
        self._vista.set_vexpand(True)
        # Everything after the first `load_html` is refused: with JS off
        # and images inlined there is nothing legitimate left to load.
        self._vista.connect("decide-policy", _refuse_everything_else)
        self.append(self._vista)

    def mostrar(
        self,
        md: str,
        tipo: str,
        fuente: str,
        correcta: str | None,
        elegida: str | None,
        alto: int,
    ) -> None:
        """Draw a card, or take it away when `md` is empty."""
        if md:
            self._vista.load_html(
                a_html(md, tipo, fuente, correcta, elegida, css=theme.FICHA_CSS),
                None,
            )
        self.set_size_request(-1, alto if md else 0)
        self.set_visible(bool(md))
        self._on_resize(alto)


def _refuse_everything_else(_vista, decision, tipo) -> bool:
    """Allow the document we handed over; refuse every other load.

    `load_html` itself arrives as a navigation, so the first one has to
    pass. Anything after it — a link, a redirect, a subresource — is a
    fetch this card has no business making.
    """
    if tipo == WebKit.PolicyDecisionType.NAVIGATION_ACTION:
        accion = decision.get_navigation_action()
        uri = accion.get_request().get_uri() or ""
        if uri.startswith(("about:", "data:")):
            decision.use()
        else:
            decision.ignore()
        return True
    decision.ignore()
    return True


def _transparente():
    from gi.repository import Gdk

    color = Gdk.RGBA()
    color.parse("rgba(0,0,0,0)")
    return color


_TRANSPARENTE = _transparente()
