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

**Matching is looser than a password and stricter than a wake word.**
`wake.py`'s single ratio is right for one word said at the start of a
sentence, where a false negative costs a repeat and a false positive
costs one unwanted answer. Handing over the whole house is not that: the
same 0.6 ratio is kept per word, because it is measured (it is what the
four real mis-transcriptions of "Jarvis" passed at), but a second rule is
added that wake.py has no use for — at least three of the four words
must match individually, and not only the phrase as a whole. Without it
a long, unrelated sentence that happens to share letters with the phrase
could pass on overall similarity alone; a stray word from a distracted
retry cannot bring the whole phrase down either.
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


def parecida(dicho: str, frase: str) -> bool:
    """Was `dicho` somebody saying `frase` out loud?

    Never an equality check: see the module docstring for why. Two
    conditions, both required — the second is the one wake word matching
    does not need:

    1. The two sentences, folded and taken as a whole, are similar at
       `wake.py`'s own 0.6 ratio.
    2. At least `len(frase) - 1` of `frase`'s own words each have a
       similar word somewhere in `dicho` — three of four, for the
       four-word phrase this module actually produces. Condition 1 alone
       would let a long sentence that happens to overlap heavily with
       the phrase's letters pass without anyone having said the words;
       condition 2 alone would let the four right words, buried in an
       unrelated sentence, pass on overall similarity that isn't there.
       Together, neither loophole is open on its own.

    Order matters, as a consequence of condition 1 rather than a rule
    added on purpose: the same four words said in a different order
    usually fail the whole-sentence ratio even though every word still
    matches individually under condition 2. That is the intended
    reading — the person is asked to say the phrase as it is shown, not
    merely to know the four words it is made of.
    """
    palabras_dicho = _palabras_normalizadas(dicho)
    palabras_frase = _palabras_normalizadas(frase)
    if not palabras_frase or not palabras_dicho:
        return False

    texto_dicho = " ".join(palabras_dicho)
    texto_frase = " ".join(palabras_frase)
    if SequenceMatcher(None, texto_dicho, texto_frase).ratio() < THRESHOLD:
        return False

    coincidencias = sum(
        1
        for objetivo in palabras_frase
        if any(
            candidato == objetivo
            or SequenceMatcher(None, candidato, objetivo).ratio() >= THRESHOLD
            for candidato in palabras_dicho
        )
    )
    necesarias = max(1, len(palabras_frase) - 1)
    return coincidencias >= necesarias


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
