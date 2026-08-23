"""Where the strip sits. Pure arithmetic, so it is worth pinning exactly.

Monitor coordinates are root-window coordinates: on a multi-head setup
the second monitor's origin is not (0, 0), and a strip that ignores that
lands on the wrong screen. That is the only multi-monitor behaviour this
plan promises (spec §8 puts placement rules out of scope).
"""

from samantha_widget import theme
from samantha_widget.geometry import strip_rect


def test_centred_on_a_1080p_screen() -> None:
    x, y, w, h = strip_rect(0, 0, 1920, 1080)

    assert w == theme.STRIP_MAX_WIDTH  # 1100 fits in 1920 - 2*48
    assert h == theme.STRIP_HEIGHT
    assert x == (1920 - 1100) // 2
    assert y == 1080 - theme.STRIP_HEIGHT - theme.BOTTOM_MARGIN


def test_narrow_screen_clamps_to_the_side_margins() -> None:
    x, y, w, h = strip_rect(0, 0, 1000, 700)

    assert w == 1000 - 2 * theme.SIDE_MARGIN
    assert x == theme.SIDE_MARGIN
    del y, h


def test_monitor_origin_is_respected() -> None:
    """A second monitor to the right of the first."""
    x, y, _w, _h = strip_rect(1920, 0, 1920, 1080)

    assert x == 1920 + (1920 - theme.STRIP_MAX_WIDTH) // 2
    assert y == 1080 - theme.STRIP_HEIGHT - theme.BOTTOM_MARGIN


def test_absurdly_small_screen_still_produces_a_positive_size() -> None:
    """A VM at 640x480 must not produce a negative width."""
    _x, _y, w, h = strip_rect(0, 0, 640, 480)

    assert w > 0
    assert h > 0
