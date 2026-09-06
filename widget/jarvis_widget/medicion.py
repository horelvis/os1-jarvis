"""Who scores against whom: the testable half of task 4's measurement.

`widget/tools/medir_voces.py` is the tool a person runs — it owns the
microphone, the prompts, the embedding model and all the printing, and none
of that can be exercised by a test (CLAUDE.md: no test in this repo touches
the network, the GPU, a display or a microphone; `pytest`'s own
`testpaths = ["tests"]` is what keeps anything under `widget/tools/` from
being collected at all). This module is what is left once those are taken
out: filenames and vectors in, other filenames and vectors out. It never
opens a microphone, never loads an ONNX model, and the only I/O it does at
all is listing what is already on disk (`siguiente_seq`) — no network, no
GPU, no display.

It exists for the same reason `wave_model.py`, `bars_model.py`, `photo.py`,
`ficha.py` and `endpoint.py` do: each is the pure half of something that
touches hardware, kept separate so the part that decides something can
actually be pinned by a test. Here what gets decided is which floor and
margin (`voz.PISO_POR_DEFECTO`, `voz.MARGEN_POR_DEFECTO`) a real household's
voices can clear — a probabilistic decision nobody tests is a probabilistic
decision nobody can trust, and a leave-one-out centroid that got
"simplified" back to a shared one would look better on every number while
being wrong about every one of them, silently.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .personas import CASA
from .voz import Huellas

# <person>__<3-digit seq>__<condition>. The condition never carries an
# underscore (`sanear_condicion` only keeps letters, digits and hyphens),
# so the double-underscore separator is not ambiguous against reasonable
# person names.
_RE_NOMBRE = re.compile(r"^([a-z0-9][a-z0-9_-]*)__(\d{3})__([a-z0-9-]+)$")


@dataclass(eq=False)
class Muestra:
    """One embedded utterance, with enough to group and re-find it."""

    persona: str
    condicion: str
    seq: int
    vector: np.ndarray
    ruta_audio: Path | None


def sanear_condicion(cruda: str) -> str:
    """A condition label safe to put in a filename, never empty."""
    limpia = re.sub(r"[^a-z0-9]+", "-", cruda.strip().casefold()).strip("-")
    return limpia or "estandar"


def parsear_nombre(stem: str) -> tuple[str, int, str] | None:
    """The inverse of the naming convention, or None if it does not match."""
    coincidencia = _RE_NOMBRE.match(stem)
    if coincidencia is None:
        return None
    persona, seq, condicion = coincidencia.groups()
    return persona, int(seq), condicion


def siguiente_seq(base: Path, persona: str) -> int:
    """The next free sequence number for `persona`, so nothing is overwritten.

    The only I/O in this module: listing `base / "vectores"`. Given a
    directory that does not exist yet, or one with no files for this
    person, the answer is 1 — a fresh start, not an error.
    """
    directorio = base / "vectores"
    if not directorio.is_dir():
        return 1
    maximo = 0
    for ruta in directorio.glob(f"{persona}__*.npy"):
        analizado = parsear_nombre(ruta.stem)
        if analizado is not None and analizado[0] == persona:
            maximo = max(maximo, analizado[1])
    return maximo + 1


def rango(minimo: float, maximo: float, paso: float) -> list[float]:
    """An inclusive floor range, `minimo` to `maximo` in steps of `paso`."""
    pasos = round((maximo - minimo) / paso)
    return [round(minimo + i * paso, 10) for i in range(pasos + 1)]


def centroide(vectores: list[np.ndarray]) -> np.ndarray:
    """The mean of one or more embeddings. Never called with zero."""
    return np.mean(np.stack(vectores), axis=0).astype(np.float32)


def centroides_loo(
    muestra: Muestra, indice: dict[str, list["Muestra"]]
) -> dict[str, np.ndarray]:
    """Centroids for scoring ONE utterance: leave-it-out of its own person's.

    Scoring an utterance against a centroid that was built partly FROM it
    inflates its own similarity — worst for the person with the fewest
    samples — so `muestra` is excluded from its own person's centroid
    before anything is compared. Every other person's centroid is
    unaffected, since the utterance was never theirs.

    A person left with nothing to build a centroid from — their only
    sample (leave-one-out empties it), or an empty entry in `indice` at
    all — is simply not a candidate for THIS utterance rather than a
    crash: `centroide([])` is never called. `Huellas({})` already answers
    `CASA` safely if nothing ends up enrolled at all.
    """
    centroides: dict[str, np.ndarray] = {}
    for persona, lista in indice.items():
        if persona == muestra.persona:
            vectores = [m.vector for m in lista if m is not muestra]
        else:
            vectores = [m.vector for m in lista]
        if not vectores:
            continue
        centroides[persona] = centroide(vectores)
    return centroides


def tabla_confusion(
    muestras: list[Muestra],
    indice: dict[str, list[Muestra]],
    pisos: list[float],
    margen: float,
) -> list[tuple[float, int, int, int, Counter]]:
    """One row per floor: how many were correct, `casa`, or wrong.

    The classification itself is `voz.Huellas.quien` — the exact function
    that will run at turn time, not a reimplementation of its branches —
    scored against the leave-one-out centroids for each utterance in turn.
    """
    filas = []
    for piso in pisos:
        correctas = rechazadas = equivocadas = 0
        ejemplos: Counter = Counter()
        for m in muestras:
            centroides = centroides_loo(m, indice)
            resultado = Huellas(centroides).quien(m.vector, piso=piso, margen=margen)
            if resultado == m.persona:
                correctas += 1
            elif resultado == CASA:
                rechazadas += 1
            else:
                equivocadas += 1
                ejemplos[(m.persona, resultado)] += 1
        filas.append((piso, correctas, rechazadas, equivocadas, ejemplos))
    return filas
