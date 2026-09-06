"""Whose house this is, on disk.

`~/.jarvis/personas.json` (`remote_auth.py`) holds phone SECRETS. This
module owns a different file, `~/.jarvis/casa.json` — who exists, what
they are called, and who is the amo — plus a sibling directory,
`~/.jarvis/voces/`, one `.npy` per person. Three files, three
sensitivities, kept apart on purpose: names are not credentials and
voiceprint vectors are not secrets, so filing all three together would
mean one leak spills all three.

The file handling follows `remote_auth.py` exactly, because that module
already paid — across several fix rounds — for every lesson this one
needs: the KIND of the node at a path is checked with `stat` before it
is ever opened (a FIFO does not raise, it blocks forever, and no
`except` catches a hang), corruption is caught as
`(OSError, UnicodeDecodeError, json.JSONDecodeError)` together, a
corrupt file is logged once by PATH and left exactly as it was — never
overwritten, never deleted — and a fresh write goes through `os.open`
with mode `0o600` so there is no window where the file exists but is
world-readable.

**The founding act happens once.** `emparejar` raises rather than
replacing an amo that already exists — not an ergonomic choice, a
security one: whoever reaches this code first becomes the owner of the
house, permanently, and the whole point of the passphrase gate in front
of it is that it only has to hold once.

**Fix round 2, both found live by review.** The first version enforced
"once" with a check-then-act — read the register, see no amo, write one
— and that is two bugs, not a style preference: (1) `_leer` collapsed
"no file at all" and "a file that exists but cannot be read" into the
same empty-looking state, so corrupting an already-founded `casa.json`
and then calling `emparejar` again quietly erased the real amo and
installed a new one; (2) nothing stopped two threads from both reading
"no amo yet" before either had written anything, so both could believe
they had founded the house, and their shared, non-unique temp file name
(`casa.json.tmp`) made a concurrent rename crash likely on top of that.
The fix is not a lock: the founding write is now an exclusive create
(`os.O_CREAT | os.O_EXCL`, the same primitive `remote_auth.py` already
uses), which the kernel — not a re-read — refuses to let two callers
both perform, and a register that already exists in ANY form, readable
or not, blocks it identically. See `_crear_registro` and `emparejar`.
"""

from __future__ import annotations

import json
import os
import secrets
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from loguru import logger

from .personas import CASA, es_valida, id_desde_nombre
from .voz import Huellas


def _estado_vacio() -> dict:
    return {"amo": None, "personas": {}}


@dataclass(frozen=True)
class Persona:
    """One entry in the register. `id` is what `id_desde_nombre` produced
    — ASCII, a valid Hermes profile name, a valid file name. `nombre` is
    what he calls her out loud, kept exactly as given, accent and all.
    """

    id: str
    nombre: str
    amo: bool


def _leer_bruto(path: Path) -> tuple[dict | None, bool]:
    """`(crudo, ilegible)`. `crudo` is the parsed top-level object at
    `path`, or `None` if there is nothing usable there. `ilegible` is
    the distinction fix round 2 was missing: it is `True` only when a
    node EXISTS at `path` and cannot be trusted — a directory, a FIFO, a
    socket, invalid JSON, bytes that are not UTF-8, JSON whose top level
    is not an object — and `False` both for a trustworthy file and for
    no file at all. Collapsing "absent" and "unreadable" into one
    `None` is exactly what let a second `emparejar` through against a
    corrupted, already-founded register: the caller that needs to tell
    them apart is `emparejar`, via `_es_ilegible` below; every other
    reader in this module is fine treating both as an empty register,
    which is what `_leer` still does.

    Never raises and never blocks: the KIND of the node is checked with
    `is_file()` before anything is opened, exactly as
    `remote_auth._read_roster_file` does, and for the same reason — a
    FIFO with no writer on the other end does not raise when opened for
    reading, it blocks forever, and no `except` below would ever run.
    A path that merely does not exist is the ordinary case of a house
    with no register yet, so it is not logged; a node that exists but
    is not a plain file, or a file that cannot be parsed, is logged once
    by path and left untouched.
    """
    if not path.exists():
        return None, False
    if not path.is_file():
        logger.warning(f"casa: {path} is not a regular file; leaving it alone")
        return None, True
    try:
        crudo = json.loads(path.read_text() or "{}")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        logger.warning(f"casa: {path} could not be read; leaving it alone")
        return None, True
    if not isinstance(crudo, dict):
        logger.warning(f"casa: {path} is not a JSON object; leaving it alone")
        return None, True
    return crudo, False


