"""The wake word, as pure state.

No GTK, no audio, no gateway — the same split `photo.py` and
`wave_model.py` already make. What it decides: whether a transcription
was addressed to him, and what is left of it once his name is taken off
the front.

The load-bearing measurement is that Whisper does not hear "Jarvis".
Driving the same synthesised sentence through the real path on
2026-08-26 produced "Carbis", "Harvish", "Jervis" and "Jarvis" — four
spellings of one word in ten minutes. An exact match would have ignored
three of them, and being ignored is the one failure a wake word cannot
afford: the user says it again, louder, and concludes he is broken.
"""

from samantha_widget.wake import WakeWord


def test_his_name_opens_a_turn():
    w = WakeWord()
    assert w.heard("Jarvis, ¿qué día es hoy?", now=0.0) == "¿qué día es hoy?"


def test_a_sentence_without_his_name_is_not_for_him():
    w = WakeWord()
    assert w.heard("pásame la sal", now=0.0) is None


def test_the_names_whisper_actually_produced_all_work():
    # Measured 2026-08-26 on the real path, one sentence, four spellings.
    for heard in ("Carbis", "Harvish", "Jervis", "Jarvis", "jarvis"):
        w = WakeWord()
        assert w.heard(f"{heard}, enséñame la entrada", now=0.0) == (
            "enséñame la entrada"
        ), heard


def test_a_name_that_is_not_his_is_still_not_his():
    w = WakeWord()
    assert w.heard("Marta, ven un momento", now=0.0) is None
    assert w.heard("mañana hablamos", now=0.0) is None


def test_just_his_name_is_a_turn_of_its_own():
    # "Jarvis." with nothing after it is somebody getting his attention.
    w = WakeWord()
    assert w.heard("Jarvis.", now=0.0) == "Jarvis."


def test_after_answering_he_keeps_listening_for_a_while():
    w = WakeWord()
    w.heard("Jarvis, ¿qué hora es?", now=0.0)
    w.answered(now=5.0)
    assert w.heard("¿y mañana?", now=10.0) == "¿y mañana?"


def test_the_window_closes_and_his_name_is_needed_again():
    w = WakeWord()
    w.heard("Jarvis, ¿qué hora es?", now=0.0)
    w.answered(now=5.0)
    assert w.heard("¿y mañana?", now=40.0) is None


def test_each_answer_pushes_the_window_out():
    w = WakeWord()
    w.heard("Jarvis, ¿qué hora es?", now=0.0)
    w.answered(now=5.0)
    w.heard("¿y mañana?", now=20.0)
    w.answered(now=25.0)
    assert w.heard("¿y el jueves?", now=50.0) == "¿y el jueves?"


def test_an_empty_word_turns_the_whole_thing_off():
    # The behaviour every version before 2026-08-26 had, kept reachable:
    # everything heard is for him.
    w = WakeWord(word="")
    assert w.heard("pásame la sal", now=0.0) == "pásame la sal"


def test_the_word_can_be_something_else():
    w = WakeWord(word="samantha")
    assert w.heard("Samantha, ¿estás?", now=0.0) == "¿estás?"
    assert w.heard("Jarvis, ¿estás?", now=0.0) is None


def test_the_name_can_come_after_a_filler():
    # "Oye, Jarvis…" is how people actually talk.
    w = WakeWord()
    assert w.heard("Oye, Jarvis, apaga la luz", now=0.0) == "apaga la luz"


def test_nothing_heard_is_never_a_turn():
    w = WakeWord()
    assert w.heard("", now=0.0) is None
    assert w.heard("   ", now=0.0) is None


def test_heard_remembers_whether_the_name_was_said():
    w = WakeWord("jarvis")
    assert w.heard("jarvis, qué hora es", now=0.0) == "qué hora es"
    assert w.named is True
    w.answered(now=1.0)
    assert w.heard("y mañana", now=2.0) == "y mañana"
    assert w.named is False


def test_with_no_wake_word_nothing_counts_as_named():
    w = WakeWord("")
    assert w.heard("hola", now=0.0) == "hola"
    assert w.named is False


def test_named_resets_even_when_nothing_was_heard():
    # A call that returns None must not leave `named` holding whatever
    # the PREVIOUS call set — it has to describe THIS call, and this
    # call heard nothing at all.
    w = WakeWord("jarvis")
    assert w.heard("jarvis, hola", now=0.0) == "hola"
    assert w.named is True

    assert w.heard("", now=1.0) is None
    assert w.named is False
