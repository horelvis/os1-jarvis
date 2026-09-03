"""The subset, and the promise that it stays a subset.

Anything outside it comes out as the literal text it is: pretending to
have understood a table is worse than showing one.
"""

from Hermes.plugins.jarvis_teacher.markdown import (
    imagenes,
    lista,
    parsear,
    sustituir_imagen,
)


def test_a_heading_and_a_paragraph() -> None:
    bloques = parsear("## ¿Qué mantiene a la Luna en órbita?\n\nLa gravedad.\n")
    assert [b.tipo for b in bloques] == ["encabezado", "parrafo"]
    assert bloques[0].texto == "¿Qué mantiene a la Luna en órbita?"


def test_a_bullet_list_becomes_one_block() -> None:
    bloques = parsear("- do\n- are\n- have\n")
    assert [b.tipo for b in bloques] == ["lista"]
    assert bloques[0].items == ["do", "are", "have"]


def test_a_numbered_list_is_also_a_list() -> None:
    assert lista("1. Presente simple\n2. Pasado simple\n") == [
        "Presente simple",
        "Pasado simple",
    ]


def test_bold_survives_into_the_item_text() -> None:
    assert lista("- **are**\n") == ["**are**"]


def test_an_image_is_its_own_block() -> None:
    bloques = parsear("![](https://x/y.png)\n")
    assert bloques[0].tipo == "imagen"
    assert bloques[0].texto == "https://x/y.png"
    assert imagenes("![](a.png)\n\n![](b.png)") == ["a.png", "b.png"]


def test_a_table_is_shown_literally_rather_than_understood() -> None:
    bloques = parsear("| a | b |\n|---|---|\n")
    assert [b.tipo for b in bloques] == ["parrafo"]
    assert "| a | b |" in bloques[0].texto


def test_substituting_an_image_keeps_the_rest() -> None:
    md = "## T\n\n![](https://x/y.png)\n\n- uno\n"
    fuera = sustituir_imagen(md, "https://x/y.png", "/spool/ab.png")
    assert "![](/spool/ab.png)" in fuera
    assert "- uno" in fuera


def test_a_list_that_is_not_there_is_empty_not_an_error() -> None:
    assert lista("Sólo un párrafo.") == []


def test_imagenes_ignores_references_inside_code_fences() -> None:
    md = "![](real.png)\n\n```\n![](example.png)\n```\n"
    assert imagenes(md) == ["real.png"]


def test_sustituir_imagen_does_not_rewrite_inside_code_fences() -> None:
    md = "![](real.png)\n\n```\n![](real.png)\n```\n"
    fuera = sustituir_imagen(md, "real.png", "new.png")
    assert "![](new.png)" in fuera
    assert "![](real.png)" in fuera  # The one inside the fence unchanged
