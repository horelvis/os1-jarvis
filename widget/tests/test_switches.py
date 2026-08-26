"""The two switches, as pure state and geometry. No GTK in here."""

from samantha_widget.switches import GAP, MARGIN, MIC, SIZE, VOICE, Switches

STRIP = (900.0, 96.0)


def test_both_senses_start_on():
    s = Switches()
    assert s.mic_on and s.voice_on


def test_there_are_two_of_them_and_they_sit_at_the_right_edge():
    s = Switches()
    boxes = s.boxes(*STRIP)

    assert [b.name for b in boxes] == [MIC, VOICE]
    assert boxes[-1].x + SIZE == 900.0 - MARGIN
    assert boxes[1].x - (boxes[0].x + SIZE) == GAP


def test_they_are_vertically_centred_on_the_strip():
    s = Switches()
    box = s.boxes(*STRIP)[0]
    assert box.y == (96.0 - SIZE) / 2.0


def test_a_press_on_one_of_them_is_named():
    s = Switches()
    mic, voice = s.boxes(*STRIP)

    assert s.hit(mic.x + 2, mic.y + 2, *STRIP) == MIC
    assert s.hit(voice.x + 2, voice.y + 2, *STRIP) == VOICE


def test_a_press_on_the_wave_is_not_a_switch():
    s = Switches()
    assert s.hit(100.0, 48.0, *STRIP) is None


def test_a_press_just_outside_a_box_misses_it():
    s = Switches()
    mic = s.boxes(*STRIP)[0]
    assert s.hit(mic.x - 1, mic.y + 2, *STRIP) is None
    assert s.hit(mic.x + 2, mic.y - 1, *STRIP) is None


def test_toggling_turns_one_sense_off_and_leaves_the_other():
    s = Switches()

    assert s.toggle(MIC) is False
    assert s.mic_on is False and s.voice_on is True

    assert s.toggle(MIC) is True
    assert s.mic_on is True


def test_the_voice_switch_is_its_own():
    s = Switches()
    s.toggle(VOICE)
    assert s.voice_on is False and s.mic_on is True


def test_a_strip_too_narrow_shows_none_rather_than_covering_the_wave():
    s = Switches()
    assert s.boxes(80.0, 96.0) == []
    assert s.hit(10.0, 10.0, 80.0, 96.0) is None