def _sanear(crudo: dict, path: Path) -> dict:
    """Parsed JSON, turned into a register that can be trusted, dropping
    anything that does not fit rather than raising on it. A hand-edited
    file is exactly the kind of thing that goes wrong in the ways a
    person makes mistakes — an id with an accent, an entry with no
    name, an `amo` pointing at nobody — and every drop is logged once,
    naming what was dropped and never any voiceprint or secret."""
    personas: dict[str, dict] = {}
    crudo_personas = crudo.get("personas")
    if isinstance(crudo_personas, dict):
        for pid, datos in crudo_personas.items():
            if not (isinstance(pid, str) and es_valida(pid)):
                logger.warning(f"casa: {path} had an invalid person id — {pid!r}")
                continue
            nombre = datos.get("nombre") if isinstance(datos, dict) else None
            if not isinstance(nombre, str) or not nombre.strip():
                logger.warning(f"casa: {path} had an entry with no name — {pid!r}")
                continue
            personas[pid] = {"nombre": nombre}

    amo = crudo.get("amo")
    if amo is not None and not (isinstance(amo, str) and amo in personas):
        logger.warning(f"casa: {path} had an amo that does not resolve; dropping it")
        amo = None

    return {"amo": amo, "personas": personas}


def _leer(path: Path) -> dict:
    """The register, in the trustworthy shape for READING — never
    raises. Absent and unreadable both degrade to an empty register
    here, same as `remote_auth.load_or_create_roster`'s own fallback:
    that is the right behaviour for `.amo`, `.personas()` and
    `.huellas()`, none of which write anything. `emparejar` is the one
    caller that must NOT make this simplification — see `_es_ilegible`.
    """
    crudo, _ilegible = _leer_bruto(path)
    if crudo is None:
        return _estado_vacio()
    return _sanear(crudo, path)


def _es_ilegible(path: Path) -> bool:
    """Whether something already sits at `path` that cannot be trusted
    — the half of `_leer_bruto`'s answer that `_leer` deliberately
    throws away. `emparejar` asks this BEFORE writing anything, so a
    corrupted, already-founded register is refused outright — logged
    once by `_leer_bruto` itself — rather than read as empty and
    written over."""
    _crudo, ilegible = _leer_bruto(path)
    return ilegible


def _sufijo_unico() -> str:
    """pid plus a few random hex characters — enough that two writers
    racing for the same temp file name never happens by accident. A
    shared, non-unique temp name is a latent crash anywhere two writers
    can meet, not only in the register's own founding write (fix round
    2: two of eight racing `emparejar` calls crashed on exactly this,
    in the voiceprint's temp file, before writing an amo was even
    reached)."""
    return f"{os.getpid()}-{secrets.token_hex(4)}"


