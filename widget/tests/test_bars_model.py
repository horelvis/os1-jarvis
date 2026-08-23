"""The equaliser's arithmetic. No GTK, no audio, no display.

What matters here is that the bars answer the sound and settle when it
stops — the two things that made the first version look wrong.
"""

from samantha_widget.bars_model import BAND_COUNT, MAX_VISIBLE_TASKS, BarsModel
from samantha_widget.wave_model import WaveState


def _settle(model: BarsModel, frames: int = 120) -> None:
    for _ in range(frames):
        model.advance(1 / 60)


def test_every_band_is_drawn_twice_mirrored() -> None:
    """The row is symmetric: low bands meet in the middle, high bands
    taper off to both edges."""
    model = BarsModel()

    heights = model.heights()
    assert len(heights) == 2 * BAND_COUNT
    assert heights == heights[::-1]


def test_heights_never_exceed_the_half_height() -> None:
    model = BarsModel()
    model.state = WaveState.SPEAKING
    model.set_bands([1.0] * BAND_COUNT)
    _settle(model)

    assert max(model.heights()) <= 1.0


def test_a_loud_band_is_taller_than_a_quiet_one() -> None:
    model = BarsModel()
    model.state = WaveState.SPEAKING
    bands = [0.05] * BAND_COUNT
    bands[10] = 0.9
    model.set_bands(bands)
    _settle(model)

    heights = model.heights()
    # Band 10 is drawn at BAND_COUNT + 10 (and mirrored at its opposite);
    # the outermost bar is the highest band, which is quiet here.
    assert heights[BAND_COUNT + 10] > 5 * heights[0]


def test_the_lowest_band_sits_at_the_centre() -> None:
    """Speech energy is low and mid; against one edge it looks lopsided."""
    model = BarsModel()
    model.state = WaveState.SPEAKING
    bands = [0.05] * BAND_COUNT
    bands[0] = 0.9
    model.set_bands(bands)
    _settle(model)

    heights = model.heights()
    centre = len(heights) // 2
    assert heights[centre] > 5 * heights[0]
    assert heights[centre - 1] > 5 * heights[-1]


def test_bars_fall_back_when_the_sound_stops() -> None:
    """The failure that started this: a bar that stays up is not sound."""
    model = BarsModel()
    model.state = WaveState.SPEAKING
    model.set_bands([0.9] * BAND_COUNT)
    _settle(model)
    loud = max(model.heights())

    model.set_bands([0.0] * BAND_COUNT)
    _settle(model)

    assert max(model.heights()) < loud / 4


def test_a_bar_rises_faster_than_it_falls() -> None:
    """Asymmetry is what makes an equaliser look alive."""
    rising = BarsModel()
    rising.state = WaveState.SPEAKING
    rising.set_bands([1.0] * BAND_COUNT)
    rising.advance(1 / 30)
    after_rise = max(rising.heights())

    falling = BarsModel()
    falling.state = WaveState.SPEAKING
    falling.set_bands([1.0] * BAND_COUNT)
    _settle(falling)
    top = max(falling.heights())
    falling.set_bands([0.0] * BAND_COUNT)
    falling.advance(1 / 30)
    dropped = top - max(falling.heights())

    assert after_rise > dropped


def test_idle_is_nearly_flat() -> None:
    model = BarsModel()
    model.state = WaveState.IDLE
    _settle(model, 200)

    assert max(model.heights()) < 0.1


def test_the_thinking_packet_travels_across_the_bands() -> None:
    model = BarsModel()
    model.state = WaveState.THINKING

    model.advance(0.1)
    first = model.heights().index(max(model.heights()))
    model.advance(0.5)
    second = model.heights().index(max(model.heights()))

    assert second > first


