"""Expression-marker safety check between Hermes and CosyVoice.

Samantha's replies carry inline expression markers — `[laughter]`,
`[breath]`, `[sigh]`, and `<laughter>palabras reales</laughter>` (see
backend/samantha/personality.py:58-61) — and `<laughter>...</laughter>`
renders its enclosed words as smiled speech. Hermes' `SentenceChunker`
splits on sentence boundaries and knows nothing about these tags, so a
reply like `<laughter>Ya. Claro</laughter>` can get cut at the period,
handing CosyVoice a clause with an opening tag and no matching close.
That produces the same silent HTTP-200-with-no-audio failure as a
too-short clause (see backend/samantha/tts.py:213-217) — so the clause
is dropped and the words inside the broken tag go unheard.

`has_unclosed_tag()` is the check `provider.py` uses to hold a clause
back — merging it with whatever text comes next — instead of sending
it broken.

Note: a reply that ends with the tag still open has no further input
to close it, so it holds forever. This is malformed model output, not
something this helper (or its caller) can repair.
"""

from __future__ import annotations

_OPEN_TAG = "<laughter>"
_CLOSE_TAG = "</laughter>"


def has_unclosed_tag(text: str) -> bool:
    """True when an opened <laughter> has not been closed yet."""
    return text.count(_OPEN_TAG) > text.count(_CLOSE_TAG)
