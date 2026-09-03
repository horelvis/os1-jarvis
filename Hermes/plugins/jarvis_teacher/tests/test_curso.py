"""The course as stored facts, not as something the model remembers."""

from datetime import datetime
from pathlib import Path

import pytest

from Hermes.plugins.jarvis_teacher.curso import Curso


@pytest.fixture
def curso(tmp_path: Path) -> Curso:
    return Curso(tmp_path / "curso.db")


def test_plan_keeps_its_order(curso: Curso) -> None:
    cid = curso.abrir("sacar el B1 de inglés", now=1000.0)
    curso.proponer_plan(
        cid, ["Presente simple", "Pasado simple", "Condicionales"], now=1000.0
    )
    assert curso.aprobar_plan(cid, now=1001.0) == "Presente simple"
    assert curso.siguiente(cid) == "Presente simple"


def test_an_unapproved_plan_does_not_advance(curso: Curso) -> None:
    cid = curso.abrir("astronomía", now=1000.0)
    curso.proponer_plan(cid, ["Órbitas", "Mareas"], now=1000.0)
    assert curso.siguiente(cid) is None


def test_a_miss_sends_a_concept_back_to_the_queue(curso: Curso) -> None:
    cid = curso.abrir("astronomía", now=1000.0)
    curso.proponer_plan(cid, ["Órbitas", "Mareas"], now=1000.0)
    curso.aprobar_plan(cid, now=1000.0)
    curso.marcar_dado(cid, "Órbitas", now=1001.0)
    curso.registrar_respuesta(cid, "Órbitas", acierto=False, now=1002.0)
    assert "Órbitas" in curso.hoja(cid)
    assert "A repasar: Órbitas" in curso.hoja(cid)


def test_two_hits_retire_a_concept(curso: Curso) -> None:
    cid = curso.abrir("astronomía", now=1000.0)
    curso.proponer_plan(cid, ["Órbitas", "Mareas"], now=1000.0)
    curso.aprobar_plan(cid, now=1000.0)
    curso.marcar_dado(cid, "Órbitas", now=1001.0)
    # Insert one incorrect and one correct pregunta before first registrar_respuesta
    # The incorrect one ensures the filter acierto=1 actually matters
    with curso.conexion() as db:
        db.execute(
            "INSERT INTO pregunta (curso, concepto, md, opciones, correcta, acierto, hecha_en) "
            "VALUES (?, ?, 'q0', 'a,b', 'a', 0, 1001.5)",
            (cid, "Órbitas"),
        )
        db.execute(
            "INSERT INTO pregunta (curso, concepto, md, opciones, correcta, acierto, hecha_en) "
            "VALUES (?, ?, 'q1', 'a,b', 'a', 1, 1002.0)",
            (cid, "Órbitas"),
        )
    curso.registrar_respuesta(cid, "Órbitas", acierto=True, now=1002.0)
    with curso.conexion() as db:
        estado = db.execute(
            "SELECT estado FROM concepto WHERE curso = ? AND titulo = ?",
            (cid, "Órbitas"),
        ).fetchone()[0]
    assert estado == "dado", f"After 1 correct, estado should be 'dado', got '{estado}'"
    # Insert one incorrect and one correct pregunta before second registrar_respuesta
    with curso.conexion() as db:
        db.execute(
            "INSERT INTO pregunta (curso, concepto, md, opciones, correcta, acierto, hecha_en) "
            "VALUES (?, ?, 'q2', 'a,b', 'a', 0, 1002.5)",
            (cid, "Órbitas"),
        )
        db.execute(
            "INSERT INTO pregunta (curso, concepto, md, opciones, correcta, acierto, hecha_en) "
            "VALUES (?, ?, 'q3', 'a,b', 'a', 1, 1003.0)",
            (cid, "Órbitas"),
        )
    curso.registrar_respuesta(cid, "Órbitas", acierto=True, now=1003.0)
    with curso.conexion() as db:
        estado = db.execute(
            "SELECT estado FROM concepto WHERE curso = ? AND titulo = ?",
            (cid, "Órbitas"),
        ).fetchone()[0]
    assert estado == "dominado", (
        f"After 2 correct, estado should be 'dominado', got '{estado}'"
    )
    assert curso.siguiente(cid) == "Mareas"
    assert "A repasar:" not in curso.hoja(cid)


