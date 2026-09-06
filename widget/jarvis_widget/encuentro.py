"""The first conversation this project has ever had.

Everything before this module is a TURN: something is said, he answers,
it is over (`turn.py`). This is a FLOW — ask, listen, confirm, retry —
and `turn.py` has no notion of one and is not touched by this module.

Written pure on purpose, exactly like `frase.py`, `casa.py` and
`borrar.py` that it is built on: no GTK, no audio, no clock of its own.
`Encuentro.oye()` is handed a transcript and, maybe, a voice vector, and
answers with what he should say — it can be driven entirely from tests,
and the audio path (task 9) is the only caller that will ever give it
real ones.

The sequence: `ESPERANDO` (nobody owns the box yet; only the passphrase
on the screen advances it) -> `BORRANDO` (he has announced that
continuing erases everything he remembers, and waits for a confirmation
that cannot be said by accident) -> `PIDIENDO` (a few sentences, to
learn a voice; then a name) -> `CONFIRMANDO` (he says the name back and
waits for a yes) -> `HECHO`. A wrong answer at any point returns to the
PREVIOUS state with something to say — never to a dead end, and never
by raising.

**Why the wipe needs a stronger confirmation than the founding act
itself.** `casa.Registro.emparejar` is already gated behind a spoken
passphrase (`frase.py`) — that is what stops a stranger from taking the
house. But saying the passphrase ALSO condemns whatever the box
currently remembers, and the two are not the same risk: the passphrase
is secret and typed once, deliberately; the wipe's own confirmation is
answered out loud, in a room, and this is a voice-driven surface where a
"sí" said to a question the machine misheard is exactly how a house
gets erased by accident (see `borrar.ejecutar`'s own docstring — the
snapshot it takes first exists for the same reason). A single word is
not enough: `CONFIRMACION_BORRADO` is a short but specific sentence,
checked with the same ordered-subsequence matcher the passphrase itself
uses (`frase.parecida`). For an accident to trigger it, a room would
have to produce five specific words, each within Whisper's own 0.6
similarity floor, IN ORDER — the same argument that makes the passphrase
itself safe against being overheard, aimed here at chance instead of an
eavesdropper. Confirming the NAME afterwards, in `CONFIRMANDO`, is a
plain affirmative/negative instead (`_es_afirmativo` / `_es_negativo`):
getting that wrong costs a repeated question, never a family's memory.

**The wipe is announced before it happens, not reported after.** The
announcement is the `Respuesta` returned when the passphrase is first
recognised (`ESPERANDO` -> `BORRANDO`); the erasure itself only runs
once the specific confirmation phrase is heard (`BORRANDO` ->
`PIDIENDO`), immediately before the first sentence is asked for. What he
says next is not assumed success: `borrar.ejecutar` returns a
`Resultado` rather than raising, precisely so a node that survived the
attempt (a permissions error, an unremovable child) can be told to the
person instead of silently left on disk while he claims a clean slate —
see `_texto_prefijo_borrado` and `Resultado.completo`.

**`PIDIENDO` hands over something to read, not a blank prompt.** Added
after a requirement change from the project's owner: "say anything"
leaves a person improvising with no idea whether three words are
enough, `locutor.Locutor.vector()` refuses anything under about a
second, and the old prompt gave no way to know either how much to say
or how many times. `lecturas.elegir` picks one short passage per sample
slot when `PIDIENDO` is entered (`self._lecturas_muestra`, indexed by
`len(self._muestras)`), and `Respuesta.lectura` carries the current
one — separately from `habla`, since a person cannot read a passage off
what they just heard spoken over it. He also says which one it is out
loud ("es la primera de tres"), answering the other half of the
complaint: how many samples this pairing needs. A refused sample (an
unusable vector) says why (`_TEXTO_MUESTRA_NO_SERVIDA`, "no he cogido
bastante") and asks for the SAME reading again — the slot index does
not advance on a refusal, so no passage is spent on an attempt that
produced no sample.

**The band shows what he is waiting for, in every state, not only
`PIDIENDO`.** A second requirement change, reported by the owner
himself trying to pair: the band kept showing the passphrase through
the whole name-and-confirmation exchange — spent, no longer doing
anything — so the screen said "say this phrase" while he was being
asked for a name, and he answered the screen twice instead of the
question. `Respuesta.lectura` is now set, deliberately, by every
handler in this file, never left to default to `None` by omission:

- `ESPERANDO` — `self._frase`, the passphrase, for as long as it is
  still what is needed — including the greeting and the reminder, and
  gone the instant it is recognised (the same `Respuesta` that advances
  to `BORRANDO` already carries `BORRANDO`'s own `lectura`, not the
  spent passphrase for one more turn).
- `BORRANDO` — `CONFIRMACION_BORRADO`, the sentence written out. This
  is the one that matters most: it is the sentence that erases the
  house, deliberately hard to say by accident, and expecting someone to
  recall it from having heard it once is the same mistake the reading
  passages exist to fix for a voice sample. A wrong answer here returns
  to `ESPERANDO` and its `lectura` switches back to the passphrase in
  the same `Respuesta`.
- `PIDIENDO` — the current passage while collecting samples
  (`_lectura_pantalla_muestra`, which also puts the "(2 de 3)" count on
  screen, since it is already said out loud); `None` once enough
  samples are in and he is asking for a name — there is nothing to
  read at that point, and showing the last passage would repeat this
  exact bug in miniature.
- `CONFIRMANDO` — the candidate name, exactly as heard. Seeing
  "Orelvis" spelled out is worth more than hearing it, because the
  whole question at that point is whether it was heard correctly —
  Whisper produced "Or Elvis", "Horelvis" and "Salvis" for one real
  name in a single afternoon. `None` again on the way back to asking
  for a new name.
- `HECHO` — `None`. The band is done.

**Dispatch is by CURRENT state, and that is what stops the passphrase
from advancing twice.** `oye()` looks at `self.estado` once and routes
to exactly one handler. Saying the passphrase again while already in
`BORRANDO` is not re-examined by `ESPERANDO`'s handler — it reaches
`BORRANDO`'s, which checks it against `CONFIRMACION_BORRADO`, not
against the passphrase, and (not matching) sends the flow back to
`ESPERANDO` instead of skipping ahead.

**`ESPERANDO` greets once, then goes quiet about it.** Added after a
requirement change from the project's owner: while nobody owns the
house, a person talking to him and not saying the passphrase must be
greeted and told, as a fact rather than an apology or a repeated
instruction, that nothing else can happen until the pairing does. That
greeting is said once per `Encuentro` (`self._saludado`, the one bit of
extra state `ESPERANDO` now carries) — every later utterance that is
still not the passphrase gets a short reminder instead, never the same
paragraph again; a presence that repeats a paragraph at every stray
sentence is a kiosk (CLAUDE.md §1.5), not what he is. Neither message
mentions erasing memory — that belongs strictly after the passphrase,
in `BORRANDO`, where there is an actual confirmation to give; warning
someone about destruction before they have asked for anything would be
a threat, not an explanation.

**The security property, restated as code:** `ESPERANDO`'s handler
checks `self._registro.amo` — read fresh from disk, per `Registro`'s own
contract, never cached — BEFORE it ever compares `texto` against the
passphrase. Once a house has an owner, the phrase that used to open it
is inert, on this instance or any other pointed at the same register.

**What counts as a usable voice sample.** The audio path's embedder
(`locutor.Locutor.vector()`) returns `None` — never raises — for an
utterance too short to embed or a model that failed to load. `PIDIENDO`
counts only the samples where `vector is not None`; an utterance that
produced nothing still gets a reply, so nobody is left wondering why the
count did not move.

**Naming, not `normalizar`.** The candidate name is turned into a
person id with `personas.id_desde_nombre`, never `personas.normalizar`
directly — the latter guards `chat_id`s off the wire and rejects every
accented name outright, which would mean the amo could not give his own
name if it happened to be `Lucía` or `Martín`. A name is refused only
when it folds all the way down to `personas.CASA`, the one id that must
never belong to a person.

**Answering "¿cómo la llamo?" is usually a sentence, not a word.**
`_nombre_desde_texto` strips the ordinary Spanish carriers — "me llamo
X", "soy X", "X, a secas" — before `id_desde_nombre` ever sees the
result, so "me llamo Marta" becomes the same candidate "Marta" a bare
answer would have given. It only strips the CARRIER; it never invents a
name, and anything it does not recognise is passed through unchanged to
the same refusal a bare bad answer already gets.

**What `oye()` does and does not swallow.** Every failure this module
can provoke through ordinary voice input is caught and turned into
something to say: `casa.Registro.emparejar` can raise `ValueError`
(an amo already exists, the register is corrupt, the name or the sample
set is empty) or, in principle, `OSError` from the voiceprint write, and
both send the flow back to `ESPERANDO` with an apology rather than
crash. The one exception, by design, is `borrar.inventario`'s
`_comprobar_seguro`: it raises `RuntimeError` if the module's own
hardcoded lists of what to erase ever collide with a directory holding
model weights, and that is a bug in our own constants, not a condition
a voice turn can recover from — it is deliberately left uncaught here,
per the module's own docstring, so it stays loud. It is not reachable
from any transcript or vector a person could produce; only editing
`borrar.py` itself can trigger it.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from . import borrar, lecturas
from .bienvenida import BIENVENIDA, NECESIDAD
from .casa import Registro
from .frase import parecida
from .personas import CASA, id_desde_nombre

if TYPE_CHECKING:
    import numpy as np

# Where a pairing looks for what to erase, and where it keeps the
# snapshot `borrar.ejecutar` takes before erasing anything — the same
# `~/.jarvis` convention every other module in this package uses
# (`vad.py`, `remote_auth.py`, `remote.py`...). The backup directory is
# a SIBLING of both roots, never nested under either: `borrar.ejecutar`
# already refuses to run if `respaldo` sits inside something about to be
# erased, and there is no reason to get anywhere near that refusal by
# default.
DEFAULT_RAIZ_JARVIS = Path.home() / ".jarvis"
DEFAULT_RAIZ_HERMES = Path.home() / ".hermes"
DEFAULT_RESPALDO = Path.home() / "jarvis-respaldo-emparejamiento"

# "A few sentences" (task brief) — enough for `voz.Huellas` to average
# out one bad take, not so many that pairing feels like an enrolment
# form.
N_MUESTRAS_POR_DEFECTO = 5

# The sentence a person must say back before anything is erased. See the
# module docstring for why this is a sentence, checked the way the
# passphrase itself is checked, and not a bare "sí".
CONFIRMACION_BORRADO = "adelante, borra toda tu memoria"

# What the band says ABOVE the phrase, per state — the small pair of
# lines a person reads before the big one. This used to be a single
# constant baked into `bienvenida_area.py`, which is how the strip ended
# up telling somebody "hasta que no la diga, no puedo hacer nada" while
# the voice was asking them to read a passage, and again while it was
# asking whether their name was Orelvis. Each state now says what its
# own phrase is FOR, and `Respuesta.rotulo` carries it out.
#
# `ESPERANDO` reuses `bienvenida.BIENVENIDA` / `NECESIDAD` rather than a
# fourth wording of the same fact: those two lines are also what he SAYS
# at boot (`__main__`'s welcome), and a screen that worded it its own way
# would be a second voice.
ROTULO_ESPERANDO = f"{BIENVENIDA}\n{NECESIDAD}"

# The one that erases the house. It says what saying it does — the band
# is the only place that fact is written down rather than spoken once —
# and "tal cual" because `frase.parecida` wants the words in order.
ROTULO_BORRANDO = "Esto borra todo lo que recuerdo.\nSi está seguro, dígamelo tal cual."

# Shared by every sample slot: the job does not change between the first
# reading and the third, and the count that DOES change is already on
# the phrase itself (`_lectura_pantalla_muestra`).
ROTULO_PIDIENDO = "Estoy aprendiendo su voz.\nLéame esto en voz alta."

# The whole question at this point is whether the name was heard right,
# so the header asks exactly that and says what answer closes it.
ROTULO_CONFIRMANDO = "¿Le he oído bien?\nDígame sí o no."

_AFIRMATIVOS = frozenset({"si", "vale", "correcto", "exacto", "afirmativo"})
_NEGATIVOS = frozenset({"no", "negativo", "incorrecto"})

# Mirrors `frase.py`'s own `_PUNTUACION` / `_fold`: duplicated rather
# than imported, for the same reason `frase.py` gives for not importing
# `wake.py`'s — this module should not depend on another module's
# unrelated behaviour changing out from under it.
_PUNTUACION = ",.;:¿?¡!…\"'“”()-—"


def _fold(palabra: str) -> str:
    palabra = palabra.strip(_PUNTUACION).lower()
    descompuesto = unicodedata.normalize("NFD", palabra)
    return "".join(c for c in descompuesto if unicodedata.category(c) != "Mn")


def _contiene_alguna(texto: str, objetivo: frozenset[str]) -> bool:
    return any(_fold(palabra) in objetivo for palabra in texto.split())


def _es_afirmativo(texto: str) -> bool:
    return _contiene_alguna(texto, _AFIRMATIVOS)


def _es_negativo(texto: str) -> bool:
    return _contiene_alguna(texto, _NEGATIVOS)


def _vector_usable(vector: "np.ndarray | None") -> bool:
    """Whether this utterance produced something `voz.Huellas` can use.

    `locutor.Locutor.vector()` returns exactly `None` — never raises —
    for an utterance it could not embed at all, and that is the only
    thing that disqualifies a sample here. Anything else about its
    quality (a bad centroid, an outlier) is `voz.Huellas`'s problem, not
    this module's.
    """
    return vector is not None


# Asked "¿cómo le llamo?", a person answers with a bare name about half
# the time and with one of these ordinary sentences the other half.
# Handling them here — rather than sending "me-llamo-marta" straight to
# `id_desde_nombre`, which folds spaces out of nothing and refuses the
# whole sentence as a person id — is what lets "me llamo Marta", "soy
# Marta", "puedes llamarme Marta" and "llámame Marta" all register
# exactly as "Marta" would. What genuinely does not survive
# `id_desde_nombre` (an unintelligible answer, silence) is still refused
# after this: this only strips the CARRIER phrase, it does not invent a
# name that was not said.
_PREFIJOS_NOMBRE = re.compile(
    r"^\s*(?:me\s+llamo|mi\s+nombre\s+es|soy|puedes\s+llamarme|ll[aá]mame)\s+(.+)$",
    re.IGNORECASE,
)

# "Marta, a secas" — the colloquial way of saying "just Marta, nothing
# more" — carries the name at the front and this filler at the end.
_SUFIJO_A_SECAS = re.compile(r"\s*,?\s*a\s+secas\s*$", re.IGNORECASE)


def _nombre_desde_texto(texto: str) -> str:
    """The candidate name inside `texto`, stripped of the ordinary
    Spanish phrases that carry it. Never invents a name and never
    raises: given nothing it recognises, it returns `texto` itself,
    trimmed — exactly what used to be handed to `id_desde_nombre`
    directly, so a name it does not need to touch is untouched.
    """
    candidato = texto.strip()
    coincidencia = _PREFIJOS_NOMBRE.match(candidato)
    if coincidencia:
        candidato = coincidencia.group(1)
    candidato = _SUFIJO_A_SECAS.sub("", candidato)
    return candidato.strip(_PUNTUACION + " ")


# --- what he says --------------------------------------------------------
# Every string below is his: Spanish, courteous, dry, no exclamation
# marks, never servile, no emoji — read against `Hermes/jarvis-soul.md`
# before changing any of them. He is not walking anyone through a setup;
# he is meeting the person whose house this is, about to forget
# everything he knew before.

_TEXTO_SALUDO_INICIAL = (
    "Buenas. Todavía no sé de quién es esta casa, y no puedo hacer nada "
    "por usted hasta que eso quede claro: diga la frase que tiene "
    "delante para empezar."
)

_TEXTO_RECORDATORIO_ESPERA = (
    "Sigo sin saber de quién es esta casa. La frase, cuando quiera."
)

_TEXTO_ANUNCIO_BORRADO = (
    "Antes de seguir, olvidaré todo lo que sé hasta ahora, y no hay forma "
    "de deshacerlo desde aquí. Si es lo que quiere, dígame exactamente "
    f"esto: «{CONFIRMACION_BORRADO}»."
)

_TEXTO_BORRADO_CANCELADO = (
    "No he oído eso. No toco nada; cuando quiera seguir, dígame de nuevo "
    "la frase de la pantalla."
)

_TEXTO_BORRADO_COMPLETO_PREFIJO = "Hecho, no queda nada de antes."

_TEXTO_BORRADO_PARCIAL_PREFIJO = (
    "No lo he podido borrar todo: algo de quien vivía aquí antes sigue en "
    "el disco. Se lo digo tal cual es."
)

# "la primera", "la segunda"... of the ordinal, spoken so a person
# knows how many samples this pairing needs, not only how much to say
# for each one — the owner's complaint had two halves, and `lecturas`
# answers the other one. Refers to the READING itself ("la [ordinal]
# [lectura]"), grammatically feminine because "lectura" is, never to
# the person — no gendering risk, same reasoning as `_TEXTO_MUESTRA_NO_SERVIDA`
# below and the review round that fixed `_TEXTO_PIDE_NOMBRE`.
_ORDINALES = (
    "primera",
    "segunda",
    "tercera",
    "cuarta",
    "quinta",
    "sexta",
    "séptima",
    "octava",
    "novena",
    "décima",
)

# For "de tres", not "de 3" — `n_muestras` is a handful in practice, and
# spelling it out reads like something said, not a field in a form.
_CARDINALES = (
    "uno",
    "dos",
    "tres",
    "cuatro",
    "cinco",
    "seis",
    "siete",
    "ocho",
    "nueve",
    "diez",
)

# What a refused sample is told, instead of the request repeated
# unchanged: "no he cogido bastante" says what to do differently
# (louder, slower, from the start of the line); a bare re-ask does not.
_TEXTO_MUESTRA_NO_SERVIDA = "No he cogido bastante."

# Neither gendered: "su voz" is the object (a feminine noun, but not a
# person), and "le llamo" is peninsular leísmo for a personal direct
# object — the amo could be the father or either daughter in this
# house, and nothing here should guess which before he even has a name.
_TEXTO_PIDE_NOMBRE = "Ya conozco su voz. ¿Cómo le llamo?"

_TEXTO_NOMBRE_INVALIDO = "Ese nombre no me sirve. Dígame otro."

_TEXTO_PIDE_NOMBRE_DE_NUEVO = "Entonces, ¿cómo se llama?"

_TEXTO_EMPAREJAR_FALLIDO = (
    # "amo" — the module's own domain term (`casa.Registro.amo`), not
    # "dueño": a role name used throughout this codebase regardless of
    # who holds it, rather than a synonym that carries its own gender.
    "No he podido completarlo: puede que esta casa ya tenga amo. No voy a insistir."
)


def _texto_prefijo_borrado(resultado: borrar.Resultado) -> str:
    """What he says once the wipe has actually run — honest about
    whether it fully succeeded, per `resultado.completo`, and never
    assumed from the fact that nothing raised. See `borrar.ejecutar`'s
    own docstring: `-> None` used to make a partial failure invisible
    here, exactly the case that matters (a previous owner's `teacher/`
    or `personas.json` surviving on disk) — this is the branch that
    closes it. Only the wipe report: what comes after it (the first
    reading) is `_respuesta_pide_muestra`'s job.
    """
    return (
        _TEXTO_BORRADO_COMPLETO_PREFIJO
        if resultado.completo
        else _TEXTO_BORRADO_PARCIAL_PREFIJO
    )


def _texto_orden(ordinal: int, total: int) -> str:
    palabra_total = (
        _CARDINALES[total - 1] if 1 <= total <= len(_CARDINALES) else str(total)
    )
    if 1 <= ordinal <= len(_ORDINALES):
        return f"la {_ORDINALES[ordinal - 1]} de {palabra_total}"
    return f"la número {ordinal} de {palabra_total}"


def _texto_pide_lectura(ordinal: int, total: int, *, otra_vez: bool) -> str:
    pregunta = "¿Me la lee otra vez?" if otra_vez else "¿Me lee esto?"
    return f"{pregunta} Es {_texto_orden(ordinal, total)}."


def _lectura_pantalla_muestra(pasaje: str, ordinal: int, total: int) -> str:
    """What the band shows while a sample is being asked for: the count
    (digits are fine on a screen — it is speech that wants them spelled
    out) above the passage itself, so glancing at it answers "how many
    of how many" as well as "what do I say"."""
    return f"({ordinal} de {total})\n{pasaje}"


