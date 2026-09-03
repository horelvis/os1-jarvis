"""The three switches, as pure state and geometry. No GTK in here."""

from jarvis_widget.switches import (
    CLOSE,
    GAP,
    MARGIN,
    MIC,
    SIZE,
    TEXT,
    VOICE,
    Switches,
)

STRIP = (900.0, 96.0)


def test_both_senses_start_on():
    s = Switches()
    assert s.mic_on and s.voice_on


def test_they_sit_in_a_row_at_the_right_edge():
    s = Switches()
    boxes = s.boxes(*STRIP)

    assert [b.name for b in boxes] == [MIC, VOICE, TEXT, CLOSE]
    assert boxes[-1].x + SIZE == 900.0 - MARGIN
    assert boxes[1].x - (boxes[0].x + SIZE) == GAP


def test_they_are_vertically_centred_on_the_strip():
    s = Switches()
    box = s.boxes(*STRIP)[0]
    assert box.y == (96.0 - SIZE) / 2.0


def test_a_press_on_one_of_them_is_named():
    s = Switches()
    mic, voice, _text, _close = s.boxes(*STRIP)

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


# ── the third one: closing him ────────────────────────────────────────


def test_there_are_four_of_them_now():
    s = Switches()
    assert [b.name for b in s.boxes(*STRIP)] == [MIC, VOICE, TEXT, CLOSE]


def test_one_press_on_close_only_arms_it():
    s = Switches()
    box = s.boxes(*STRIP)[3]
    assert s.press(box.x + 2, box.y + 2, *STRIP, now=0.0) is None
    assert s.armed(now=0.5)


def test_a_second_press_closes_him():
    s = Switches()
    box = s.boxes(*STRIP)[3]
    s.press(box.x + 2, box.y + 2, *STRIP, now=0.0)
    assert s.press(box.x + 2, box.y + 2, *STRIP, now=1.0) == CLOSE


def test_waiting_too_long_disarms_it():
    s = Switches()
    box = s.boxes(*STRIP)[3]
    s.press(box.x + 2, box.y + 2, *STRIP, now=0.0)
    assert not s.armed(now=4.0)
    # And the press after that is a first press again, not a second.
    assert s.press(box.x + 2, box.y + 2, *STRIP, now=4.0) is None


def test_pressing_elsewhere_is_a_change_of_mind():
    s = Switches()
    close = s.boxes(*STRIP)[3]
    s.press(close.x + 2, close.y + 2, *STRIP, now=0.0)
    s.press(400.0, 48.0, *STRIP, now=0.5)  # the wave
    assert not s.armed(now=0.6)


def test_the_other_two_still_toggle_through_press():
    s = Switches()
    mic, voice, _text, _close = s.boxes(*STRIP)
    assert s.press(mic.x + 2, mic.y + 2, *STRIP, now=0.0) == MIC
    assert s.mic_on is False
    assert s.press(voice.x + 2, voice.y + 2, *STRIP, now=0.0) == VOICE
    assert s.voice_on is False


def test_the_text_switch_is_an_action_not_a_toggle():
    # Pressing it reports itself so the widget can open the line; it has
    # no state of its own and it does not touch the senses.
    s = Switches()
    text = s.boxes(*STRIP)[2]
    assert s.press(text.x + 2, text.y + 2, *STRIP, now=0.0) == TEXT
    assert s.mic_on and s.voice_on


def test_the_text_switch_disarms_the_door():
    s = Switches()
    close, text = s.boxes(*STRIP)[3], s.boxes(*STRIP)[2]
    s.press(close.x + 2, close.y + 2, *STRIP, now=0.0)
    s.press(text.x + 2, text.y + 2, *STRIP, now=0.5)
    assert not s.armed(now=0.6)
