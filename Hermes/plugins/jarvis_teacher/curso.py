"""The course as facts on disk. No model, no gateway, no network here.

The plugin stores that a concept is third in the plan, was taught on
Tuesday and missed once. It never stores the explanation: the model
writes that again tomorrow with these facts in front of it. That
division is why this file exists at all — see the design, "the division
that makes resume true".
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

# How many other concepts pass before a missed one comes round again.
# Small on purpose: this is a lesson, not a spaced-repetition schedule,
# and the user asked for neither.
REPASO_HUECO = 3
# Correct answers that retire a concept from the queue.
ACIERTOS_PARA_DOMINAR = 2

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS curso (
  id INTEGER PRIMARY KEY,
  tema TEXT NOT NULL,
  abierto_en REAL NOT NULL,
  tocado_en REAL NOT NULL,
  plan_aprobado_en REAL,
  cerrado INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS concepto (
  id INTEGER PRIMARY KEY,
  curso INTEGER NOT NULL,
  titulo TEXT NOT NULL,
  orden INTEGER NOT NULL,
  estado TEXT NOT NULL,
  dado_en REAL,
  fallado_tras INTEGER
);
CREATE TABLE IF NOT EXISTS pregunta (
  id INTEGER PRIMARY KEY,
  curso INTEGER NOT NULL,
  concepto TEXT NOT NULL,
  md TEXT NOT NULL,
  opciones TEXT NOT NULL,
  correcta TEXT NOT NULL,
  elegida TEXT,
  acierto INTEGER,
  fuente INTEGER,
  hecha_en REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS sesion (
  id INTEGER PRIMARY KEY,
  curso INTEGER NOT NULL,
  empezo_en REAL NOT NULL,
  acabo_en REAL
);
CREATE TABLE IF NOT EXISTS fuente (
  id INTEGER PRIMARY KEY,
  curso INTEGER NOT NULL,
  url TEXT NOT NULL,
  titulo TEXT NOT NULL,
  traida_en REAL NOT NULL,
  hash TEXT NOT NULL,
  archivo TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS dominio (
  id INTEGER PRIMARY KEY,
  curso INTEGER NOT NULL,
  host TEXT NOT NULL,
  aprobado_en REAL NOT NULL
);
"""