def _crear_registro(path: Path, estado: dict) -> None:
    """THE founding write, and the actual enforcement of "the founding
    act happens once" — not a check-then-act. `os.O_CREAT | os.O_EXCL`
    asks the kernel to create `path` if and only if nothing is there
    yet, atomically: two threads racing `emparejar` cannot both
    succeed, and the loser is told by a raised `FileExistsError`, never
    by a re-read that could already be stale by the time it runs. Same
    primitive `remote_auth.load_or_create_secret` already uses
    (`remote_auth.py:55`), not a new one — and it refuses identically
    whether what is already there is a valid register, a corrupt one, a
    directory, or a dangling symlink, which is exactly the property
    `emparejar` needs.

    0600 from the moment the file exists, same reasoning as everywhere
    else in this codebase that opens with `O_CREAT`: creating it
    world-readable and fixing the mode afterwards leaves a window in
    which it is not.

    This function is ONLY for the founding write. There is no other
    writer of `casa.json` today — `recordar` only ever touches
    `voces/` — but if one is ever added, it belongs on a replace-based
    path of its own, the way `remote_auth.save_roster` stays separate
    from `load_or_create_secret`'s exclusive one, rather than reusing
    this.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump(estado, handle)
        handle.flush()
        os.fsync(handle.fileno())


class Registro:
    """Who lives in this house, on disk.

    Every public method reads the register fresh from disk and, for the
    two that write, saves it back before returning — there is no
    in-memory state to go stale, and no caller can observe a write this
    object made before it landed.
    """

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        # A sibling directory, not a subdirectory of anything sensitive
        # — see the module docstring for why voiceprints are not filed
        # next to names, and names are not filed next to phone secrets.
        self._voces_dir = self._path.parent / "voces"

    @property
    def amo(self) -> str | None:
        return _leer(self._path)["amo"]

    def personas(self) -> list[Persona]:
        estado = _leer(self._path)
        amo = estado["amo"]
        return [
            Persona(id=pid, nombre=datos["nombre"], amo=(pid == amo))
            for pid, datos in sorted(estado["personas"].items())
        ]

    def huellas(self) -> Huellas:
        estado = _leer(self._path)
        centroides: dict[str, np.ndarray] = {}
        for pid in estado["personas"]:
            vectores = self._leer_vectores(pid)
            if vectores is not None:
                centroides[pid] = vectores.mean(axis=0)
        return Huellas(centroides)

    def emparejar(self, nombre: str, vectores: Sequence[np.ndarray]) -> Persona:
        """The founding act: this house gets its first person, and its
        only amo, from `nombre` and the voice samples gathered while
        pairing.

        The id is `id_desde_nombre(nombre)`, not `normalizar(nombre)`
        directly: most names in this house carry an accent — `Lucía`,
        `Martín`, the amo's own — and `normalizar` alone would send
        every one of them to `CASA`, since it guards `chat_id`s off the
        wire and is deliberately not the place diacritics get stripped.
        `nombre` itself is kept exactly as given, accent and all, as
        `Persona.nombre` — that is what he calls this person out loud.

        Raises `ValueError` rather than proceeding when: an amo already
        exists, or the register cannot even be read (the founding act
        happens once — see the module docstring, and fix round 2 there
        for why a corrupted register must refuse rather than be treated
        as empty); `nombre` does not survive `id_desde_nombre` even
        after diacritics are stripped — which includes `nombre` folding
        to `casa`, the one id this must never produce, since it is the
        shared identity an unattributed turn falls back to, not a
        person; or `vectores` is empty, which would found an amo whose
        voiceprint can never clear any floor `Huellas.quien` sets — a
        broken amo, not merely an unverified one.

        None of the checks above are what actually stops two callers
        from both founding the house — they are a fast, friendlier
        refusal for the common cases, and every one of them can be
        stale the instant after it runs. The actual enforcement is the
        exclusive create at the bottom of this method: see
        `_crear_registro`.
        """
        if _es_ilegible(self._path):
            raise ValueError(
                f"{self._path} exists but cannot be trusted; refusing to "
                "found a house on top of it — move it aside by hand and "
                "try again"
            )
        if _leer(self._path)["amo"] is not None:
            raise ValueError("an amo already exists; emparejar does not repeat")

        persona_id = id_desde_nombre(nombre)
        if persona_id == CASA:
            raise ValueError(f"not a usable person name: {nombre!r}")
        if not vectores:
            raise ValueError("emparejar needs at least one voice sample")

        estado = {"amo": persona_id, "personas": {persona_id: {"nombre": nombre}}}

        # Order is load-bearing: the voiceprint is written FIRST. If
        # writing it fails partway, `casa.json` is never created and
        # there is simply no amo yet — recoverable by pairing again. The
        # reverse order is not symmetric: a `casa.json` write that
        # succeeds while the voiceprint write then fails would leave an
        # amo who exists, whose passphrase has already been consumed,
        # and who can never be recognised again — a locked box, with no
        # recovery flow yet. Vectors with no amo are harmless orphans
        # the next pairing simply overwrites; an amo with no vectors is
        # not. Do not reorder this to "look" more natural.
        self._guardar_vectores(persona_id, np.asarray(vectores, dtype=np.float32))

        # THE enforcement of "the founding act happens once": an
        # exclusive create, not the checks above. Two threads racing
        # this method cannot both get past `_crear_registro` — the
        # kernel lets exactly one CREATE succeed and raises
        # `FileExistsError` at the other, whether the file that beat it
        # there is a fresh, valid register from the winning thread or
        # anything else that appeared in the meantime.
        try:
            _crear_registro(self._path, estado)
        except OSError as exc:
            raise ValueError(
                "an amo already exists (or the register could not be "
                "created); emparejar does not repeat"
            ) from exc

        return Persona(id=persona_id, nombre=nombre, amo=True)

    def recordar(self, persona_id: str, vector: np.ndarray) -> None:
        """One more sample of `persona_id`'s voice. The centroid
        `huellas()` reports is always the mean of every sample on disk,
        recomputed on read rather than kept running — simpler to get
        right than an incremental average, and cheap enough at this
        scale.

        A no-op, logged once by id and never raising, for a person not
        already in the register: this is called from the audio path
        (task 9), which has nowhere to put an exception, and there is
        nothing to found a voiceprint on top of.
        """
        estado = _leer(self._path)
        if persona_id not in estado["personas"]:
            logger.warning(
                f"casa: recordar() for a person not registered — {persona_id!r}"
            )
            return
        existentes = self._leer_vectores(persona_id)
        nuevo = np.asarray(vector, dtype=np.float32).reshape(1, -1)
        combinado = nuevo if existentes is None else np.vstack([existentes, nuevo])
        self._guardar_vectores(persona_id, combinado)

    # --- voiceprints: their own files, never touching casa.json -------

    def _ruta_vectores(self, persona_id: str) -> Path:
        return self._voces_dir / f"{persona_id}.npy"

    def _leer_vectores(self, persona_id: str) -> np.ndarray | None:
        ruta = self._ruta_vectores(persona_id)
        if not ruta.is_file():
            return None
        try:
            datos = np.load(ruta)
        except (OSError, ValueError) as exc:
            logger.warning(f"casa: could not read the voiceprint at {ruta} — {exc!r}")
            return None
        if datos.ndim != 2 or datos.shape[0] == 0:
            logger.warning(f"casa: {ruta} is not shaped like a voiceprint; ignoring")
            return None
        return datos

    def _guardar_vectores(self, persona_id: str, vectores: np.ndarray) -> None:
        self._voces_dir.mkdir(parents=True, exist_ok=True)
        ruta = self._ruta_vectores(persona_id)
        # A unique suffix, not a fixed ".tmp.npy": two writers for the
        # SAME person (`recordar` from two callers, or `emparejar`
        # racing itself before the exclusive create decides a winner)
        # must never share a temp file name — fix round 2 found exactly
        # this crash, live, on the register's own temp file.
        temporal = ruta.with_name(f"{ruta.stem}.{_sufijo_unico()}.tmp.npy")
        np.save(temporal, vectores)
        temporal.replace(ruta)
