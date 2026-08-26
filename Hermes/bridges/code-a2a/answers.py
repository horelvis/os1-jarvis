"""Is that Spanish a yes? Shared by the gate hook and the checkpoint."""

from __future__ import annotations

import unicodedata

_YES = frozenset(
    {"sí", "si", "vale", "ok", "okay", "dale", "adelante", "hazlo", "claro", "perfecto"}
)
_YES_PHRASES = ("de acuerdo", "por supuesto", "que sí")


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.casefold().strip())
    return "".join(c for c in text if not unicodedata.combining(c))


def assent(text: str) -> bool:
    folded = _fold(text)
    if not folded:
        return False
    first = folded.split(",")[0].split(".")[0].strip()
    return first in {_fold(w) for w in _YES} or any(
        folded.startswith(_fold(p)) for p in _YES_PHRASES
    )