class Curso:
    """Everything the course knows about itself, on disk."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self.conexion() as db:
            db.executescript(_ESQUEMA)

    @contextmanager
    def conexion(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self._path)
        try:
            yield db
            db.commit()
        finally:
            db.close()

    # ── opening ───────────────────────────────────────────────────────

    def abrir(self, tema: str, *, now: float) -> int:
        with self.conexion() as db:
            fila = db.execute(
                "SELECT id FROM curso WHERE tema = ? AND cerrado = 0", (tema,)
            ).fetchone()
            if fila is not None:
                db.execute(
                    "UPDATE curso SET tocado_en = ? WHERE id = ?", (now, fila[0])
                )
                return int(fila[0])
            cur = db.execute(
                "INSERT INTO curso (tema, abierto_en, tocado_en) VALUES (?, ?, ?)",
                (tema, now, now),
            )
            return int(cur.lastrowid)

    def ultimo_abierto(self) -> int | None:
        with self.conexion() as db:
            fila = db.execute(
                "SELECT id FROM curso WHERE cerrado = 0 ORDER BY tocado_en DESC LIMIT 1"
            ).fetchone()
        return int(fila[0]) if fila else None

    def tema(self, curso_id: int) -> str:
        with self.conexion() as db:
            fila = db.execute(
                "SELECT tema FROM curso WHERE id = ?", (curso_id,)
            ).fetchone()
        return str(fila[0]) if fila else ""

    # ── the plan ──────────────────────────────────────────────────────

    def proponer_plan(self, curso_id: int, titulos: list[str], *, now: float) -> None:
        """Store a syllabus. Anything it drops is discarded, not deleted."""
        with self.conexion() as db:
            previos = db.execute(
                "SELECT id, titulo FROM concepto WHERE curso = ? AND estado != 'descartada'",
                (curso_id,),
            ).fetchall()
            quedan = set(titulos)
            for ident, titulo in previos:
                if titulo not in quedan:
                    db.execute(
                        "UPDATE concepto SET estado = 'descartada' WHERE id = ?",
                        (ident,),
                    )
            existentes = {t for _i, t in previos}
            for orden, titulo in enumerate(titulos):
                if titulo in existentes:
                    db.execute(
                        "UPDATE concepto SET orden = ? WHERE curso = ? AND titulo = ?",
                        (orden, curso_id, titulo),
                    )
                else:
                    db.execute(
                        "INSERT INTO concepto (curso, titulo, orden, estado) "
                        "VALUES (?, ?, ?, 'pendiente')",
                        (curso_id, titulo, orden),
                    )
            db.execute(
                "UPDATE curso SET plan_aprobado_en = NULL WHERE id = ?", (curso_id,)
            )

    def aprobar_plan(self, curso_id: int, *, now: float) -> str | None:
        with self.conexion() as db:
            db.execute(
                "UPDATE curso SET plan_aprobado_en = ? WHERE id = ?", (now, curso_id)
            )
        return self.siguiente(curso_id)

    def plan_aprobado(self, curso_id: int) -> bool:
        with self.conexion() as db:
            fila = db.execute(
                "SELECT plan_aprobado_en FROM curso WHERE id = ?", (curso_id,)
            ).fetchone()
        return bool(fila and fila[0] is not None)

    def siguiente(self, curso_id: int) -> str | None:
        """The next concept to teach, or None while the plan is unapproved."""
        if not self.plan_aprobado(curso_id):
            return None
        with self.conexion() as db:
            # Count how many concepts have been taught (including those being reviewed)
            taught = db.execute(
                "SELECT COUNT(*) FROM concepto WHERE curso = ? AND estado IN "
                "('dado', 'dominado', 'a repasar')",
                (curso_id,),
            ).fetchone()[0]

            # Get next pending concept
            pending = db.execute(
                "SELECT titulo, orden FROM concepto WHERE curso = ? AND estado = 'pendiente' "
                "ORDER BY orden LIMIT 1",
                (curso_id,),
            ).fetchone()

            # Get next 'a repasar' concept that is ready (gap satisfied)
            ready_review = db.execute(
                "SELECT titulo, orden FROM concepto WHERE curso = ? AND estado = 'a repasar' "
                "AND (fallado_tras IS NULL OR fallado_tras + ? <= ?) "
                "ORDER BY orden LIMIT 1",
                (curso_id, REPASO_HUECO, taught),
            ).fetchone()

            # Return whichever comes first by orden, preferring ready_review if both have same orden
            if pending and ready_review:
                return (
                    str(ready_review[0])
                    if ready_review[1] <= pending[1]
                    else str(pending[0])
                )
            if ready_review:
                return str(ready_review[0])
            if pending:
                return str(pending[0])

            # No ready concepts. Return any 'a repasar' as fallback (for when nothing pending).
            fila = db.execute(
                "SELECT titulo FROM concepto WHERE curso = ? AND estado = 'a repasar' "
                "ORDER BY orden LIMIT 1",
                (curso_id,),
            ).fetchone()
        return str(fila[0]) if fila else None

    # ── a lesson ──────────────────────────────────────────────────────

    def marcar_dado(self, curso_id: int, titulo: str, *, now: float) -> None:
        with self.conexion() as db:
            db.execute(
                "UPDATE concepto SET estado = 'dado', dado_en = ? "
                "WHERE curso = ? AND titulo = ? AND estado != 'dominado'",
                (now, curso_id, titulo),
            )

    def registrar_respuesta(
        self, curso_id: int, titulo: str, *, acierto: bool, now: float
    ) -> None:
        with self.conexion() as db:
            if not acierto:
                fallado_tras = db.execute(
                    "SELECT COUNT(*) FROM concepto WHERE curso = ? AND estado IN "
                    "('dado', 'dominado', 'a repasar')",
                    (curso_id,),
                ).fetchone()[0]
                db.execute(
                    "UPDATE concepto SET estado = 'a repasar', fallado_tras = ? "
                    "WHERE curso = ? AND titulo = ?",
                    (fallado_tras, curso_id, titulo),
                )
                return
            aciertos = db.execute(
                "SELECT COUNT(*) FROM pregunta WHERE curso = ? AND concepto = ? AND acierto = 1",
                (curso_id, titulo),
            ).fetchone()[0]
            estado = "dominado" if aciertos >= ACIERTOS_PARA_DOMINAR else "dado"
            db.execute(
                "UPDATE concepto SET estado = ? WHERE curso = ? AND titulo = ?",
                (estado, curso_id, titulo),
            )

    def empezar_sesion(self, curso_id: int, *, now: float) -> None:
        """Open a class, unless one is already open.

        `terminar` closes these, and without this there would be nothing
        to close: "lo dejamos el jueves" is a row somebody has to write.
        """
        with self.conexion() as db:
            abierta = db.execute(
                "SELECT 1 FROM sesion WHERE curso = ? AND acabo_en IS NULL", (curso_id,)
            ).fetchone()
            if not abierta:
                db.execute(
                    "INSERT INTO sesion (curso, empezo_en) VALUES (?, ?)",
                    (curso_id, now),
                )

    # ── what the model is shown ───────────────────────────────────────

    def hoja(self, curso_id: int) -> str:
        """Labelled data, never a sentence.

        A sentence would be repaired by the model into something else —
        that is what a camera called `fuera` cost in August (§12,
        2026-08-24). Values with names in front of them are not.
        """
        with self.conexion() as db:
            tema = self.tema(curso_id)
            total = db.execute(
                "SELECT COUNT(*) FROM concepto WHERE curso = ? AND estado != 'descartada'",
                (curso_id,),
            ).fetchone()[0]
            dados = db.execute(
                "SELECT COUNT(*) FROM concepto WHERE curso = ? AND estado IN "
                "('dado', 'dominado', 'a repasar')",
                (curso_id,),
            ).fetchone()[0]
            flojos = [
                str(f[0])
                for f in db.execute(
                    "SELECT titulo FROM concepto WHERE curso = ? AND estado = 'a repasar' "
                    "ORDER BY orden",
                    (curso_id,),
                ).fetchall()
            ]
            fuentes = db.execute(
                "SELECT COUNT(*) FROM fuente WHERE curso = ?", (curso_id,)
            ).fetchone()[0]
            dominios = db.execute(
                "SELECT COUNT(*) FROM dominio WHERE curso = ?", (curso_id,)
            ).fetchone()[0]
            reales = db.execute(
                "SELECT COUNT(*) FROM pregunta WHERE curso = ? AND fuente IS NOT NULL",
                (curso_id,),
            ).fetchone()[0]
            preguntas = db.execute(
                "SELECT COUNT(*) FROM pregunta WHERE curso = ?", (curso_id,)
            ).fetchone()[0]

        plan = "aprobado" if self.plan_aprobado(curso_id) else "propuesto, sin aprobar"
        lineas = [
            f"Tema: {tema}. Plan: {plan}.",
            f"Base: {fuentes} fuentes, {dominios} dominios.",
            f"Dados: {dados} de {total}.",
        ]
        if flojos:
            lineas.append("A repasar: " + ", ".join(flojos) + ".")
        siguiente = self.siguiente(curso_id)
        lineas.append(
            f"Siguiente: {siguiente}." if siguiente else "Siguiente: nada pendiente."
        )
        lineas.append(
            f"Practicado con material real: {reales} preguntas de {preguntas}."
        )
        return "\n".join(lineas)
