"""The first conversation this project has ever had, driven from tests.

No audio, no GTK, no clock: `Encuentro.oye()` is handed a transcript and
a voice vector directly. `_avanzar_*` helpers walk the flow up to a
given state, using tiny fixed vectors instead of real voiceprints.
"""

import os
from pathlib import Path

import numpy as np
import pytest

from jarvis_widget import casa
from jarvis_widget.bienvenida import NECESIDAD
from jarvis_widget.encuentro import (
    CONFIRMACION_BORRADO,
    ROTULO_ESPERANDO,
    Encuentro,
    Estado,
    Respuesta,
)

FRASE = "gato ventana lento roble"


def _v(*xs: float) -> np.ndarray:
    return np.array(xs, dtype=np.float32)


def _roots(tmp_path: Path) -> dict:
    return {
        "raiz_jarvis": tmp_path / "jarvis",
        "raiz_hermes": tmp_path / "hermes",
        "respaldo": tmp_path / "respaldo",
    }


def _nuevo(tmp_path: Path, *, n_muestras: int = 2) -> tuple[Encuentro, casa.Registro]:
    registro = casa.Registro(tmp_path / "casa.json")
    enc = Encuentro(registro, FRASE, n_muestras=n_muestras, **_roots(tmp_path))
    return enc, registro


def _hasta_borrando(tmp_path: Path, **kwargs) -> tuple[Encuentro, casa.Registro]:
    enc, registro = _nuevo(tmp_path, **kwargs)
    r = enc.oye(FRASE)
    assert enc.estado is Estado.BORRANDO
    assert r is not None
    return enc, registro


def _hasta_pidiendo(tmp_path: Path, **kwargs) -> tuple[Encuentro, casa.Registro]:
    enc, registro = _hasta_borrando(tmp_path, **kwargs)
    enc.oye(CONFIRMACION_BORRADO)
    assert enc.estado is Estado.PIDIENDO
    return enc, registro


def _hasta_confirmando(
    tmp_path: Path, *, nombre: str = "Marta", n_muestras: int = 2
) -> tuple[Encuentro, casa.Registro]:
    enc, registro = _hasta_pidiendo(tmp_path, n_muestras=n_muestras)
    vector = _v(1.0, 0.0, 0.0)
    for _ in range(n_muestras):
        enc.oye("una frase cualquiera", vector)
    assert enc.estado is Estado.PIDIENDO  # still asking, now for the name
    r = enc.oye(nombre)
    assert enc.estado is Estado.CONFIRMANDO
    assert nombre in r.habla
    return enc, registro


# --- ESPERANDO -------------------------------------------------------------


def test_nothing_but_the_passphrase_leaves_esperando(tmp_path):
    enc, _registro = _nuevo(tmp_path)

    # A stranger's talk is answered (greeted), but it does not advance.
    assert enc.oye("hola, buenos días") is not None
    assert enc.estado is Estado.ESPERANDO

    # True silence stays silence — nothing was actually said.
    assert enc.oye("") is None
    assert enc.estado is Estado.ESPERANDO


def test_a_stranger_talking_is_answered_without_advancing(tmp_path):
    enc, _registro = _nuevo(tmp_path)

    r = enc.oye("qué tal, cómo estás por aquí")

    assert r is not None and r.habla
    assert enc.estado is Estado.ESPERANDO


def test_the_first_stranger_utterance_is_greeted_and_told_why_he_cannot_help(
    tmp_path,
):
    enc, _registro = _nuevo(tmp_path)

    r = enc.oye("¿qué hora es?")

    assert r is not None
    assert enc.estado is Estado.ESPERANDO
    habla = r.habla.casefold()
    # A greeting, and the fact that nothing else is possible yet.
    assert "buenas" in habla
    assert "casa" in habla
    # Never a threat about erasing memory — that belongs after the
    # passphrase, where there is a confirmation to give.
    assert "borra" not in habla
    assert "memoria" not in habla
    assert "olvid" not in habla


