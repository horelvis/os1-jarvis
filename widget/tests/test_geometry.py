"""Where the strip sits. Pure arithmetic, so it is worth pinning exactly.

Monitor coordinates are root-window coordinates: on a multi-head setup
the second monitor's origin is not (0, 0), and a strip that ignores that
lands on the wrong screen. That is the only multi-monitor behaviour this
plan promises (spec §8 puts placement rules out of scope).

The strip is a fixed-width block centred on the bottom edge (user,
2026-08-23, after trying full width). Both shapes are tested, because
`STRIP_MAX_WIDTH = 0` still means "edge to edge" and that path must keep
working.
"""

from samantha_widget import theme
from samantha_widget.geometry import strip_rect


def test_it_is_a_fixed_width_block_centred_horizontally() -> None:
    x, _y, w, _h = strip_rect(0, 0, 1920, 1080)

    assert w == theme.STRIP_MAX_WIDTH
    assert x == (1920 - theme.STRIP_MAX_WIDTH) // 2


def test_it_sits_flush_against_the_bottom_edge() -> None:
    """No air underneath: it is anchored to the edge, not floating."""
    _x, y, _w, h = strip_rect(0, 0, 1920, 1080)

    assert y + h == 1080
    assert h == theme.STRIP_HEIGHT


def test_zero_means_edge_to_edge() -> None:
    """The full-width shape is still reachable with one constant."""
    original = theme.STRIP_MAX_WIDTH
    theme.STRIP_MAX_WIDTH = 0
    try:
        x, _y, w, _h = strip_rect(0, 0, 1920, 1080)
    finally:
        theme.STRIP_MAX_WIDTH = original

    assert w == 1920
    assert x == 0


def test_monitor_origin_is_respected() -> None:
    """A second monitor to the right of the first."""
    x, y, w, _h = strip_rect(1920, 0, 1920, 1080)

    assert w == theme.STRIP_MAX_WIDTH
    assert x == 1920 + (1920 - theme.STRIP_MAX_WIDTH) // 2
    assert y == 1080 - theme.STRIP_HEIGHT


def test_a_screen_narrower_than_the_fixed_width_does_not_overflow() -> None:
    """A 720p-wide screen must not get a strip wider than itself."""
    x, _y, w, _h = strip_rect(0, 0, 800, 600)

    assert w <= 800
    assert x >= 0


def test_absurdly_small_screen_still_produces_a_positive_size() -> None:
    """A VM at 640x480 must not produce a negative width."""
    _x, _y, w, h = strip_rect(0, 0, 640, 480)

    assert w > 0
    assert h > 0
