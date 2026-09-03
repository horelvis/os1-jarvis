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

import json
import os
import re
import sys
from pathlib import Path

from .vad import INPUT_RATE

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


DEFAULT_MODEL_PATH = Path.home() / ".samantha" / "models" / "vosk-model-small-es-0.42"


class _Stream:
    """One Vosk recognizer, and the words it has produced so far.

    `VoskPartials` hands each of `.turn` and `.room` its own instance of
    this, built from the same loaded `Model` — so `reset()` on one never
    touches the other, and a `push()` on one is invisible to the other.
    """

    def __init__(self, make_recognizer) -> None:
        self._make_recognizer = make_recognizer
        self._recognizer = make_recognizer()
        self._settled = ""
        # Whether anything has been pushed since the last reset — the
        # whole of what makes `reset()` free when there is nothing to
        # forget. See its docstring for the 22.7 ms it is protecting.
        self._dirty = False

    def push(self, frame: bytes) -> None:
        """One 16 kHz mono int16 frame. Same frames the VAD sees."""
        # Set BEFORE the call, not after: if `AcceptWaveform` raises
        # halfway through, the recognizer may already have swallowed
        # part of the frame, and the safe direction is to rebuild it.
        self._dirty = True
        if self._recognizer.AcceptWaveform(frame):
            done = json.loads(self._recognizer.Result())["text"]
            self._settled = f"{self._settled} {done}".strip()

    def partial(self) -> str:
        """Everything heard since the last reset, settled and in flight.

        Before the first `push()`, Vosk's own result has no "partial"
        key at all (`{"text": ""}`) — `.get` treats that the same as an
        empty one rather than raising.
        """
        flying = json.loads(self._recognizer.PartialResult()).get("partial", "")
        return f"{self._settled} {flying}".strip()

    def reset(self) -> None:
        """A turn ended. Forget it, or the next one inherits its words.

        Free when there is nothing to forget, and that is not an
        optimisation for its own sake. Constructing a `KaldiRecognizer`
        measured **22.7 ms** on this machine (20 iterations, warm) — 71%
        of a 32 ms frame period, on the PortAudio reader thread, which
        must never block. Three separate review rounds each caught this
        being called once per FRAME instead of once per transition, in
        three different places, because nothing at a call site says it
        is expensive.

        So the price is paid here instead of at every call site. The
        three hand-written transition guards upstream stay — they are
        still correct, and they skip even this check — but they are now
        an optimisation rather than the only thing standing between the
        microphone thread and a 22.7 ms stall thirty-one times a second.
        """
        if not self._dirty:
            return
        self._recognizer = self._make_recognizer()
        self._settled = ""
        self._dirty = False


class VoskPartials:
    """The room, transcribed as it arrives, for nobody to read.

    Vosk rather than Whisper because this text is never shown, never
    spoken and never sent — and because it is better at THIS job for the
    reason it is worse at the other one (see the module docstring). It
    costs ~5% of one core and 39 MB on disk.

    One `Model` is loaded and carries two independent streams, `.turn`
    and `.room` — see the module docstring for why they must not hear
    each other. A second `KaldiRecognizer` on the same model is cheap:
    ~10% of one core total, and never both fed at once in practice.
    """

    def __init__(self, model_path: str | os.PathLike[str] | None = None) -> None:
        from vosk import KaldiRecognizer, Model, SetLogLevel

        path = Path(
            model_path or os.getenv("JARVIS_WIDGET_VOSK_MODEL") or DEFAULT_MODEL_PATH
        )
        if not path.is_dir():
            raise FileNotFoundError(f"Vosk model not at {path} — see widget/README.md")
        SetLogLevel(-1)  # it prints a page of Kaldi banner otherwise
        model = Model(str(path))
        self.turn = _Stream(lambda: KaldiRecognizer(model, INPUT_RATE))
        self.room = _Stream(lambda: KaldiRecognizer(model, INPUT_RATE))


def load_partials() -> VoskPartials | None:
    """`VoskPartials`, or None with one line of explanation.

    None is not an error: it means the endpointing and the text-based
    barge-in are off and he behaves exactly as he did before this
    existed. Every caller must be written so that is true.
    """
    try:
        return VoskPartials()
    except Exception as exc:  # any failure means "off"
        print(
            f"endpointing apagado, Vosk no cargó: {exc!r}",
            file=sys.stderr,
            flush=True,
        )
        return None