def test_a_later_stranger_utterance_gets_a_shorter_reminder_not_the_greeting_again(
    tmp_path,
):
    enc, _registro = _nuevo(tmp_path)

    primera = enc.oye("¿qué hora es?")
    segunda = enc.oye("hola, hay alguien ahí")

    assert enc.estado is Estado.ESPERANDO
    assert segunda is not None and segunda.habla
    # Not the same paragraph twice — the second answer is shorter and
    # different text, never a repeat of the full greeting.
    assert segunda.habla != primera.habla
    assert len(segunda.habla) < len(primera.habla)
    assert "borra" not in segunda.habla.casefold()
    assert "memoria" not in segunda.habla.casefold()

    # And it keeps being the short reminder on a third stray utterance,
    # not escalating or reverting to the long one.
    tercera = enc.oye("perdona, no te entiendo")
    assert tercera is not None
    assert tercera.habla == segunda.habla


def test_the_passphrase_still_works_after_a_greeting(tmp_path):
    enc, _registro = _nuevo(tmp_path)

    enc.oye("hola")
    assert enc.estado is Estado.ESPERANDO

    r = enc.oye(FRASE)

    assert enc.estado is Estado.BORRANDO
    assert r is not None


def test_the_passphrase_advances_esperando_to_borrando(tmp_path):
    enc, _registro = _nuevo(tmp_path)

    r = enc.oye(FRASE)

    assert enc.estado is Estado.BORRANDO
    assert isinstance(r, Respuesta)
    assert r.habla
    assert not r.terminado
    # The band shows what BORRANDO is waiting for, immediately — never
    # the spent passphrase for one more turn.
    assert r.lectura == CONFIRMACION_BORRADO


def test_esperando_shows_the_passphrase_on_the_band_while_it_waits(tmp_path):
    enc, _registro = _nuevo(tmp_path)

    saludo = enc.oye("hola")
    recordatorio = enc.oye("hola de nuevo")

    assert saludo.lectura == FRASE
    assert recordatorio.lectura == FRASE


def test_borrando_returns_to_showing_the_passphrase_on_a_wrong_answer(tmp_path):
    enc, _registro = _hasta_borrando(tmp_path)

    r = enc.oye("esto no es la confirmación")

    assert enc.estado is Estado.ESPERANDO
    assert r.lectura == FRASE


def test_the_phrase_read_with_filler_still_advances(tmp_path):
    # `frase.parecida` tolerates a "vale" read off the screen — the
    # same tolerance the passphrase itself was designed for.
    enc, _registro = _nuevo(tmp_path)

    enc.oye("vale, gato ventana lento roble, ya está")

    assert enc.estado is Estado.BORRANDO


def test_the_passphrase_advances_once_and_not_twice(tmp_path):
    enc, _registro = _nuevo(tmp_path)

    enc.oye(FRASE)
    assert enc.estado is Estado.BORRANDO

    # Said again: dispatch is by CURRENT state, so this reaches
    # BORRANDO's handler and is checked against the wipe confirmation,
    # not the passphrase. It does not match, so it does NOT skip ahead
    # to PIDIENDO.
    r2 = enc.oye(FRASE)

    assert enc.estado is not Estado.PIDIENDO
    assert enc.estado is Estado.ESPERANDO
    assert r2 is not None and r2.habla


def test_the_passphrase_does_nothing_once_an_amo_exists(tmp_path):
    registro = casa.Registro(tmp_path / "casa.json")
    registro.emparejar("Marta", [_v(1.0, 0.0, 0.0)])
    enc = Encuentro(registro, FRASE, **_roots(tmp_path))

    r = enc.oye(FRASE)

    assert r is None
    assert enc.estado is Estado.ESPERANDO
    # And the existing amo is untouched.
    assert registro.amo == "marta"


# --- BORRANDO ----------------------------------------------------------


