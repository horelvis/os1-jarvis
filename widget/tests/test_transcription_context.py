"""Conversation context reaches only its own local decoder invocation."""

from types import SimpleNamespace

from jarvis_widget.stt import Transcriber, TranscriptionContext


def test_phone_context_is_not_shared_with_other_people_or_unknown_room_speech():
    context = TranscriptionContext()
    context.remember("marta", "Buscas un puesto de consultor Alfresco.")
    context.remember("lucia", "Estamos estudiando integrales.")
    assert "Alfresco" in context.snapshot("marta")
    assert "Alfresco" not in context.snapshot("lucia")
    assert context.snapshot(None) == ""
    assert context.snapshot("unknown") == ""
    context.clear()
    assert context.snapshot("marta") == ""


def test_context_is_bounded_and_a_snapshot_survives_later_updates():
    context = TranscriptionContext(max_chars=40, max_personas=2)
    context.remember("a", "Primera frase")
    snapshot = context.snapshot("a")
    context.remember("a", "Otra frase bastante más larga que el límite de memoria")
    assert snapshot == "Primera frase"
    assert len(context.snapshot("a")) <= 40
    context.remember("b", "Segunda persona")
    context.remember("c", "Tercera persona")
    assert context.snapshot("a") == ""


def test_actual_decoder_call_gets_its_context_without_postprocessing_words():
    seen = []

    class Model:
        def transcribe(self, audio, **options):
            seen.append(options["initial_prompt"])
            return iter([SimpleNamespace(text="Hoy hace fresco.")]), None

    transcriber = Transcriber(hint="Hola Jarvis.")
    transcriber._model = Model()
    result = transcriber.transcribe(b"\x00\x01" * 100, context="Hablamos de Alfresco.")
    assert seen == ["Hola Jarvis. Hablamos de Alfresco."]
    assert result == "Hoy hace fresco."


def test_synthesis_markers_do_not_become_expected_recognition_words():
    context = TranscriptionContext()
    context.remember("a", "<laughter>Alfresco.</laughter> [breath] Claro.")
    assert "Alfresco" in context.snapshot("a")
    assert "laughter" not in context.snapshot("a")
    assert "breath" not in context.snapshot("a")