def test_replanning_discards_rather_than_deletes(curso: Curso) -> None:
    cid = curso.abrir("astronomía", now=1000.0)
    curso.proponer_plan(cid, ["Órbitas", "Mareas"], now=1000.0)
    curso.proponer_plan(cid, ["Órbitas", "Eclipses"], now=1001.0)
    with curso.conexion() as db:
        filas = db.execute(
            "SELECT titulo, estado FROM concepto WHERE curso = ? ORDER BY id", (cid,)
        ).fetchall()
    assert ("Mareas", "descartada") in [(f[0], f[1]) for f in filas]


def test_a_session_is_opened_once_and_closed_by_terminar(curso: Curso) -> None:
    cid = curso.abrir("astronomía", now=1000.0)
    curso.empezar_sesion(cid, now=1000.0)
    curso.empezar_sesion(cid, now=1001.0)
    with curso.conexion() as db:
        assert (
            db.execute(
                "SELECT COUNT(*) FROM sesion WHERE curso = ?", (cid,)
            ).fetchone()[0]
            == 1
        )


def test_the_fact_sheet_is_labelled_data(curso: Curso) -> None:
    cid = curso.abrir("sacar el B1 de inglés", now=1000.0)
    curso.proponer_plan(cid, ["Presente simple", "Pasado simple"], now=1000.0)
    curso.aprobar_plan(cid, now=1000.0)
    hoja = curso.hoja(cid)
    assert "Tema: sacar el B1 de inglés" in hoja
    assert "Dados: 0 de 2" in hoja
    assert "Siguiente: Presente simple" in hoja


def test_repaso_hueco_gap_between_miss_and_return(curso: Curso) -> None:
    """A missed concept returns after REPASO_HUECO other concepts are taught."""
    cid = curso.abrir("cinco temas", now=1000.0)
    conceptos = ["A", "B", "C", "D", "E"]
    curso.proponer_plan(cid, conceptos, now=1000.0)
    curso.aprobar_plan(cid, now=1000.0)

    # Teach and miss concept A
    curso.marcar_dado(cid, "A", now=1001.0)
    with curso.conexion() as db:
        db.execute(
            "INSERT INTO pregunta (curso, concepto, md, opciones, correcta, acierto, hecha_en) "
            "VALUES (?, ?, 'q', 'a,b', 'a', 0, 1001.0)",
            (cid, "A"),
        )
    curso.registrar_respuesta(cid, "A", acierto=False, now=1001.0)

    # Next should be B (skip A during the gap)
    assert curso.siguiente(cid) == "B"

    # Teach B, C, D (REPASO_HUECO = 3)
    for i, titulo in enumerate(["B", "C", "D"], start=1):
        curso.marcar_dado(cid, titulo, now=1002.0 + i)
        with curso.conexion() as db:
            db.execute(
                "INSERT INTO pregunta (curso, concepto, md, opciones, correcta, acierto, hecha_en) "
                "VALUES (?, ?, 'q', 'a,b', 'a', 1, ?)",
                (cid, titulo, 1002.0 + i),
            )
        curso.registrar_respuesta(cid, titulo, acierto=True, now=1002.0 + i)

    # Now A should come back (gap is satisfied)
    assert curso.siguiente(cid) == "A"