def _texto_confirma_nombre(nombre: str) -> str:
    return f"{nombre}, ha dicho. ¿Es así?"


def _texto_bienvenida(nombre: str) -> str:
    return f"{nombre}. Ya sé quién es usted, y esta casa es suya a partir de ahora."


class Estado(str, Enum):
    ESPERANDO = "esperando"
    BORRANDO = "borrando"
    PIDIENDO = "pidiendo"
    CONFIRMANDO = "confirmando"
    HECHO = "hecho"


@dataclass(frozen=True)
class Respuesta:
    """What he says, whether this is the last thing he will say, and
    what the strip should show while it waits — kept separate from
    `habla` on purpose. `habla` is what reaches the speakers; a person
    cannot read a passphrase, a passage, or their own name spelled out
    off what they just heard spoken over it, so the band is something
    to look at, never something spoken.

    Every `Respuesta` from a state that is waiting for something sets
    `lectura` explicitly — see the module docstring's "the band shows
    what he is waiting for" for the full mapping. `None` means there is
    genuinely nothing to look at right now (asking for a name, `HECHO`),
    not "leave whatever was there": nothing in this module ever relies
    on a stale value surviving from a previous `Respuesta`, which is
    exactly the bug this field's every-state coverage exists to close.

    `rotulo` is the small line ABOVE it — what the phrase is for —
    and travels with `lectura` for the same reason: it used to be a
    fixed constant on the band ("Hasta que no la diga, no puedo hacer
    nada"), which meant the screen kept giving the passphrase
    instruction over a reading passage and over a name. The two are
    always set together: a `lectura` with no `rotulo` is a phrase
    nobody is told what to do with, and a `rotulo` with no `lectura`
    labels an empty band.

    Optional and defaulting to `None` so a caller that does not care
    about it — most pointedly whoever is wiring `Respuesta` into
    `__main__.py` — keeps working unchanged.
    """

    habla: str
    terminado: bool = False
    lectura: str | None = None
    rotulo: str | None = None


