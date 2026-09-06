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
"""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from loguru import logger

from .personas import CASA, es_valida, normalizar
from .voz import Huellas


def _estado_vacio() -> dict:
    return {"amo": None, "personas": {}}


@dataclass(frozen=True)
class Persona:
    """One entry in the register. `id` is what `normalizar` produced —
    ASCII, a valid Hermes profile name, a valid file name. `nombre` is
    what he calls her out loud, kept exactly as given, accent and all.
    """

    id: str
    nombre: str
    amo: bool


def _leer_bruto(path: Path) -> dict | None:
    """The parsed top-level object at `path`, or `None` if the node
    there cannot be trusted at all — missing, a directory, a FIFO, a
    socket, invalid JSON, bytes that are not UTF-8, or JSON whose top
    level is not an object.

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
        return None
    if not path.is_file():
        logger.warning(f"casa: {path} is not a regular file; leaving it alone")
        return None
    try:
        crudo = json.loads(path.read_text() or "{}")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        logger.warning(f"casa: {path} could not be read; leaving it alone")
        return None
    if not isinstance(crudo, dict):
        logger.warning(f"casa: {path} is not a JSON object; leaving it alone")
        return None
    return crudo


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
    """The register, always in the trustworthy shape — never raises."""
    crudo = _leer_bruto(path)
    if crudo is None:
        return _estado_vacio()
    return _sanear(crudo, path)


def _escribir(path: Path, estado: dict) -> None:
    """Replace the register on disk, 0600, atomically: written to a
    temporary file first — flushed and fsynced before the handle closes
    — then renamed over the target, so a reader never sees a half
    written file and a power cut never leaves an empty one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporal = path.with_name(path.name + ".tmp")
    fd = os.open(temporal, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump(estado, handle)
        handle.flush()
        os.fsync(handle.fileno())
    temporal.replace(path)


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

        Raises `ValueError` rather than proceeding when: an amo already
        exists (the founding act happens once — see the module
        docstring); `nombre` does not survive `normalizar` — which
        includes `nombre` literally being `casa`, the one id this must
        never produce, since it is the shared identity an unattributed
        turn falls back to, not a person; or `vectores` is empty, which
        would found an amo whose voiceprint can never clear any floor
        `Huellas.quien` sets — a broken amo, not merely an unverified
        one.
        """
        estado = _leer(self._path)
        if estado["amo"] is not None:
            raise ValueError("an amo already exists; emparejar does not repeat")

        persona_id = normalizar(nombre)
        if persona_id == CASA:
            raise ValueError(f"not a usable person name: {nombre!r}")
        if not vectores:
            raise ValueError("emparejar needs at least one voice sample")

        estado["personas"][persona_id] = {"nombre": nombre}
        estado["amo"] = persona_id
        _escribir(self._path, estado)
        self._guardar_vectores(persona_id, np.asarray(vectores, dtype=np.float32))
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
        temporal = ruta.with_name(ruta.stem + ".tmp.npy")
        np.save(temporal, vectores)
        temporal.replace(ruta)