def test_repaso_hueco_fallback_when_nothing_pending(curso: Curso) -> None:
    """When nothing pending is left, offer 'a repasar' even inside the gap."""
    cid = curso.abrir("tres temas", now=1000.0)
    conceptos = ["X", "Y", "Z"]
    curso.proponer_plan(cid, conceptos, now=1000.0)
    curso.aprobar_plan(cid, now=1000.0)

    # Teach and miss X
    curso.marcar_dado(cid, "X", now=1001.0)
    with curso.conexion() as db:
        db.execute(
            "INSERT INTO pregunta (curso, concepto, md, opciones, correcta, acierto, hecha_en) "
            "VALUES (?, ?, 'q', 'a,b', 'a', 0, 1001.0)",
            (cid, "X"),
        )
    curso.registrar_respuesta(cid, "X", acierto=False, now=1001.0)

    # Teach Y and Z (only 2 concepts, less than REPASO_HUECO=3)
    for i, titulo in enumerate(["Y", "Z"], start=1):
        curso.marcar_dado(cid, titulo, now=1002.0 + i)
        with curso.conexion() as db:
            db.execute(
                "INSERT INTO pregunta (curso, concepto, md, opciones, correcta, acierto, hecha_en) "
                "VALUES (?, ?, 'q', 'a,b', 'a', 1, ?)",
                (cid, titulo, 1002.0 + i),
            )
        curso.registrar_respuesta(cid, titulo, acierto=True, now=1002.0 + i)

    # Nothing pending left, so X should be offered despite the gap
    assert curso.siguiente(cid) == "X"


def test_two_simultaneous_misses_maintain_independent_gaps(curso: Curso) -> None:
    """Two missed concepts maintain independent gaps, not affected by each other."""
    cid = curso.abrir("cinco temas", now=1000.0)
    conceptos = ["A", "B", "C", "D", "E"]
    curso.proponer_plan(cid, conceptos, now=1000.0)
    curso.aprobar_plan(cid, now=1000.0)

    # Teach and miss A
    curso.marcar_dado(cid, "A", now=1001.0)
    with curso.conexion() as db:
        db.execute(
            "INSERT INTO pregunta (curso, concepto, md, opciones, correcta, acierto, hecha_en) "
            "VALUES (?, ?, 'q', 'a,b', 'a', 0, 1001.0)",
            (cid, "A"),
        )
    curso.registrar_respuesta(cid, "A", acierto=False, now=1001.0)

    # Teach and miss B
    curso.marcar_dado(cid, "B", now=1002.0)
    with curso.conexion() as db:
        db.execute(
            "INSERT INTO pregunta (curso, concepto, md, opciones, correcta, acierto, hecha_en) "
            "VALUES (?, ?, 'q', 'a,b', 'a', 0, 1002.0)",
            (cid, "B"),
        )
    curso.registrar_respuesta(cid, "B", acierto=False, now=1002.0)

    # Teach C, D, E (3 genuine successes, satisfies both gaps)
    for i, titulo in enumerate(["C", "D", "E"], start=1):
        curso.marcar_dado(cid, titulo, now=1003.0 + i)
        with curso.conexion() as db:
            db.execute(
                "INSERT INTO pregunta (curso, concepto, md, opciones, correcta, acierto, hecha_en) "
                "VALUES (?, ?, 'q', 'a,b', 'a', 1, ?)",
                (cid, titulo, 1003.0 + i),
            )
        curso.registrar_respuesta(cid, titulo, acierto=True, now=1003.0 + i)

    # Both A and B should be ready (they both have fallado_tras = 0)
    # A comes first in order
    assert curso.siguiente(cid) == "A"


