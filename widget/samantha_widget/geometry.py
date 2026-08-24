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


def placement_is_wrong(
    actual: tuple[int, int, int, int] | None,
    wanted: tuple[int, int, int, int],
) -> bool:
    """Did the window manager put the strip somewhere other than asked?

    `actual` is what was read back off the X connection, `wanted` is what
    was asked for; both are (x, y, width, height) in root coordinates.

    `None` — the geometry could not be read at all — is deliberately NOT
    wrong. Unknown is not the same as misplaced, and a caller that
    treated it as misplaced would re-place a window that may no longer
    exist, forever.
    """
    return actual is not None and actual != wanted
