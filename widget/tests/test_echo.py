"""Taking his own voice out of the transcript, on text alone.

The case in `test_the_measured_case` is verbatim from the evening the
microphone gate came off: his own sentence came back through the room
and Whisper transcribed it along with a real person talking.
"""

from jarvis_widget.echo import EchoFilter


def test_nothing_said_means_nothing_is_cut():
    f = EchoFilter()
    assert f.clean("¿qué hora es?", now=0.0) == "¿qué hora es?"


def test_his_own_line_coming_back_is_removed_entirely():
    f = EchoFilter()
    f.spoke("La entrada está despejada, señor.", now=0.0)
    assert f.clean("La entrada está despejada, señor.", now=1.0) == ""


def test_the_measured_case():
    # 2026-08-26, with the gate off and the canceller running.
    said = (
        "Buenas tardes, señor. Le cuento algo un poco más largo para que "
        "podamos comprobar si el micrófono me está oyendo a mí mismo "
        "mientras hablo, que es justo lo que queremos evitar."
    )
    heard = (
        "Hey Jarvis, me llamo Rebeca. Buenas tardes señor, le cuento algo "
        "un poco más largo para que podamos comprobar si el micrófono me "
        "está oyendo a mí mismo mientras hablo, punto. Que es justo lo que "
        "queremos evitar. Hey Jarvis, me llamo Rebeca."
    )
    f = EchoFilter()
    f.spoke(said, now=0.0)
    kept = f.clean(heard, now=12.0)

    assert "Rebeca" in kept, kept
    assert "un poco más largo" not in kept, kept


def test_a_person_saying_something_else_survives_untouched():
    f = EchoFilter()
    f.spoke("La entrada está despejada, señor.", now=0.0)
    assert f.clean("Jarvis, apaga la luz del salón", now=1.0) == (
        "Jarvis, apaga la luz del salón"
    )


def test_accents_and_punctuation_survive_the_cut():
    f = EchoFilter()
    f.spoke("Le aviso cuando llegue alguien.", now=0.0)
    kept = f.clean("Le aviso cuando llegue alguien. ¿Qué día es hoy?", now=1.0)
    assert kept == "¿Qué día es hoy?"


def test_an_old_line_is_forgotten():
    # Repeating him a minute later is your own sentence, not his echo.
    f = EchoFilter()
    f.spoke("La entrada está despejada, señor.", now=0.0)
    assert f.clean("La entrada está despejada, señor.", now=90.0) != ""


def test_a_very_short_line_is_not_matched_on():
    # "Sí, señor." would otherwise swallow a person saying the same.
    f = EchoFilter()
    f.spoke("Sí, señor.", now=0.0)
    assert f.clean("Sí, señor.", now=1.0) == "Sí, señor."


def test_whisper_mangling_the_tail_still_matches():
    f = EchoFilter()
    f.spoke("Ahí la tiene, señor: la entrada, en directo.", now=0.0)
    # What came back through the room, transcribed imperfectly.
    assert f.clean("Ahí la tiene señor la entrada en directo", now=2.0) == ""


def test_two_of_his_lines_in_one_transcript():
    f = EchoFilter()
    f.spoke("Buenas tardes, señor. ¿En qué puedo ayudarle?", now=0.0)
    f.spoke("La entrada está despejada, sin novedad.", now=3.0)
    kept = f.clean(
        "Buenas tardes, señor. ¿En qué puedo ayudarle? "
        "Oye Jarvis. "
        "La entrada está despejada, sin novedad.",
        now=5.0,
    )
    assert kept == "Oye Jarvis."
