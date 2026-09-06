"""What a pairing destroys, and what it must not.

The user's decision of 2026-09-06: **a pairing erases all previous
memory.** That is what lets this box change hands — a new amo inherits
neither the last owner's conversations, nor their courses, nor their
enrolled phones — and it is the stronger of the two reasons the founding
act (`casa.Registro.emparejar`) is gated behind a spoken passphrase:
pairing with whoever speaks first would not merely hand the house over,
it would erase it first.

**"Everything" is 24 MB of memory, not 87 GB of model weights**, measured
on this box 2026-09-06. Confusing the two turns a clean slate into three
days of re-downloading, so the two lists below are kept apart on
purpose, and `_comprobar_seguro` exists purely to catch, from the
inside, the mistake `test_borrar.py` catches from the outside: a
protected name creeping into the "goes" list.

One letter apart, opposite fates: `~/.jarvis/voces/` (plural without the
`i`) is the voiceprints `casa.py` writes, and it goes. `~/.jarvis/voices/`
is 136 MB of TTS reference audio, and it stays. Do not "tidy" one into
the other.

This module only inspects and only deletes what it is told to; it never
decides ON ITS OWN that a pairing should happen, and it is never run
against a real home directory except from task 7's state machine, at the
one moment in the whole project where erasing everything is the correct
thing to do — a fresh box, a spoken passphrase, and nobody's memory to
lose yet.

The file handling follows `remote_auth.py` and `casa.py`: the KIND of a
node is checked (via `stat`/`lstat`) before it is ever opened, because a
FIFO does not raise when opened for reading — it blocks forever, and no
`except` catches a hang — corruption and I/O failure are caught together
as `(OSError, UnicodeDecodeError)`, and every failure is logged once,
naming the path and never its contents.
"""

from __future__ import annotations

import os
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

# --- the two lists, kept apart on purpose --------------------------------

# Fixed relative paths under ~/.hermes that a pairing erases.
_HERMES_FIJOS: tuple[str, ...] = (
    "state.db",  # sessions
    "sessions",  # session bodies
    "profiles",  # every per-person profile, once they exist
)

# `~/.hermes/home/memories/*.md` — NOT `~/.hermes/memories/`, which is a
# 4 KB directory holding no `.md` at all. Confirmed by listing this box
# 2026-09-06 (task 5b): `~/.hermes/home/` does not exist yet on a
# freshly-installed gateway, and `~/.hermes/memories/` is present but
# empty — the per-person path is created only once a profile exists,
# exactly like `~/.hermes/profiles/` above.
_HERMES_MEMORIAS_REL = Path("home") / "memories"

# Fixed relative paths under ~/.jarvis that a pairing erases.
_JARVIS_FIJOS: tuple[str, ...] = (
    "memory",  # the old store
    "teacher",  # courses and everything filed under them
    "personas.json",  # every phone is de-enrolled ...
    "remote.token",  # ... (the pre-roster secret, if this box still has one)
    "certs",  # ... and every certificate with it
    "ref-candidates",  # recordings of the household's voices
    # Not in the brief's own table, added per task instructions: task 4
    # writes the household's recorded voices here (see
    # `widget/tools/medir_voces.py`, BASE_POR_DEFECTO). A new owner must
    # not inherit recordings of the previous family, any more than they
    # inherit `ref-candidates/`.
    "medicion",
    "casa.json",  # the register (task 5)
    "voces",  # the voiceprints (task 5) — NOT `voices/`, see module doc
)

# `~/.jarvis/dump*/` — recordings dumped for debugging (utterances, the
# endpointer, the phone audio path). Matched by glob because the exact
# set of dump directories has grown ad hoc (`dump`, `dump-endpoint`,
# `dump-movil`) and is expected to keep doing so.
_JARVIS_DUMP_GLOB = "dump*"

