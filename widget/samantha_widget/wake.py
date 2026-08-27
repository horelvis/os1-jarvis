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

# How long a hold may last with nothing arriving to close it. A hold is
# opened by the gateway when something is waiting for the user's answer
# (the code assistant's own question, a gate, the closing checkpoint) and
# shut by the frame that says it stopped waiting — so this is only the
# backstop for a frame that never comes: a gateway killed mid-question, a
# plugin that lost the stream. It is longer than every clock on the other
# side (300 s for a gate, 600 s for a checkpoint) by a wide margin,
# because a held question has no clock at all and a person thinking is
# not a fault. Ours, and a bound rather than a measurement: an open
# window that never shuts is a worse bug than the one it fixes.
MAX_HOLD_SECONDS = 900.0

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

    `named` says HOW the last accepted sentence got in — by name, or
    through the window; the adapter routes on it while the code
    assistant waits for an answer.

    `hold()` and `release()` are the second way in, and they are the
    gateway's rather than the room's. While the code assistant waits for
    an answer, an unnamed sentence must reach the gateway however long
    the user took to think — the 30-second window is not that, and the
    spec's claim that it was is the premise this fixes (design v2,
    "Answers are routed by the adapter"). A hold outlives the window and
    is shut by the frame that says nobody is waiting any more.
    """

    def __init__(
        self,
        word: str = "jarvis",
        *,
        window: float = WINDOW_SECONDS,
        max_hold: float = MAX_HOLD_SECONDS,
    ) -> None:
        # An empty word disables the whole mechanism: everything heard is
        # for him, which is how he behaved before 2026-08-26.
        self.word = _fold(word)
        self.window = window
        self.max_hold = max_hold
        self._open_until = 0.0
        self._held_until = 0.0
        self.named = False

    def heard(self, text: str, now: float) -> str | None:
        """The sentence to send on, or None to stay quiet."""
        # Reset before the empty-text early return, not after: `named`
        # must reflect THIS call, never a stale True left over from the
        # last one that actually matched his name.
        self.named = False
        text = text.strip()
        if not text:
            return None
        if not self.word:
            return text

        words = text.split()
        for lead in range(min(MAX_LEAD_WORDS, len(words))):
            if _is_the_name(words[lead], self.word):
                rest = " ".join(words[lead + 1 :]).lstrip(_SEPARATORS).strip()
                self.named = True
                # His name and nothing else is somebody getting his
                # attention, and he should answer that rather than
                # receive an empty turn.
                return rest or text

        # Inside the window a sentence needs no name — but it does not
        # extend the window on its own. Only an answer does, so a room
        # that keeps talking near him does not hold the door open.
        #
        # A hold counts the same way and for longer: somebody is waiting
        # for an answer, and refusing the sentence that carries it would
        # leave the user certain he answered and the run certain he did
        # not.
        if now < self._open_until or now < self._held_until:
            return text
        return None

    def answered(self, now: float) -> None:
        """He has finished replying. Keep listening for a while."""
        self._open_until = now + self.window

    def hold(self, now: float) -> None:
        """Something is waiting for an answer: keep listening, unnamed.

        Capped at `max_hold` so a `release()` that never arrives — a
        gateway killed mid-question — cannot leave him answering the
        room forever.
        """
        self._held_until = now + self.max_hold

    def release(self) -> None:
        """Nobody is waiting any more."""
        self._held_until = 0.0

    def close(self) -> None:
        """Shut the window now. The conversation is over.

        Deliberately not the hold: the microphone going off does not
        mean the code assistant stopped waiting, and it will still be
        waiting when the switch comes back on.
        """
        self._open_until = 0.0
