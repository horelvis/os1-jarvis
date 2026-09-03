"""Opening a course, in two steps, and what each one may not do.

Nothing is fetched before `aprobar`: that is the whole security
property of the split, so it is asserted rather than trusted.
"""

import asyncio
from pathlib import Path

import pytest

from Hermes.plugins.jarvis_teacher.curso import Curso
from Hermes.plugins.jarvis_teacher.fuentes import Base, Resultado
from Hermes.plugins.jarvis_teacher.tool import Aula


@pytest.fixture
def aula(tmp_path: Path, monkeypatch) -> Aula:
    monkeypatch.setenv("JARVIS_TEACHER_HOME", str(tmp_path))
    curso = Curso(tmp_path / "curso.db")
    traidas: list[str] = []

    def traer(url: str) -> str:
        traidas.append(url)
        return "<p>El present perfect se usa para experiencias.</p>"

    base = Base(
        curso,
        tmp_path / "fuentes",
        buscar=lambda _q: [
            Resultado("https://cambridgeenglish.org/b1", "B1", "examen")
        ],
        traer=traer,
    )
    aula = Aula(curso, base, push_ficha=_recoger([]))
    aula.traidas = traidas  # type: ignore[attr-defined]
    return aula


def _recoger(destino: list) -> callable:
    async def push(md: str, tipo: str, **kw):
        destino.append((tipo, md, kw))
        return True

    push.recogido = destino  # type: ignore[attr-defined]
    return push


def test_a_new_course_returns_candidates_and_fetches_nothing(aula: Aula) -> None:
    salida = asyncio.run(aula.ensename({"tema": "sacar el B1 de inglés"}))
    assert "cambridgeenglish.org" in salida
    assert aula.traidas == []


def test_no_tema_resumes_the_last_open_course(aula: Aula) -> None:
    asyncio.run(aula.ensename({"tema": "astronomía"}))
    salida = asyncio.run(aula.ensename({}))
    assert "Tema: astronomía" in salida


def test_planificar_draws_a_plan_card(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("JARVIS_TEACHER_HOME", str(tmp_path))
    curso = Curso(tmp_path / "curso.db")
    base = Base(curso, tmp_path / "f", buscar=lambda _q: [], traer=lambda _u: "")
    recogido: list = []
    aula = Aula(curso, base, push_ficha=_recoger(recogido))
    asyncio.run(aula.ensename({"tema": "astronomía"}))
    asyncio.run(aula.planificar({"temario": "1. Órbitas\n2. Mareas\n"}))
    assert recogido[-1][0] == "plan"
    assert "Órbitas" in recogido[-1][1]


def test_a_temario_with_no_list_asks_for_one_instead_of_drawing(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("JARVIS_TEACHER_HOME", str(tmp_path))
    curso = Curso(tmp_path / "curso.db")
    base = Base(curso, tmp_path / "f", buscar=lambda _q: [], traer=lambda _u: "")
    recogido: list = []
    aula = Aula(curso, base, push_ficha=_recoger(recogido))
    asyncio.run(aula.ensename({"tema": "astronomía"}))
    salida = asyncio.run(aula.planificar({"temario": "un párrafo suelto"}))
    assert "lista" in salida.lower()
    assert recogido == []


def test_aprobar_is_what_fetches(aula: Aula) -> None:
    asyncio.run(aula.ensename({"tema": "B1"}))
    asyncio.run(aula.planificar({"temario": "1. Present perfect\n"}))
    assert aula.traidas == []
    salida = asyncio.run(aula.aprobar({}))
    assert aula.traidas == ["https://cambridgeenglish.org/b1"]
    assert "Present perfect" in salida


def test_a_broken_database_costs_a_sentence_not_a_turn(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("JARVIS_TEACHER_HOME", str(tmp_path))
    curso = Curso(tmp_path / "curso.db")
    base = Base(curso, tmp_path / "f", buscar=lambda _q: [], traer=lambda _u: "")
    aula = Aula(curso, base, push_ficha=_recoger([]))
    monkeypatch.setattr(
        curso, "abrir", lambda *a, **k: (_ for _ in ()).throw(OSError("bloqueada"))
    )
    salida = asyncio.run(aula.ensename({"tema": "x"}))
    assert isinstance(salida, str) and salida


def test_aprobar_with_no_remembered_candidates_and_no_sources_refuses(
    tmp_path: Path, monkeypatch
) -> None:
    """A restarted gateway has a plan but has forgotten the candidates.

    Without any source on disk either, `aprobar` must not wave the plan
    through — that would teach a concept with nothing behind it, and it
    would sound exactly like a real approval.
    """
    monkeypatch.setenv("JARVIS_TEACHER_HOME", str(tmp_path))
    curso = Curso(tmp_path / "curso.db")
    traidas: list[str] = []

    def traer(url: str) -> str:
        traidas.append(url)
        return "<p>...</p>"

    base = Base(
        curso,
        tmp_path / "fuentes",
        buscar=lambda _q: [Resultado("https://x.org/a", "A", "r")],
        traer=traer,
    )
    aula_1 = Aula(curso, base, push_ficha=_recoger([]))
    asyncio.run(aula_1.ensename({"tema": "algo"}))
    asyncio.run(aula_1.planificar({"temario": "1. Uno\n"}))
    curso_id = curso.ultimo_abierto()
    assert curso_id is not None
    assert not curso.plan_aprobado(curso_id)

    # A fresh Aula over the same course and base: memory of the
    # candidates is gone, and nothing was ever fetched.
    aula_2 = Aula(curso, base, push_ficha=_recoger([]))
    salida = asyncio.run(aula_2.aprobar({}))

    assert not curso.plan_aprobado(curso_id)
    assert traidas == []
    assert "Plan aprobado" not in salida
    assert isinstance(salida, str) and salida


def test_aprobar_with_no_remembered_candidates_but_sources_on_disk_approves(
    tmp_path: Path, monkeypatch
) -> None:
    """Sources already on disk (an earlier approval) are enough on their own."""
    monkeypatch.setenv("JARVIS_TEACHER_HOME", str(tmp_path))
    curso = Curso(tmp_path / "curso.db")
    traidas: list[str] = []

    def traer(url: str) -> str:
        traidas.append(url)
        return "<p>El pretérito perfecto se usa para experiencias.</p>"

    base = Base(
        curso,
        tmp_path / "fuentes",
        buscar=lambda _q: [Resultado("https://x.org/a", "A", "r")],
        traer=traer,
    )
    aula_1 = Aula(curso, base, push_ficha=_recoger([]))
    asyncio.run(aula_1.ensename({"tema": "algo"}))
    asyncio.run(aula_1.planificar({"temario": "1. Uno\n"}))
    asyncio.run(aula_1.aprobar({}))  # a real approval: fetches, stores a `fuente` row
    curso_id = curso.ultimo_abierto()
    assert curso_id is not None
    assert curso.plan_aprobado(curso_id)
    assert traidas == ["https://x.org/a"]

    # The plan is amended, which un-approves it again.
    asyncio.run(aula_1.planificar({"temario": "1. Uno\n2. Dos\n"}))
    assert not curso.plan_aprobado(curso_id)

    # A fresh Aula, memory of the candidates gone — but the earlier
    # `fuente` row is still on disk, so nothing needs re-fetching.
    traidas.clear()
    aula_2 = Aula(curso, base, push_ficha=_recoger([]))
    salida = asyncio.run(aula_2.aprobar({}))

    assert curso.plan_aprobado(curso_id)
    assert traidas == []
    assert "Plan aprobado" in salida
