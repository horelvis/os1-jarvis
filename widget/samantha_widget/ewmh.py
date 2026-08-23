"""Always-above and pixel placement, via EWMH over ctypes/libX11.

GTK4 removed the APIs that would make this a two-line file: there is no
`set_keep_above`, no `move`, no `set_position` and no `get_position` on
a GTK4 window — verified with `hasattr` against a real one during the
2026-08-22 spike. The modern replacement, gtk4-layer-shell, is
Wayland-only and this box runs X11.

So the window manager is asked directly, the way every panel and dock
does it: a `_NET_WM_STATE` ClientMessage sent to the root window, plus
an `XMoveResizeWindow` for the geometry. ctypes against libX11 is
enough; python-xlib, wmctrl and xdotool are not installed here and none
of them is needed for ~50 lines of this.
"""

from __future__ import annotations

import ctypes
import ctypes.util

# _NET_WM_STATE actions (EWMH 1.5, §7.5)
NET_WM_STATE_REMOVE = 0
NET_WM_STATE_ADD = 1
NET_WM_STATE_TOGGLE = 2

# data[1] and data[2]. There is no data[5] for a third atom: the message
# is five longs and the rest are spoken for.
MAX_PROPS_PER_MESSAGE = 2

# Event masks the root window needs for the WM to act on the message.
_SUBSTRUCTURE_NOTIFY = 1 << 19
_SUBSTRUCTURE_REDIRECT = 1 << 20

_CLIENT_MESSAGE = 33


class _XClientMessageEvent(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_int),
        ("serial", ctypes.c_ulong),
        ("send_event", ctypes.c_int),
        ("display", ctypes.c_void_p),
        ("window", ctypes.c_ulong),
        ("message_type", ctypes.c_ulong),
        ("format", ctypes.c_int),
        ("data", ctypes.c_long * 5),
    ]


class XEvent(ctypes.Union):
    """XEvent is a union sized by its largest member.

    The padding member is not decoration: XSendEvent reads a full XEvent
    (24 longs) regardless of which member was filled in, and a structure
    that is merely large enough for a ClientMessage would have it read
    past the end of our allocation.
    """

    _fields_ = [
        ("type", ctypes.c_int),
        ("xclient", _XClientMessageEvent),
        ("pad", ctypes.c_long * 24),
    ]


def build_state_event(root: int, xid: int, atoms: list[int], action: int) -> XEvent:
    """Build one `_NET_WM_STATE` ClientMessage.

    `atoms` must hold one or two atoms. Three is a ValueError rather than
    a silent drop — see the module docstring of the tests.
    """
    if not atoms:
        raise ValueError("a _NET_WM_STATE message with no atoms does nothing")
    if len(atoms) > MAX_PROPS_PER_MESSAGE:
        raise ValueError(
            f"_NET_WM_STATE carries two properties per message, got "
            f"{len(atoms)} — send them in pairs. A third atom is dropped "
            f"silently by the window manager."
        )

    event = XEvent()
    event.type = _CLIENT_MESSAGE
    event.xclient.type = _CLIENT_MESSAGE
    event.xclient.send_event = True
    event.xclient.window = xid
    event.xclient.format = 32
    event.xclient.data[0] = action
    event.xclient.data[1] = atoms[0]
    event.xclient.data[2] = atoms[1] if len(atoms) > 1 else 0
    event.xclient.data[3] = 1  # source indication: a normal application
    event.xclient.data[4] = 0
    del root  # addressed at send time, not build time; kept for symmetry
    return event


class Ewmh:
    """A thin, live connection to the X server for the two things GTK4 lost."""

    def __init__(self, display_name: str | None = None) -> None:
        path = ctypes.util.find_library("X11") or "libX11.so.6"
        self._x11 = ctypes.CDLL(path)
        self._x11.XOpenDisplay.restype = ctypes.c_void_p
        self._x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
        self._x11.XInternAtom.restype = ctypes.c_ulong
        self._x11.XInternAtom.argtypes = [
            ctypes.c_void_p,
            ctypes.c_char_p,
            ctypes.c_int,
        ]
        self._x11.XDefaultRootWindow.restype = ctypes.c_ulong
        self._x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]

        name = display_name.encode() if display_name else None
        self._display = self._x11.XOpenDisplay(name)
        if not self._display:
            raise RuntimeError(f"cannot open X display {display_name or '$DISPLAY'}")
        self._root = self._x11.XDefaultRootWindow(self._display)
        self._atoms: dict[str, int] = {}

    def atom(self, name: str) -> int:
        if name not in self._atoms:
            self._atoms[name] = self._x11.XInternAtom(
                self._display, name.encode(), False
            )
        return self._atoms[name]

    def add_state(self, xid: int, *names: str) -> None:
        """Add up to two `_NET_WM_STATE` properties, in one message."""
        event = build_state_event(
            root=self._root,
            xid=xid,
            atoms=[self.atom(n) for n in names],
            action=NET_WM_STATE_ADD,
        )
        event.xclient.display = self._display
        event.xclient.message_type = self.atom("_NET_WM_STATE")
        self._x11.XSendEvent(
            ctypes.c_void_p(self._display),
            ctypes.c_ulong(self._root),
            ctypes.c_int(False),
            ctypes.c_long(_SUBSTRUCTURE_REDIRECT | _SUBSTRUCTURE_NOTIFY),
            ctypes.byref(event),
        )

    def move_resize(self, xid: int, x: int, y: int, w: int, h: int) -> None:
        self._x11.XMoveResizeWindow(
            ctypes.c_void_p(self._display),
            ctypes.c_ulong(xid),
            ctypes.c_int(x),
            ctypes.c_int(y),
            ctypes.c_uint(w),
            ctypes.c_uint(h),
        )

    def flush(self) -> None:
        self._x11.XFlush(ctypes.c_void_p(self._display))
