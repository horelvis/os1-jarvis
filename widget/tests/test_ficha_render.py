"""What a card turns into, decided without a display.

`a. b. c.` for a question and `1. 2. 3.` for a plan is a rule, not
decoration: "la b" has to have something to refer to, and a syllabus is
about its order.
"""

from jarvis_widget.ficha_area import bloques_a_widgets


def test_a_question_is_lettered() -> None:
    piezas = bloques_a_widgets("## ¿Cuál?\n\n- do\n- are\n", "pregunta", None, None)
    letras = [p["letra"] for p in piezas if p["tipo"] == "opcion"]
    assert letras == ["a.", "b."]


def test_a_plan_is_numbered() -> None:
    piezas = bloques_a_widgets("## Temario\n\n- Uno\n- Dos\n", "plan", None, None)
    assert [p["letra"] for p in piezas if p["tipo"] == "opcion"] == ["1.", "2."]


def test_an_explanation_has_no_numbering() -> None:
    piezas = bloques_a_widgets("Texto suelto.", "explicacion", None, None)
    assert all(p["tipo"] != "opcion" for p in piezas)


def test_the_correction_marks_the_right_one_and_yours() -> None:
    piezas = [
        p
        for p in bloques_a_widgets("## ¿Cuál?\n\n- do\n- are\n", "pregunta", "b", "a")
        if p["tipo"] == "opcion"
    ]
    assert piezas[1]["estado"] == "correcta"
    assert piezas[0]["estado"] == "fallada"


def test_an_unanswered_question_marks_nothing() -> None:
    piezas = [
        p
        for p in bloques_a_widgets("- do\n- are\n", "pregunta", None, None)
        if p["tipo"] == "opcion"
    ]
    assert {p["estado"] for p in piezas} == {""}


def test_an_image_becomes_its_own_piece() -> None:
    piezas = bloques_a_widgets("![](/spool/x.png)\n\n- a\n", "pregunta", None, None)
    assert piezas[0]["tipo"] == "imagen"
    assert piezas[0]["texto"] == "/spool/x.png"


def test_inline_bold_becomes_pango_markup() -> None:
    piezas = bloques_a_widgets("Esto es **importante**.", "explicacion", None, None)
    assert "<b>importante</b>" in piezas[0]["texto"]


def test_markup_characters_in_the_source_are_escaped() -> None:
    piezas = bloques_a_widgets("a < b & c", "explicacion", None, None)
    assert "&lt;" in piezas[0]["texto"] and "&amp;" in piezas[0]["texto"]


# ── final review: only the first list is the question ──────────────────


def test_only_the_first_list_is_lettered() -> None:
    """A trailing note-list drew options `d.` and `e.` nobody could pick.

    `markdown.lista()` — what `tool.py` scores the spoken answer
    against — reads the first list and stops, so anything lettered
    after it is an option `_letra` can never match.
    """
    md = (
        "## ¿Cuál?\n\n"
        "- do\n- are\n- have\n\n"
        "Recuerde:\n\n"
        "- el auxiliar concuerda\n"
        "- la forma -ing no cambia\n"
    )
    piezas = bloques_a_widgets(md, "pregunta", None, None)
    assert [p["letra"] for p in piezas if p["tipo"] == "opcion"] == ["a.", "b.", "c."]
    assert [p["texto"] for p in piezas if p["tipo"] == "opcion"] == [
        "do",
        "are",
        "have",
    ]
    assert any("auxiliar" in p["texto"] for p in piezas if p["tipo"] == "parrafo")


def test_a_heading_closes_the_first_list_too() -> None:
    md = "- do\n- are\n\n## Nota\n\n- otra cosa\n"
    piezas = bloques_a_widgets(md, "pregunta", None, None)
    assert [p["letra"] for p in piezas if p["tipo"] == "opcion"] == ["a.", "b."]


def test_a_plan_numbers_only_its_own_list() -> None:
    md = "## Temario\n\n1. Uno\n2. Dos\n\nY además:\n\n- una nota\n"
    piezas = bloques_a_widgets(md, "plan", None, None)
    assert [p["letra"] for p in piezas if p["tipo"] == "opcion"] == ["1.", "2."]


def test_the_correction_never_reaches_a_later_list() -> None:
    """Marking is by option index; a later list must not be marked at all."""
    md = "- do\n- are\n\nNota:\n\n- algo más\n"
    piezas = bloques_a_widgets(md, "pregunta", "b", "a")
    assert [p["estado"] for p in piezas if p["tipo"] == "opcion"] == [
        "fallada",
        "correcta",
    ]
