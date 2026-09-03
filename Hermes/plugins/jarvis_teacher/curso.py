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
from datetime import datetime
from pathlib import Path

# The day and the month, written out. Spelled here rather than taken
# from the C locale: a systemd user service inherits whatever locale the
# session happens to have, and "Thu" in the middle of a Spanish fact
# sheet is exactly the kind of half-language the model repairs into
# something else (§12, 2026-08-24, "en la fuera de casa").
_DIAS = (
    "lunes",
    "martes",
    "miércoles",
    "jueves",
    "viernes",
    "sábado",
    "domingo",
)
_MESES = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)

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
  -- The title of the source the question came from, or NULL when the
  -- model made it up. TEXT because that is what it has always held:
  -- declared INTEGER until 2026-09-03, which SQLite does not enforce
  -- but every reader of this schema was entitled to believe.
  fuente TEXT,
  -- A question replaced by another one, or left open when the class
  -- ended. Not a wrong answer — an unanswered one, which is why it is
  -- its own column and not `acierto = 0`: counting it as a miss would
  -- poison the list of weak concepts, and counting it as practice
  -- would inflate the denominator he reads out loud.
  abandonada INTEGER NOT NULL DEFAULT 0,
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
            # `CREATE TABLE IF NOT EXISTS` does nothing to a table that
            # already exists, so a database written before `abandonada`
            # existed would be missing the column and every INSERT would
            # fail — a course silently unable to ask a question. One
            # PRAGMA is cheaper than that risk.
            columnas = {
                str(fila[1]) for fila in db.execute("PRAGMA table_info(pregunta)")
            }
            if "abandonada" not in columnas:
                db.execute(
                    "ALTER TABLE pregunta ADD COLUMN abandonada "
                    "INTEGER NOT NULL DEFAULT 0"
                )

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
        """Store a syllabus. Anything it drops is discarded, not deleted.

        A title is matched against EVERY row of the course, discarded
        ones included, and a discarded row is revived rather than
        inserted beside. Matching only the live rows is what let a
        syllabus amended twice — take "Mareas" out, put it back — end up
        with two rows called "Mareas": `marcar_dado`'s `WHERE titulo = ?`
        then updated both and resurrected the discarded one, and the
        fact sheet counted a plan of three as a plan of four. The fact
        sheet is the one datum "resume" rests on, so it may not drift.
        """
        with self.conexion() as db:
            previos = db.execute(
                "SELECT id, titulo, estado FROM concepto WHERE curso = ? ORDER BY id",
                (curso_id,),
            ).fetchall()
            quedan = set(titulos)
            for ident, titulo, estado in previos:
                if titulo not in quedan and estado != "descartada":
                    db.execute(
                        "UPDATE concepto SET estado = 'descartada' WHERE id = ?",
                        (ident,),
                    )
            # By id, not by title: the row is addressed individually so
            # that a database which already carries a duplicate from
            # before this fix is not made worse by touching both.
            por_titulo = {str(t): (int(i), str(e)) for i, t, e in previos}
            for orden, titulo in enumerate(titulos):
                fila = por_titulo.get(titulo)
                if fila is None:
                    db.execute(
                        "INSERT INTO concepto (curso, titulo, orden, estado) "
                        "VALUES (?, ?, ?, 'pendiente')",
                        (curso_id, titulo, orden),
                    )
                    continue
                ident, estado = fila
                if estado == "descartada":
                    # Back in the plan, and back at the start of it: the
                    # row remembers it was once taught (`dado_en`), but a
                    # concept the user took out and put back is one they
                    # want gone through again.
                    db.execute(
                        "UPDATE concepto SET orden = ?, estado = 'pendiente' "
                        "WHERE id = ?",
                        (orden, ident),
                    )
                else:
                    db.execute(
                        "UPDATE concepto SET orden = ? WHERE id = ?", (orden, ident)
                    )
            db.execute(
                "UPDATE curso SET plan_aprobado_en = NULL WHERE id = ?", (curso_id,)
            )

    def tiene_plan(self, curso_id: int) -> bool:
        """Whether this course has a syllabus a person could have seen.

        `aprobar` asks before it fetches anything: the plan card is what
        puts the domains in front of the user, and approving a course
        with no concepts in it would fetch every candidate page with no
        card ever drawn (design, "opening a course, in two steps").
        """
        with self.conexion() as db:
            fila = db.execute(
                "SELECT 1 FROM concepto WHERE curso = ? AND estado != 'descartada' "
                "LIMIT 1",
                (curso_id,),
            ).fetchone()
        return bool(fila)

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
            # Count how many concepts have been genuinely taught (not including those being reviewed)
            taught = db.execute(
                "SELECT COUNT(*) FROM concepto WHERE curso = ? AND estado IN "
                "('dado', 'dominado')",
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
            if fila:
                return str(fila[0])

            # And last, what has been taught once and answered right
            # once. `dado` was terminal until 2026-09-03, which made it
            # behaviourally identical to `dominado` and left the queue
            # empty the moment the plan had been gone through — the spec
            # says a `dominado` concept is not taught again, and that
            # sentence only means anything if a `dado` one is.
            fila = db.execute(
                "SELECT titulo FROM concepto WHERE curso = ? AND estado = 'dado' "
                "ORDER BY orden LIMIT 1",
                (curso_id,),
            ).fetchone()
        return str(fila[0]) if fila else None

    def ultima_clase(self, curso_id: int) -> str:
        """When the last finished class was, in words. Empty when there is none.

        Written out — "jueves 28 de agosto" — rather than handed over as
        a timestamp or as "hace 5 días": the model would have to do
        arithmetic on either, and this project's record on a model doing
        arithmetic it was not given is that it invents the answer (§12,
        2026-09-01).
        """
        with self.conexion() as db:
            fila = db.execute(
                "SELECT MAX(acabo_en) FROM sesion WHERE curso = ? "
                "AND acabo_en IS NOT NULL",
                (curso_id,),
            ).fetchone()
        if not fila or fila[0] is None:
            return ""
        try:
            # Local time deliberately: "jueves" has to be the day it
            # was in the room, not in UTC.
            momento = datetime.fromtimestamp(float(fila[0]))  # noqa: DTZ006
        except (OSError, OverflowError, ValueError):
            return ""
        return (
            f"{_DIAS[momento.weekday()]} {momento.day} de {_MESES[momento.month - 1]}"
        )

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
                # Count OTHER concepts already taught, not including this one
                fallado_tras = db.execute(
                    "SELECT COUNT(*) FROM concepto WHERE curso = ? AND estado IN "
                    "('dado', 'dominado') AND titulo != ?",
                    (curso_id, titulo),
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
            # Both counts skip the questions nobody answered — one
            # replaced by another, or left open when the class ended.
            # An unanswered question is not practice, and counting it
            # inflated the denominator he reads out loud.
            reales = db.execute(
                "SELECT COUNT(*) FROM pregunta WHERE curso = ? AND fuente IS NOT NULL "
                "AND abandonada = 0",
                (curso_id,),
            ).fetchone()[0]
            preguntas = db.execute(
                "SELECT COUNT(*) FROM pregunta WHERE curso = ? AND abandonada = 0",
                (curso_id,),
            ).fetchone()[0]

        plan = "aprobado" if self.plan_aprobado(curso_id) else "propuesto, sin aprobar"
        ultima = self.ultima_clase(curso_id)
        cabecera = f"Tema: {tema}."
        if ultima:
            cabecera += f" Última clase: {ultima}."
        lineas = [
            f"{cabecera} Plan: {plan}.",
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