def test_repaso_hueco_insufficient_gap_does_not_return_early(curso: Curso) -> None:
    """Missed concepts must wait for REPASO_HUECO, not coming back early due to 'a repasar' counting."""
    cid = curso.abrir("seis temas", now=1000.0)
    conceptos = ["A", "B", "C", "D", "E", "F"]
    curso.proponer_plan(cid, conceptos, now=1000.0)
    curso.aprobar_plan(cid, now=1000.0)

    # Teach and miss A
    curso.marcar_dado(cid, "A", now=1001.0)
    with curso.conexion() as db:
        db.execute(
            "INSERT INTO pregunta (curso, concepto, md, opciones, correcta, acierto, hecha_en) "
            "VALUES (?, ?, 'q', 'a,b', 'a', 0, 1001.0)",
            (cid, "A"),
        )
    curso.registrar_respuesta(cid, "A", acierto=False, now=1001.0)

    # Teach and miss B
    curso.marcar_dado(cid, "B", now=1002.0)
    with curso.conexion() as db:
        db.execute(
            "INSERT INTO pregunta (curso, concepto, md, opciones, correcta, acierto, hecha_en) "
            "VALUES (?, ?, 'q', 'a,b', 'a', 0, 1002.0)",
            (cid, "B"),
        )
    curso.registrar_respuesta(cid, "B", acierto=False, now=1002.0)

    # Teach C and D successfully (only 2 genuine successes, less than REPASO_HUECO=3)
    for i, titulo in enumerate(["C", "D"], start=1):
        curso.marcar_dado(cid, titulo, now=1003.0 + i)
        with curso.conexion() as db:
            db.execute(
                "INSERT INTO pregunta (curso, concepto, md, opciones, correcta, acierto, hecha_en) "
                "VALUES (?, ?, 'q', 'a,b', 'a', 1, ?)",
                (cid, titulo, 1003.0 + i),
            )
        curso.registrar_respuesta(cid, titulo, acierto=True, now=1003.0 + i)

    # Neither A nor B should be ready yet (gap not satisfied)
    # Next should be a pending concept (E), not a missed one (A or B)
    siguiente = curso.siguiente(cid)
    assert siguiente == "E", (
        f"With only 2 genuine successes (less than REPASO_HUECO=3), "
        f"missed concepts should not be offered. Got '{siguiente}' instead of 'E'"
    )


# ── final review: the fact sheet may not drift ─────────────────────────


def test_a_readded_title_revives_its_row_instead_of_duplicating_it(
    curso: Curso,
) -> None:
    """Taking a concept out and putting it back is one row, not two.

    Without this, `existentes` was computed from the live rows only, so
    the re-added title was INSERTed beside the discarded one and
    `marcar_dado`'s `WHERE titulo = ?` updated both — a syllabus of
    three reporting "Dados: 2 de 4".
    """
    cid = curso.abrir("astronomía", now=1000.0)
    curso.proponer_plan(cid, ["Órbitas", "Mareas", "Eclipses"], now=1000.0)
    curso.proponer_plan(cid, ["Órbitas", "Eclipses"], now=1001.0)
    curso.proponer_plan(cid, ["Órbitas", "Mareas", "Eclipses"], now=1002.0)
    curso.aprobar_plan(cid, now=1003.0)

    with curso.conexion() as db:
        cuantas = db.execute(
            "SELECT COUNT(*) FROM concepto WHERE curso = ? AND titulo = 'Mareas'",
            (cid,),
        ).fetchone()[0]
    assert cuantas == 1

    curso.marcar_dado(cid, "Órbitas", now=1004.0)
    curso.marcar_dado(cid, "Mareas", now=1005.0)
    assert "Dados: 2 de 3" in curso.hoja(cid)


def test_a_revived_concept_is_pending_again(curso: Curso) -> None:
    cid = curso.abrir("astronomía", now=1000.0)
    curso.proponer_plan(cid, ["Órbitas", "Mareas"], now=1000.0)
    curso.proponer_plan(cid, ["Órbitas"], now=1001.0)
    curso.proponer_plan(cid, ["Órbitas", "Mareas"], now=1002.0)
    with curso.conexion() as db:
        estado = db.execute(
            "SELECT estado FROM concepto WHERE curso = ? AND titulo = 'Mareas'",
            (cid,),
        ).fetchone()[0]
    assert estado == "pendiente"


def test_the_fact_sheet_says_when_the_last_class_was(curso: Curso) -> None:
    """ "Where we left off" is a reading, not a recollection.

    2026-08-27 was a Thursday; the sheet has to say so, because a model
    handed nothing invents it.
    """
    cid = curso.abrir("astronomía", now=1000.0)
    curso.empezar_sesion(cid, now=1000.0)
    jueves = datetime(2026, 8, 27, 19, 30).timestamp()  # noqa: DTZ001 — local, as the sheet is
    with curso.conexion() as db:
        db.execute("UPDATE sesion SET acabo_en = ? WHERE curso = ?", (jueves, cid))
    assert "Última clase: jueves 27 de agosto." in curso.hoja(cid)


