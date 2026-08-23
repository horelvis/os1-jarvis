"""What we do with what Whisper says.

The model itself is not tested here — it needs a GPU and 1.5 GB of
weights. What IS tested is the part that bites: Whisper hallucinates
politeness into silence, and a strip that is always listening meets
that failure hundreds of times a day.
"""

from samantha_widget.stt import Transcriber, clean


def test_whitespace_is_trimmed() -> None:
    assert clean("  hola  ") == "hola"


def test_a_hallucinated_thank_you_is_dropped() -> None:
    """Whisper's favourite output for near-silence, in Spanish and English."""
    for phrase in (
        "Gracias.",
        "gracias por ver el video",
        "Subtítulos realizados por la comunidad de Amara.org",
        "Thank you.",
        "¡Suscríbete al canal!",
    ):
        assert clean(phrase) == "", phrase


def test_a_real_sentence_containing_gracias_survives() -> None:
    assert clean("Gracias, pero prefiero quedarme en casa") != ""


def test_an_empty_transcription_stays_empty() -> None:
    assert clean("") == ""
    assert clean("   ") == ""


def test_transcriber_is_not_ready_before_load() -> None:
    """The strip appears immediately and simply cannot hear for a while."""
    assert Transcriber().ready is False


def test_transcribing_before_load_returns_nothing_rather_than_raising() -> None:
    """A turn during startup is lost, not fatal."""
    assert Transcriber().transcribe(b"\x00\x00" * 16000) == ""
