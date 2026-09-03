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


# ── review round 1: three findings ─────────────────────────────────────


def test_preguntar_after_a_restart_asks_about_the_taught_concept(
    tmp_path: Path, monkeypatch
) -> None:
    """`_concepto_actual` is memory only; a restart is a fresh `Aula`.

    Reproduces the review's finding exactly: two concepts, the first
    explained, then a fresh `Aula` over the same database asks a
    question. Without the `_ultimo_dado` fallback, `preguntar` would ask
    `curso.siguiente()`, which — now that "Past continuous" is 'dado' —
    names "Present perfect" instead, and a wrong answer would mark the
    WRONG concept for review.
    """
    monkeypatch.setenv("JARVIS_TEACHER_HOME", str(tmp_path))
    curso = Curso(tmp_path / "curso.db")
    base = Base(
        curso,
        tmp_path / "f",
        buscar=lambda _q: [Resultado("https://cambridgeenglish.org/b1", "B1", "x")],
        traer=lambda _u: "<p>The past continuous: what were you doing?</p>",
    )

    async def push_1(md: str, tipo: str, **kw):
        return True

    aula_1 = Aula(curso, base, push_ficha=push_1)
    asyncio.run(aula_1.ensename({"tema": "B1"}))
    asyncio.run(
        aula_1.planificar({"temario": "1. Past continuous\n2. Present perfect\n"})
    )
    asyncio.run(aula_1.aprobar({}))
    asyncio.run(aula_1.explicar({"concepto": "Past continuous"}))

    recogido_2: list = []

    async def push_2(md: str, tipo: str, **kw):
        recogido_2.append((tipo, md, kw))
        return True

    # A restart: a fresh `Aula`, `_concepto_actual` empty, same database.
    aula_2 = Aula(curso, base, push_ficha=push_2)
    asyncio.run(aula_2.preguntar({"ficha": PREGUNTA, "correcta": "b"}))
    asyncio.run(aula_2.responder({"elegida": "a"}))

    hoja = curso.hoja(curso.ultimo_abierto())
    assert "A repasar: Past continuous" in hoja
    assert "A repasar: Present perfect" not in hoja


def test_preguntar_cites_the_source_explicar_found(aula) -> None:
    asyncio.run(aula.explicar({"concepto": "Past continuous"}))
    asyncio.run(aula.preguntar({"ficha": PREGUNTA, "correcta": "b"}))
    _tipo, _md, kw = aula.recogido[-1]
    assert kw["fuente"]
    with aula._curso.conexion() as db:
        fila = db.execute(
            "SELECT fuente FROM pregunta ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert fila[0]


def test_no_passages_means_no_citation_ever_invented(aula) -> None:
    """When `explicar` found nothing, `preguntar` must not fake a source."""
    asyncio.run(aula.explicar({"concepto": "Subjunctive inversion"}))
    asyncio.run(aula.preguntar({"ficha": PREGUNTA, "correcta": "b"}))
    _tipo, _md, kw = aula.recogido[-1]
    assert not kw.get("fuente")
    with aula._curso.conexion() as db:
        fila = db.execute(
            "SELECT fuente FROM pregunta ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert fila[0] is None


def test_letra_reads_an_ordinal() -> None:
    opciones = ["did", "were", "have"]
    assert Aula._letra("la segunda", opciones) == "b"
    assert Aula._letra("la primera", opciones) == "a"
    assert Aula._letra("la tercera", opciones) == "c"


def test_letra_strips_trailing_punctuation() -> None:
    opciones = ["did", "were", "have"]
    assert Aula._letra("b.", opciones) == "b"
    assert Aula._letra("¿la segunda?", opciones) == "b"


def test_responder_understands_a_spoken_ordinal(aula) -> None:
    asyncio.run(aula.preguntar({"ficha": PREGUNTA, "correcta": "b"}))
    salida = asyncio.run(aula.responder({"elegida": "la segunda"}))
    assert "correcta" in salida.lower()
