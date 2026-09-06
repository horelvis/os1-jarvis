"""Who spoke, decided as arithmetic on vectors.

Pure: this module never sees audio, never loads a model and never opens
a file. It is handed embeddings and it answers with a person id, so the
one probabilistic decision in the system is the one thing here that can
be tested exhaustively without a microphone in the room.

Two floors, not one, and the second is the interesting one. `piso` is
how sure he must be at all; `margen` is how much clearer the best
answer must be than the second. Two sisters of the same age in the same
house are the case this project actually has, and for them the failure
is not "nobody is close" but "two people are equally close" — which the
first floor cannot see. Below either, the answer is `CASA`.

**A failure degrades to `CASA` and never to another person**, which is
what makes it safe to build the rest on.
"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np

from .personas import CASA

# Where "sure enough" sits. Calibrated against real voices in task 4;
# until then it is a placeholder that fails safe by being high.
PISO_POR_DEFECTO = 0.6

# How much clearer the winner must be than the runner-up.
MARGEN_POR_DEFECTO = 0.05


def coseno(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity, and 0.0 rather than a division by zero.

    A silent or clipped utterance can produce a zero vector, and this is
    called from the audio path where an exception has nowhere to go.
    """
    na = float(np.linalg.norm(a))
    nb = float(np.linalg.norm(b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


class Huellas:
    """The stored centroids, and the question asked of them."""

    def __init__(self, centroides: Mapping[str, np.ndarray]) -> None:
        self._centroides = dict(centroides)

    def __len__(self) -> int:
        return len(self._centroides)

    def quien(
        self,
        vector: np.ndarray,
        *,
        piso: float = PISO_POR_DEFECTO,
        margen: float = MARGEN_POR_DEFECTO,
    ) -> str:
        """The person this voice belongs to, or `CASA`.

        `CASA` means "not attributable", which covers three different
        situations deliberately collapsed into one: nobody is enrolled,
        nobody is close enough, and two people are equally close. The
        caller must not be able to tell them apart, because acting
        differently on them is how a guess becomes an identity.
        """
        if not self._centroides:
            return CASA
        puntuados = sorted(
            ((coseno(vector, c), quien) for quien, c in self._centroides.items()),
            reverse=True,
        )
        mejor, quien = puntuados[0]
        if mejor < piso:
            return CASA
        if len(puntuados) > 1 and mejor - puntuados[1][0] < margen:
            return CASA
        return quien
