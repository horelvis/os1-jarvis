"""Text safety rules between Hermes' sentence chunker and CosyVoice.

Hermes' SentenceChunker already merges fragments under min_len=20 chars
into the next sentence, but this floor is below what CosyVoice tolerates.
CosyVoice's hifigan vocoder crashes when `tts_text` is much shorter than
`prompt_text`, returning HTTP 200 with an empty body (see
backend/samantha/tts.py:213-217). This guard enforces a minimum length
and prevents clause boundaries inside expression markers (which can
trigger the same silent failure).

Two rules enforced:

  1. Each emission is at least `min_chars` long (default 40).
  2. Expression marker tags are never split across clause boundaries.

Markers are exactly `[laughter]`, `[breath]`, `[sigh]` and
`<laughter>...</laughter>` (backend/samantha/personality.py:58-61).

Note: The final flush does not recheck tag balance, so a malformed
stream with an unclosed `<laughter>` will emit it broken. This is
inherent — no further input arrives to fix it.
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
