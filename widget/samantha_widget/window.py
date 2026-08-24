"""The strip itself: a GTK4 window that tries hard not to look like one."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("GdkX11", "4.0")

from gi.repository import Gdk, GdkX11, GLib, Gtk  # noqa: E402

from . import theme  # noqa: E402
from .ewmh import Ewmh  # noqa: E402
from .geometry import strip_rect  # noqa: E402


class StripWindow(Gtk.ApplicationWindow):
    def __init__(self, app: Gtk.Application) -> None:
        super().__init__(application=app)

        self.set_decorated(False)
        self.set_resizable(False)
        # Out of the alt-tab list and off the taskbar: this is furniture,
        # not an application the user switches to. The title is also what
        # `xprop -name Samantha` looks for when verifying the states.
        self.set_title("Samantha")

        self._ewmh: Ewmh | None = None
        self._xid: int | None = None
        # The strip at rest: what `resize_to` grows from and returns to.
        self._rect: tuple[int, int, int, int] | None = None

        # Vertical, because the band of photos sits ON TOP of the wave
        # and pushes the window's top edge up. Horizontal until
        # 2026-08-24, when there was only ever one child.
        self._frame = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._frame.add_css_class("samantha-strip")
        self._frame.set_hexpand(True)
        self._frame.set_vexpand(True)
        self.set_child(self._frame)

        self._content: Gtk.Widget | None = None
        self._band: Gtk.Widget | None = None

        self._install_css()

        # The X11 window id does not exist until the window is realized,
        # so every EWMH call has to wait for the map. Doing it in
        # __init__ silently does nothing: xid is 0 and the WM never hears
        # about it.
        self.connect("map", self._on_map)

    def set_content(self, widget: Gtk.Widget) -> None:
        """The wave. Always the bottom child, always the one that expands."""
        if self._content is not None:
            self._frame.remove(self._content)
        widget.set_hexpand(True)
        widget.set_vexpand(True)
        self._frame.append(widget)
        self._content = widget

    def set_band(self, widget: Gtk.Widget) -> None:
        """The photo band, above the wave and zero pixels tall until used."""
        if self._band is not None:
            self._frame.remove(self._band)
        widget.set_hexpand(True)
        widget.set_vexpand(False)
        self._frame.prepend(widget)
        self._band = widget

    def resize_to(self, extra_height: int) -> None:
        """Grow the strip upward by `extra_height`, or back to the strip.

        Upward, and that is the whole reason this cannot be left to GTK.
        The child asking for more height makes GTK resize the toplevel on
        its own — downward, off the bottom edge of the screen, since the
        strip's y is already flush against it. So the same placement call
        `_on_map` makes is repeated with the top edge moved up by exactly
        as much as the window grew.

        `set_default_size` first: the window is `set_resizable(False)`,
        so GTK pins the WM size hints to the current natural size and a
        window manager that honours them would refuse the new geometry.

        And then AGAIN on the next idle, which is not belt and braces.
        Mutter constrains a move against the size it currently believes
        the window to be, and that belief is one layout pass behind:
        shrinking back from 900x480 to 900x96, the move to y=984 was
        read as "put a 480-tall window at 984", which runs 384 px off
        the bottom of a 1080 screen, so it was clamped to y=600 — and
        the strip ended up floating in the middle of the desktop.
        Measured 2026-08-24 with `xwininfo -name Samantha`. By the idle
        the new size is in place and the identical call lands.
        """
        if self._ewmh is None or self._xid is None or self._rect is None:
            return
        x, y, w, h = self._rect
        extra = max(0, extra_height)
        self.set_default_size(w, h + extra)
        self._place(x, y - extra, w, h + extra)
        GLib.idle_add(self._place, x, y - extra, w, h + extra)

    def _place(self, x: int, y: int, w: int, h: int) -> bool:
        if self._ewmh is None or self._xid is None:
            return False  # GLib.SOURCE_REMOVE
        self._ewmh.move_resize(self._xid, x, y, w, h)
        self._ewmh.flush()
        return False  # GLib.SOURCE_REMOVE

    def _install_css(self) -> None:
        provider = Gtk.CssProvider()
        provider.load_from_data(theme.CSS.encode("utf-8"), -1)
        display = Gdk.Display.get_default()
        Gtk.StyleContext.add_provider_for_display(
            display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def _on_map(self, _widget: Gtk.Widget) -> None:
        surface = self.get_surface()
        if not isinstance(surface, GdkX11.X11Surface):
            # Wayland. Out of scope (spec §8): the strip will still draw,
            # it just will not be placed or kept above.
            return

        xid = surface.get_xid()
        monitor = Gdk.Display.get_default().get_monitor_at_surface(surface)
        rect = monitor.get_geometry()
        x, y, w, h = strip_rect(rect.x, rect.y, rect.width, rect.height)

        self.set_default_size(w, h)
        self._xid = xid
        self._rect = (x, y, w, h)

        self._ewmh = Ewmh()
        # Two at a time. A third atom in one message is dropped silently
        # — that is the whole reason ewmh.py refuses more than two.
        self._ewmh.add_state(xid, "_NET_WM_STATE_ABOVE", "_NET_WM_STATE_SKIP_TASKBAR")
        self._ewmh.add_state(xid, "_NET_WM_STATE_SKIP_PAGER", "_NET_WM_STATE_STICKY")
        self._ewmh.move_resize(xid, x, y, w, h)
        self._ewmh.flush()
