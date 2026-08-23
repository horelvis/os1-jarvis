"""The strip itself: a GTK4 window that tries hard not to look like one."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("GdkX11", "4.0")

from gi.repository import Gdk, GdkX11, Gtk  # noqa: E402

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

        self._frame = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self._frame.add_css_class("samantha-strip")
        self._frame.set_hexpand(True)
        self._frame.set_vexpand(True)
        self.set_child(self._frame)

        self._install_css()

        # The X11 window id does not exist until the window is realized,
        # so every EWMH call has to wait for the map. Doing it in
        # __init__ silently does nothing: xid is 0 and the WM never hears
        # about it.
        self.connect("map", self._on_map)

    def set_content(self, widget: Gtk.Widget) -> None:
        child = self._frame.get_first_child()
        if child is not None:
            self._frame.remove(child)
        widget.set_hexpand(True)
        widget.set_vexpand(True)
        self._frame.append(widget)

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

        self._ewmh = Ewmh()
        # Two at a time. A third atom in one message is dropped silently
        # — that is the whole reason ewmh.py refuses more than two.
        self._ewmh.add_state(xid, "_NET_WM_STATE_ABOVE", "_NET_WM_STATE_SKIP_TASKBAR")
        self._ewmh.add_state(xid, "_NET_WM_STATE_SKIP_PAGER", "_NET_WM_STATE_STICKY")
        self._ewmh.move_resize(xid, x, y, w, h)
        self._ewmh.flush()
