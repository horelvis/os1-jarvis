"""The card as state: how tall, how long, and what a press does.

No GTK in here, the way `photo.py` sits under `photo_area.py`.
"""

from jarvis_widget.ficha import (
    AMPLIA,
    COMPACTA,
    CORREGIDA_S,
    ESPERA_S,
    EXPLICACION_S,
    MAX_ALTO,
    FichaModel,
)

PREGUNTA = "## ¿Cuál?\n\n- a\n- b\n- c\n"


def test_a_question_takes_room_and_says_so() -> None:
    m = FichaModel()
    assert m.mostrar(PREGUNTA, "pregunta", "", None, None, now=0.0) is True
    assert m.visible
    assert 0 < m.height <= MAX_ALTO


def test_a_question_does_not_fade_while_it_waits() -> None:
    m = FichaModel()
    m.mostrar(PREGUNTA, "pregunta", "", None, None, now=0.0)
    assert m.tick(now=EXPLICACION_S + 1) is False
    assert m.visible


def test_a_question_gives_up_after_five_minutes() -> None:
    m = FichaModel()
    m.mostrar(PREGUNTA, "pregunta", "", None, None, now=0.0)
    assert m.tick(now=ESPERA_S + 1) is True
    assert not m.visible


def test_an_explanation_goes_after_a_minute() -> None:
    m = FichaModel()
    m.mostrar("## La tercera ley\n\nTexto.", "explicacion", "", None, None, now=0.0)
    assert m.tick(now=EXPLICACION_S - 1) is False
    assert m.tick(now=EXPLICACION_S + 1) is True


def test_a_correction_replaces_the_question_and_then_goes() -> None:
    m = FichaModel()
    m.mostrar(PREGUNTA, "pregunta", "", None, None, now=0.0)
    m.mostrar(PREGUNTA, "pregunta", "", "b", "a", now=10.0)
    assert m.correcta == "b" and m.elegida == "a"
    assert m.tick(now=10.0 + CORREGIDA_S + 1) is True
    assert not m.visible


def test_a_plan_waits_like_a_question() -> None:
    m = FichaModel()
    m.mostrar("## Temario\n\n1. Uno\n2. Dos\n", "plan", "", None, None, now=0.0)
    assert m.tick(now=EXPLICACION_S + 1) is False


def test_a_press_puts_it_away() -> None:
    m = FichaModel()
    m.mostrar(PREGUNTA, "pregunta", "", None, None, now=0.0)
    assert m.click(now=1.0) is True
    assert not m.visible


def test_a_press_with_nothing_up_changes_nothing() -> None:
    assert FichaModel().click(now=1.0) is False


def test_a_short_card_takes_the_compact_band():
    m = FichaModel()
    m.mostrar("## ¿Cuál?\n\n- a\n- b\n", "pregunta", "", None, None, now=0.0)
    assert m.height == COMPACTA


def test_a_long_card_takes_the_wide_band_and_scrolls_inside_it():
    # Eleven points is the real syllabus that broke the previous
    # approach: it asked for 334 px of a 430 px window and squeezed the
    # wave out of the strip. A band that cannot exceed its own size
    # cannot do that, whatever the content.
    md = "## Temario\n\n" + "\n".join(f"{i + 1}. Punto {i + 1}" for i in range(11))
    m = FichaModel()
    m.mostrar(md, "plan", "", None, None, now=0.0)
    assert m.height == AMPLIA
    assert m.height <= MAX_ALTO


def test_no_card_however_long_can_exceed_the_ceiling():
    md = "\n".join(f"- opción {i}" for i in range(200))
    m = FichaModel()
    m.mostrar(md, "pregunta", "", None, None, now=0.0)
    assert m.height <= MAX_ALTO
