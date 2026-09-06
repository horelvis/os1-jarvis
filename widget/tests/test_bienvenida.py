"""Tests for `bienvenida.BienvenidaModel` — no GTK, no display needed."""

from __future__ import annotations

from jarvis_widget.bienvenida import ALTO, BIENVENIDA, NECESIDAD, BienvenidaModel


def test_starts_hidden() -> None:
    modelo = BienvenidaModel()
    assert not modelo.visible
    assert modelo.height == 0
    assert modelo.frase is None


def test_mostrar_makes_it_visible_and_reports_the_resize() -> None:
    modelo = BienvenidaModel()
    assert modelo.mostrar("gato ventana lento roble") is True
    assert modelo.visible
    assert modelo.frase == "gato ventana lento roble"
    assert modelo.height == ALTO


def test_mostrar_again_with_the_same_height_reports_no_change() -> None:
    modelo = BienvenidaModel()
    modelo.mostrar("gato ventana lento roble")
    # A different phrase, same size band: the height does not move.
    assert modelo.mostrar("roble lento ventana gato") is False
    assert modelo.frase == "roble lento ventana gato"


def test_ocultar_hides_it_and_reports_the_resize() -> None:
    modelo = BienvenidaModel()
    modelo.mostrar("gato ventana lento roble")
    assert modelo.ocultar() is True
    assert not modelo.visible
    assert modelo.height == 0
    assert modelo.frase is None


def test_ocultar_when_already_hidden_is_a_harmless_no_op() -> None:
    modelo = BienvenidaModel()
    assert modelo.ocultar() is False
    assert not modelo.visible


def test_bienvenida_greets_a_stranger() -> None:
    assert BIENVENIDA == "Buenas. Aún no sé quién es usted."


def test_necesidad_says_plainly_nothing_happens_without_the_phrase() -> None:
    assert NECESIDAD == "Hasta que no la diga, no puedo hacer nada."


def test_neither_line_mentions_erasing_anything() -> None:
    # What saying the phrase actually does (founding the house, wiping
    # what came before it) belongs to the spoken confirmation later in
    # the flow, not to a strip nobody has spoken to yet.
    for texto in (BIENVENIDA, NECESIDAD):
        assert "borr" not in texto.lower()
        assert "elimin" not in texto.lower()
        assert "memoria" not in texto.lower()


def test_neither_line_is_a_shout_or_carries_an_emoji() -> None:
    # Courteous, precise, dry — never an exclamation mark, never an
    # emoji (Hermes/jarvis-soul.md: "Cero emojis. Ninguno.").
    for texto in (BIENVENIDA, NECESIDAD):
        assert "!" not in texto
        assert all(ord(c) < 0x2000 for c in texto)


def test_both_lines_are_short() -> None:
    # "Tres [frases] si de verdad hace falta. Nunca un párrafo"
    # (jarvis-soul.md) — and a strip is narrower than a paragraph needs.
    for texto in (BIENVENIDA, NECESIDAD):
        assert len(texto) <= 60
