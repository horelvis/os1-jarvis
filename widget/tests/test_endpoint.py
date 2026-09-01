"""Whether a partial transcript reads as a finished thought.

Every case here was measured on 2026-09-01 against the user's own voice
(the spec has the traces). Vosk emits no punctuation at all, so the only
signal available is the last word — which is why the word list IS the
rule, and why it is tested this heavily.
"""

import pytest

# VoskPartials and load_partials are unused until Task 3 completes the
# module; imported now so the import line does not have to change later.
from samantha_widget.endpoint import (  # noqa: F401
    CompletionRule,
    VoskPartials,
    load_partials,
)


@pytest.fixture
def rule() -> CompletionRule:
    return CompletionRule()


@pytest.mark.parametrize(
    "partial",
    [
        # Measured: the mid-sentence pause Whisper punctuated into a
        # clean sentence and Vosk left hanging. The user was not done.
        "ahora mismo las dos camaras habra que comprobar que esten encendidas y",
        "hola ya veis que pueda se",
        "enciendeme la luz del",
        "manana tengo que",
        "ponme una alarma para las",
    ],
)
def test_a_thought_still_in_flight_waits(rule: CompletionRule, partial: str) -> None:
    assert rule.looks_complete(partial) is False


@pytest.mark.parametrize(
    "partial",
    [
        # Measured: the true end of the same recording.
        "de otro proveedor que no son las que habia antes",
        "hola ya veis que puedas en madrid en las ultimas veinticuatro horas",
        "enciendeme la luz del salon",
        "apaga la luz",
    ],
)
def test_a_finished_thought_closes(rule: CompletionRule, partial: str) -> None:
    assert rule.looks_complete(partial) is True


@pytest.mark.parametrize("partial", ["que hora es", "dame mas", "creo que no"])
def test_words_that_can_end_a_sentence_are_not_dangling(
    rule: CompletionRule, partial: str
) -> None:
    """The regression the spec names.

    The spike's first draft put `es` in the list, so "¿qué hora es?"
    could never close early. That costs no cut — the 1.2 s fallback
    still fires — but it silently forfeits the gain on one of the
    commonest question forms. Only words that CANNOT end a sentence
    belong in the list.
    """
    assert rule.looks_complete(partial) is True


def test_too_few_words_is_never_complete(rule: CompletionRule) -> None:
    assert rule.looks_complete("hola") is False


def test_empty_is_never_complete(rule: CompletionRule) -> None:
    assert rule.looks_complete("") is False
    assert rule.looks_complete("   ") is False


def test_accents_separate_a_question_from_a_conjunction(
    rule: CompletionRule,
) -> None:
    """`que` cannot end a sentence; `qué` can. Same for como/cómo.

    Whisper writes the accent and Vosk does not, so this matters mostly
    for the tests — but folding accents away would put `qué` into the
    dangling set and lose "no sé qué".
    """
    assert rule.looks_complete("no se que") is False
    assert rule.looks_complete("no se que hacer") is True