# What a pairing must NEVER touch — model weights, not memory. Checked
# by exact first-path-component match in `_comprobar_seguro`, which is
# the inside half of `test_borrar.py`'s
# `test_inventario_never_returns_a_path_under_a_protected_directory`:
# that test catches a mistake here from the outside, by name; this
# catches it from the inside, so a future edit to `_JARVIS_FIJOS` that
# collides with one of these fails LOUDLY instead of wiping 87 GB
# quietly. Sizes measured 2026-09-06: models/ 69 GB, cosyvoice3/ 9.1 GB,
# qwen3-tts/ 8.5 GB, xtts-cache/ 1.8 GB, voices/ 136 MB.
_PROTEGIDOS_JARVIS = frozenset(
    {"models", "cosyvoice3", "qwen3-tts", "xtts-cache", "voices"}
)


# --- the inventory itself -------------------------------------------------


@dataclass(frozen=True)
class Nodo:
    """One path a pairing would erase, and whether it is actually there.

    `origen` and `relativo` are what let `ejecutar` rebuild an identical
    layout inside the snapshot directory — `respaldo/jarvis/memory`,
    `respaldo/hermes/sessions` — so putting the house back by hand is
    copying `respaldo/jarvis/` over `~/.jarvis` and `respaldo/hermes/`
    over `~/.hermes`, not reverse-engineering which root a bare filename
    came from.
    """

    ruta: Path
    presente: bool
    origen: str  # "jarvis" or "hermes"
    relativo: Path


@dataclass(frozen=True)
class Borrado:
    """Everything one pairing erases: the full inventory, present or not."""

    nodos: tuple[Nodo, ...]

    @property
    def presentes(self) -> tuple[Nodo, ...]:
        """Only the nodes that are actually on disk right now — what
        `ejecutar` will touch."""
        return tuple(n for n in self.nodos if n.presente)


def _existe(ruta: Path) -> bool:
    """Whether something is at `ruta` at all.

    `Path.exists()` alone follows a symlink and reports `False` for one
    whose target is gone, which would leave a dangling link unaccounted
    for in the inventory — and it IS a node on disk, one `ejecutar` must
    still remove. Never raises: an unreadable parent directory is "not
    there" for inventory purposes, not a reason to crash a report on
    what would be erased.
    """
    try:
        return ruta.exists() or ruta.is_symlink()
    except OSError:
        return False


def _nodo(raiz: Path, origen: str, relativo: str | Path) -> Nodo:
    relativo = Path(relativo)
    ruta = raiz / relativo
    return Nodo(ruta=ruta, presente=_existe(ruta), origen=origen, relativo=relativo)


def _nodos_memorias(raiz_hermes: Path) -> list[Nodo]:
    """One `Nodo` per `.md` file under `~/.hermes/home/memories/`, or a
    single absent `Nodo` for the directory itself when it does not exist
    yet — which is the ordinary case on a box with nobody enrolled."""
    directorio = raiz_hermes / _HERMES_MEMORIAS_REL
    if not directorio.is_dir():
        return [
            Nodo(
                ruta=directorio,
                presente=False,
                origen="hermes",
                relativo=_HERMES_MEMORIAS_REL,
            )
        ]
    try:
        candidatos = sorted(directorio.glob("*.md"))
    except OSError as exc:
        logger.warning(f"borrar: no se pudo listar {directorio} — {exc!r}")
        return [
            Nodo(
                ruta=directorio,
                presente=True,
                origen="hermes",
                relativo=_HERMES_MEMORIAS_REL,
            )
        ]
    return [
        Nodo(
            ruta=md,
            presente=True,
            origen="hermes",
            relativo=_HERMES_MEMORIAS_REL / md.name,
        )
        for md in candidatos
    ]


def _nodos_dump(raiz_jarvis: Path) -> list[Nodo]:
    """One `Nodo` per `dump*` DIRECTORY directly under `~/.jarvis/`. A
    file that merely starts with `dump` (a report, a log) is not one of
    these and is left alone."""
    try:
        candidatos = sorted(
            p for p in raiz_jarvis.glob(_JARVIS_DUMP_GLOB) if p.is_dir()
        )
    except OSError as exc:
        logger.warning(f"borrar: no se pudo listar {raiz_jarvis} — {exc!r}")
        return []
    return [
        Nodo(ruta=p, presente=True, origen="jarvis", relativo=Path(p.name))
        for p in candidatos
    ]


