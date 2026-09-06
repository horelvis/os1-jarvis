"""The passphrase: made once, said aloud, and gone.

A box with no memory does not guess whose house it is, and does not
serve anyone. It waits, and shows a phrase on the strip. Whoever says
that phrase becomes the owner — and, because pairing also erases
everything the machine remembers, that sentence is the most
consequential thing anybody will ever say to it.

**It is words, not a code, and that is the whole design.** Whisper
transcribes language, not strings: "X7K-9QM" comes back as "equis siete
ka" or worse. Being unheard is the one failure a spoken interface cannot
afford (CLAUDE.md §12, 2026-08-26) — the wake word needed five spellings
of one name in a single morning before it worked. So `parecida` never
compares strings for equality; it asks how close they sound, the way
`wake.py` already does for his own name.

**Matching is an ordered subsequence, not a bag of words.** `wake.py`'s
single 0.6 ratio is right for one word said at the start of a sentence.
Handing over the whole house — and erasing everything the machine
remembers, in the same motion — is not that, and the first version of
this function got it wrong: it required only that three of the four
words each turn up somewhere, plus the whole two sentences be similar as
strings. Three-of-four-plus-a-ratio permits exactly what three-of-four
alone permits (three correct words already clear the ratio on their
own), so a missing word, a substituted word, or three overheard words
recited in whatever order all authenticated. A houseguest who overheard
three words owned the house.

What `parecida` does instead: every word of `frase`, in order, must be
found among `dicho`'s words, consumed left to right, each match decided
by the same 0.6 ratio. A missing word has nothing left to match against
by the time its turn comes. A substituted word is not close enough to
what it replaced. A reordered phrase runs out of `dicho` to search
before its later words are found, because the words that would have
matched them were already consumed matching something earlier out of
place. Extra words — before, after, or between — are not merely
tolerated but required to be: Whisper prepends his own name, and a
person reading the phrase off a screen says "vale" first and narrates as
they go. No whole-string ratio runs alongside this any more: it added
nothing the subsequence rule does not already give more strictly, and
keeping it would have worked against the one requirement above — a
sentence with real filler around the phrase reads as less similar to the
bare phrase as strings, so an AND with a ratio would start rejecting the
exact "vale, gato ventana lento roble" case this design exists to allow.
"""

from __future__ import annotations

import os
import secrets
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

from loguru import logger

from .palabras import PALABRAS

# How close a heard word has to be to the one on the strip. Reused from
# `wake.py`, not re-derived: it is the same problem (Whisper's own
# spelling of a word it did not train on) at the same threshold, not a
# coincidence of naming.
THRESHOLD = 0.6

# Characters folded away before comparing, mirroring `wake.py`'s own
# `_PUNCTUATION`: a spoken sentence reaches here through Whisper, which
# punctuates and capitalises freely and inconsistently.
_PUNCTUATION = ",.;:¿?¡!…\"'“”()-—"


def _fold(word: str) -> str:
    """Lowercase, unaccented, unpunctuated. Identical in kind to
    `wake.py`'s `_fold` — duplicated rather than imported, because this
    module consumes nothing else in the widget and a passphrase gating
    ownership of the machine should not depend on a module that governs
    something else entirely."""
    word = word.strip(_PUNCTUATION).lower()
    decomposed = unicodedata.normalize("NFD", word)
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn")


def _palabras_normalizadas(texto: str) -> list[str]:
    return [w for w in (_fold(p) for p in texto.split()) if w]


def generar(n: int = 4) -> str:
    """`n` distinct ordinary words, space-separated, chosen with
    `secrets.choice` — never `random`, because this phrase decides who
    owns the machine."""
    elegidas: list[str] = []
    while len(elegidas) < n:
        palabra = secrets.choice(PALABRAS)
        if palabra not in elegidas:
            elegidas.append(palabra)
    return " ".join(elegidas)


def _es_similar(candidato: str, objetivo: str) -> bool:
    return (
        candidato == objetivo
        or SequenceMatcher(None, candidato, objetivo).ratio() >= THRESHOLD
    )


def parecida(dicho: str, frase: str) -> bool:
    """Was `dicho` somebody saying `frase` out loud?

    An ordered subsequence match. `frase`'s words are folded and taken in
    order; `dicho`'s are folded and scanned left to right, once, never
    backtracking. For each word of `frase` in turn, scanning resumes
    where the previous match left off and advances until a word similar
    enough is found (`_es_similar`, the same 0.6 ratio `wake.py` uses) or
    `dicho` runs out. Running out at any word means `frase` was not said:
    that is what rejects a missing word, a substituted word, and a
    reordered phrase alike (reordering strands the words that would have
    matched later targets behind the point already consumed matching an
    earlier one out of place). Words in `dicho` that are skipped over
    while scanning are never rejected on their own — that is what a
    prefix like "vale, ..." or a mid-phrase "eh" needs, and what a name
    Whisper prepends needs too.
    """
    palabras_dicho = _palabras_normalizadas(dicho)
    palabras_frase = _palabras_normalizadas(frase)
    if not palabras_frase or not palabras_dicho:
        return False

    idx = 0
    for objetivo in palabras_frase:
        encontrado = False
        while idx < len(palabras_dicho):
            candidato = palabras_dicho[idx]
            idx += 1
            if _es_similar(candidato, objetivo):
                encontrado = True
                break
        if not encontrado:
            return False
    return True


def cargar_o_crear(path: Path | str) -> str:
    """The phrase currently on the strip, made once and reused.

    Read at boot, with nobody to catch a traceback (CLAUDE.md §2.8):
    this function must never raise into its caller. Anything that goes
    wrong — the path is a directory, a permission is missing, the disk
    is full — falls back to a phrase that is simply never persisted,
    which behaves exactly like a box that has not paired with anyone
    yet, just without a saved copy.

    Written 0600 with `os.open`, before anything is put in it: creating
    the file world-readable and fixing the mode afterwards would leave a
    window where the phrase is on disk and readable by anyone on the
    box, exactly the trap `remote_auth.py` avoids for the same reason.
    """
    target = Path(path)
    try:
        if target.exists():
            if not target.is_file():
                logger.warning(
                    f"frase: {target} no es un archivo normal; se genera una en memoria"
                )
                return generar()
            try:
                contenido = target.read_text().strip()
            except (OSError, UnicodeDecodeError):
                logger.warning(
                    f"frase: no se puede leer {target}; se genera una en memoria"
                )
                return generar()
            if contenido:
                return contenido
            # An empty file behaves like no file at all: fall through
            # and write a fresh phrase into it.

        frase = generar()
        target.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as handle:
            handle.write(frase)
        return frase
    except OSError as exc:
        logger.warning(f"frase: no se pudo crear o leer {target} — {exc}")
        return generar()


def consumir(path: Path | str) -> None:
    """The phrase has been said and accepted: it is spent.

    Removing the file is enough — the next `cargar_o_crear` finds
    nothing there and mints a new one. Never raises: this runs at the
    moment somebody has just become the owner of the machine, and a
    stray `OSError` here must not be what answers them.
    """
    target = Path(path)
    try:
        target.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning(f"frase: no se pudo consumir {target} — {exc}")
