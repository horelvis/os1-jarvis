"""Type into whatever has keyboard focus, through XTEST.

The companion of `click.py`, and it exists for the same reason: the
strip grew a typed line on 2026-08-26, and there is no way to test it
without a keyboard — `xdotool` is not installed here, `libXtst` is.

    DISPLAY=:1 python tools/type.py "hola, qué tal" --enter

Plain ASCII plus the handful of keys a test needs. Accented characters
are deliberately not handled: they need the keyboard's own layout and
level shifts, and a test that types "que" instead of "qué" still proves
the line works.
"""

from __future__ import annotations

import ctypes
import sys
import time

_SHIFT = "Shift_L"


def _keysym_for(char: str) -> tuple[str, bool]:
    """The X keysym name for `char`, and whether it needs Shift."""
    named = {
        " ": ("space", False),
        ",": ("comma", False),
        ".": ("period", False),
        "?": ("question", True),
        "!": ("exclam", True),
        "-": ("minus", False),
        "_": ("underscore", True),
        "/": ("slash", False),
        ":": ("colon", True),
        "\n": ("Return", False),
    }
    if char in named:
        return named[char]
    if char.isupper():
        return (char.lower(), True)
    return (char, False)


def type_text(display_name: str, text: str, *, enter: bool = False) -> None:
    x11 = ctypes.CDLL("libX11.so.6")
    xtst = ctypes.CDLL("libXtst.so.6")
    x11.XOpenDisplay.restype = ctypes.c_void_p
    x11.XStringToKeysym.restype = ctypes.c_ulong
    x11.XStringToKeysym.argtypes = [ctypes.c_char_p]
    x11.XKeysymToKeycode.restype = ctypes.c_ubyte

    display = x11.XOpenDisplay(display_name.encode())
    if not display:
        raise SystemExit(f"no display {display_name!r}")
    display = ctypes.c_void_p(display)

    def code_for(name: str) -> int:
        keysym = x11.XStringToKeysym(name.encode())
        if not keysym:
            return 0
        return int(x11.XKeysymToKeycode(display, ctypes.c_ulong(keysym)))

    shift = code_for(_SHIFT)

    for char in text + ("\n" if enter else ""):
        name, needs_shift = _keysym_for(char)
        code = code_for(name)
        if not code:
            print(f"(sin tecla para {char!r})", file=sys.stderr)
            continue
        if needs_shift:
            xtst.XTestFakeKeyEvent(display, shift, True, 0)
        xtst.XTestFakeKeyEvent(display, code, True, 0)
        xtst.XTestFakeKeyEvent(display, code, False, 0)
        if needs_shift:
            xtst.XTestFakeKeyEvent(display, shift, False, 0)
        x11.XFlush(display)
        time.sleep(0.02)

    x11.XCloseDisplay(display)


if __name__ == "__main__":
    import os

    args = [a for a in sys.argv[1:] if a != "--enter"]
    if not args:
        raise SystemExit('usage: type.py "text" [--enter]')
    type_text(
        os.environ.get("DISPLAY", ":0"),
        args[0],
        enter="--enter" in sys.argv,
    )
