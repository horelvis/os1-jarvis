"""A declared subset of Markdown, parsed into blocks.

Not a CommonMark implementation and never to become one. There is no
browser here (CLAUDE.md §3) and the widget draws these blocks as GTK
widgets, so the subset is exactly what can be drawn: a heading,
paragraphs, bullet and numbered lists, images, and fenced code.
Anything else is a paragraph containing its own literal text — a table
shown as its own pipes is honest; a table half-rendered is not.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_ENCABEZADO = re.compile(r"^#{1,3}\s+(.*)$")
_VINETA = re.compile(r"^[-*]\s+(.*)$")
_NUMERADA = re.compile(r"^\d+[.)]\s+(.*)$")
_IMAGEN = re.compile(r"^!\[[^\]]*\]\(([^)]+)\)$")
_IMAGEN_INLINE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
_CERCA = re.compile(r"^```")


@dataclass
class Bloque:
    """One drawable thing. `items` is filled only for a list."""

    tipo: str
    texto: str = ""
    items: list[str] = field(default_factory=list)


def parsear(md: str) -> list[Bloque]:
    """Split a document into blocks. Never raises on anything."""
    bloques: list[Bloque] = []
    parrafo: list[str] = []
    items: list[str] = []
    en_codigo = False
    codigo: list[str] = []

    def cerrar_parrafo() -> None:
        if parrafo:
            bloques.append(Bloque("parrafo", "\n".join(parrafo)))
            parrafo.clear()

    def cerrar_lista() -> None:
        if items:
            bloques.append(Bloque("lista", items=list(items)))
            items.clear()

    for linea in (md or "").splitlines():
        if _CERCA.match(linea.strip()):
            if en_codigo:
                bloques.append(Bloque("codigo", "\n".join(codigo)))
                codigo.clear()
            else:
                cerrar_parrafo()
                cerrar_lista()
            en_codigo = not en_codigo
            continue
        if en_codigo:
            codigo.append(linea)
            continue

        desnuda = linea.strip()
        if not desnuda:
            cerrar_parrafo()
            cerrar_lista()
            continue

        encabezado = _ENCABEZADO.match(desnuda)
        if encabezado:
            cerrar_parrafo()
            cerrar_lista()
            bloques.append(Bloque("encabezado", encabezado.group(1).strip()))
            continue

        imagen = _IMAGEN.match(desnuda)
        if imagen:
            cerrar_parrafo()
            cerrar_lista()
            bloques.append(Bloque("imagen", imagen.group(1).strip()))
            continue

        punto = _VINETA.match(desnuda) or _NUMERADA.match(desnuda)
        if punto:
            cerrar_parrafo()
            items.append(punto.group(1).strip())
            continue

        cerrar_lista()
        parrafo.append(desnuda)

    if en_codigo and codigo:
        bloques.append(Bloque("codigo", "\n".join(codigo)))
    cerrar_parrafo()
    cerrar_lista()
    return bloques


def lista(md: str) -> list[str]:
    """The first list in the document — the options, or the syllabus.

    Empty when there is none, which is what the tool handlers turn into
    "repítelo con las opciones en una lista" rather than an error.
    """
    for bloque in parsear(md):
        if bloque.tipo == "lista":
            return bloque.items
    return []


def imagenes(md: str) -> list[str]:
    """Every image reference, in order, block-level or inline.

    Skips references inside code fences (they are literal, not images).
    """
    referencias: list[str] = []
    for bloque in parsear(md):
        if bloque.tipo == "imagen":
            referencias.append(bloque.texto)
        elif bloque.tipo in ("encabezado", "parrafo"):
            referencias.extend(m.strip() for m in _IMAGEN_INLINE.findall(bloque.texto))
        elif bloque.tipo == "lista":
            for item in bloque.items:
                referencias.extend(m.strip() for m in _IMAGEN_INLINE.findall(item))
    return referencias


def sustituir_imagen(md: str, origen: str, destino: str) -> str:
    """Point one reference somewhere else, leaving everything else alone.

    Preserves references inside code fences as literal text.
    """
    if not md:
        return md
    result: list[str] = []
    en_codigo = False
    for linea in md.splitlines(keepends=True):
        if _CERCA.match(linea.strip()):
            en_codigo = not en_codigo
            result.append(linea)
        elif en_codigo:
            result.append(linea)
        else:
            result.append(linea.replace(f"]({origen})", f"]({destino})"))
    return "".join(result)


def quitar_imagen(md: str, referencia: str) -> str:
    """Drop one image reference, leaving the rest of the document alone.

    An inline reference is cut out mid-sentence. A reference alone on
    its line takes the whole line with it, so no blank line is left.
    References in code fences are not handed here (imagenes() filters them).
    """
    # Pattern to match the image syntax with this specific reference.
    patron = rf"!\[[^\]]*\]\({re.escape(referencia)}\)"

    lineas = md.splitlines(keepends=True)
    result = []
    i = 0
    while i < len(lineas):
        linea = lineas[i]
        if referencia not in linea:
            result.append(linea)
            i += 1
            continue

        # Check if this line is JUST the image reference (own-line).
        desnuda = linea.strip()
        if re.match(rf"^!\[[^\]]*\]\({re.escape(referencia)}\)$", desnuda):
            # Own-line reference; skip the entire line.
            # Also skip the following blank line if there is one.
            i += 1
            if i < len(lineas) and lineas[i].strip() == "":
                i += 1
            continue

        # Inline reference; remove just the image syntax.
        modified = re.sub(patron, "", linea)
        # Clean up double spaces left behind.
        modified = re.sub(r" {2,}", " ", modified)
        result.append(modified)
        i += 1

    return "".join(result)
