"""The one place a person id is made, and the one place `casa` comes from."""

import pathlib
import re

import pytest

from jarvis_widget.personas import CASA, es_valida, normalizar


def test_casa_is_the_fallback_for_nothing_at_all():
    assert normalizar(None) == CASA
    assert normalizar("") == CASA
    assert normalizar("   ") == CASA


def test_a_name_is_folded_and_trimmed():
    assert normalizar("  Marta  ") == "marta"
    # Accented names become CASA because es_valida mirrors Hermes'
    # profile grammar, which is ASCII-only.
    assert normalizar("PAPÁ") == CASA


def test_anything_that_could_escape_a_path_or_a_key_becomes_casa():
    # A person id becomes a Hermes chat_id, a profile name and a file
    # name. Degrading to `casa` is the rule; never raise, never pass it
    # through, and never land on another person.
    for hostile in ("../papá", "a/b", "papá\n", "x" * 65, "a b"):
        assert normalizar(hostile) == CASA


def test_es_valida_agrees_with_normalizar():
    assert es_valida("marta")
    assert not es_valida("../papá")


def test_non_string_inputs_to_es_valida_return_false():
    # The type hint is a promise to readers; guarding non-strings is a
    # promise to the process. A socket handler can send a JSON number,
    # a list, or bytes without warning. None returns False, never raises.
    assert es_valida(123) is False
    assert es_valida(["a"]) is False
    assert es_valida(b"marta") is False


def test_non_string_inputs_to_normalizar_return_casa():
    # The type hint is a promise to readers; guarding non-strings is a
    # promise to the process. A socket handler or audio thread can send
    # a JSON number, a list, or bytes without warning. All degrade to
    # CASA, never raise.
    assert normalizar(123) == CASA
    assert normalizar(["a"]) == CASA
    assert normalizar(b"marta") == CASA


def test_the_grammar_is_hermes_own_profile_grammar():
    # Read from the live vendored source rather than copying the
    # pattern: a copy only catches OUR drift, and the drift that
    # actually breaks routing in silence is HERMES changing its
    # grammar under us on a vendor update.
    fuente = (
        pathlib.Path(__file__).resolve().parents[2]
        / ".hermes/src/hermes_cli/profiles.py"
    )
    if not fuente.is_file():
        pytest.skip("el árbol vendorizado de Hermes no está en esta caja")
    encontrado = re.search(
        r"_PROFILE_ID_RE = re\.compile\(r\"(.+?)\"\)", fuente.read_text()
    )
    assert encontrado, "no se encuentra _PROFILE_ID_RE en profiles.py"
    hermes = re.compile(encontrado.group(1))
    for candidato in (
        "marta",
        "lucia",
        "papa",
        "casa",
        "a-b_c",
        "x9",
        "Marta",
        "lucía",
        "-x",
        "",
        "a" * 65,
    ):
        assert es_valida(candidato) == bool(hermes.match(candidato))
