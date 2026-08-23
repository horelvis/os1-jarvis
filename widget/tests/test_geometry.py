"""Where the strip sits. Pure arithmetic, so it is worth pinning exactly.

Monitor coordinates are root-window coordinates: on a multi-head setup
the second monitor's origin is not (0, 0), and a strip that ignores that
lands on the wrong screen. That is the only multi-monitor behaviour this
plan promises (spec §8 puts placement rules out of scope).

The strip is edge to edge along the bottom (user, 2026-08-23). The tests
are written against `theme`'s constants rather than against literals, so
that putting a number back in STRIP_MAX_WIDTH — which restores the
floating card the design originally described — does not break them.
"""

from samantha_widget import theme
from samantha_widget.geometry import strip_rect


def test_it_spans_the_whole_screen_by_default() -> None:
    x, y, w, h = strip_rect(0, 0, 1920, 1080)

    assert w == 1920
    assert x == 0
    assert h == theme.STRIP_HEIGHT
    assert y == 1080 - theme.STRIP_HEIGHT


def test_it_sits_flush_against_the_bottom_edge() -> None:
    """No air underneath: it is a bar along the edge, not a card."""
    _x, y, _w, h = strip_rect(0, 0, 1920, 1080)

    assert y + h == 1080


def test_a_cap_makes_it_a_centred_card_again() -> None:
    """STRIP_MAX_WIDTH is the one knob between a bar and a floating card."""
    original = theme.STRIP_MAX_WIDTH
    theme.STRIP_MAX_WIDTH = 1100
    try:
        x, _y, w, _h = strip_rect(0, 0, 1920, 1080)
    finally:
        theme.STRIP_MAX_WIDTH = original

    assert w == 1100
    assert x == (1920 - 1100) // 2


def test_monitor_origin_is_respected() -> None:
    """A second monitor to the right of the first."""
    x, y, w, _h = strip_rect(1920, 0, 1920, 1080)

    assert x == 1920
    assert w == 1920
    assert y == 1080 - theme.STRIP_HEIGHT


def test_absurdly_small_screen_still_produces_a_positive_size() -> None:
    """A VM at 640x480 must not produce a negative width."""
    _x, _y, w, h = strip_rect(0, 0, 640, 480)

    assert w > 0
    assert h > 0