def test_borrando_announces_the_wipe_before_it_happens(tmp_path):
    raiz_jarvis = tmp_path / "jarvis"
    raiz_jarvis.mkdir()
    (raiz_jarvis / "personas.json").write_text("familia anterior")

    _hasta_borrando(tmp_path)

    # Announced, not yet erased: the file from the previous family is
    # still there until the confirmation is heard.
    assert (raiz_jarvis / "personas.json").exists()


def test_a_bare_yes_does_not_confirm_the_wipe(tmp_path):
    # The wipe's confirmation cannot be given by accident: a bare "sí"
    # — the word a room says about almost anything — is not enough.
    enc, _registro = _hasta_borrando(tmp_path)

    r = enc.oye("sí")

    assert enc.estado is Estado.ESPERANDO
    assert r is not None and r.habla


def test_the_exact_confirmation_phrase_confirms_the_wipe(tmp_path):
    enc, _registro = _hasta_borrando(tmp_path)

    r = enc.oye(CONFIRMACION_BORRADO)

    assert enc.estado is Estado.PIDIENDO
    assert r is not None and r.habla


def test_the_confirmation_phrase_with_filler_still_confirms(tmp_path):
    enc, _registro = _hasta_borrando(tmp_path)

    enc.oye(f"bueno, {CONFIRMACION_BORRADO}, vale")

    assert enc.estado is Estado.PIDIENDO


def test_a_wrong_answer_in_borrando_returns_to_esperando_and_erases_nothing(tmp_path):
    raiz_jarvis = tmp_path / "jarvis"
    raiz_jarvis.mkdir()
    objetivo = raiz_jarvis / "personas.json"
    objetivo.write_text("familia anterior")

    enc, _registro = _hasta_borrando(tmp_path)
    enc.oye("no sé de qué me hablas")

    assert enc.estado is Estado.ESPERANDO
    assert objetivo.exists()
    assert objetivo.read_text() == "familia anterior"

    # And saying the passphrase again reopens BORRANDO from the top.
    r = enc.oye(FRASE)
    assert enc.estado is Estado.BORRANDO
    assert r is not None


def test_confirming_the_wipe_actually_erases_what_borrar_lists(tmp_path):
    raiz_jarvis = tmp_path / "jarvis"
    raiz_hermes = tmp_path / "hermes"
    raiz_jarvis.mkdir()
    raiz_hermes.mkdir()
    (raiz_jarvis / "personas.json").write_text("familia anterior")
    (raiz_hermes / "state.db").write_bytes(b"sesion vieja")

    enc, _registro = _hasta_borrando(tmp_path)
    enc.oye(CONFIRMACION_BORRADO)

    assert not (raiz_jarvis / "personas.json").exists()
    assert not (raiz_hermes / "state.db").exists()


# --- PIDIENDO ------------------------------------------------------------


def test_a_partial_wipe_is_reported_honestly_not_claimed_as_clean(tmp_path):
    """Mirrors `test_borrar.py`'s own proof that `ejecutar` reports a
    node it could not remove: this is the test that the STATE MACHINE
    actually reads `Resultado.completo` rather than assuming success
    because `ejecutar` did not raise."""
    raiz_jarvis = tmp_path / "jarvis"
    raiz_hermes = tmp_path / "hermes"
    raiz_jarvis.mkdir()
    raiz_hermes.mkdir()
    intocable = raiz_jarvis / "teacher"
    intocable.mkdir()
    (intocable / "curso.json").write_text("{}")

    modo_original = os.stat(intocable).st_mode
    canario = intocable / "canario"
    canario.write_text("")
    try:
        os.chmod(intocable, 0o500)
        try:
            canario.unlink()
            pytest.skip("this environment does not enforce permission bits on removal")
        except PermissionError:
            pass

        enc, _registro = _hasta_borrando(tmp_path)
        r = enc.oye(CONFIRMACION_BORRADO)
    finally:
        os.chmod(intocable, modo_original)

    assert enc.estado is Estado.PIDIENDO
    assert r is not None and r.habla
    # He says, in his own words, that it is NOT entirely done — never
    # the same sentence he'd use for a clean wipe ("no queda nada de
    # antes" would be a lie here).
    assert "no queda nada" not in r.habla.casefold()
    assert "sigue en el disco" in r.habla.casefold()


