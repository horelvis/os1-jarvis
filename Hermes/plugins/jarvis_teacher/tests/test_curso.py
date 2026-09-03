"""The course as stored facts, not as something the model remembers."""

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
    # Insert one correct pregunta before first registrar_respuesta
    with curso.conexion() as db:
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
    # Insert second correct pregunta before second registrar_respuesta
    with curso.conexion() as db:
        db.execute(
            "INSERT INTO pregunta (curso, concepto, md, opciones, correcta, acierto, hecha_en) "
            "VALUES (?, ?, 'q2', 'a,b', 'a', 1, 1003.0)",
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
