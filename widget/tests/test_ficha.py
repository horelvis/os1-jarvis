"""The card as state: how tall, how long, and what a press does.

No GTK in here, the way `photo.py` sits under `photo_area.py`.
"""

from samantha_widget.ficha import (
    CHARS_PER_LINEA,
    CORREGIDA_S,
    ESPERA_S,
    EXPLICACION_S,
    LINEA,
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


def test_height_follows_the_content_and_is_capped() -> None:
    m = FichaModel()
    m.mostrar("## T\n\n- a\n", "pregunta", "", None, None, now=0.0)
    corto = m.height
    m.mostrar(
        "## T\n\n" + "\n".join(f"- opción {i}" for i in range(40)),
        "pregunta",
        "",
        None,
        None,
        now=1.0,
    )
    assert m.height > corto
    assert m.height <= MAX_ALTO


def test_a_press_with_nothing_up_changes_nothing() -> None:
    assert FichaModel().click(now=1.0) is False


def test_long_paragraph_reserves_more_height_than_short_one() -> None:
    """Text wrapping: a long paragraph should reserve more lines than a short one."""
    m = FichaModel()
    short = "Brief."
    m.mostrar(f"## Title\n\n{short}", "pregunta", "", None, None, now=0.0)
    short_height = m.height

    long = "a" * (CHARS_PER_LINEA + 50)  # Force wrapping
    m.mostrar(f"## Title\n\n{long}", "pregunta", "", None, None, now=1.0)
    long_height = m.height

    assert long_height > short_height


def test_paragraph_at_wrap_boundary_wraps_correctly() -> None:
    """Text at wrap boundary: exactly at limit wraps to 1 line, one char past wraps to 2."""
    m = FichaModel()

    # Exactly at the boundary should be 1 line
    at_boundary = "x" * CHARS_PER_LINEA
    m.mostrar(f"## Title\n\n{at_boundary}", "pregunta", "", None, None, now=0.0)
    boundary_height = m.height

    # One char past should wrap to 2 lines and be taller
    past_boundary = "x" * (CHARS_PER_LINEA + 1)
    m.mostrar(f"## Title\n\n{past_boundary}", "pregunta", "", None, None, now=1.0)
    wrapped_height = m.height

    assert wrapped_height > boundary_height
    # One extra line of text = one extra LINEA
    assert wrapped_height == boundary_height + LINEA


def test_forty_line_card_still_clamps_to_max_alto() -> None:
    """The 40-line card test still respects MAX_ALTO ceiling."""
    m = FichaModel()
    m.mostrar(
        "## T\n\n" + "\n".join(f"- opción {i}" for i in range(40)),
        "pregunta",
        "",
        None,
        None,
        now=0.0,
    )
    assert m.height <= MAX_ALTO