def test_pidiendo_shows_a_reading_before_the_first_sample(tmp_path):
    enc, _registro = _hasta_borrando(tmp_path, n_muestras=3)

    r = enc.oye(CONFIRMACION_BORRADO)

    assert enc.estado is Estado.PIDIENDO
    assert r is not None
    assert r.lectura is not None and r.lectura.strip()
    assert "primera de tres" in r.habla.casefold()


def test_pidiendo_offers_a_different_reading_for_each_new_sample(tmp_path):
    enc, _registro = _hasta_pidiendo(tmp_path, n_muestras=3)
    vector = _v(1.0, 0.0, 0.0)

    # Each response asks for the NEXT slot: after the 1st accepted
    # sample, he is asking for the 2nd reading; after the 2nd, the 3rd.
    tras_primera = enc.oye("una frase", vector)
    assert enc.estado is Estado.PIDIENDO
    tras_segunda = enc.oye("otra frase", vector)
    assert enc.estado is Estado.PIDIENDO

    assert tras_primera.lectura is not None
    assert tras_segunda.lectura is not None
    assert tras_primera.lectura != tras_segunda.lectura
    assert "segunda de tres" in tras_primera.habla.casefold()
    assert "tercera de tres" in tras_segunda.habla.casefold()


def test_a_refused_sample_says_why_and_keeps_the_same_reading(tmp_path):
    enc, _registro = _hasta_pidiendo(tmp_path, n_muestras=3)

    primera = enc.oye("algo dicho", None)  # no vector: refused

    assert enc.estado is Estado.PIDIENDO
    assert primera is not None
    assert "no he cogido bastante" in primera.habla.casefold()
    # Still the FIRST reading — nothing was recorded, so the slot (and
    # its passage) has not advanced.
    assert "primera de tres" in primera.habla.casefold()

    otra_vez = enc.oye("algo dicho de nuevo", None)
    assert primera.lectura == otra_vez.lectura


def test_the_reading_count_advances_correctly_through_every_slot(tmp_path):
    enc, _registro = _hasta_pidiendo(tmp_path, n_muestras=3)
    vector = _v(1.0, 0.0, 0.0)

    # `_hasta_pidiendo` already consumed the "primera de tres" ask (the
    # transition out of `BORRANDO`); from here, each accepted sample
    # asks for the NEXT slot.
    r1 = enc.oye("frase uno", vector)
    assert "segunda de tres" in r1.habla.casefold()
    r2 = enc.oye("frase dos", vector)
    assert "tercera de tres" in r2.habla.casefold()
    r3 = enc.oye("frase tres", vector)
    # The third accepted sample reaches the floor: no more readings,
    # he moves on to asking for a name.
    assert enc.estado is Estado.PIDIENDO
    assert r3.lectura is None
    assert "cómo le llamo" in r3.habla.casefold()


def test_pidiendo_counts_only_usable_vectors(tmp_path):
    enc, _registro = _hasta_pidiendo(tmp_path, n_muestras=3)
    vector = _v(1.0, 0.0, 0.0)

    # A vector of None (nothing could be embedded) does not count.
    r1 = enc.oye("algo dicho", None)
    assert enc.estado is Estado.PIDIENDO
    assert r1 is not None and r1.habla

    enc.oye("una frase", vector)
    assert enc.estado is Estado.PIDIENDO

    enc.oye("otra frase", vector)
    assert enc.estado is Estado.PIDIENDO  # only 2 usable so far, need 3

    r4 = enc.oye("una más", vector)
    # The third USABLE sample reaches the floor and he asks for a name.
    assert enc.estado is Estado.PIDIENDO
    assert "nombre" in r4.habla.casefold() or "llamo" in r4.habla.casefold()


