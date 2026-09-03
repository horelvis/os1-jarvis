"""What the course stands on: searched, fetched, reduced and stored.

Two things are deliberate here and both are in the design.

The plugin searches, not the model. "Always look it up" is then a
property of the mechanism rather than a discipline the model can skip
on a Tuesday.

And the fetching is gated on a host the user has approved, because this
text lands in the context of an agent that has held `terminal` since
2026-08-26. The gate bounds who the text comes from. Nothing bounds
what it says, which is why every passage leaves here inside an explicit
"material, not instructions" envelope (`tool.py`).
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

from loguru import logger

from .curso import Curso

# What one source contributes at most, applied BEFORE the text is
# written to disk. Anything past this point is never stored, so it is
# not merely kept out of the model's context — it cannot be found by
# `pasajes` either. The hash taken below is of the truncated text, so
# the file and its hash always agree on what the source actually held.
MAX_CARACTERES = 20_000
# A passage handed back for one concept.
PASAJE = 1_200

_ESPACIOS = re.compile(r"[ \t]+")
_LINEAS = re.compile(r"\n{3,}")


@dataclass(frozen=True)
class Resultado:
    """One search hit. Metadata only — nothing has been fetched."""

    url: str
    titulo: str
    resumen: str


class _Texto(HTMLParser):
    """HTML in, words out. `script` and `style` never contribute."""

    def __init__(self) -> None:
        super().__init__()
        self.trozos: list[str] = []
        self._mudo = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self._mudo += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self._mudo:
            self._mudo -= 1
        if tag in {"p", "div", "li", "h1", "h2", "h3", "br"}:
            self.trozos.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._mudo:
            self.trozos.append(data)


def a_texto(html: str) -> str:
    """Reduce a page to readable text. Never raises."""
    parser = _Texto()
    try:
        parser.feed(html or "")
    except Exception as exc:  # noqa: BLE001 — html.parser is lenient, but not a promise
        logger.warning(f"jarvis-teacher: no se pudo leer la página: {exc}")
    crudo = "".join(parser.trozos)
    crudo = _ESPACIOS.sub(" ", crudo)
    return _LINEAS.sub("\n\n", crudo).strip()


def host_de(url: str) -> str:
    """The host a domain approval is about, without `www.`."""
    host = (urlparse(url).hostname or "").lower()
    return host.removeprefix("www.")


class Base:
    """The course's sources: choosing them, storing them, reading them back."""

    def __init__(
        self,
        curso: Curso,
        raiz: Path,
        *,
        buscar: Callable[[str], list[Resultado]],
        traer: Callable[[str], str],
    ) -> None:
        self.curso = curso
        self._raiz = Path(raiz)
        self._buscar = buscar
        self._traer = traer
        # A search result's real title, remembered by url so `construir`
        # can cite it later instead of a bare host — the whole payoff
        # of "the material came from Cambridge B1, sample paper 2"
        # rather than from a model's memory.
        self._titulos: dict[str, str] = {}

    def candidatos(self, curso_id: int, tema: str) -> list[Resultado]:
        """Search, and keep only titles and links. Nothing is downloaded."""
        try:
            resultados = list(self._buscar(tema))
        except Exception as exc:  # noqa: BLE001 — a search must not crash the tool
            logger.warning(f"jarvis-teacher: la búsqueda falló: {exc}")
            return []
        self._titulos.update({r.url: r.titulo for r in resultados})
        return resultados

    def aprobar_dominios(
        self, curso_id: int, urls: list[str], *, now: float
    ) -> list[str]:
        """Record the hosts these urls belong to as approved for this course."""
        hosts = sorted({host_de(u) for u in urls if host_de(u)})
        with self.curso.conexion() as db:
            for host in hosts:
                ya = db.execute(
                    "SELECT 1 FROM dominio WHERE curso = ? AND host = ?",
                    (curso_id, host),
                ).fetchone()
                if not ya:
                    db.execute(
                        "INSERT INTO dominio (curso, host, aprobado_en) VALUES (?, ?, ?)",
                        (curso_id, host, now),
                    )
        return hosts

    def _aprobado(self, curso_id: int, url: str) -> bool:
        with self.curso.conexion() as db:
            fila = db.execute(
                "SELECT 1 FROM dominio WHERE curso = ? AND host = ?",
                (curso_id, host_de(url)),
            ).fetchone()
        return bool(fila)

    def construir(self, curso_id: int, urls: list[str], *, now: float) -> int:
        """Fetch the approved urls into the base. Returns how many landed.

        A source that will not fetch costs that source and never the
        class — the same rule `tool.py` applies to a picture.
        """
        directorio = self._raiz / str(curso_id)
        traidas = 0
        for url in urls:
            if not self._aprobado(curso_id, url):
                logger.warning(
                    f"jarvis-teacher: dominio no aprobado, no se trae: {host_de(url)}"
                )
                continue
            try:
                texto = a_texto(self._traer(url))[:MAX_CARACTERES]
            except Exception as exc:  # noqa: BLE001 — one source must not cost the class
                logger.warning(
                    f"jarvis-teacher: no se pudo traer {host_de(url)}: {exc}"
                )
                continue
            if not texto:
                continue
            directorio.mkdir(parents=True, exist_ok=True)
            firma = hashlib.sha256(texto.encode("utf-8")).hexdigest()
            destino = directorio / f"{firma[:16]}.txt"
            destino.write_text(texto, encoding="utf-8")
            titulo = self._titulos.get(url, host_de(url))
            with self.curso.conexion() as db:
                db.execute(
                    "INSERT INTO fuente (curso, url, titulo, traida_en, hash, archivo) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (curso_id, url, titulo, now, firma, str(destino)),
                )
            traidas += 1
        return traidas

    def pasajes(
        self, curso_id: int, concepto: str, *, maximo: int = 3
    ) -> list[tuple[str, str]]:
        """The stored text that bears on a concept, best first.

        Keyword scoring over what is on disk. No embeddings and no
        ChromaDB: §2.7's store has been unused since August and this
        does not need one — the base is a handful of pages, not a
        corpus.
        """
        # Longer than two characters, OR carrying a digit — the second
        # clause is what admits CEFR levels ("B1", "A2", "C1") without
        # readmitting Spanish two-letter stopwords ("de", "la", "el"),
        # which would otherwise outscore the concept they surround.
        terminos = [
            t
            for t in re.split(r"\W+", concepto.lower())
            if len(t) > 2 or any(c.isdigit() for c in t)
        ]
        with self.curso.conexion() as db:
            filas = db.execute(
                "SELECT titulo, archivo FROM fuente WHERE curso = ?", (curso_id,)
            ).fetchall()

        puntuados: list[tuple[int, str, str]] = []
        for titulo, archivo in filas:
            try:
                texto = Path(archivo).read_text(encoding="utf-8")
            except OSError as exc:
                logger.warning(f"jarvis-teacher: no se puede leer una fuente: {exc}")
                continue
            bajo = texto.lower()
            mejor, punto = 0, 0
            for posicion in range(0, len(texto), PASAJE // 2):
                trozo = bajo[posicion : posicion + PASAJE]
                marca = sum(trozo.count(t) for t in terminos)
                if marca > mejor:
                    mejor, punto = marca, posicion
            if mejor:
                puntuados.append((mejor, str(titulo), texto[punto : punto + PASAJE]))

        puntuados.sort(key=lambda p: p[0], reverse=True)
        return [(titulo, trozo) for _marca, titulo, trozo in puntuados[:maximo]]
