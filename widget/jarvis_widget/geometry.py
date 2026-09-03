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


def input_region(
    live_rect: tuple[float, float, float, float] | None,
    *,
    extra: int,
    band_extra: int,
    width: int,
    height: int,
) -> list[tuple[int, int, int, int]]:
    """Which parts of the strip take the pointer while a live view is up.

    An empty list means "the whole window", which is what the strip is
    when there is nothing to see through: the caller hands that straight
    to `XShapeCombineRectangles` (`ewmh.py`), where an empty region
    restores the default.

    `live_rect` is the moving picture, in window coordinates — the band
    is the first child of the frame and has no margin, so its own
    coordinates ARE the window's. Everything BELOW the photo band is
    ours and must keep taking clicks: the card, the console, the typed
    line and the wave. Until 2026-09-03 only the wave did, so a press on
    a question went through to the desktop and press-to-dismiss silently
    stopped working while a camera was open — the one combination
    nobody had put together.
    """
    if live_rect is None:
        return []
    lx, ly, lw, lh = live_rect
    debajo = height + extra - band_extra
    rects = [(round(lx), round(ly), round(lw), round(lh))]
    if debajo > 0:
        rects.append((0, band_extra, width, debajo))
    return rects
