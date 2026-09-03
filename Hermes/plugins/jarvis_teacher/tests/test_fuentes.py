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


def test_pasajes_finds_a_cefr_level_by_its_two_character_code(tmp_path: Path) -> None:
    """B1, A2, C1 are the driving example of the whole plan — they must not
    be filtered out as if they were noise.

    The concept is "B1" alone (not "B1 Preliminary"): with any other
    word in the concept, a longer surviving token like "preliminary"
    can still find the passage on its own, which would make this test
    pass whether or not the two-character code is kept — exactly the
    gap the first version of this test had.
    """
    curso = Curso(tmp_path / "curso.db")

    def traer(url: str) -> str:
        return "<p>Prepárate para el examen B1 Preliminary de Cambridge.</p>"

    base = Base(curso, tmp_path / "f", buscar=lambda _q: [], traer=traer)
    cid = curso.abrir("t", now=1.0)
    urls = ["https://a.com/x"]
    base.aprobar_dominios(cid, urls, now=1.0)
    base.construir(cid, urls, now=1.0)
    pasajes = base.pasajes(cid, "B1")
    assert pasajes
    assert "b1" in pasajes[0][1].lower()


def test_pasajes_a_stopword_only_concept_scores_nothing(tmp_path: Path) -> None:
    """ "de", "la", "el" are two letters too, but they are noise, not levels."""
    curso = Curso(tmp_path / "curso.db")

    def traer(url: str) -> str:
        return "<p>Prepárate para el examen B1 Preliminary de Cambridge.</p>"

    base = Base(curso, tmp_path / "f", buscar=lambda _q: [], traer=traer)
    cid = curso.abrir("t", now=1.0)
    urls = ["https://a.com/x"]
    base.aprobar_dominios(cid, urls, now=1.0)
    base.construir(cid, urls, now=1.0)
    assert base.pasajes(cid, "de la el") == []


def test_construir_remembers_the_real_title_from_candidatos(tmp_path: Path) -> None:
    """The card cites its source at the foot — that citation is the payoff
    of this feature, and a bare hostname is a weaker claim than the real
    title `candidatos` already had and threw away."""
    curso = Curso(tmp_path / "curso.db")

    def buscar(consulta: str) -> list[Resultado]:
        return [
            Resultado(
                "https://cambridgeenglish.org/b1",
                "Cambridge B1 Preliminary, sample paper 2",
                "resumen",
            )
        ]

    def traer(url: str) -> str:
        return "<p>The present perfect is used for experience.</p>"

    base = Base(curso, tmp_path / "f", buscar=buscar, traer=traer)
    cid = curso.abrir("t", now=1.0)
    base.candidatos(cid, "B1")
    urls = ["https://cambridgeenglish.org/b1"]
    base.aprobar_dominios(cid, urls, now=1.0)
    base.construir(cid, urls, now=1.0)
    pasajes = base.pasajes(cid, "present perfect")
    assert pasajes
    assert pasajes[0][0] == "Cambridge B1 Preliminary, sample paper 2"


def test_a_url_already_in_the_base_is_not_fetched_twice(tmp_path: Path) -> None:
    """Amending a plan un-approves it; approving again re-ran `construir`.

    Without this the course ended up with two `fuente` rows per source,
    a doubled "Base: N fuentes" and the same passage twice in front of
    the model.
    """
    curso = Curso(tmp_path / "curso.db")
    traidas: list[str] = []

    def traer(url: str) -> str:
        traidas.append(url)
        return "<p>El present perfect se usa para experiencias.</p>"

    base = Base(curso, tmp_path / "fuentes", buscar=lambda _q: [], traer=traer)
    cid = curso.abrir("B1", now=1000.0)
    urls = ["https://cambridgeenglish.org/b1"]
    base.aprobar_dominios(cid, urls, now=1000.0)

    assert base.construir(cid, urls, now=1000.0) == 1
    assert base.construir(cid, urls, now=1001.0) == 0
    assert traidas == ["https://cambridgeenglish.org/b1"]
    with base.curso.conexion() as db:
        cuantas = db.execute(
            "SELECT COUNT(*) FROM fuente WHERE curso = ?", (cid,)
        ).fetchone()[0]
    assert cuantas == 1
    assert "Base: 1 fuentes" in curso.hoja(cid)


def test_the_same_url_twice_in_one_call_lands_once(base: Base) -> None:
    cid = base.curso.abrir("B1", now=1000.0)
    urls = ["https://cambridgeenglish.org/b1", "https://cambridgeenglish.org/b1"]
    base.aprobar_dominios(cid, urls, now=1000.0)
    assert base.construir(cid, urls, now=1000.0) == 1


def test_aprobado_answers_for_the_course_that_approved_it(base: Base) -> None:
    """The domain gate is asked by the image fetcher too, so it is public."""
    cid = base.curso.abrir("B1", now=1000.0)
    otro = base.curso.abrir("otra cosa", now=1000.0)
    base.aprobar_dominios(cid, ["https://cambridgeenglish.org/b1"], now=1000.0)
    assert base.aprobado(cid, "https://cambridgeenglish.org/otra-pagina") is True
    assert base.aprobado(cid, "http://192.168.1.1/admin") is False
    assert base.aprobado(otro, "https://cambridgeenglish.org/b1") is False
