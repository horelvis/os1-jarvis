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


def test_letra_prefers_an_options_own_text_over_an_ordinal_inside_it() -> None:
    """An option can itself contain an ordinal word ("la segunda derivada").

    Naming that option by its own words must win over reading the
    ordinal it happens to contain as if it named a DIFFERENT option —
    the exact collision review round 1's ordinal fix introduced.
    """
    opciones = ["la derivada primera", "la integral", "la segunda derivada"]
    assert Aula._letra("la segunda derivada", opciones) == "c"
    # A bare ordinal, naming nothing's own text, still reads as an ordinal.
    assert Aula._letra("la segunda", opciones) == "b"


def test_responder_understands_a_spoken_ordinal(aula) -> None:
    asyncio.run(aula.preguntar({"ficha": PREGUNTA, "correcta": "b"}))
    salida = asyncio.run(aula.responder({"elegida": "la segunda"}))
    assert "correcta" in salida.lower()


# ── final review: scoring, and what a card is worth if it scores wrong ──


def test_the_stored_answer_is_normalised_the_way_the_spoken_one_is(aula) -> None:
    """The model writes "b."; the person says "la b". Both are 'b'.

    Untouched, `correcta` was compared raw against a normalised
    `elegida`, so EVERY answer scored wrong: he said "No: la correcta
    era la b." out loud, the card marked nothing right, and the concept
    was filed 'a repasar'.
    """
    asyncio.run(aula.preguntar({"ficha": PREGUNTA, "correcta": "b."}))
    salida = asyncio.run(aula.responder({"elegida": "la b"}))
    assert salida == "Respuesta correcta."
    _tipo, _md, kw = aula.recogido[-1]
    assert (kw["correcta"], kw["elegida"]) == ("b", "b")


def test_the_stored_answer_may_be_the_options_own_words(aula) -> None:
    asyncio.run(aula.preguntar({"ficha": PREGUNTA, "correcta": "were"}))
    salida = asyncio.run(aula.responder({"elegida": "la segunda"}))
    assert salida == "Respuesta correcta."
    with aula._curso.conexion() as db:
        guardada = db.execute(
            "SELECT correcta FROM pregunta ORDER BY id DESC LIMIT 1"
        ).fetchone()[0]
    assert guardada == "b"


def test_a_correct_answer_nobody_can_read_asks_for_the_card_again(aula) -> None:
    antes = len(aula.recogido)
    salida = asyncio.run(aula.preguntar({"ficha": PREGUNTA, "correcta": "ninguna"}))
    assert len(aula.recogido) == antes
    assert "lista" in salida.lower()


def test_an_option_that_is_a_word_inside_another_never_matches(aula) -> None:
    """The archetypal B1 article question: options `a` / `an` / `the`.

    "la tercera" contains the letters of option `a` inside "tercera",
    and a bare substring match answered 'a' to somebody who had said
    the third one.
    """
    opciones = ["a", "an", "the"]
    assert Aula._letra("la tercera", opciones) == "c"
    assert Aula._letra("la segunda", opciones) == "b"


def test_an_options_own_words_still_win_inside_a_longer_sentence(aula) -> None:
    """Whole words, not whole utterances: he answers in a sentence."""
    opciones = ["did", "were", "have"]
    assert Aula._letra("pues yo diría que were, señor", opciones) == "b"


def test_aprobar_refuses_a_course_that_has_no_plan_and_fetches_nothing(
    tmp_path: Path, monkeypatch
) -> None:
    """`ensename` then `aprobar` inside one model turn, with no plan.

    The plan card is what puts the candidate domains in front of a
    person; without one, approving would fetch every page into the
    context of an agent holding `terminal` with nobody having seen a
    thing.
    """
    monkeypatch.setenv("JARVIS_TEACHER_HOME", str(tmp_path))
    curso = Curso(tmp_path / "curso.db")
    traidas: list[str] = []

    def traer(url: str) -> str:
        traidas.append(url)
        return "<p>lo que sea</p>"

    base = Base(
        curso,
        tmp_path / "f",
        buscar=lambda _q: [Resultado("https://x.org/a", "A", "r")],
        traer=traer,
    )

    async def push(md: str, tipo: str, **kw):
        return True

    aula = Aula(curso, base, push_ficha=push)
    asyncio.run(aula.ensename({"tema": "B1"}))
    salida = asyncio.run(aula.aprobar({}))

    curso_id = curso.ultimo_abierto()
    assert curso_id is not None
    assert not curso.plan_aprobado(curso_id)
    assert traidas == []
    assert "aprobado" not in salida.lower()