def _comprobar_seguro(nodos: list[Nodo]) -> None:
    """Refuse, loudly, if anything in `nodos` resolves under a protected
    directory. This is a static invariant on the hardcoded lists above —
    it can only fire if a future edit to `_JARVIS_FIJOS` or the dump glob
    collides with `_PROTEGIDOS_JARVIS` — and it is deliberately NOT
    swallowed the way a runtime I/O failure is elsewhere in this module:
    a security invariant breaking is a programming error that must stop
    the world, not disk content that must be tolerated.
    """
    for nodo in nodos:
        if nodo.origen != "jarvis" or not nodo.relativo.parts:
            continue
        if nodo.relativo.parts[0] in _PROTEGIDOS_JARVIS:
            raise RuntimeError(
                f"borrar: {nodo.relativo} está bajo un directorio protegido "
                "(models/cosyvoice3/qwen3-tts/xtts-cache/voices); se rechaza "
                "todo el inventario"
            )


def inventario(raiz_jarvis: Path, raiz_hermes: Path) -> Borrado:
    """Pure inspection: what a pairing would erase under these two
    roots, and which of it actually exists. No side effects at all —
    nothing is opened for writing, nothing is deleted, nothing is
    created. Callers pass the real `~/.jarvis` and `~/.hermes` only from
    task 7's flow; every test in this repo passes a `tmp_path`.
    """
    raiz_jarvis = Path(raiz_jarvis)
    raiz_hermes = Path(raiz_hermes)

    nodos: list[Nodo] = []
    for relativo in _HERMES_FIJOS:
        nodos.append(_nodo(raiz_hermes, "hermes", relativo))
    nodos.extend(_nodos_memorias(raiz_hermes))

    for relativo in _JARVIS_FIJOS:
        nodos.append(_nodo(raiz_jarvis, "jarvis", relativo))
    nodos.extend(_nodos_dump(raiz_jarvis))

    _comprobar_seguro(nodos)
    return Borrado(nodos=tuple(nodos))


# --- ejecutar: snapshot first, delete second ------------------------------


def _resuelto(ruta: Path) -> Path:
    try:
        return ruta.resolve()
    except OSError:
        return ruta.absolute()


def _solapan(a: Path, b: Path) -> bool:
    return a == b or a.is_relative_to(b) or b.is_relative_to(a)


def _respaldo_conflictivo(respaldo: Path, presentes: tuple[Nodo, ...]) -> bool:
    """Whether `respaldo` sits inside — or would swallow — something
    about to be erased. Backing up into a tree that is then deleted
    would destroy the snapshot along with the original, which defeats
    the entire point of taking one first."""
    resuelto = _resuelto(respaldo)
    return any(_solapan(resuelto, _resuelto(nodo.ruta)) for nodo in presentes)


