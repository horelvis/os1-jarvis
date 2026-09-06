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
see `_texto_tras_borrado` and `Resultado.completo`.

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

from . import borrar
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


# Asked "¿cómo la llamo?", a person answers with a bare name about half
# the time and with one of these ordinary sentences the other half.
# Handling them here — rather than sending "me-llamo-marta" straight to
# `id_desde_nombre`, which folds spaces out of nothing and refuses the
# whole sentence as a person id — is what lets "me llamo Marta" and "soy
# Marta" register exactly as "Marta" would. What genuinely does not
# survive `id_desde_nombre` (an unintelligible answer, silence) is still
# refused after this: this only strips the CARRIER phrase, it does not
# invent a name that was not said.
_PREFIJOS_NOMBRE = re.compile(
    r"^\s*(?:me\s+llamo|mi\s+nombre\s+es|soy)\s+(.+)$", re.IGNORECASE
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

_TEXTO_PIDE_PRIMERA_MUESTRA = "Dígame algo, lo que quiera, para conocer su voz."

_TEXTO_PIDE_UNA_MUESTRA_MAS = "Dígame algo más."

_TEXTO_MUESTRA_NO_SERVIDA = "Esa no la he oído bien. Dígame algo más, cuando quiera."

_TEXTO_PIDE_NOMBRE = "Ya la conozco. ¿Cómo la llamo?"

_TEXTO_NOMBRE_INVALIDO = "Ese nombre no me sirve. Dígame otro."

_TEXTO_PIDE_NOMBRE_DE_NUEVO = "Entonces, ¿cómo se llama?"

_TEXTO_EMPAREJAR_FALLIDO = (
    "No he podido completarlo: puede que esta casa ya tenga dueño. No voy a insistir."
)


def _texto_tras_borrado(resultado: borrar.Resultado) -> str:
    """What he says once the wipe has actually run — honest about
    whether it fully succeeded, per `resultado.completo`, and never
    assumed from the fact that nothing raised. See `borrar.ejecutar`'s
    own docstring: `-> None` used to make a partial failure invisible
    here, exactly the case that matters (a previous owner's `teacher/`
    or `personas.json` surviving on disk) — this is the branch that
    closes it.
    """
    prefijo = (
        _TEXTO_BORRADO_COMPLETO_PREFIJO
        if resultado.completo
        else _TEXTO_BORRADO_PARCIAL_PREFIJO
    )
    return f"{prefijo} {_TEXTO_PIDE_PRIMERA_MUESTRA}"


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
    """What he says, and whether this is the last thing he will say."""

    habla: str
    terminado: bool = False


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
            self.estado = Estado.BORRANDO
            return Respuesta(habla=_TEXTO_ANUNCIO_BORRADO, terminado=False)
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
        # kiosk (CLAUDE.md §1.5), not what he is.
        if not self._saludado:
            self._saludado = True
            return Respuesta(habla=_TEXTO_SALUDO_INICIAL, terminado=False)
        return Respuesta(habla=_TEXTO_RECORDATORIO_ESPERA, terminado=False)

    # --- BORRANDO ------------------------------------------------------

    def _en_borrando(self, texto: str) -> Respuesta:
        if not parecida(texto, CONFIRMACION_BORRADO):
            # Wrong answer -> the previous state, with something to
            # say. Nothing has been touched: the passphrase (still
            # unconsumed outside this module) said again reopens
            # `BORRANDO` from the top.
            self.estado = Estado.ESPERANDO
            return Respuesta(habla=_TEXTO_BORRADO_CANCELADO, terminado=False)

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
        return Respuesta(habla=_texto_tras_borrado(resultado), terminado=False)

    # --- PIDIENDO --------------------------------------------------------

    def _en_pidiendo(self, texto: str, vector: "np.ndarray | None") -> Respuesta:
        if len(self._muestras) < self._n_muestras:
            if _vector_usable(vector):
                self._muestras.append(vector)
            if len(self._muestras) < self._n_muestras:
                habla = (
                    _TEXTO_PIDE_UNA_MUESTRA_MAS
                    if _vector_usable(vector)
                    else _TEXTO_MUESTRA_NO_SERVIDA
                )
                return Respuesta(habla=habla, terminado=False)
            return Respuesta(habla=_TEXTO_PIDE_NOMBRE, terminado=False)

        # Enough samples already: this utterance is the candidate name,
        # said plainly or wrapped in "me llamo…" / "soy…" / "…, a secas".
        nombre = _nombre_desde_texto(texto)
        if id_desde_nombre(nombre) == CASA:
            return Respuesta(habla=_TEXTO_NOMBRE_INVALIDO, terminado=False)
        self._nombre_candidato = nombre
        self.estado = Estado.CONFIRMANDO
        return Respuesta(habla=_texto_confirma_nombre(nombre), terminado=False)

    # --- CONFIRMANDO -----------------------------------------------------

    def _en_confirmando(self, texto: str) -> Respuesta:
        if _es_negativo(texto):
            # Wrong answer -> the previous state ("asking"), with
            # something to say. The samples already gathered are kept;
            # only the name is asked again.
            self.estado = Estado.PIDIENDO
            return Respuesta(habla=_TEXTO_PIDE_NOMBRE_DE_NUEVO, terminado=False)

        if not _es_afirmativo(texto):
            # Neither a yes nor a no: repeat the question rather than
            # guess. Still `CONFIRMANDO`, still something to say.
            assert self._nombre_candidato is not None
            return Respuesta(
                habla=_texto_confirma_nombre(self._nombre_candidato),
                terminado=False,
            )

        assert self._nombre_candidato is not None
        try:
            persona = self._registro.emparejar(self._nombre_candidato, self._muestras)
        except (ValueError, OSError) as exc:
            # An amo already exists (a race lost against another
            # pairing attempt), the register is unreadable, or the
            # voiceprint could not be written. None of this is
            # recoverable by trying the same name again, so back to
            # `ESPERANDO` — where, if a house now exists, the security
            # check above makes the passphrase inert anyway.
            logger.warning(f"encuentro: emparejar failed — {exc!r}")
            self.estado = Estado.ESPERANDO
            return Respuesta(habla=_TEXTO_EMPAREJAR_FALLIDO, terminado=False)

        self.estado = Estado.HECHO
        return Respuesta(habla=_texto_bienvenida(persona.nombre), terminado=True)