def test_pidiendo_refuses_a_name_that_does_not_survive_id_desde_nombre(tmp_path):
    enc, _registro = _hasta_pidiendo(tmp_path, n_muestras=1)
    vector = _v(1.0, 0.0, 0.0)
    enc.oye("una frase", vector)
    assert enc.estado is Estado.PIDIENDO

    r = enc.oye("!!!")

    assert enc.estado is Estado.PIDIENDO
    assert isinstance(r, Respuesta)
    assert r.habla
    # Every string he says is Spanish.
    assert "not" not in r.habla.casefold().split()


def test_pidiendo_accepts_an_accented_name(tmp_path):
    enc, _registro = _hasta_pidiendo(tmp_path, n_muestras=1)
    vector = _v(1.0, 0.0, 0.0)
    enc.oye("una frase", vector)

    r = enc.oye("Lucía")

    assert enc.estado is Estado.CONFIRMANDO
    assert "Lucía" in r.habla


@pytest.mark.parametrize(
    "respuesta",
    [
        "Marta",
        "me llamo Marta",
        "Me llamo Marta.",
        "soy Marta",
        "Marta, a secas",
        "puedes llamarme Marta",
        "Puedes llamarme Marta.",
        "llámame Marta",
        "llamame Marta",
    ],
)
def test_pidiendo_extracts_the_name_from_ordinary_spanish_answers(tmp_path, respuesta):
    enc, _registro = _hasta_pidiendo(tmp_path, n_muestras=1)
    vector = _v(1.0, 0.0, 0.0)
    enc.oye("una frase", vector)

    r = enc.oye(respuesta)

    assert enc.estado is Estado.CONFIRMANDO
    assert "Marta" in r.habla

    enc.oye("sí")
    assert enc.estado is Estado.HECHO
    assert _registro.amo == "marta"


def test_pidiendo_still_refuses_what_does_not_survive_after_extraction(tmp_path):
    enc, _registro = _hasta_pidiendo(tmp_path, n_muestras=1)
    vector = _v(1.0, 0.0, 0.0)
    enc.oye("una frase", vector)

    r = enc.oye("me llamo !!!")

    assert enc.estado is Estado.PIDIENDO
    assert r is not None and r.habla


def test_an_unrecognised_word_still_needs_an_explicit_confirmation(tmp_path):
    """The conclusion on "should a single unrecognised word need
    confirmation rather than acceptance": it already does. Every
    candidate — a real name or Whisper's garble of one ("Salvis") —
    goes through `CONFIRMANDO`'s explicit yes before `emparejar` is
    ever called; a "no" here refuses it without founding anything."""
    enc, registro = _hasta_pidiendo(tmp_path, n_muestras=1)
    enc.oye("una frase", _v(1.0, 0.0, 0.0))

    r = enc.oye("Salvis")

    assert enc.estado is Estado.CONFIRMANDO
    assert registro.amo is None
    assert "Salvis" in r.habla
    assert r.lectura == "Salvis"

    enc.oye("no")

    assert enc.estado is Estado.PIDIENDO
    assert registro.amo is None


# --- CONFIRMANDO -----------------------------------------------------------


def test_pidiendo_asks_for_a_name_without_gendering_the_person(tmp_path):
    # This house has a father and two daughters; the amo is whoever
    # says the phrase, so nothing here may guess a gender before he
    # even has a name.
    enc, _registro = _hasta_pidiendo(tmp_path, n_muestras=1)

    r = enc.oye("una frase", _v(1.0, 0.0, 0.0))

    assert enc.estado is Estado.PIDIENDO
    habla = r.habla.casefold()
    assert "cómo la llamo" not in habla
    assert "cómo lo llamo" not in habla


