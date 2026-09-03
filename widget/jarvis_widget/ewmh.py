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

from loguru import logger

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

# XShape (X11/extensions/shape.h), the constants `set_input_region` needs
# and the only place in this file that reaches libXext rather than
# libX11.
_SHAPE_INPUT = 2  # ShapeInput: the pointer-hit-testing shape, not the visible one
_SHAPE_SET = 0  # ShapeSet: replace the shape outright
_SHAPE_YX_BANDED = 3  # YXBanded ordering: no ordering guarantee is made


class _XRectangle(ctypes.Structure):
    """XRectangle, as XShapeCombineRectangles wants an array of."""

    _fields_ = [
        ("x", ctypes.c_short),
        ("y", ctypes.c_short),
        ("width", ctypes.c_ushort),
        ("height", ctypes.c_ushort),
    ]


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

    def __init__(
        self,
        display_name: str | None = None,
        *,
        xid: int | None = None,
        x11: ctypes.CDLL | None = None,
        xext: ctypes.CDLL | None = None,
    ) -> None:
        """Open a live X connection, unless `x11` says not to.

        `xid`, `x11` and `xext` exist for `tests/test_ewmh.py`: passing
        `x11` skips the whole real-display setup below, because a fake
        has none of the methods that setup would call on it — a plain
        `object()` cannot even take the `.restype` assignments, and that
        is deliberate (see the "missing xext" test). Production code
        never passes them; it gets the real libX11 this class has always
        opened, plus libXext, loaded lazily and tolerated if absent
        (`set_input_region` is the only thing here that needs it).

        `xid` is new for the same reason libXext is: every other method
        on this class takes the window id as a call argument rather than
        storing it, because it predates `set_input_region` needing one
        stored. Passing it here does not change those methods.
        """
        if x11 is not None:
            self._x11 = x11
            self._display = 0
            self._root = 0
            self._xext = xext
        else:
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
                raise RuntimeError(
                    f"cannot open X display {display_name or '$DISPLAY'}"
                )
            self._root = self._x11.XDefaultRootWindow(self._display)
            self._xext = xext if xext is not None else self._load_xext()

        self._atoms: dict[str, int] = {}
        self._xid = xid

    @staticmethod
    def _load_xext() -> ctypes.CDLL | None:
        """libXext, if this box has one. Its absence is not an error.

        Nothing before `set_input_region` existed needed it, so a box
        without it keeps every click landing on the whole band — exactly
        the behaviour this file has always had.
        """
        try:
            path = ctypes.util.find_library("Xext") or "libXext.so.6"
            xext = ctypes.CDLL(path)
        except OSError:
            logger.debug("ewmh: libXext not found, input region unavailable")
            return None

        xext.XShapeCombineRectangles.restype = None
        xext.XShapeCombineRectangles.argtypes = [
            ctypes.c_void_p,  # Display*
            ctypes.c_ulong,  # Window
            ctypes.c_int,  # destKind
            ctypes.c_int,  # xOff
            ctypes.c_int,  # yOff
            ctypes.POINTER(_XRectangle),
            ctypes.c_int,  # n_rects
            ctypes.c_int,  # op
            ctypes.c_int,  # ordering
        ]
        xext.XShapeCombineMask.restype = None
        xext.XShapeCombineMask.argtypes = [
            ctypes.c_void_p,  # Display*
            ctypes.c_ulong,  # Window
            ctypes.c_int,  # destKind
            ctypes.c_int,  # xOff
            ctypes.c_int,  # yOff
            ctypes.c_ulong,  # Pixmap src (0 == None: the whole window)
            ctypes.c_int,  # op
        ]
        return xext

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

    def geometry(self, xid: int) -> tuple[int, int, int, int] | None:
        """Where the window ACTUALLY is, in root coordinates. None if unknown.

        `XGetGeometry` alone is not enough and the difference is silent:
        mutter reparents the client into a frame, so the x and y it
        returns are relative to that frame and read as 0,0 on a window
        that is plainly at (510, 984). `XTranslateCoordinates` against
        the root is what turns them into the numbers `xwininfo` prints,
        which are the numbers anything here is compared against.

        On a window that no longer exists this would reach Xlib's default
        error handler, which prints and calls `exit()`. The caller is a
        GLib timeout, and a GLib timeout cannot outlive the main loop,
        which cannot outlive the window — so the window is alive whenever
        this runs. Anything that calls it from somewhere else has to
        think about that again.
        """
        root = ctypes.c_ulong()
        x = ctypes.c_int()
        y = ctypes.c_int()
        w = ctypes.c_uint()
        h = ctypes.c_uint()
        border = ctypes.c_uint()
        depth = ctypes.c_uint()
        ok = self._x11.XGetGeometry(
            ctypes.c_void_p(self._display),
            ctypes.c_ulong(xid),
            ctypes.byref(root),
            ctypes.byref(x),
            ctypes.byref(y),
            ctypes.byref(w),
            ctypes.byref(h),
            ctypes.byref(border),
            ctypes.byref(depth),
        )
        if not ok:
            return None

        abs_x = ctypes.c_int()
        abs_y = ctypes.c_int()
        child = ctypes.c_ulong()
        ok = self._x11.XTranslateCoordinates(
            ctypes.c_void_p(self._display),
            ctypes.c_ulong(xid),
            ctypes.c_ulong(self._root),
            ctypes.c_int(0),
            ctypes.c_int(0),
            ctypes.byref(abs_x),
            ctypes.byref(abs_y),
            ctypes.byref(child),
        )
        if not ok:
            return None
        return (abs_x.value, abs_y.value, w.value, h.value)

    def flush(self) -> None:
        self._x11.XFlush(ctypes.c_void_p(self._display))

    def set_input_region(self, rects: list[tuple[int, int, int, int]]) -> bool:
        """Which parts of the window take the pointer. False when it could not.

        The band is as wide as the strip and mostly transparent, so
        without this it swallows every click over its whole area — for
        fifteen seconds with a photo, and for up to two minutes with a
        live view, which is what made this worth doing (CLAUDE.md §12,
        deferred 2026-08-25).

        `Gdk.Surface.set_input_region` is the GTK way and wants a
        `cairo.Region`; Cairo is the trap this machine is built around
        (CLAUDE.md §2.3), so this goes through XShape by hand, the same
        way everything else in this file reaches past what GTK4 lost.

        `rects` are `(x, y, width, height)` in WINDOW coordinates — the
        caller's job to work out, not this method's; `window.py` is
        where that translation happens. An empty list restores the
        whole window, which is also what a missing libXext or a window
        not yet mapped leaves it as: this can only ever narrow the
        window's input area, never widen it past "the whole thing".
        """
        xext = self._xext
        if xext is None:
            logger.debug("ewmh: no libXext, input region left alone")
            return False
        if self._xid is None:
            logger.debug("ewmh: no xid yet, input region left alone")
            return False

        try:
            if not rects:
                xext.XShapeCombineMask(
                    self._display, self._xid, _SHAPE_INPUT, 0, 0, 0, _SHAPE_SET
                )
            else:
                array = (_XRectangle * len(rects))()
                for slot, (x, y, width, height) in zip(array, rects):
                    slot.x, slot.y = int(x), int(y)
                    slot.width, slot.height = int(width), int(height)
                xext.XShapeCombineRectangles(
                    self._display,
                    self._xid,
                    _SHAPE_INPUT,
                    0,
                    0,
                    array,
                    len(rects),
                    _SHAPE_SET,
                    _SHAPE_YX_BANDED,
                )
            self.flush()
        except Exception as exc:
            # Losing the input region costs clicks; raising costs the
            # strip. Whatever reached here — a missing symbol, a dead
            # display, a fake in a test that does not implement one of
            # these — is worth a line in the log and nothing more.
            logger.warning(f"ewmh: input region not set — {exc}")
            return False
        return True