class Encuentro:
    """The state machine for one pairing, start to finish.

    One instance covers one attempt: from a box with no owner to a
    fresh amo, or back to `ESPERANDO` if it is abandoned partway. Its
    only state is in-memory; everything it PERSISTS goes through
    `registro` (`casa.Registro`) and, at the wipe, through `borrar`.
    """

    def __init__(
        self,
        registro: Registro,
        frase: str,
        *,
        raiz_jarvis: Path | str = DEFAULT_RAIZ_JARVIS,
        raiz_hermes: Path | str = DEFAULT_RAIZ_HERMES,
        respaldo: Path | str = DEFAULT_RESPALDO,
        n_muestras: int = N_MUESTRAS_POR_DEFECTO,
    ) -> None:
        self._registro = registro
        self._frase = frase
        self._raiz_jarvis = Path(raiz_jarvis)
        self._raiz_hermes = Path(raiz_hermes)
        self._respaldo = Path(respaldo)
        self._n_muestras = max(1, n_muestras)
        self.estado = Estado.ESPERANDO
        self._muestras: list[np.ndarray] = []
        self._nombre_candidato: str | None = None
        # One reading per sample slot, chosen once when `PIDIENDO` is
        # entered (`lecturas.elegir`) and indexed by `len(self._muestras)`
        # — see `_respuesta_pide_muestra`. Fixed per slot rather than
        # re-picked on every call: a retry after a refused sample shows
        # the SAME passage again, never a fresh one wasted on an attempt
        # that produced no sample at all.
        self._lecturas_muestra: list[str] = []
        # `ESPERANDO`'s own little state: whether he has already
        # greeted whoever is talking to him. See `_en_esperando` — the
        # full greeting is said once, not on every utterance that is
        # not the passphrase.
        self._saludado = False

    def oye(self, texto: str, vector: "np.ndarray | None" = None) -> Respuesta | None:
        """One utterance in. What he should say, or `None` for silence.

        Never raises for anything a person could actually say — see the
        module docstring for the one deliberate exception, which no
        transcript or vector can trigger. `texto` that is not a string
        (a stray `None` from the audio path, say) is treated as silence
        rather than inspected.
        """
        if not isinstance(texto, str):
            texto = ""

        if self.estado is Estado.ESPERANDO:
            return self._en_esperando(texto)
        if self.estado is Estado.BORRANDO:
            return self._en_borrando(texto)
        if self.estado is Estado.PIDIENDO:
            return self._en_pidiendo(texto, vector)
        if self.estado is Estado.CONFIRMANDO:
            return self._en_confirmando(texto)
        # HECHO: the flow is over, and there is nothing left to hear.
        return None

    # --- ESPERANDO ---------------------------------------------------

    def _en_esperando(self, texto: str) -> Respuesta | None:
        if self._registro.amo is not None:
            # The security property: once this house has an owner, the
            # phrase that used to open it is inert — read fresh from
            # disk, never cached, so this holds even if another
            # `Encuentro` (or `emparejar` called directly) founded the
            # house a moment ago.
            return None
        if parecida(texto, self._frase):
            # The passphrase is SPENT the moment it is said — the band
            # must stop showing it right here, in the same `Respuesta`,
            # not on some later turn. It switches straight to what
            # `BORRANDO` is waiting for instead of going blank in
            # between, so there is never a turn where the band shows
            # nothing at all for a state that IS waiting for something.
            self.estado = Estado.BORRANDO
            return Respuesta(
                habla=_TEXTO_ANUNCIO_BORRADO,
                lectura=CONFIRMACION_BORRADO,
                rotulo=ROTULO_BORRANDO,
            )
        if not texto.strip():
            # Nothing was actually said — not "somebody talking to him
            # and it was not the passphrase", just silence. Answered
            # with silence in kind, and the greeting below is not
            # spent on it.
            return None

        # Somebody is talking to a machine that knows nobody. He greets
        # once — this is the first thing he has ever said to anybody —
        # and says, as a fact about his situation rather than an
        # apology or a repeated instruction, that nothing else is
        # possible yet. What he must NOT say here is anything about
        # erasing memory: that warning belongs after the passphrase,
        # where there is an actual confirmation to give (`BORRANDO`) —
        # here nobody has asked for anything yet, so raising it would
        # be a threat, not an explanation.
        #
        # Every later utterance that is still not the passphrase gets a
        # short reminder instead of the same paragraph again: a
        # presence that repeats itself on every stray sentence is a
        # kiosk (CLAUDE.md §1.5), not what he is. Either way, the band
        # keeps showing the passphrase — it is still what `ESPERANDO`
        # is waiting for, said once or said again.
        if not self._saludado:
            self._saludado = True
            return Respuesta(
                habla=_TEXTO_SALUDO_INICIAL,
                lectura=self._frase,
                rotulo=ROTULO_ESPERANDO,
            )
        return Respuesta(
            habla=_TEXTO_RECORDATORIO_ESPERA,
            lectura=self._frase,
            rotulo=ROTULO_ESPERANDO,
        )

    # --- BORRANDO ------------------------------------------------------

    def _en_borrando(self, texto: str) -> Respuesta:
        if not parecida(texto, CONFIRMACION_BORRADO):
            # Wrong answer -> the previous state, with something to
            # say. Nothing has been touched: the passphrase (still
            # unconsumed outside this module) said again reopens
            # `BORRANDO` from the top. The band switches back to it
            # too — `ESPERANDO` is waiting for it again.
            self.estado = Estado.ESPERANDO
            return Respuesta(
                habla=_TEXTO_BORRADO_CANCELADO,
                lectura=self._frase,
                rotulo=ROTULO_ESPERANDO,
            )

        # The wipe happens here, once, between the passphrase and the
        # first sentence — announced already (`_TEXTO_ANUNCIO_BORRADO`,
        # above), never merely reported after the fact.
        #
        # `borrar.inventario`'s `_comprobar_seguro` raises `RuntimeError`
        # deliberately if the goes/stays lists ever collide — see the
        # module docstring for why that is left uncaught here.
        borrado = borrar.inventario(self._raiz_jarvis, self._raiz_hermes)
        resultado = borrar.ejecutar(borrado, respaldo=self._respaldo)

        self.estado = Estado.PIDIENDO
        self._muestras = []
        self._lecturas_muestra = lecturas.elegir(self._n_muestras)
        return self._respuesta_pide_muestra(prefijo=_texto_prefijo_borrado(resultado))

    # --- PIDIENDO --------------------------------------------------------

    def _respuesta_pide_muestra(
        self, *, prefijo: str | None = None, motivo: str | None = None
    ) -> Respuesta:
        """Ask for the sample at the current slot (`len(self._muestras)`),
        handing over the reading for that slot and saying which one it
        is — how many are left is the other half of what "say anything"
        never answered. `motivo`, when given (a sample was just
        refused), is said before the question, and turns the question
        itself into "again" rather than a fresh ask — the SAME reading,
        since nothing was recorded for this slot yet.
        """
        ordinal = len(self._muestras) + 1
        pasaje = self._lecturas_muestra[len(self._muestras)]
        pregunta = _texto_pide_lectura(
            ordinal, self._n_muestras, otra_vez=motivo is not None
        )
        habla = " ".join(parte for parte in (prefijo, motivo, pregunta) if parte)
        lectura = _lectura_pantalla_muestra(pasaje, ordinal, self._n_muestras)
        return Respuesta(
            habla=habla,
            terminado=False,
            lectura=lectura,
            rotulo=ROTULO_PIDIENDO,
        )

    def _en_pidiendo(self, texto: str, vector: "np.ndarray | None") -> Respuesta:
        if len(self._muestras) < self._n_muestras:
            aceptada = _vector_usable(vector)
            if aceptada:
                self._muestras.append(vector)
            if len(self._muestras) < self._n_muestras:
                motivo = None if aceptada else _TEXTO_MUESTRA_NO_SERVIDA
                return self._respuesta_pide_muestra(motivo=motivo)
            # Enough samples: nothing left to read, so the band goes
            # blank rather than keep showing the last passage — there
            # is genuinely nothing to look at while he asks for a name,
            # and showing stale reading material here is exactly the
            # bug this round exists to fix.
            return Respuesta(habla=_TEXTO_PIDE_NOMBRE, lectura=None, rotulo=None)

        # Enough samples already: this utterance is the candidate name,
        # said plainly or wrapped in "me llamo…" / "soy…" /
        # "puedes llamarme…" / "llámame…" / "…, a secas". Whatever
        # candidate comes out of that — a real name, or Whisper's own
        # garble of one — is never trusted outright: it goes to
        # `CONFIRMANDO`, which reads it back and waits for an explicit
        # yes before `emparejar` is ever called. That is the answer to
        # "should an unrecognised single word need confirmation rather
        # than acceptance": it already does, for every candidate alike.
        nombre = _nombre_desde_texto(texto)
        if id_desde_nombre(nombre) == CASA:
            return Respuesta(habla=_TEXTO_NOMBRE_INVALIDO, lectura=None, rotulo=None)
        self._nombre_candidato = nombre
        self.estado = Estado.CONFIRMANDO
        # The band shows the name exactly as heard — seeing "Orelvis"
        # spelled out is worth more than hearing it, since the whole
        # question at this point is whether it was heard correctly.
        return Respuesta(
            habla=_texto_confirma_nombre(nombre),
            lectura=nombre,
            rotulo=ROTULO_CONFIRMANDO,
        )

    # --- CONFIRMANDO -----------------------------------------------------

    def _en_confirmando(self, texto: str) -> Respuesta:
        if self._nombre_candidato is None:
            # Unreachable under normal operation — `CONFIRMANDO` is only
            # ever entered from `_en_pidiendo`, immediately after it
            # sets this — but `oye()`'s contract is that it never
            # raises, and an `assert` is exactly the construct that can
            # break that promise silently: `python -O` strips it. Treat
            # a broken invariant the same way a lost `emparejar` race is
            # treated below — log it once, and recover to `ESPERANDO`
            # with something to say, rather than crash on it.
            logger.warning("encuentro: CONFIRMANDO reached with no candidate name")
            self.estado = Estado.ESPERANDO
            return Respuesta(
                habla=_TEXTO_EMPAREJAR_FALLIDO,
                lectura=self._frase,
                rotulo=ROTULO_ESPERANDO,
            )

        if _es_negativo(texto):
            # Wrong answer -> the previous state ("asking"), with
            # something to say. The samples already gathered are kept;
            # only the name is asked again — nothing to read while that
            # happens, same as the first time it was asked.
            self.estado = Estado.PIDIENDO
            return Respuesta(
                habla=_TEXTO_PIDE_NOMBRE_DE_NUEVO, lectura=None, rotulo=None
            )

        if not _es_afirmativo(texto):
            # Neither a yes nor a no: repeat the question rather than
            # guess. Still `CONFIRMANDO`, still something to say, and
            # the band keeps showing the same name — it has not changed.
            return Respuesta(
                habla=_texto_confirma_nombre(self._nombre_candidato),
                lectura=self._nombre_candidato,
                rotulo=ROTULO_CONFIRMANDO,
            )

        try:
            persona = self._registro.emparejar(self._nombre_candidato, self._muestras)
        except (ValueError, OSError) as exc:
            # An amo already exists (a race lost against another
            # pairing attempt), the register is unreadable, or the
            # voiceprint could not be written. None of this is
            # recoverable by trying the same name again, so back to
            # `ESPERANDO` — where, if a house now exists, the security
            # check above makes the passphrase inert anyway. The band
            # goes back to showing the passphrase along with it.
            logger.warning(f"encuentro: emparejar failed — {exc!r}")
            self.estado = Estado.ESPERANDO
            return Respuesta(
                habla=_TEXTO_EMPAREJAR_FALLIDO,
                lectura=self._frase,
                rotulo=ROTULO_ESPERANDO,
            )

        self.estado = Estado.HECHO
        # HECHO: nothing left to show — the band is done.
        return Respuesta(
            habla=_texto_bienvenida(persona.nombre),
            terminado=True,
            lectura=None,
            rotulo=None,
        )
