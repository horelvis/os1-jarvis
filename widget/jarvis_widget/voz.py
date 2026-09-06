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

# Where "sure enough" sits. **Calibrated 2026-09-06**, which is what
# this comment promised and did not have until a real iPhone and a real
# owner found the gap. It was 0.6, a placeholder that "fails safe by
# being high" — and it failed the owner of the house instead.
#
# Seven utterances from the amo, embedded and compared against his own
# enrolled centroid (`~/.jarvis/voces/orelvis.npy`):
#
#     1.5 s -> 0.307      3.0 s -> 0.614
#     2.0 s -> 0.446      3.8 s -> 0.652, 0.678
#     2.3 s -> 0.635      5.5 s -> 0.746
#
# **The mean of his own speech was 0.583 — below the old floor.** More
# than half his turns came back `CASA`, which is why he could not ask
# his own house to pair a phone. 0.45 admits every utterance from 2.3 s
# upward (0.614 at worst) and still sits well clear of the 0.0-0.3 band
# a different speaker occupies for this model.
#
# **This number does not stand alone.** `locutor._MINIMO_SEGUNDOS`
# refuses to embed anything shorter than the measurements support: his
# OWN voice at 1.5 s scores 0.307, so a low floor without that duration
# guard would be an open door rather than a calibration.
#
# Calibrated on one person and seven utterances. That is enough to
# replace a placeholder and not enough to be final: re-measure with
# `widget/tools/medir_voces.py` when a second person is enrolled.
PISO_POR_DEFECTO = 0.45

# How much clearer the winner must be than the runner-up.
MARGEN_POR_DEFECTO = 0.05


def coseno(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity: 0.0 for zero, shape mismatch, or non-finite result.

    A silent or clipped utterance can produce a zero vector, an embedding
    with non-finite values can appear on the audio path, and a centroid
    stored by a different model has a different width. This function is
    called from the audio path where an exception has nowhere to go, so it
    returns 0.0 instead of raising.
    """
    # Shape mismatch: treat as similar to nothing
    if a.shape != b.shape:
        return 0.0

    na = float(np.linalg.norm(a))
    nb = float(np.linalg.norm(b))

    # Zero vectors or non-finite norms: treat as similar to nothing
    if na == 0.0 or nb == 0.0 or not (np.isfinite(na) and np.isfinite(nb)):
        return 0.0

    result = float(np.dot(a, b) / (na * nb))

    # Non-finite result: treat as similar to nothing
    if not np.isfinite(result):
        return 0.0

    return result


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
