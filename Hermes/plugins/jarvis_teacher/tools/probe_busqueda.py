"""What does Hermes' web search actually return, and can a plugin call it?

Not a test — a thing you run by hand, once, to replace a guess with a
measurement. The design's `_buscar` was a stub because nobody had
established how a plugin reaches Hermes' own web search, or what shape
its results take. This is that check, and it needs the NETWORK and not
the GPU, so it can be run while JARVIS himself is down (the box's GPU
was busy the day this plugin was written).

**This probe must run with the pinned Hermes' own Python, not the
widget's venv.** The widget's venv has no `tools` package and none of
the vendor SDKs (httpx, the Exa/Firecrawl/Tavily clients) that back it —
those live only in `.hermes/src/.venv`, alongside the `tools`, `agent`
and `gateway` packages a running gateway process imports as top-level
names. `Hermes/run-gateway.sh` sets `PYTHONPATH` and `HERMES_HOME` for
exactly this reason; this script needs the same two things and the same
interpreter.

Run:
    cd /home/nexus/git/os1-samantha
    export HERMES_HOME="$PWD/.hermes/home"
    [ -f .env ] && { set -a; . .env; set +a; }
    .hermes/src/.venv/bin/python3 \
        Hermes/plugins/jarvis_teacher/tools/probe_busqueda.py "B1 preliminary grammar"

**Observed side effect, worth knowing before you run this twice.**
`web_search_tool` calls `_ensure_web_plugins_loaded()`, which triggers
Hermes' own plugin discovery — ALL of it, not only the web providers.
On this box that means `samantha_vision`'s `register()` runs too, which
starts its camera watcher threads against the house's real RTSP
cameras, using whatever credentials `.env` provides. This script does
not open a camera itself; discovery does, as a side effect of asking
"is a search backend configured". Nothing here closes those threads —
they die with the process when the script exits, a few seconds later.

What this printed against the live box, 2026-09-03, query
"B1 preliminary grammar", backend `exa` (Hermes' configured default),
no key present anywhere in `.env` or the environment:

    check_web_api_key(): True
    {
      "success": true,
      "data": {
        "web": [
          {"url": "https://test-english.com/grammar-points/b1/contents-b1/",
           "title": "Table of grammar contents – B1 - Test-English",
           "description": "B1 Preliminary (PET) This is a list of all the
             grammar topics covered in level B1. ...",
           "position": 1},
          ...
        ]
      }
    }

So: the import path is `tools.web_tools.web_search_tool(query, limit)`,
not `hermes.tools.web` — that guess, like the adapter-API guess before
it, was wrong. It needs no key (Exa's keyless free tier is what
`check_web_api_key()` is seeing). Each result carries a `url`, a
`title` and a `description` (the design's `resumen`). **None carries an
image** — `data.web` items have exactly those four keys
(`url`, `title`, `description`, `position`) and nothing else, so a
syllabus's candidate sources are text-only; a card's image, when there
is one, can only come from `explicar`'s own material, never from
`candidatos()`.
"""

from __future__ import annotations

import json
import sys


def main() -> int:
    consulta = " ".join(sys.argv[1:]) or "present perfect grammar"
    try:
        from tools.web_tools import check_web_api_key, web_search_tool
    except Exception as exc:
        print(f"no se puede importar el buscador de Hermes desde un plugin: {exc}")
        print(
            "¿Se ha ejecutado con .hermes/src/.venv/bin/python3, "
            "con HERMES_HOME y PYTHONPATH puestos como en run-gateway.sh?"
        )
        return 1

    print(f"check_web_api_key(): {check_web_api_key()}")

    try:
        crudo = web_search_tool(consulta, limit=5)
    except Exception as exc:
        print(f"web_search_tool() lanzó una excepción: {exc}")
        return 1

    print(f"\ntipo de lo devuelto: {type(crudo).__name__}")
    print(crudo)

    try:
        datos = json.loads(crudo)
    except Exception as exc:
        print(f"\nno es JSON válido: {exc}")
        return 1

    resultados = datos.get("data", {}).get("web", [])
    print(f"\n{len(resultados)} resultado(s).")
    for r in resultados:
        claves = sorted(r.keys())
        tiene_imagen = any("image" in k.lower() or "img" in k.lower() for k in claves)
        print(f"  claves: {claves} — ¿imagen?: {tiene_imagen}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