def test_a_replaced_question_is_settled_as_unanswered(aula) -> None:
    """A second `preguntar` while one is open orphaned the first row.

    `elegida` and `acierto` stayed NULL for ever, and the fact sheet
    counted it as practice — the denominator he reads out loud.
    """
    asyncio.run(aula.preguntar({"ficha": PREGUNTA, "correcta": "b"}))
    asyncio.run(aula.preguntar({"ficha": PREGUNTA, "correcta": "a"}))
    asyncio.run(aula.responder({"elegida": "a"}))

    with aula._curso.conexion() as db:
        filas = db.execute(
            "SELECT abandonada, elegida, acierto FROM pregunta ORDER BY id"
        ).fetchall()
    assert filas[0] == (1, None, None)
    assert filas[1] == (0, "a", 1)
    assert "Practicado con material real: 0 preguntas de 1." in aula._curso.hoja(
        aula._curso.ultimo_abierto()
    )


def test_responder_corrects_its_own_row_not_the_newest_one(aula) -> None:
    """The row is captured at insert, not looked up as `MAX(id)`."""
    asyncio.run(aula.preguntar({"ficha": PREGUNTA, "correcta": "b"}))
    abierta = dict(aula._abierta or {})
    # Something else lands in the table after the open question.
    with aula._curso.conexion() as db:
        db.execute(
            "INSERT INTO pregunta (curso, concepto, md, opciones, correcta, hecha_en) "
            "VALUES (?, 'otro', 'q', 'a,b', 'a', 9999.0)",
            (abierta["curso"],),
        )
    asyncio.run(aula.responder({"elegida": "la b"}))
    with aula._curso.conexion() as db:
        elegida_suya = db.execute(
            "SELECT elegida FROM pregunta WHERE id = ?", (abierta["id"],)
        ).fetchone()[0]
        elegida_ajena = db.execute(
            "SELECT elegida FROM pregunta WHERE concepto = 'otro'"
        ).fetchone()[0]
    assert elegida_suya == "b"
    assert elegida_ajena is None


def test_terminar_settles_a_question_left_open(aula) -> None:
    asyncio.run(aula.preguntar({"ficha": PREGUNTA, "correcta": "b"}))
    asyncio.run(aula.terminar({}))
    with aula._curso.conexion() as db:
        abandonada = db.execute(
            "SELECT abandonada FROM pregunta ORDER BY id DESC LIMIT 1"
        ).fetchone()[0]
    assert abandonada == 1


def test_he_speaks_to_the_user_as_usted(tmp_path: Path, monkeypatch) -> None:
    """`jarvis-soul.md` is usted and "señor"; three of these tuteaban.

    And what `ensename` hands the model must not name a tool: the text
    can be relayed out loud, and §1 says he never performs using his
    tools.
    """
    monkeypatch.setenv("JARVIS_TEACHER_HOME", str(tmp_path))
    curso = Curso(tmp_path / "curso.db")
    sin_nada = Base(curso, tmp_path / "f", buscar=lambda _q: [], traer=lambda _u: "")
    con_algo = Base(
        curso,
        tmp_path / "f",
        buscar=lambda _q: [Resultado("https://x.org/a", "A", "r")],
        traer=lambda _u: "<p>x</p>",
    )

    async def push(md: str, tipo: str, **kw):
        return True

    # No course open at all.
    vacia = asyncio.run(Aula(curso, sin_nada, push_ficha=push).ensename({}))
    assert "Dígame qué quiere estudiar" in vacia

    # A search that brings nothing back.
    nada = asyncio.run(Aula(curso, sin_nada, push_ficha=push).ensename({"tema": "x"}))
    assert "Pruebe a decírmelo" in nada

    # The candidates, and the instruction that goes with them.
    ofrecidas = asyncio.run(
        Aula(curso, con_algo, push_ficha=push).ensename({"tema": "y"})
    )
    assert "planificar" not in ofrecidas

    # A plan whose candidates the process has forgotten.
    curso_id = curso.ultimo_abierto()
    assert curso_id is not None
    curso.proponer_plan(curso_id, ["Uno"], now=1000.0)
    olvidada = asyncio.run(Aula(curso, con_algo, push_ficha=push).aprobar({}))
    assert "Dígame otra vez" in olvidada
