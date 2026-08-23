"""The equaliser's arithmetic. No GTK, no audio, no display.

What matters here is that the bars answer the sound and settle when it
stops — the two things that made the first version look wrong.
"""

from samantha_widget.bars_model import BAND_COUNT, BarsModel
from samantha_widget.wave_model import WaveState


def _settle(model: BarsModel, frames: int = 120) -> None:
    for _ in range(frames):
        model.advance(1 / 60)


def test_there_is_one_height_per_band() -> None:
    model = BarsModel()

    assert len(model.heights()) == BAND_COUNT


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
    assert heights[10] > 5 * heights[0]


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
