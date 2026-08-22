"""Expression-marker safety check between Hermes and CosyVoice.

Samantha's replies carry inline expression markers — `[laughter]`,
`[breath]`, `[sigh]`, and `<laughter>palabras reales</laughter>` (see
backend/samantha/personality.py:58-61) — and `<laughter>...</laughter>`
renders its enclosed words as smiled speech. Hermes' `SentenceChunker`
splits on sentence boundaries and knows nothing about these tags, so a
reply like `<laughter>Ya. Claro</laughter>` can get cut at the period,
handing CosyVoice a clause with an opening tag and no matching close —
an isolated fragment, which is exactly the shape that measurement
against the live server showed failing intermittently (see
provider.py's module docstring for the numbers). Losing that clause
loses the words inside the broken tag.

`has_unclosed_tag()` is the check `provider.py` uses to hold a clause
back — merging it with whatever text comes next — instead of sending
it broken.

Note: a reply that ends with the tag still open has no further input
to close it, so it holds forever. This is malformed model output, not
something this helper (or its caller) can repair.

Note also the inverse case, not yet observed: a *legitimate*
`<laughter>...</laughter>` span that runs longer than
`MAX_PENDING_CHARS` before the model emits the closing tag would trip
provider.py's cap mid-span and get released with the tag still open,
likely losing whatever text was inside it. The personality spec favors
short laughter phrases, so this is low-probability, but nothing in
this module or provider.py prevents it — worth knowing before someone
spends time debugging a dropped clause that turns out to be this.
"""

from __future__ import annotations

_OPEN_TAG = "<laughter>"
_CLOSE_TAG = "</laughter>"


def has_unclosed_tag(text: str) -> bool:
    """True when an opened <laughter> has not been closed yet."""
    return text.count(_OPEN_TAG) > text.count(_CLOSE_TAG)
