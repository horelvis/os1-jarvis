"""The one place a person id is made, and the one place `casa` comes from."""

import pathlib
import re

import pytest

from jarvis_widget.personas import CASA, es_valida, id_desde_nombre, normalizar


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


def test_id_desde_nombre_strips_diacritics_that_normalizar_would_refuse():
    # A NAME, not a chat_id off the wire — most names in this house have
    # an accent, and `normalizar` alone would send every one of them to
    # CASA (see test_a_name_is_folded_and_trimmed above).
    assert id_desde_nombre("Lucía") == "lucia"
    assert id_desde_nombre("Martín") == "martin"
    assert id_desde_nombre("José") == "jose"
    assert id_desde_nombre("Papá") == "papa"


def test_id_desde_nombre_still_refuses_a_name_that_survives_to_nothing():
    # Stripping diacritics does not rescue a name that was never a name
    # to begin with — the founding act must still refuse these exactly
    # as `normalizar` refuses them on its own.
    assert id_desde_nombre("!!!") == CASA
    assert id_desde_nombre("...") == CASA
    assert id_desde_nombre("") == CASA


def test_id_desde_nombre_does_not_change_what_normalizar_does_with_a_chat_id():
    # The one thing this function must NOT do is quietly become a second
    # way to reach `normalizar`'s job: an accented chat_id off the phone
    # socket still folds to CASA through `normalizar` itself, unchanged.
    assert normalizar("Lucía") == CASA


def test_id_desde_nombre_non_string_input_is_casa():
    assert id_desde_nombre(123) == CASA
    assert id_desde_nombre(None) == CASA


def test_id_desde_nombre_folds_more_than_accents():
    # Disclosed, not hidden (see the function's own docstring): NFKD is
    # COMPATIBILITY decomposition, not accent-stripping. `ñ` is not "n
    # with a mark" the way `á` is, yet it still folds to `n` — and so do
    # symbols with no accent involved at all. This is the trade that
    # makes the founding act possible for names like `Begoña` and
    # `Ñoño`, not a bug to "fix" by switching to NFD.
    assert id_desde_nombre("Begoña") == "begona"
    assert id_desde_nombre("Ñoño") == "nono"
    assert id_desde_nombre("™") == "tm"
    assert id_desde_nombre("Ⅷ") == "viii"


def test_id_desde_nombre_folds_an_accented_and_unaccented_spelling_together():
    # The disclosed collision, spelled out: this is not two different
    # people who happen to share an id, it is the SAME id on purpose —
    # a visible, recoverable collision (refused at the ordinary "id
    # already taken" path) traded deliberately against the amo being
    # unable to say his own name (see the function's own docstring).
    assert id_desde_nombre("Adrián") == id_desde_nombre("Adrian") == "adrian"


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
