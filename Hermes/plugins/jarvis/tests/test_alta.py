"""Asking, out loud, to pair a phone — and who is allowed to.

Enrolment mints a permanent credential for a named person, and the
father's holds `terminal`. Until 2026-09-06 it required a shell on this
box (`widget/tools/enrolar.py`), which was its own gate. Asking for it
by voice removes that gate, so this module is the replacement.
"""

import json

import pytest

from Hermes.plugins.jarvis.alta import amo, hacer_alta


def _casa(tmp_path, contenido):
    ruta = tmp_path / "casa.json"
    ruta.write_text(json.dumps(contenido))
    return ruta


def test_amo_reads_the_register(tmp_path):
    ruta = _casa(tmp_path, {"amo": "orelvis", "personas": {}})

    assert amo(ruta) == "orelvis"


def test_a_house_with_no_amo_has_none(tmp_path):
    assert amo(_casa(tmp_path, {"personas": {}})) is None


def test_an_unreadable_register_is_nobody_not_everybody(tmp_path):
    """The failure that matters. If a missing or corrupt casa.json
    returned something truthy, an unreadable disk would open enrolment
    to whoever was talking."""
    assert amo(tmp_path / "no-existe.json") is None
    (tmp_path / "roto.json").write_text("{no es json")
    assert amo(tmp_path / "roto.json") is None


def test_the_amo_gets_the_window(tmp_path):
    pendiente = tmp_path / "enrolamiento.json"
    señales = []

    texto = hacer_alta(
        "Nata",
        quien="orelvis",
        casa=_casa(tmp_path, {"amo": "orelvis", "personas": {}}),
        pendiente=pendiente,
        señal=lambda: señales.append(True),
    )

    assert señales == [True]
    assert json.loads(pendiente.read_text())["persona"] == "nata"
    assert "nata" in texto.casefold()


def test_somebody_else_gets_nothing_written_and_no_signal(tmp_path):
    """Not merely a refusal: nothing may be written and no signal sent.
    A guest in the room is `casa` to the voiceprint, and `casa` asking
    must not leave a pending file behind for the NEXT signal to consume."""
    pendiente = tmp_path / "enrolamiento.json"
    señales = []

    texto = hacer_alta(
        "Nata",
        quien="casa",
        casa=_casa(tmp_path, {"amo": "orelvis", "personas": {}}),
        pendiente=pendiente,
        señal=lambda: señales.append(True),
    )

    assert señales == []
    assert not pendiente.exists()
    assert texto


def test_an_unattributable_turn_is_refused(tmp_path):
    """`quien` is None when the adapter cannot say which chat asked —
    zero open turns, or several at once. Ambiguity refuses; it never
    falls through to the amo."""
    pendiente = tmp_path / "enrolamiento.json"
    señales = []

    hacer_alta(
        "Nata",
        quien=None,
        casa=_casa(tmp_path, {"amo": "orelvis", "personas": {}}),
        pendiente=pendiente,
        señal=lambda: señales.append(True),
    )

    assert señales == []
    assert not pendiente.exists()


def test_a_name_that_cannot_be_a_person_is_refused(tmp_path):
    """`casa` is the id of an unattributable turn, not a person. Pairing
    a phone TO it would hand a credential to the one identity that means
    'nobody'."""
    pendiente = tmp_path / "enrolamiento.json"
    señales = []

    hacer_alta(
        "casa",
        quien="orelvis",
        casa=_casa(tmp_path, {"amo": "orelvis", "personas": {}}),
        pendiente=pendiente,
        señal=lambda: señales.append(True),
    )

    assert señales == []
    assert not pendiente.exists()


def test_the_pending_file_is_not_world_readable(tmp_path):
    """It names who is about to be given a credential."""
    pendiente = tmp_path / "enrolamiento.json"

    hacer_alta(
        "Nata",
        quien="orelvis",
        casa=_casa(tmp_path, {"amo": "orelvis", "personas": {}}),
        pendiente=pendiente,
        señal=lambda: None,
    )

    assert pendiente.stat().st_mode & 0o077 == 0
