"""Deciding that somebody has finished talking, from what they have said.

Two halves, deliberately separate the way `vad.py` is: `CompletionRule`
is the policy and is pure enough to test phrase by phrase, and
`VoskPartials` is the model, the only part that needs a file on disk.

Measured 2026-09-01, and it inverts the obvious answer: the BEST
transcriber is the WORST at this. At the user's mid-sentence pause
Whisper wrote «…habrá que comprobar que estén encendidas y con red.» — a
clean, punctuated, finished Spanish sentence — and closing there cut him
off mid-thought. Vosk, at the same instant, wrote «…que estén encendidas
y» and waited. Whisper COMPLETES the sentence it heard; Vosk leaves it
hanging where the speaker left it. For this one job, the engine that
cannot punctuate is the one that tells the truth.
"""

from __future__ import annotations

import re

# Spanish words that CANNOT end a sentence. The distinction is the whole
# rule and it is narrower than it looks: a word that merely *usually*
# does not end a sentence must stay out, because every entry costs the
# 880 ms saving on every sentence that legitimately ends with it.
#
# Deliberately ABSENT, each one measured or reasoned:
#   es, era, hay   — "¿qué hora es?", "no hay"
#   no, sí, ya     — "creo que no"
#   más, menos     — "dame más"
#   también, tampoco, nunca, siempre, bien, mal, aquí, allí
#   otro, otra     — "quiero otro"
#
# Accents are NOT folded away: `que` cannot end a sentence and `qué` can
# ("no sé qué"), and the same holds for como/cómo, cuando/cuándo,
# donde/dónde. Folding would put the interrogatives into this set.
_CANNOT_END = frozenset(
    # determiners and possessives
    "el la los las un una unos unas mi mis tu tus su sus nuestro nuestra "
    "nuestros nuestras vuestro vuestra este esta estos estas ese esa esos "
    "esas aquel aquella aquellos aquellas cada cierto cierta cuyo cuya "
    "cuyos cuyas"
    " "
    # prepositions, and the two contractions
    "a ante bajo con contra de desde durante en entre hacia hasta mediante "
    "para por segun sin sobre tras del al"
    " "
    # conjunctions and subordinators (unaccented forms only)
    "y e o u ni pero sino aunque porque pues que si como cuando donde "
    "mientras"
    " "
    # unstressed pronouns, which always precede their verb
    "me te se nos os le les"
    " "
    # degree adverbs that must be followed by what they modify
    "muy tan".split()
)

_WORD = re.compile(r"[a-záéíóúüñ]+", re.IGNORECASE)


class CompletionRule:
    """Does this partial transcript read as a finished thought?"""

    def __init__(self, min_words: int = 2) -> None:
        self.min_words = min_words

    def looks_complete(self, partial: str) -> bool:
        words = _WORD.findall(partial.lower())
        if len(words) < self.min_words:
            return False
        return words[-1] not in _CANNOT_END


class VoskPartials:  # completed in Task 3
    def __init__(self, *_args, **_kwargs) -> None:
        raise FileNotFoundError("Vosk support arrives in Task 3")


def load_partials():  # completed in Task 3
    return None