def test_set_level_shapes_the_bands_instead_of_flattening_them() -> None:
    """One number in, a curve out — a flat block does not read as sound."""
    model = BarsModel()
    model.state = WaveState.SPEAKING
    model.set_level(0.8)
    _settle(model)

    heights = model.heights()
    assert heights[BAND_COUNT // 2] > heights[0]


def test_bands_are_clamped() -> None:
    model = BarsModel()
    model.state = WaveState.SPEAKING
    model.set_bands([50.0] * BAND_COUNT)
    _settle(model)

    assert max(model.heights()) <= 1.0


def test_a_short_band_list_leaves_the_rest_silent() -> None:
    model = BarsModel()
    model.state = WaveState.SPEAKING
    model.set_bands([0.9, 0.9])
    _settle(model)

    assert model.heights()[-1] < 0.05


# ── the waveform ──────────────────────────────────────────────────────


def test_a_quiet_voice_still_fills_the_strip() -> None:
    """Speech peaks around 0.3-0.5 of full scale; drawn literally that is
    a flat line with bumps, which is why the editor-style auto-gain is
    there."""
    from samantha_widget.bars_model import WaveformModel

    model = WaveformModel()
    model.state = WaveState.SPEAKING
    model.set_history([0.05] * 40 + [0.35] + [0.05] * 40)

    assert max(model.heights()) > 0.8


def test_silence_is_not_amplified_into_a_wall() -> None:
    """Auto-gain against the noise floor would make silence look loud."""
    from samantha_widget.bars_model import WaveformModel

    model = WaveformModel()
    model.state = WaveState.SPEAKING
    model.set_history([0.002] * 90)

    assert max(model.heights()) < 0.05


def test_the_shape_survives_normalisation() -> None:
    """A peak twice as tall as its neighbour stays twice as tall."""
    from samantha_widget.bars_model import WaveformModel

    model = WaveformModel()
    model.state = WaveState.SPEAKING
    model.set_history([0.2] * 10 + [0.4] + [0.2] * 10)

    heights = model.heights()
    tallest = max(heights)
    neighbour = heights[-1]
    assert tallest > 1.8 * neighbour


def test_a_short_history_is_padded_not_stretched() -> None:
    from samantha_widget.bars_model import HISTORY_LEN, WaveformModel

    model = WaveformModel()
    model.state = WaveState.SPEAKING
    model.set_history([0.5, 0.5])

    assert len(model.heights()) == HISTORY_LEN


def test_the_waveform_is_symmetric_about_the_centre() -> None:
    """Growing outwards from the middle, not scrolling sideways."""
    from samantha_widget.bars_model import WaveformModel

    model = WaveformModel()
    model.state = WaveState.SPEAKING
    model.set_history([0.1] * 40 + [0.9] * 5)

    heights = model.heights()
    half = len(heights) // 2
    for i in range(half):
        assert heights[half + i] == heights[half - 1 - i]


def test_the_newest_sound_is_in_the_middle() -> None:
    """A loud burst that just happened belongs at the centre, and the
    quiet that preceded it out at the edges."""
    from samantha_widget.bars_model import WaveformModel

    model = WaveformModel()
    model.state = WaveState.SPEAKING
    model.set_history([0.05] * 60 + [0.9] * 4)

    heights = model.heights()
    half = len(heights) // 2
    assert heights[half] > 5 * heights[0]


# ── working: one pulse per task ───────────────────────────────────────


def _peak_count(heights: list[float], floor: float = 0.15) -> int:
    """How many separate blips are on the row."""
    count, inside = 0, False
    for value in heights:
        if value >= floor and not inside:
            count += 1
            inside = True
        elif value < floor:
            inside = False
    return count


def test_working_with_no_tasks_falls_back_to_one_pulse() -> None:
    """ "Working on nothing" is just waiting."""
    model = BarsModel()
    model.state = WaveState.WORKING
    model.set_task_count(0)
    model.advance(0.3)

    assert _peak_count(model.heights()) >= 1


def test_two_tasks_show_two_pulses() -> None:
    model = BarsModel()
    model.state = WaveState.WORKING
    model.set_task_count(2)
    model.advance(0.25)

    assert _peak_count(model.heights()) == 2


def test_three_tasks_show_three_pulses() -> None:
    model = BarsModel()
    model.state = WaveState.WORKING
    model.set_task_count(3)
    model.advance(0.25)

    assert _peak_count(model.heights()) == 3


def test_the_pulses_travel_at_different_speeds() -> None:
    """Locked in step they would read as one task, not three."""
    model = BarsModel()
    model.state = WaveState.WORKING
    model.set_task_count(3)

    def peaks() -> list[int]:
        heights = model.heights()
        return [i for i, v in enumerate(heights) if v >= 0.15]

    model.advance(0.2)
    first = peaks()
    model.advance(0.6)
    second = peaks()

    assert first != second


def test_a_crossing_never_overflows_the_strip() -> None:
    """Pulses add where they meet; the sum must stay on screen."""
    model = BarsModel()
    model.state = WaveState.WORKING
    model.set_task_count(MAX_VISIBLE_TASKS)
    for _ in range(200):
        model.advance(1 / 60)
        assert max(model.heights()) <= 1.0


def test_more_tasks_than_can_be_counted_are_capped() -> None:
    """Past a point it just looks busy, which is the honest reading."""
    model = BarsModel()
    model.state = WaveState.WORKING
    model.set_task_count(40)
    model.advance(0.25)

    assert _peak_count(model.heights()) <= MAX_VISIBLE_TASKS
