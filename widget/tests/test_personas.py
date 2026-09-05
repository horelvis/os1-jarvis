"""The one place a person id is made, and the one place `casa` comes from."""

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


def test_the_grammar_is_hermes_own_profile_grammar():
    # If these ever disagree, a person gets an id that cannot be a
    # profile, and `profile_routes` stops matching in silence.
    import re

    hermes = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
    for candidato in ("marta", "lucia", "papa", "casa", "a-b_c", "x9"):
        assert es_valida(candidato) == bool(hermes.match(candidato))
    for candidato in ("Marta", "lucía", "-x", "", "a" * 65):
        assert es_valida(candidato) == bool(hermes.match(candidato))
