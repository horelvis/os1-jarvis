"""Whether a partial transcript reads as a finished thought.

Every case here was measured on 2026-09-01 against the user's own voice
(the spec has the traces). Vosk emits no punctuation at all, so the only
signal available is the last word — which is why the word list IS the
rule, and why it is tested this heavily.
"""

from pathlib import Path

import pytest

from samantha_widget.endpoint import (
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

    Both engines write the accent, and the accent is what separates
    `que` from `qué` and `se` from `sé` — which is why the word list
    keeps the unaccented forms only and never folds accents away.
    """
    assert rule.looks_complete("no se que") is False
    assert rule.looks_complete("no se que hacer") is True


def test_the_accented_verb_can_end_a_sentence(rule: CompletionRule) -> None:
    """`se` (pronoun) cannot end a sentence; `sé` (verb) can, and Vosk
    writes the accent — measured on this box, 2026-09-01."""
    assert rule.looks_complete("no lo sé") is True
    assert rule.looks_complete("hola ya veis que pueda se") is False


def test_a_missing_model_is_reported_not_raised(tmp_path, monkeypatch) -> None:
    """Failure here must cost the FEATURE, never the widget.

    2026-08-30 is the precedent: a model that would not fit left Whisper
    unable to load, the exception was caught and printed, and JARVIS was
    deaf for three days looking perfectly healthy. A thing whose whole
    purpose is making him faster must not be able to make him worse.
    """
    monkeypatch.setenv("SAMANTHA_WIDGET_VOSK_MODEL", str(tmp_path / "nope"))

    assert load_partials() is None


def test_the_model_path_can_be_overridden(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SAMANTHA_WIDGET_VOSK_MODEL", str(tmp_path / "nope"))
    with pytest.raises(FileNotFoundError):
        VoskPartials()


@pytest.mark.skipif(
    not (Path.home() / ".samantha/models/vosk-model-small-es-0.42").is_dir(),
    reason="the Vosk model is not installed on this box",
)
def test_silence_transcribes_to_nothing() -> None:
    """The one test that needs the model. Silence in, nothing out —
    enough to prove the wiring without shipping any audio."""
    partials = VoskPartials()
    for _ in range(30):
        partials.turn.push(b"\x00\x00" * 512)

    assert partials.turn.partial() == ""


@pytest.mark.skipif(
    not (Path.home() / ".samantha/models/vosk-model-small-es-0.42").is_dir(),
    reason="the Vosk model is not installed on this box",
)
def test_the_two_streams_do_not_hear_each_other() -> None:
    """The property the whole split exists for: audio fed to one stream
    must not appear in the other's partial. Without it his echo lands in
    the sentence being judged for endpointing."""
    partials = VoskPartials()
    for _ in range(30):
        partials.room.push(b"\x00\x00" * 512)

    assert partials.turn.partial() == ""
    assert partials.turn is not partials.room
