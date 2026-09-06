"""Tests for `bienvenida.BienvenidaModel` — no GTK, no display needed."""

from __future__ import annotations

from jarvis_widget.bienvenida import ALTO, INSTRUCCION, BienvenidaModel


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


def test_instruccion_stands_on_its_own() -> None:
    # The whole point: there is no second screen, so this one sentence
    # has to be a complete instruction by itself.
    assert INSTRUCCION == "Dígame esta frase para que sepa quién es usted."
