"""Monitor rectangle in, strip rectangle out. No GTK, no X, no state."""

from __future__ import annotations

from . import theme


def strip_rect(
    monitor_x: int, monitor_y: int, monitor_w: int, monitor_h: int
) -> tuple[int, int, int, int]:
    """Where the strip goes, in root-window coordinates.

    Returns (x, y, width, height). The monitor origin is added back in so
    that a second monitor gets the strip on itself rather than on the
    first one.
    """
    available = monitor_w - 2 * theme.SIDE_MARGIN
    # STRIP_MAX_WIDTH == 0 means "no cap": edge to edge.
    width = (
        min(theme.STRIP_MAX_WIDTH, available) if theme.STRIP_MAX_WIDTH else available
    )
    # A tiny screen must not produce a zero or negative width; below this
    # the strip stops obeying the margins rather than disappearing.
    width = max(width, 240)
    height = theme.STRIP_HEIGHT

    x = monitor_x + (monitor_w - width) // 2
    y = monitor_y + monitor_h - height - theme.BOTTOM_MARGIN
    return x, y, width, height
