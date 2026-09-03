"""`_buscar` against a recorded response — never a live call in a test.

The fixture below is verbatim what `tools/probe_busqueda.py` printed
against the live box on 2026-09-03 for "B1 preliminary grammar",
backend `exa`, no key configured anywhere. It is not invented: it is
the measurement `_buscar`'s own docstring cites. `tools.web_tools` is
injected into `sys.modules` rather than imported for real, so this test
runs in the widget's venv — which has neither the `tools` package nor
its vendor SDKs — exactly as `fuentes.py`'s own tests take `buscar` as
a plain callable and never touch a socket.
"""

from __future__ import annotations

import json
import sys
import types

from Hermes.plugins.jarvis_teacher import _buscar

# Recorded 2026-09-03, `tools/probe_busqueda.py "B1 preliminary grammar"`,
# against the pinned Hermes on this box (backend `exa`, no key set).
RESPUESTA_GRABADA = json.dumps(
    {
        "success": True,
        "data": {
            "web": [
                {
                    "url": "https://test-english.com/grammar-points/b1/contents-b1/",
                    "title": "Table of grammar contents – B1 - Test-English",
                    "description": (
                        "B1 Preliminary (PET) This is a list of all the grammar "
                        "topics covered in level B1. B1 Review of all verb "
                        "tenses B1 Modals, the imperative, phrasal verbs, etc . ..."
                    ),
                    "position": 1,
                },
                {
                    "url": "https://www.cambridgeenglish.org/exams-and-tests/qualifications/preliminary/preparation/",
                    "title": "Preparing for B1 Preliminary for Schools and ... - Cambridge English",
                    "description": (
                        "The activity booklet includes lesson plans for "
                        "vocabulary, grammar and speaking. This booklet includes "
                        "seven exercises each for primary, lower secondary and ..."
                    ),
                    "position": 2,
                },
                {
                    "url": "https://engxam.com/handbook/exams/b1-pet/",
                    "title": "B1 Preliminary (PET) Handbook : free grammar, exercises & tips",
                    "description": (
                        "B1 Preliminary (PET) handbook with free learning "
                        "resources for English language exams. Useful exam "
                        "tips, articles, grammar and exercises."
                    ),
                    "position": 3,
                },
            ]
        },
    }
)


def _instalar_buscador_falso(monkeypatch, respuesta: str | Exception) -> list[str]:
    """Put a fake `tools.web_tools` in `sys.modules`. Returns queries seen."""
    vistas: list[str] = []

    def web_search_tool(query: str, limit: int = 5) -> str:
        vistas.append(query)
        if isinstance(respuesta, Exception):
            raise respuesta
        return respuesta

    tools_pkg = types.ModuleType("tools")
    web_tools_mod = types.ModuleType("tools.web_tools")
    web_tools_mod.web_search_tool = web_search_tool  # type: ignore[attr-defined]
    tools_pkg.web_tools = web_tools_mod  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "tools", tools_pkg)
    monkeypatch.setitem(sys.modules, "tools.web_tools", web_tools_mod)
    return vistas


def test_a_recorded_response_becomes_three_resultados(monkeypatch) -> None:
    vistas = _instalar_buscador_falso(monkeypatch, RESPUESTA_GRABADA)
    buscar = _buscar(ctx=None)
    resultados = buscar("B1 preliminary grammar")
    assert vistas == ["B1 preliminary grammar"]
    assert [r.url for r in resultados] == [
        "https://test-english.com/grammar-points/b1/contents-b1/",
        "https://www.cambridgeenglish.org/exams-and-tests/qualifications/preliminary/preparation/",
        "https://engxam.com/handbook/exams/b1-pet/",
    ]
    assert resultados[0].titulo == "Table of grammar contents – B1 - Test-English"
    assert resultados[0].resumen.startswith("B1 Preliminary (PET)")


def test_no_result_carries_anything_but_url_title_description(monkeypatch) -> None:
    """`Resultado` has no image field, and the recorded response has nothing to put in one."""
    _instalar_buscador_falso(monkeypatch, RESPUESTA_GRABADA)
    buscar = _buscar(ctx=None)
    resultados = buscar("B1 preliminary grammar")
    for r in resultados:
        assert set(vars(r).keys()) == {"url", "titulo", "resumen"}


def test_hermes_reporting_no_provider_configured_returns_nothing(monkeypatch) -> None:
    sin_backend = json.dumps(
        {
            "success": False,
            "error": "No web search provider configured. Run `hermes tools` to set one up.",
        }
    )
    _instalar_buscador_falso(monkeypatch, sin_backend)
    buscar = _buscar(ctx=None)
    assert buscar("cualquier cosa") == []


def test_a_search_that_raises_returns_nothing_and_does_not_crash(monkeypatch) -> None:
    _instalar_buscador_falso(monkeypatch, RuntimeError("sin red"))
    buscar = _buscar(ctx=None)
    assert buscar("cualquier cosa") == []


def test_missing_tools_package_returns_nothing(monkeypatch) -> None:
    """The widget's own venv, and any box with no pinned Hermes on the path."""
    monkeypatch.delitem(sys.modules, "tools", raising=False)
    monkeypatch.delitem(sys.modules, "tools.web_tools", raising=False)
    import builtins

    original_import = builtins.__import__

    def bloqueado(name, *args, **kwargs):
        if name == "tools.web_tools" or name.startswith("tools."):
            raise ImportError("no module named tools")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", bloqueado)
    buscar = _buscar(ctx=None)
    assert buscar("cualquier cosa") == []


def test_a_result_with_no_url_is_dropped(monkeypatch) -> None:
    sin_url = json.dumps({"success": True, "data": {"web": [{"title": "x"}]}})
    _instalar_buscador_falso(monkeypatch, sin_url)
    buscar = _buscar(ctx=None)
    assert buscar("cualquier cosa") == []
