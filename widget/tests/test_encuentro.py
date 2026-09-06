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
from jarvis_widget.encuentro import (
    CONFIRMACION_BORRADO,
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

    assert enc.oye("hola, buenos días") is None
    assert enc.estado is Estado.ESPERANDO

    assert enc.oye("") is None
    assert enc.estado is Estado.ESPERANDO


def test_a_stranger_talking_is_answered_without_advancing(tmp_path):
    enc, _registro = _nuevo(tmp_path)

    r = enc.oye("qué tal, cómo estás por aquí")

    assert r is None
    assert enc.estado is Estado.ESPERANDO


def test_the_passphrase_advances_esperando_to_borrando(tmp_path):
    enc, _registro = _nuevo(tmp_path)

    r = enc.oye(FRASE)

    assert enc.estado is Estado.BORRANDO
    assert isinstance(r, Respuesta)
    assert r.habla
    assert not r.terminado


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


# --- CONFIRMANDO -----------------------------------------------------------


def test_confirmando_requires_an_affirmative(tmp_path):
    enc, _registro = _hasta_confirmando(tmp_path, nombre="Marta")

    r = enc.oye("perdona, puedes repetir eso")

    # Neither yes nor no: repeats the question, stays put.
    assert enc.estado is Estado.CONFIRMANDO
    assert r is not None and r.habla


def test_confirmando_no_sends_it_back_to_asking(tmp_path):
    enc, _registro = _hasta_confirmando(tmp_path, nombre="Marta")

    r = enc.oye("no")

    assert enc.estado is Estado.PIDIENDO
    assert r is not None and r.habla
    assert _registro.amo is None


def test_confirmando_si_finishes_and_the_register_has_an_amo(tmp_path):
    enc, registro = _hasta_confirmando(tmp_path, nombre="Marta")

    r = enc.oye("sí")

    assert enc.estado is Estado.HECHO
    assert r is not None
    assert r.terminado is True
    assert "Marta" in r.habla
    assert registro.amo == "marta"
    assert registro.personas()[0].nombre == "Marta"


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