def test_confirmando_recovers_if_the_candidate_name_is_somehow_missing(tmp_path):
    """Pins the defensive branch that replaced an `assert`: unreachable
    through the public API today (`CONFIRMANDO` is only entered right
    after `_nombre_candidato` is set), but `python -O` strips asserts,
    and `oye()`'s contract is that it never raises."""
    enc, registro = _hasta_confirmando(tmp_path, nombre="Marta")
    enc._nombre_candidato = None  # force the broken invariant by hand

    r = enc.oye("sí")

    assert enc.estado is Estado.ESPERANDO
    assert r is not None and r.habla
    assert registro.amo is None


def test_pidiendo_shows_the_heard_name_on_the_band_entering_confirmando(tmp_path):
    enc, _registro = _hasta_pidiendo(tmp_path, n_muestras=1)
    enc.oye("una frase", _v(1.0, 0.0, 0.0))

    r = enc.oye("Marta")

    assert enc.estado is Estado.CONFIRMANDO
    # Seeing "Marta" spelled out is worth more than hearing it — the
    # whole question is whether it was heard correctly.
    assert r.lectura == "Marta"


def test_confirmando_requires_an_affirmative(tmp_path):
    enc, _registro = _hasta_confirmando(tmp_path, nombre="Marta")

    r = enc.oye("perdona, puedes repetir eso")

    # Neither yes nor no: repeats the question, stays put, and the
    # band keeps showing the same name.
    assert enc.estado is Estado.CONFIRMANDO
    assert r is not None and r.habla
    assert r.lectura == "Marta"


def test_confirmando_no_sends_it_back_to_asking(tmp_path):
    enc, _registro = _hasta_confirmando(tmp_path, nombre="Marta")

    r = enc.oye("no")

    assert enc.estado is Estado.PIDIENDO
    assert r is not None and r.habla
    assert _registro.amo is None
    # Nothing to read while a new name is asked for.
    assert r.lectura is None


def test_confirmando_si_finishes_and_the_register_has_an_amo(tmp_path):
    enc, registro = _hasta_confirmando(tmp_path, nombre="Marta")

    r = enc.oye("sí")

    assert enc.estado is Estado.HECHO
    assert r is not None
    assert r.terminado is True
    assert "Marta" in r.habla
    assert registro.amo == "marta"
    assert registro.personas()[0].nombre == "Marta"
    # HECHO: the band is done.
    assert r.lectura is None


def test_a_name_rejected_by_no_can_be_corrected(tmp_path):
    enc, registro = _hasta_confirmando(tmp_path, nombre="Equivocado")
    enc.oye("no")
    assert enc.estado is Estado.PIDIENDO

    r = enc.oye("Marta")
    assert enc.estado is Estado.CONFIRMANDO
    assert "Marta" in r.habla

    enc.oye("sí")
    assert enc.estado is Estado.HECHO
    assert registro.amo == "marta"


def test_emparejar_failing_sends_it_back_to_esperando_without_raising(tmp_path):
    # A race lost against another pairing: an amo already exists by the
    # time the affirmative arrives.
    enc, registro = _hasta_confirmando(tmp_path, nombre="Marta")
    registro.emparejar("Otro", [_v(0.0, 1.0, 0.0)])

    r = enc.oye("sí")

    assert enc.estado is Estado.ESPERANDO
    assert r is not None and r.habla
    assert registro.amo == "otro"


# --- oye() never raises, whatever it is handed ------------------------------


