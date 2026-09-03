"""A card, as HTML. No GTK in here, on purpose.

`ficha_area.py` renders what this produces; this half can be tested on a
box with no display, which is every box this repo's tests run on. It
replaced a hand-written Markdown subset and a pixel-arithmetic height
estimate on 2026-09-03, at the user's instruction: *"no es una buena
práctica el cálculo que haces, debes buscar un componente visor de
markdown"*. He was right, and the evidence was in the file — the
estimate had to be re-calibrated by hand the moment the card's CSS
changed, and got it wrong by half, so an eleven-point syllabus showed
five of its points.

Two rules govern what comes out of here, and both are security rather
than style:

- **The document is self-contained.** No stylesheet, no font, no script
  and no image is fetched: the CSS is inlined and images arrive as
  `data:` URIs. A card can carry text taken from a web page (that is
  what the teacher's documentary base is), and a renderer that fetches
  is a renderer that can be told what to fetch.
- **Everything from outside is escaped.** The Markdown comes from a
  model that was fed pages we did not write. `markdown-it-py` is
  configured to escape HTML rather than pass it through, so a card
  carrying `<script>` shows those characters instead of running them —
  though the renderer has JavaScript switched off as well
  (`ficha_area.py`), because one guard is not a guarantee.
"""

from __future__ import annotations

import base64
import re
from html import escape
from pathlib import Path

from markdown_it import MarkdownIt

# What one card may be, and what its list means. `pregunta` letters its
# options because "la b" spoken out loud needs something to point at;
# `plan` numbers them because an order is what a syllabus is about.
TIPOS = frozenset({"pregunta", "plan", "explicacion"})

_IMG = re.compile(r'<img src="([^"]+)"')

# Only these are inlined. A card's images come from the teacher's spool,
# which holds what `imagen.py` already downloaded, size-capped and
# decoded — this is the second gate, not the first.
_TIPOS_IMAGEN = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
}
MAX_IMAGEN = 4 * 1024 * 1024


def _md() -> MarkdownIt:
    """CommonMark, with raw HTML escaped rather than passed through."""
    return MarkdownIt("commonmark", {"html": False, "linkify": False})


def _inline_images(html: str) -> str:
    """Turn every `<img src="…">` into a data: URI, or drop the tag.

    A path that cannot be read costs the picture and never the card —
    the same rule the plugin applies one layer up.
    """

    def replace(match: re.Match[str]) -> str:
        src = match.group(1)
        if src.startswith("data:"):
            return match.group(0)
        path = Path(src)
        mime = _TIPOS_IMAGEN.get(path.suffix.lower())
        try:
            if mime is None or path.stat().st_size > MAX_IMAGEN:
                return '<img alt="" style="display:none"'
            datos = base64.b64encode(path.read_bytes()).decode("ascii")
        except OSError:
            return '<img alt="" style="display:none"'
        return f'<img src="data:{mime};base64,{datos}"'

    return _IMG.sub(replace, html)


def _marcar_opciones(
    html: str, tipo: str, correcta: str | None, elegida: str | None
) -> str:
    """Letter or number the first list, and mark the correction on it.

    Only the FIRST list is the answer set — a card with a trailing note
    would otherwise draw options nobody can choose, which is a defect
    this file's predecessor was fixed for.
    """
    if tipo not in {"pregunta", "plan"}:
        return html
    marca = "opciones" if tipo == "pregunta" else "plan"
    # The first <ul>/<ol> becomes the answer set; later ones stay plain.
    for abre, cierra in (("<ul>", "</ul>"), ("<ol>", "</ol>")):
        if abre in html:
            html = html.replace(abre, f'<{abre[1:-1]} class="{marca}">', 1)
            break
    if correcta is None:
        return html
    # Mark the items in document order: the nth <li> is the nth option.
    partes = html.split("<li>")
    salida = [partes[0]]
    for indice, resto in enumerate(partes[1:]):
        letra = chr(97 + indice)
        clase = ""
        if letra == correcta:
            clase = " class='correcta'"
        elif letra == elegida:
            clase = " class='fallada'"
        elif elegida is not None:
            clase = " class='apagada'"
        salida.append(f"<li{clase}>{resto}")
    return "".join(salida)


def a_html(
    md: str,
    tipo: str,
    fuente: str = "",
    correcta: str | None = None,
    elegida: str | None = None,
    *,
    css: str = "",
) -> str:
    """One self-contained document. Never raises."""
    try:
        cuerpo = _md().render(md or "")
    except Exception:
        # A renderer that throws must not cost the turn: show the source.
        cuerpo = f"<pre>{escape(md or '')}</pre>"
    cuerpo = _inline_images(cuerpo)
    cuerpo = _marcar_opciones(cuerpo, tipo, correcta, elegida)
    pie = f'<p class="fuente">{escape(fuente)}</p>' if fuente else ""
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<style>{css}</style></head>"
        f"<body class='{escape(tipo)}'>{cuerpo}{pie}</body></html>"
    )