def test_a_course_with_no_finished_class_says_nothing_about_one(curso: Curso) -> None:
    cid = curso.abrir("astronomía", now=1000.0)
    curso.empezar_sesion(cid, now=1000.0)
    assert "Última clase" not in curso.hoja(cid)


def test_a_dado_concept_comes_back_once_nothing_is_pending(curso: Curso) -> None:
    """`dado` was terminal, which made `dominado` mean nothing."""
    cid = curso.abrir("astronomía", now=1000.0)
    curso.proponer_plan(cid, ["Órbitas"], now=1000.0)
    curso.aprobar_plan(cid, now=1000.0)
    curso.marcar_dado(cid, "Órbitas", now=1001.0)
    with curso.conexion() as db:
        db.execute(
            "INSERT INTO pregunta (curso, concepto, md, opciones, correcta, acierto, hecha_en) "
            "VALUES (?, ?, 'q', 'a,b', 'a', 1, 1001.0)",
            (cid, "Órbitas"),
        )
    curso.registrar_respuesta(cid, "Órbitas", acierto=True, now=1001.0)
    assert curso.siguiente(cid) == "Órbitas"


def test_a_dominado_concept_never_comes_back(curso: Curso) -> None:
    cid = curso.abrir("astronomía", now=1000.0)
    curso.proponer_plan(cid, ["Órbitas"], now=1000.0)
    curso.aprobar_plan(cid, now=1000.0)
    curso.marcar_dado(cid, "Órbitas", now=1001.0)
    for marca in (1001.0, 1002.0):
        with curso.conexion() as db:
            db.execute(
                "INSERT INTO pregunta (curso, concepto, md, opciones, correcta, acierto, hecha_en) "
                "VALUES (?, ?, 'q', 'a,b', 'a', 1, ?)",
                (cid, "Órbitas", marca),
            )
        curso.registrar_respuesta(cid, "Órbitas", acierto=True, now=marca)
    assert curso.siguiente(cid) is None


def test_a_discarded_concept_is_never_offered(curso: Curso) -> None:
    cid = curso.abrir("astronomía", now=1000.0)
    curso.proponer_plan(cid, ["Órbitas", "Mareas"], now=1000.0)
    curso.aprobar_plan(cid, now=1000.0)
    curso.marcar_dado(cid, "Órbitas", now=1001.0)
    curso.proponer_plan(cid, ["Órbitas"], now=1002.0)
    curso.aprobar_plan(cid, now=1003.0)
    assert curso.siguiente(cid) == "Órbitas"


def test_a_course_with_no_concepts_has_no_plan(curso: Curso) -> None:
    cid = curso.abrir("astronomía", now=1000.0)
    assert curso.tiene_plan(cid) is False
    curso.proponer_plan(cid, ["Órbitas"], now=1000.0)
    assert curso.tiene_plan(cid) is True
    curso.proponer_plan(cid, [], now=1001.0)
    assert curso.tiene_plan(cid) is False


def test_an_unanswered_question_is_not_counted_as_practice(curso: Curso) -> None:
    cid = curso.abrir("astronomía", now=1000.0)
    curso.proponer_plan(cid, ["Órbitas"], now=1000.0)
    curso.aprobar_plan(cid, now=1000.0)
    with curso.conexion() as db:
        db.execute(
            "INSERT INTO pregunta (curso, concepto, md, opciones, correcta, elegida, "
            "acierto, fuente, abandonada, hecha_en) "
            "VALUES (?, 'Órbitas', 'q', 'a,b', 'a', 'a', 1, 'B1', 0, 1001.0)",
            (cid,),
        )
        db.execute(
            "INSERT INTO pregunta (curso, concepto, md, opciones, correcta, fuente, "
            "abandonada, hecha_en) "
            "VALUES (?, 'Órbitas', 'q', 'a,b', 'a', 'B1', 1, 1002.0)",
            (cid,),
        )
    assert "Practicado con material real: 1 preguntas de 1." in curso.hoja(cid)
