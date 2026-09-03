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

from jarvis_widget import geometry, theme
from jarvis_widget.geometry import placement_is_wrong, strip_rect


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


# ── the placement read-back ───────────────────────────────────────────
#
# The strip asks the window manager for a rectangle; the window manager
# is free to give it another one, and did (2026-08-24: a shrink clamped
# to y=600, leaving the strip floating in the middle of the desktop).
# Nothing read the answer back. This is the decision that follows the
# read, kept pure so it can be exercised without an X server.


def test_the_geometry_it_asked_for_is_not_wrong():
    assert placement_is_wrong((510, 984, 900, 96), (510, 984, 900, 96)) is False


def test_a_clamped_position_is_wrong():
    # The exact failure: the right size at the wrong y.
    assert placement_is_wrong((510, 600, 900, 96), (510, 984, 900, 96)) is True


def test_a_wrong_size_is_wrong_too():
    assert placement_is_wrong((510, 984, 900, 210), (510, 984, 900, 96)) is True


def test_a_geometry_that_could_not_be_read_is_not_wrong():
    # None means the question could not be answered — the connection is
    # gone, or the window is. Re-placing a window that may not exist
    # buys nothing and would loop forever against a dead server.
    assert placement_is_wrong(None, (510, 984, 900, 96)) is False


# ── the input region, while a live camera is up ────────────────────────


def test_no_live_view_leaves_the_whole_window_taking_clicks() -> None:
    assert (
        geometry.input_region(None, extra=210, band_extra=0, width=900, height=96) == []
    )


def test_a_live_view_keeps_the_picture_and_everything_under_the_band() -> None:
    rects = geometry.input_region(
        (10.0, 20.0, 654.0, 368.0), extra=384, band_extra=384, width=900, height=96
    )
    assert rects == [(10, 20, 654, 368), (0, 384, 900, 96)]


def test_a_card_under_a_live_view_still_takes_its_press() -> None:
    """Press-to-dismiss stopped working in exactly this combination.

    With a camera up (384 px of band) and a question drawn under it
    (210 px of card), the region was the picture plus the wave only, so
    a press on the card went to the desktop and the card could not be
    dismissed until its five minutes ran out.
    """
    rects = geometry.input_region(
        (0.0, 0.0, 900.0, 384.0), extra=594, band_extra=384, width=900, height=96
    )
    assert rects == [(0, 0, 900, 384), (0, 384, 900, 306)]
    _x, y, _w, alto = rects[1]
    assert y <= 384 and y + alto == 594 + 96  # the card, and the wave below it
