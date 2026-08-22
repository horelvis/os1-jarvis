"""Expression-marker safety check between Hermes and CosyVoice.

Samantha's replies carry inline expression markers — `[laughter]`,
`[breath]`, `[sigh]`, and `<laughter>palabras reales</laughter>` (see
backend/samantha/personality.py:58-62), the last of which renders its
enclosed words as smiled speech. Hermes' `SentenceChunker` knows
nothing about them, so `<laughter>Ya. Claro</laughter>` can be cut at
the period, handing CosyVoice a clause with an opening tag and no
close. `has_unclosed_tag()` is the check `provider.py` uses to hold
such a clause back and merge it with what follows, instead of sending
it broken.

Why a broken fragment is worth avoiding, and the measurements behind
it, live in one place: `provider.py`'s `stream()` docstring.

Two cases neither this helper nor its caller can repair:
- a reply that ends with the tag still open never gets the input that
  would close it, so it is held forever (malformed model output);
- a *legitimate* `<laughter>` span longer than `MAX_PENDING_CHARS`
  trips provider.py's cap mid-span and is released with the tag still
  open, likely losing the words inside. Not yet observed — the
  personality spec favours short laughter phrases — but worth knowing
  before debugging a dropped clause that turns out to be this.
"""

from __future__ import annotations

_OPEN_TAG = "<laughter>"
_CLOSE_TAG = "</laughter>"


def has_unclosed_tag(text: str) -> bool:
    """True when an opened <laughter> has not been closed yet."""
    return text.count(_OPEN_TAG) > text.count(_CLOSE_TAG)
