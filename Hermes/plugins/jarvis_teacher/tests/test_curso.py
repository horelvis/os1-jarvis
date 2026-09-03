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
    curso.registrar_respuesta(cid, "Órbitas", acierto=True, now=1002.0)
    curso.registrar_respuesta(cid, "Órbitas", acierto=True, now=1003.0)
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
