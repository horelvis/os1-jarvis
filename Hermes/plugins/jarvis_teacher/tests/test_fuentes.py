"""The base he leans on, and the gate in front of it.

Nothing here goes to the network: `buscar` and `traer` are callables,
the way `cameras.py` takes `on_detections`.
"""

from pathlib import Path

import pytest

from Hermes.plugins.jarvis_teacher.curso import Curso
from Hermes.plugins.jarvis_teacher.fuentes import Base, Resultado, a_texto, host_de


@pytest.fixture
def base(tmp_path: Path) -> Base:
    curso = Curso(tmp_path / "curso.db")

    def buscar(consulta: str) -> list[Resultado]:
        return [
            Resultado("https://cambridgeenglish.org/b1", "B1 Preliminary", "El examen"),
            Resultado("https://ejemplo.net/gramatica", "Gramática", "Tiempos verbales"),
        ]

    def traer(url: str) -> str:
        if "cambridge" in url:
            return "<html><body><p>The present perfect is used for experience.</p></body></html>"
        return "<html><body><p>El pasado simple se usa para acciones terminadas.</p></body></html>"

    return Base(curso, tmp_path / "fuentes", buscar=buscar, traer=traer)


def test_candidates_are_metadata_and_nothing_is_fetched(
    base: Base, tmp_path: Path
) -> None:
    cid = base.curso.abrir("B1", now=1000.0)
    candidatos = base.candidatos(cid, "B1")
    assert [c.titulo for c in candidatos] == ["B1 Preliminary", "Gramática"]
    assert not (tmp_path / "fuentes").exists()


def test_building_the_base_stores_text_and_domains(base: Base) -> None:
    cid = base.curso.abrir("B1", now=1000.0)
    urls = ["https://cambridgeenglish.org/b1"]
    base.aprobar_dominios(cid, urls, now=1000.0)
    assert base.construir(cid, urls, now=1000.0) == 1
    with base.curso.conexion() as db:
        assert (
            db.execute(
                "SELECT COUNT(*) FROM fuente WHERE curso = ?", (cid,)
            ).fetchone()[0]
            == 1
        )
        assert (
            db.execute(
                "SELECT COUNT(*) FROM dominio WHERE curso = ?", (cid,)
            ).fetchone()[0]
            == 1
        )


def test_a_domain_that_was_never_approved_is_refused(base: Base) -> None:
    cid = base.curso.abrir("B1", now=1000.0)
    base.aprobar_dominios(cid, ["https://cambridgeenglish.org/b1"], now=1000.0)
    assert base.construir(cid, ["https://otro.com/x"], now=1001.0) == 0


def test_a_fetch_that_fails_costs_only_its_source(tmp_path: Path) -> None:
    curso = Curso(tmp_path / "curso.db")

    def traer(url: str) -> str:
        if "roto" in url:
            raise OSError("timeout")
        return "<p>bien</p>"

    base = Base(curso, tmp_path / "f", buscar=lambda _q: [], traer=traer)
    cid = curso.abrir("t", now=1.0)
    urls = ["https://a.com/roto", "https://a.com/bien"]
    base.aprobar_dominios(cid, urls, now=1.0)
    assert base.construir(cid, urls, now=1.0) == 1


def test_passages_are_found_by_keyword_in_what_was_stored(base: Base) -> None:
    cid = base.curso.abrir("B1", now=1000.0)
    urls = ["https://cambridgeenglish.org/b1", "https://ejemplo.net/gramatica"]
    base.aprobar_dominios(cid, urls, now=1000.0)
    base.construir(cid, urls, now=1000.0)
    pasajes = base.pasajes(cid, "present perfect")
    assert pasajes
    assert "present perfect" in pasajes[0][1].lower()


def test_html_is_reduced_to_text() -> None:
    texto = a_texto("<html><script>malo()</script><p>Hola <b>mundo</b></p></html>")
    assert "malo" not in texto
    assert "Hola mundo" in texto


def test_the_host_is_what_is_approved() -> None:
    assert host_de("https://www.cambridgeenglish.org/b1?x=1") == "cambridgeenglish.org"
