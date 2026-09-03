"""What a card turns into, decided without a display.

This replaced `test_ficha_render.py` on 2026-09-03, when the card
stopped being GTK labels and became a WebKitGTK document. The split
survives: the HTML is built by a pure function, so everything that
matters — the escaping, the lettering, the correction, the inlining —
is still testable on a box with no screen, which is every box this
repo's tests run on.
"""

import base64

from jarvis_widget.ficha_html import a_html

PREGUNTA = "## ¿Cuál?\n\n- did\n- were\n- have\n"


def test_a_question_letters_its_options():
    html = a_html(PREGUNTA, "pregunta")
    assert 'class="opciones"' in html


def test_a_plan_numbers_them_instead():
    html = a_html("## Temario\n\n- Uno\n- Dos\n", "plan")
    assert 'class="plan"' in html
    assert 'class="opciones"' not in html


def test_an_explanation_marks_no_answer_set():
    html = a_html("Texto suelto con una lista\n\n- una nota\n", "explicacion")
    assert 'class="opciones"' not in html and 'class="plan"' not in html


def test_the_correction_marks_the_right_one_and_yours():
    html = a_html(PREGUNTA, "pregunta", correcta="b", elegida="a")
    assert "<li class='correcta'>were" in html
    assert "<li class='fallada'>did" in html
    assert "<li class='apagada'>have" in html


def test_an_unanswered_question_marks_nothing():
    html = a_html(PREGUNTA, "pregunta")
    assert "correcta" not in html and "fallada" not in html


def test_html_in_the_markdown_is_escaped_not_run():
    # The card can carry text taken from a web page, so this is the
    # boundary that matters most in the file.
    html = a_html("Mira <script>alert(1)</script> y <b>esto</b>", "explicacion")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_a_local_image_is_inlined_as_a_data_uri(tmp_path):
    png = tmp_path / "x.png"
    png.write_bytes(
        base64.b64decode(
            b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
        )
    )
    html = a_html(f"![]({png})", "explicacion")
    assert "data:image/png;base64," in html
    assert str(png) not in html


def test_a_remote_image_never_survives_into_the_document():
    # `imagen.py` resolves references to the spool before a card is
    # pushed; this is the second gate, and it must not fetch either.
    html = a_html("![](https://evil.example/x.png)", "explicacion")
    assert "https://evil.example" not in html


def test_an_image_that_is_not_there_costs_the_picture_not_the_card():
    html = a_html("## T\n\n![](/no/existe.png)\n\n- a\n", "pregunta")
    assert "<h2>T</h2>" in html
    assert "did" not in html
    assert "<li" in html


def test_the_source_line_is_escaped_too():
    html = a_html("x", "explicacion", fuente="Cambridge <b>B1</b>")
    assert "&lt;b&gt;B1&lt;/b&gt;" in html


def test_an_empty_card_is_still_a_document():
    html = a_html("", "explicacion")
    assert html.startswith("<!doctype html>")


def test_only_the_first_list_is_the_answer_set():
    # A card with a trailing note-list would otherwise draw options
    # nobody can choose — the defect the previous renderer was fixed for.
    html = a_html("## ¿Cuál?\n\n- did\n- were\n\nY además:\n\n- una nota\n", "pregunta")
    assert html.count('class="opciones"') == 1