@pytest.mark.parametrize(
    "texto,vector",
    [
        (None, None),
        ("", None),
        (123, None),
        ("algo", "no soy un vector"),
    ],
)
def test_oye_never_raises_on_malformed_input(tmp_path, texto, vector):
    for estado_inicial in ("esperando", "borrando", "pidiendo", "confirmando"):
        raiz = tmp_path / estado_inicial
        raiz.mkdir()
        if estado_inicial == "esperando":
            enc, _registro = _nuevo(raiz)
        elif estado_inicial == "borrando":
            enc, _registro = _hasta_borrando(raiz)
        elif estado_inicial == "pidiendo":
            enc, _registro = _hasta_pidiendo(raiz)
        else:
            enc, _registro = _hasta_confirmando(raiz)
        enc.oye(texto, vector)  # must not raise


def test_hecho_answers_nothing_further(tmp_path):
    enc, _registro = _hasta_confirmando(tmp_path, nombre="Marta")
    enc.oye("sí")
    assert enc.estado is Estado.HECHO

    r = enc.oye("hola de nuevo")

    assert r is None
    assert enc.estado is Estado.HECHO


# ── the band's HEADER, not only its phrase ────────────────────────────
#
# The half of the owner's own bug that the `lectura` round left open:
# the two small lines above the phrase were a fixed constant
# ("Hasta que no la diga, no puedo hacer nada"), so the screen kept
# instructing a person to say the passphrase while the voice was asking
# them to read a passage, or asking whether their name was Orelvis.


def test_esperando_labels_the_band_with_the_welcome(tmp_path):
    enc, _registro = _nuevo(tmp_path)

    saludo = enc.oye("hola")

    assert saludo.rotulo == ROTULO_ESPERANDO
    assert NECESIDAD in saludo.rotulo


def test_every_state_that_shows_something_labels_it_differently(tmp_path):
    """No two consecutive states may leave the same header over a
    different phrase — that is exactly what made the strip contradict
    the question being asked out loud."""
    enc, _registro = _nuevo(tmp_path, n_muestras=2)
    vector = _v(1.0, 0.0, 0.0)

    esperando = enc.oye("hola")
    borrando = enc.oye(FRASE)
    pidiendo = enc.oye(CONFIRMACION_BORRADO)
    pidiendo_2 = enc.oye("una frase leída", vector)
    sin_nada = enc.oye("otra frase leída", vector)
    confirmando = enc.oye("me llamo Marta")

    # Each state that puts a phrase on the band says what the phrase is
    # for, and no two of these four say the same thing.
    rotulos = [
        esperando.rotulo,
        borrando.rotulo,
        pidiendo.rotulo,
        confirmando.rotulo,
    ]
    assert all(r is not None and r.strip() for r in rotulos)
    assert len(set(rotulos)) == 4

    # The two slots of PIDIENDO share one header: same job, same words.
    assert pidiendo.rotulo == pidiendo_2.rotulo

    # Nothing to show, nothing to label.
    assert sin_nada.lectura is None
    assert sin_nada.rotulo is None


def test_the_passphrase_instruction_never_outlives_the_passphrase(tmp_path):
    """The bug itself, pinned: past ESPERANDO, no reply may carry the
    "until you say it" line while the band shows something that is not
    the passphrase."""
    enc, _registro = _nuevo(tmp_path, n_muestras=1)
    vector = _v(1.0, 0.0, 0.0)

    respuestas = [
        enc.oye(FRASE),  # BORRANDO: the wipe confirmation
        enc.oye(CONFIRMACION_BORRADO),  # PIDIENDO: the first passage
        enc.oye("una frase leída", vector),  # PIDIENDO: asking for a name
        enc.oye("me llamo Marta"),  # CONFIRMANDO: the name heard
    ]

    for r in respuestas:
        if r.lectura != FRASE:
            assert r.rotulo != ROTULO_ESPERANDO
            assert r.rotulo is None or NECESIDAD not in r.rotulo


def test_a_cancelled_wipe_puts_the_welcome_back_over_the_passphrase(tmp_path):
    enc, _registro = _hasta_borrando(tmp_path)

    r = enc.oye("esto no es la confirmación")

    assert r.lectura == FRASE
    assert r.rotulo == ROTULO_ESPERANDO
