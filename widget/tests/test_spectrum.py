"""The spectrum analyser, at both rates. No GTK, no device, no display.

Written for a reported bug: while he LISTENS the strip drew a shape with
no relation to the voice — every band moving together in a fixed arch —
because a spectrum was only ever computed for his OWN voice. The
microphone path had nothing but a single RMS, and `BarsModel.set_level`
says in its own docstring that it is a "fallback for callers with no
spectrum".

So what is tested here is the thing that was missing: the same analysis
the player already did, available at the microphone's rate.
"""

import math

from samantha_widget.audio import OUTPUT_RATE, SpectrumAnalyser
from samantha_widget.bars_model import BAND_COUNT
from samantha_widget.vad import INPUT_RATE


def _tone(hz: float, rate: int, samples: int = 4096) -> list[float]:
    return [math.sin(2 * math.pi * hz * i / rate) * 0.8 for i in range(samples)]


def _loudest(bands: list[float]) -> int:
    return max(range(len(bands)), key=lambda i: bands[i])


def test_a_band_per_bar_all_within_range() -> None:
    analyser = SpectrumAnalyser(INPUT_RATE)

    bands = analyser.analyse(_tone(440, INPUT_RATE))

    assert len(bands) == BAND_COUNT
    assert all(0.0 <= value <= 1.0 for value in bands)


def test_a_low_tone_and_a_high_tone_light_different_bars() -> None:
    """The whole point: the picture must depend on WHAT was said.

    This is what the listening strip could not do. With one RMS driving
    every band, these two would produce the same arch at the same height.
    """
    low = SpectrumAnalyser(INPUT_RATE).analyse(_tone(200, INPUT_RATE))
    high = SpectrumAnalyser(INPUT_RATE).analyse(_tone(3000, INPUT_RATE))

    assert _loudest(low) < _loudest(high)


def test_a_tone_is_a_peak_and_not_a_block() -> None:
    """A pure tone lights a few bars, not all of them equally.

    The fallback shape (`level * (0.45 + 0.55 sin pi u)`) has every band
    non-zero by construction, so it can never satisfy this.
    """
    bands = SpectrumAnalyser(INPUT_RATE).analyse(_tone(1000, INPUT_RATE))

    peak = max(bands)
    loud = [value for value in bands if value > peak * 0.5]
    assert len(loud) < BAND_COUNT // 2


def test_silence_reads_as_silence() -> None:
    bands = SpectrumAnalyser(INPUT_RATE).analyse([0.0] * 4096)

    assert max(bands) == 0.0


def test_the_players_rate_still_works() -> None:
    """The player keeps its own rate; the analyser is shared, not moved."""
    bands = SpectrumAnalyser(OUTPUT_RATE).analyse(_tone(440, OUTPUT_RATE))

    assert len(bands) == BAND_COUNT
    assert max(bands) > 0.0
