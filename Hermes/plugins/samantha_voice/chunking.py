"""Text safety rules between Hermes' sentence chunker and CosyVoice.

Two upstream failures this prevents, both of which surface as HTTP 200
with an empty body (see backend/samantha/tts.py:213-217):

  1. `tts_text` much shorter than `prompt_text` crashes hifigan.
  2. A clause boundary inside an expression marker.

Markers are exactly `[laughter]`, `[breath]`, `[sigh]` and
`<laughter>...</laughter>` (backend/samantha/personality.py:58-61).
"""

from __future__ import annotations

from typing import Iterable, Iterator

_OPEN_TAG = "<laughter>"
_CLOSE_TAG = "</laughter>"


def _has_unclosed_tag(text: str) -> bool:
    """True when an opened <laughter> has not been closed yet."""
    return text.count(_OPEN_TAG) > text.count(_CLOSE_TAG)


def safe_clauses(clauses: Iterable[str], min_chars: int = 40) -> Iterator[str]:
    """Merge clauses until each is safe to synthesise, then yield.

    One-clause lookahead: a buffer that already satisfies the rules is
    held in `ready` and only released once a further clause arrives, so
    a short final clause always merges into the last emission instead
    of trailing on its own and crashing the vocoder.
    """
    ready: str | None = None  # satisfies the rules, awaiting release
    pending: str | None = None  # still accumulating

    for raw in clauses:
        clause = raw.strip()
        if not clause:
            continue

        pending = clause if pending is None else f"{pending} {clause}"

        if len(pending) < min_chars or _has_unclosed_tag(pending):
            continue

        if ready is not None:
            yield ready
        ready, pending = pending, None

    if pending is not None:
        ready = pending if ready is None else f"{ready} {pending}"
    if ready is not None:
        yield ready
