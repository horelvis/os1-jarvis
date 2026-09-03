"""The card, drawn. Text is widgets, because the band has no text.

`photo_area.py` draws with GSK, which has no text primitive — that is
why the console is a widget in the box rather than something painted
(window.py:148). A card is mostly text, so it is a `Gtk.Box` of labels
and pictures, and it joins the strip the way the console does: its own
child, its own contribution to the height.

`bloques_a_widgets` is the half that decides WHAT to build, and it is
pure so it can be tested on a box with no display — which is every box
this repo's tests run on.
"""

from __future__ import annotations

import re
from html import escape

_NEGRITA = re.compile(r"\*\*(.+?)\*\*")
_CURSIVA = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)")
_CODIGO = re.compile(r"`([^`]+)`")
_ENCABEZADO = re.compile(r"^#{1,3}\s+(.*)$")
_PUNTO = re.compile(r"^(?:[-*]|\d+[.)])\s+(.*)$")
_IMAGEN = re.compile(r"^!\[[^\]]*\]\(([^)]+)\)$")


def _inline(texto: str) -> str:
    """Markdown emphasis into Pango markup, everything else escaped.

    Escaping FIRST is what keeps a `<` in somebody's source text from
    becoming half a tag: Pango is strict and an unbalanced one makes the
    whole label fail to parse, which shows as an empty card.
    """
    seguro = escape(texto)
    seguro = _NEGRITA.sub(r"<b>\1</b>", seguro)
    seguro = _CURSIVA.sub(r"<i>\1</i>", seguro)
    return _CODIGO.sub(r"<tt>\1</tt>", seguro)


def bloques_a_widgets(
    md: str, tipo: str, correcta: str | None, elegida: str | None
) -> list[dict]:
    """Describe the card as pieces. GTK is built from this, and tests read it."""
    piezas: list[dict] = []
    indice = 0
    for linea in (md or "").splitlines():
        desnuda = linea.strip()
        if not desnuda:
            continue

        imagen = _IMAGEN.match(desnuda)
        if imagen:
            piezas.append(
                {"tipo": "imagen", "texto": imagen.group(1), "letra": "", "estado": ""}
            )
            continue

        encabezado = _ENCABEZADO.match(desnuda)
        if encabezado:
            piezas.append(
                {
                    "tipo": "encabezado",
                    "texto": _inline(encabezado.group(1)),
                    "letra": "",
                    "estado": "",
                }
            )
            continue

        punto = _PUNTO.match(desnuda)
        if punto and tipo in {"pregunta", "plan"}:
            letra = f"{indice + 1}." if tipo == "plan" else f"{chr(97 + indice)}."
            estado = ""
            if correcta is not None:
                mia = chr(97 + indice)
                if mia == correcta:
                    estado = "correcta"
                elif mia == elegida:
                    estado = "fallada"
                else:
                    estado = "apagada"
            piezas.append(
                {
                    "tipo": "opcion",
                    "texto": _inline(punto.group(1)),
                    "letra": letra,
                    "estado": estado,
                }
            )
            indice += 1
            continue

        piezas.append(
            {"tipo": "parrafo", "texto": _inline(desnuda), "letra": "", "estado": ""}
        )
    return piezas


import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402


class FichaArea(Gtk.Box):
    """The card as a column of widgets, zero pixels tall until one lands."""

    def __init__(self, on_resize) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.add_css_class("samantha-ficha")
        self.set_visible(False)
        self._on_resize = on_resize

    def mostrar(
        self,
        md: str,
        tipo: str,
        fuente: str,
        correcta: str | None,
        elegida: str | None,
        alto: int,
    ) -> None:
        """Rebuild the card. Called for the question and again for its correction."""
        while (hijo := self.get_first_child()) is not None:
            self.remove(hijo)

        for pieza in bloques_a_widgets(md, tipo, correcta, elegida):
            if pieza["tipo"] == "imagen":
                imagen = Gtk.Picture.new_for_filename(pieza["texto"])
                imagen.set_content_fit(Gtk.ContentFit.CONTAIN)
                imagen.set_size_request(300, 169)
                self.append(imagen)
                continue
            etiqueta = Gtk.Label()
            etiqueta.set_xalign(0.0)
            etiqueta.set_wrap(True)
            if pieza["tipo"] == "opcion":
                etiqueta.set_markup(f"<tt>{pieza['letra']}</tt>  {pieza['texto']}")
                etiqueta.add_css_class("samantha-ficha-opcion")
                if pieza["estado"]:
                    etiqueta.add_css_class(f"samantha-ficha-{pieza['estado']}")
            else:
                etiqueta.set_markup(pieza["texto"])
                etiqueta.add_css_class(f"samantha-ficha-{pieza['tipo']}")
            self.append(etiqueta)

        if fuente:
            pie = Gtk.Label(label=fuente)
            pie.set_xalign(0.0)
            pie.add_css_class("samantha-ficha-fuente")
            self.append(pie)

        self.set_visible(bool(md))
        self._on_resize(alto)
