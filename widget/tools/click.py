"""Send a real click to a real pixel, through XTEST.

CLAUDE.md §5 says nothing about the strip's appearance is provable by a
test, and until 2026-08-26 that extended to its behaviour under a
press: with `xdotool` not installed there was no way to click the
window, so the switches could only be tested as pure state and looked
at in a screenshot.

`libXtst` IS installed, and it is reachable the same way `ewmh.py`
reaches libX11 — ctypes, no new dependency. This drives the pointer
exactly as a hand would: the strip cannot tell the difference, which is
the point.

    DISPLAY=:1 python tools/click.py 1309 1032        # one click
    DISPLAY=:1 python tools/click.py 1381 1032 1381 1032   # two, in a row

Coordinates are absolute screen pixels. `xwininfo -name "JARVIS"`
gives the window's origin; the switches sit at its right end.
"""

from __future__ import annotations

import ctypes
import sys
import time

_LEFT_BUTTON = 1


def click(display_name: str, points: list[tuple[int, int]]) -> None:
    x11 = ctypes.CDLL("libX11.so.6")
    xtst = ctypes.CDLL("libXtst.so.6")
    x11.XOpenDisplay.restype = ctypes.c_void_p

    display = x11.XOpenDisplay(display_name.encode())
    if not display:
        raise SystemExit(f"no display {display_name!r}")
    display = ctypes.c_void_p(display)

    for x, y in points:
        # -1 is "current screen". Motion first, then the button: a
        # button event carries no coordinates of its own.
        xtst.XTestFakeMotionEvent(display, -1, int(x), int(y), 0)
        x11.XFlush(display)
        time.sleep(0.05)
        xtst.XTestFakeButtonEvent(display, _LEFT_BUTTON, True, 0)
        xtst.XTestFakeButtonEvent(display, _LEFT_BUTTON, False, 0)
        x11.XFlush(display)
        print(f"clicked {x},{y}", file=sys.stderr)
        time.sleep(0.4)

    x11.XCloseDisplay(display)


if __name__ == "__main__":
    import os

    coords = [int(a) for a in sys.argv[1:]]
    if not coords or len(coords) % 2:
        raise SystemExit("usage: click.py X Y [X Y ...]")
    click(
        os.environ.get("DISPLAY", ":0"),
        list(zip(coords[0::2], coords[1::2])),
    )
