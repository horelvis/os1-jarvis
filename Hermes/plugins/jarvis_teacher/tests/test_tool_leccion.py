"""A lesson: the passages, the card, and who decides you were right.

Scoring is the plugin's, not the model's opinion: the correct option
has been stored since the card was made.
"""

import asyncio
from pathlib import Path

import pytest

from Hermes.plugins.jarvis_teacher.curso import Curso
from Hermes.plugins.jarvis_teacher.fuentes import Base, Resultado
from Hermes.plugins.jarvis_teacher.tool import Aula

PREGUNTA = "## What ___ you doing?\n\n- did\n- were\n- have\n"


@pytest.fixture
def aula(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("JARVIS_TEACHER_HOME", str(tmp_path))
    curso = Curso(tmp_path / "curso.db")
    base = Base(
        curso,
        tmp_path / "f",
        buscar=lambda _q: [Resultado("https://cambridgeenglish.org/b1", "B1", "x")],
        traer=lambda _u: "<p>The past continuous: what were you doing?</p>",
    )
    recogido: list = []

    async def push(md: str, tipo: str, **kw):
        recogido.append((tipo, md, kw))
        return True

    aula = Aula(curso, base, push_ficha=push)
    aula.recogido = recogido  # type: ignore[attr-defined]
    asyncio.run(aula.ensename({"tema": "B1"}))
    asyncio.run(aula.planificar({"temario": "1. Past continuous\n"}))
    asyncio.run(aula.aprobar({}))
    return aula


def test_explicar_hands_back_passages_inside_an_envelope(aula) -> None:
    salida = asyncio.run(aula.explicar({"concepto": "Past continuous"}))
    assert "MATERIAL DE ESTUDIO" in salida
    assert "past continuous" in salida.lower()


def test_explicar_records_the_concept_as_taught(aula) -> None:
    asyncio.run(aula.explicar({"concepto": "Past continuous"}))
    assert "Dados: 1 de 1" in aula._curso.hoja(aula._curso.ultimo_abierto())


def test_preguntar_draws_the_card_with_letters(aula) -> None:
    asyncio.run(aula.preguntar({"ficha": PREGUNTA, "correcta": "b"}))
    tipo, md, _kw = aula.recogido[-1]
    assert tipo == "pregunta"
    assert "were" in md


def test_a_card_without_a_list_is_never_drawn(aula) -> None:
    antes = len(aula.recogido)
    salida = asyncio.run(aula.preguntar({"ficha": "## sin opciones", "correcta": "b"}))
    assert len(aula.recogido) == antes
    assert "lista" in salida.lower()


def test_responder_scores_against_what_was_stored(aula) -> None:
    asyncio.run(aula.preguntar({"ficha": PREGUNTA, "correcta": "b"}))
    salida = asyncio.run(aula.responder({"elegida": "la b"}))
    assert "correcta" in salida.lower()
    _tipo, _md, kw = aula.recogido[-1]
    assert (kw["correcta"], kw["elegida"]) == ("b", "b")


def test_a_wrong_answer_sends_the_concept_back(aula) -> None:
    asyncio.run(aula.explicar({"concepto": "Past continuous"}))
    asyncio.run(aula.preguntar({"ficha": PREGUNTA, "correcta": "b"}))
    asyncio.run(aula.responder({"elegida": "a"}))
    assert "A repasar: Past continuous" in aula._curso.hoja(
        aula._curso.ultimo_abierto()
    )


def test_responder_with_nothing_open_says_so(aula) -> None:
    salida = asyncio.run(aula.responder({"elegida": "b"}))
    assert "ninguna" in salida.lower()


def test_a_second_question_replaces_the_first(aula) -> None:
    asyncio.run(aula.preguntar({"ficha": PREGUNTA, "correcta": "b"}))
    asyncio.run(aula.preguntar({"ficha": PREGUNTA, "correcta": "a"}))
    asyncio.run(aula.responder({"elegida": "a"}))
    _tipo, _md, kw = aula.recogido[-1]
    assert kw["correcta"] == "a"


def test_terminar_closes_the_session_and_summarises(aula) -> None:
    salida = asyncio.run(aula.terminar({}))
    assert "Past continuous" in salida or "1" in salida