def _guardar_snapshot(presentes: tuple[Nodo, ...], respaldo: Path) -> bool:
    """Copy every present node into `respaldo`, mirroring `origen/relativo`
    exactly. Returns whether it fully succeeded; `ejecutar` treats a
    partial snapshot as a failed one and deletes nothing at all."""
    try:
        respaldo.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.error(f"borrar: no se pudo crear el respaldo en {respaldo} — {exc!r}")
        return False

    for nodo in presentes:
        destino = respaldo / nodo.origen / nodo.relativo
        try:
            # The KIND of the node is checked with `lstat` — which never
            # blocks — before anything is opened for reading. A FIFO or
            # a socket does not raise when `shutil.copy2` tries to open
            # it; it simply blocks forever, so the branch below never
            # lets either kind reach `copy2` or `copytree` at all.
            info = nodo.ruta.lstat()
        except OSError as exc:
            logger.error(f"borrar: no se pudo inspeccionar {nodo.ruta} — {exc!r}")
            return False
        try:
            destino.parent.mkdir(parents=True, exist_ok=True)
            if stat.S_ISLNK(info.st_mode):
                # Recreate the LINK, never copy what it points at. A
                # "goes" entry can legitimately be a symlink into a
                # "stays" directory (`certs/` -> somewhere under
                # `models/`, say) — following it here to copy CONTENT
                # would duplicate gigabytes of protected model weights
                # into the snapshot, exactly the "24 MB, not 87 GB"
                # confusion this whole module exists to prevent.
                # Restoring a symlink is recreating the same symlink,
                # not duplicating the bytes on the other end of it —
                # and the other end is untouched anyway, since
                # `_eliminar` never deletes it either.
                try:
                    objetivo = os.readlink(nodo.ruta)
                except OSError as exc:
                    logger.error(
                        f"borrar: no se pudo leer el enlace {nodo.ruta} — {exc!r}"
                    )
                    return False
                destino.symlink_to(objetivo)
            elif stat.S_ISDIR(info.st_mode):
                shutil.copytree(nodo.ruta, destino, dirs_exist_ok=True, symlinks=True)
            elif stat.S_ISREG(info.st_mode):
                shutil.copy2(nodo.ruta, destino)
            else:
                logger.warning(
                    f"borrar: {nodo.ruta} no es un archivo ni directorio normal; "
                    "se omite del respaldo"
                )
        except (OSError, UnicodeDecodeError, shutil.Error) as exc:
            logger.error(f"borrar: no se pudo respaldar {nodo.ruta} — {exc!r}")
            return False
    return True


def _eliminar(ruta: Path) -> None:
    """Remove exactly the node at `ruta`.

    If it is a symlink, remove the LINK ONLY — never whatever it points
    at. A `goes` entry that happens, on some box, to be a symlink into a
    `stays` directory (`models/`, say) must not take the model weights
    on the other end of it down with it. `is_symlink()` is checked
    first, before any recursive removal is even considered — leaving it
    to `shutil.rmtree` would not be safe, since `rmtree` only refuses a
    symlink to a directory after partially resolving the path.

    Never raises: this is called from a loop with several nodes left to
    go, and a caller that has already committed to erasing everything
    has nowhere better to put an exception than a log line naming the
    path.
    """
    try:
        if ruta.is_symlink():
            ruta.unlink()
            return
        info = ruta.lstat()
        if stat.S_ISDIR(info.st_mode):
            shutil.rmtree(ruta)
        else:
            ruta.unlink()
    except OSError as exc:
        logger.error(f"borrar: no se pudo eliminar {ruta} — {exc!r}")


def ejecutar(borrado: Borrado, *, respaldo: Path) -> None:
    """Snapshot every present node under `respaldo`, then remove it.

    Order is load-bearing, exactly as in `casa.Registro.emparejar`: the
    snapshot is written FIRST, and this refuses to delete anything at
    all if the snapshot could not be written in full. This runs on a
    voice-driven surface, and a "sí" said to a question the machine
    mis-heard is exactly how a house gets erased by accident — the
    snapshot is what makes that recoverable, so it is not a courtesy,
    it is what makes running this safe to approve.

    Also refuses, without deleting anything, if `respaldo` sits inside
    (or would swallow) something about to be erased — backing up into a
    tree that is then deleted would destroy the snapshot along with the
    original.

    A second call on an already-clean box — nothing present — is a
    no-op: an (empty) snapshot directory is still made, and nothing is
    removed, because there is nothing left to remove.

    Never raises into the caller: task 7's state machine is a voice
    turn, and it has nowhere to put an exception either.
    """
    respaldo = Path(respaldo)
    presentes = borrado.presentes

    if not presentes:
        try:
            respaldo.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.warning(
                f"borrar: no se pudo crear el respaldo vacío en {respaldo} — {exc!r}"
            )
        return

    if _respaldo_conflictivo(respaldo, presentes):
        logger.error(
            f"borrar: el respaldo {respaldo} está dentro de algo que se iba a "
            "borrar (o lo contendría); se aborta sin tocar nada"
        )
        return

    if not _guardar_snapshot(presentes, respaldo):
        logger.error(
            f"borrar: el respaldo en {respaldo} no se pudo escribir completo; "
            "se aborta sin borrar nada"
        )
        return

    for nodo in presentes:
        _eliminar(nodo.ruta)
