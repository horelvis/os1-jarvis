"""Whether he was being spoken to, and what was said once his name is off.

Pure state, no GTK and no audio: the split `photo.py` and `wave_model.py`
already make.

Until 2026-08-26 he answered everything the microphone heard — CLAUDE.md
§2.3 called that "always listening, no wake word", and it was a
deliberate decision. What changed it is the user's, on 2026-08-26: he
answers to his name now, and a room he is in can be talked in without
talking to him.

**Matching is deliberately loose, and that is the whole design.** Whisper
does not reliably hear "Jarvis". The same synthesised sentence, driven
through the real path four times on 2026-08-26, came back as "Carbis",
"Harvish", "Jervis" and "Jarvis". An exact match ignores three of them,
and being ignored is the one failure a wake word cannot afford: the user
repeats himself, louder, and concludes the thing is broken. A false
positive costs one unwanted answer, which he can be told to forget; a
false negative costs trust in the whole surface. So the comparison is a
similarity ratio, and the threshold is set where those four spellings
pass.
"""

from __future__ import annotations

import unicodedata
from difflib import SequenceMatcher

# How close a heard word has to be to his name. 0.6 is where the four
# spellings Whisper actually produced all pass — "carbis" against
# "jarvis" is the worst of them at 0.67 — and where ordinary Spanish
# words at the start of a sentence mostly do not. It is ours, and a
# measurement, not a guess; it is NOT one of BarnDoor's constants.
THRESHOLD = 0.6

# How long he keeps listening after answering. A conversation is not a
# sequence of commands, and making somebody say his name before every
# sentence would be the assistant CLAUDE.md §1 says he is not. Ours, and
# a guess.
WINDOW_SECONDS = 30.0

# How far into a sentence his name may be. "Oye, Jarvis, apaga la luz"
# is how people talk; a name in the sixth word is somebody talking ABOUT
# him, not to him.
MAX_LEAD_WORDS = 2

# Word characters, for splitting. Kept here rather than a regex import
# for the same reason the rest of this module has no dependencies.
_PUNCTUATION = ",.;:¿?¡!…\"'“”()-—"

# What separates his name from the sentence after it — a comma, a pause.
# NOT the full set above: stripping that would eat the "¿" that opens a
# Spanish question, and "¿qué hora es?" would reach him as "qué hora
# es?", which CosyVoice reads with the wrong intonation.
_SEPARATORS = ",.;: -—"


def _fold(word: str) -> str:
    """Lowercase, unaccented, unpunctuated. `Jarvis,` → `jarvis`."""
    word = word.strip(_PUNCTUATION).lower()
    decomposed = unicodedata.normalize("NFD", word)
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn")


def _is_the_name(word: str, name: str) -> bool:
    if not word:
        return False
    folded = _fold(word)
    if folded == name:
        return True
    return SequenceMatcher(None, folded, name).ratio() >= THRESHOLD


class WakeWord:
    """Did somebody just talk to him, and what did they say?

    `heard()` returns the sentence with his name taken off the front, or
    None when the sentence was not for him. `answered()` opens the
    window during which the next sentence needs no name.
    """

    def __init__(
        self,
        word: str = "jarvis",
        *,
        window: float = WINDOW_SECONDS,
    ) -> None:
        # An empty word disables the whole mechanism: everything heard is
        # for him, which is how he behaved before 2026-08-26.
        self.word = _fold(word)
        self.window = window
        self._open_until = 0.0

    def heard(self, text: str, now: float) -> str | None:
        """The sentence to send on, or None to stay quiet."""
        text = text.strip()
        if not text:
            return None
        if not self.word:
            return text

        words = text.split()
        for lead in range(min(MAX_LEAD_WORDS, len(words))):
            if _is_the_name(words[lead], self.word):
                rest = " ".join(words[lead + 1 :]).lstrip(_SEPARATORS).strip()
                # His name and nothing else is somebody getting his
                # attention, and he should answer that rather than
                # receive an empty turn.
                return rest or text

        # Inside the window a sentence needs no name — but it does not
        # extend the window on its own. Only an answer does, so a room
        # that keeps talking near him does not hold the door open.
        if now < self._open_until:
            return text
        return None

    def answered(self, now: float) -> None:
        """He has finished replying. Keep listening for a while."""
        self._open_until = now + self.window

    def close(self) -> None:
        """Shut the window now. The conversation is over."""
        self._open_until = 0.0
