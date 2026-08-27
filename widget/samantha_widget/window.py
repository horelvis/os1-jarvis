"""The strip itself: a GTK4 window that tries hard not to look like one."""

from __future__ import annotations

import sys
import time
from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Pango", "1.0")
gi.require_version("Gdk", "4.0")
gi.require_version("GdkX11", "4.0")

from gi.repository import Gdk, GdkX11, GLib, Gtk, Pango  # noqa: E402

from . import theme  # noqa: E402
from .ewmh import Ewmh  # noqa: E402
from . import console as console_mod  # noqa: E402
from .console import Console  # noqa: E402
from .geometry import placement_is_wrong, strip_rect  # noqa: E402

# How much taller the strip gets while the typed line is open. One line
# of text with room to breathe — it is an entry, not a message box.
PROMPT_HEIGHT = 38

# How long to leave the window manager before checking it obeyed, and
# how many times to insist. Three tries at 120 ms is a third of a
# second: under a blink, and bounded so a WM that simply refuses the
# geometry is reported rather than argued with forever.
_VERIFY_MS = 120
_VERIFY_TRIES = 3


def _make_terminal():
    """A `Vte.Terminal`, or None when the GTK4 VTE is not installed.

    Returning None rather than raising: the strip predates this and
    works without it. `sudo apt install gir1.2-vte-3.91
    libvte-2.91-gtk4-0` is what turns the console into a real terminal.
    """
    try:
        gi.require_version("Vte", "3.91")
        from gi.repository import Vte

        term = Vte.Terminal()
        term.set_scrollback_lines(2000)
        term.set_cursor_blink_mode(Vte.CursorBlinkMode.OFF)
        term.set_scroll_on_output(True)

        # VTE paints its own background over anything CSS says, so the
        # strip's colours have to be given to it directly or it lands on
        # the desktop as a black rectangle — which is what it did the
        # first time (user: "se ve igual de mal").
        background = Gdk.RGBA()
        background.parse(theme.CONSOLE_BACKGROUND)
        foreground = Gdk.RGBA()
        foreground.parse(theme.CONSOLE_FOREGROUND)
        term.set_colors(foreground, background, None)
        term.set_color_cursor(None)

        # The desktop's own monospace font, the way GNOME Console does
        # it, falling back to the theme's string when the setting is not
        # readable. A terminal that uses a different font from every
        # other terminal on the machine looks wrong before you can say
        # why.
        name = theme.CONSOLE_FONT
        try:
            from gi.repository import Gio

            settings = Gio.Settings.new("org.gnome.desktop.interface")
            chosen = settings.get_string("monospace-font-name")
            if chosen:
                name = chosen
        except Exception:
            pass
        font = Pango.FontDescription.from_string(name)
        font.set_size(int(theme.CONSOLE_FONT_POINTS * Pango.SCALE))
        term.set_font(font)

        # Room to breathe, and lines that are not glued together. Both
        # are what separates a terminal you can read from a wall of
        # characters — kgx does the same.
        term.set_cell_height_scale(theme.CONSOLE_LINE_SCALE)
        return term
    except Exception as exc:
        print(f"sin terminal VTE ({exc}); consola en modo texto", file=sys.stderr)
        return None


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
        # The rectangle it is currently trying to occupy.
        self._wanted: tuple[int, int, int, int] | None = None

        # Vertical, because the band of photos sits ON TOP of the wave
        # and pushes the window's top edge up. Horizontal until
        # 2026-08-24, when there was only ever one child.
        # Two things can make the strip taller now — the band and the
        # typed line — so the window keeps both and adds them, rather
        # than the last caller winning.
        self._band_extra = 0
        self._prompt_extra = 0
        self._console_extra = 0

        self._frame = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._frame.add_css_class("samantha-strip")
        self._frame.set_hexpand(True)
        self._frame.set_vexpand(True)
        self.set_child(self._frame)

        # The line you type at him in (user, 2026-08-26). Built here and
        # kept hidden: it is the first child of this window that takes
        # keyboard focus, and it takes it only while it is open.
        self._prompt = Gtk.Entry()
        self._prompt.add_css_class("samantha-prompt")
        self._prompt.set_placeholder_text("Escribe a JARVIS…")
        self._prompt.set_visible(False)
        self._prompt.connect("activate", self._on_prompt_activate)
        # Closed the moment it stops being the focused thing. The strip
        # is always on top, so an open line keeps the keyboard: measured
        # 2026-08-26, the user typing in his own terminal had "colo"
        # land in it and go out with the next sentence — "se inyecta el
        # último texto". Furniture does not get to hold the keyboard
        # after you have looked away.
        focus = Gtk.EventControllerFocus()
        focus.connect("leave", lambda _c: self.set_prompt_open(False))
        self._prompt.add_controller(focus)
        self._frame.prepend(self._prompt)
        self.on_prompt: Callable[[str], None] = lambda _text: None

        # What something working is saying, shown on the strip rather
        # than in a terminal (user, 2026-08-26). A label in a scroller:
        # the band draws with GSK and has no text primitive, and this
        # needs to be selectable and to wrap like text, which is what
        # the widget is for.
        self.console = Console()
        # A real terminal when the system has one, a label when it does
        # not. VTE is the widget GNOME Terminal is built on, so the
        # assistant's output arrives with its colours and its cursor
        # rather than as text somebody re-rendered — the user's point,
        # 2026-08-26: use what exists instead of implementing it all.
        # `gir1.2-vte-3.91`; the 2.91 typelib on this box is GTK3's and
        # cannot live in a GTK4 process.
        self._term = _make_terminal()
        self._console_label = Gtk.Label()
        self._console_label.set_xalign(0.0)
        self._console_label.set_yalign(1.0)
        self._console_label.set_wrap(False)
        self._console_label.set_selectable(True)
        self._console_label.add_css_class("samantha-console")
        self._console = Gtk.ScrolledWindow()
        self._console.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self._console.set_child(self._term or self._console_label)
        self._console.add_css_class("samantha-console-frame")
        # Pinned to the height the window grows by, minus its margins.
        # Without this the scroller takes its natural height — the label
        # asks for all its lines and gets a fraction of them, which is
        # how it first showed two and a half lines of five in a strip
        # that had grown by 190 (2026-08-26).
        self._console.set_size_request(-1, -1)
        self._console.set_vexpand(False)
        self._console.set_propagate_natural_height(False)
        self._console.set_visible(False)
        # A press anywhere on it puts it away — the same gesture that
        # dismisses a photo and closes a live camera, because they are
        # the same band and a third way of closing things would be a
        # third thing to remember. CAPTURE, or VTE takes the press first
        # and starts a selection with it: this is somewhere to glance
        # (see `console.py`), not somewhere to select from.
        dismiss = Gtk.GestureClick()
        dismiss.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        dismiss.connect("pressed", self._on_console_pressed)
        self._console.add_controller(dismiss)
        self._frame.prepend(self._console)
        # Reads the clock rather than counting down, so a second that
        # went missing while the widget was busy is not a second the
        # console overstays.
        GLib.timeout_add_seconds(1, self._on_console_tick)

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

    # ── the lines something working is writing ────────────────────────

    def write_console(self, text: str) -> None:
        """Show these lines on the strip, keeping the last few."""
        changed = self.console.write(text)
        # The scroller follows the model's height, so three lines take
        # the room of three lines — and the terminal is asked how tall
        # a line actually IS rather than guessed at. Guessing 15 px for
        # a line that measured 20 cut the top off every time
        # (2026-08-26).
        if self._term is not None:
            try:
                per_line = int(self._term.get_char_height())
                if per_line > 0:
                    self.console.line_height = per_line
            except Exception:
                pass
        self._console.set_size_request(-1, max(0, self.console.height - 6))
        if self._term is not None:
            # Straight through, escape codes and all — that is the point
            # of a terminal. CRLF because a terminal takes a carriage
            # return literally: without it every line starts where the
            # last one ended.
            self._term.feed(text.replace("\n", "\r\n").encode())
        else:
            self._console_label.set_text(self.console.text())
        self._console.set_visible(self.console.visible)
        if changed:
            self._console_extra = self.console.height
            self._resize()
        # Newest at the bottom, like a terminal: the scroller is pinned
        # to the end rather than left where the user last dragged it.
        GLib.idle_add(self._console_to_end)

    def _console_to_end(self) -> bool:
        adjustment = self._console.get_vadjustment()
        adjustment.set_value(adjustment.get_upper() - adjustment.get_page_size())
        return False  # GLib.SOURCE_REMOVE

    def finish_console(self) -> None:
        """The work is over: start the clock that puts this away."""
        self.console.finish(time.monotonic())
        # One line per run, not per line of output. A console that
        # closes at the wrong moment is otherwise indistinguishable from
        # one that closes at the right one — which cost a measurement
        # here (2026-08-26).
        print(
            f"console: fin del trabajo, se cierra en {console_mod.LINGER_SECONDS:.0f}s"
            f" ({len(self.console.lines)} lineas)",
            file=sys.stderr,
        )

    def _on_console_tick(self) -> bool:
        if self.console.tick(time.monotonic()):
            print("console: cerrada por el reloj", file=sys.stderr)
            self.clear_console()
        return True  # GLib.SOURCE_CONTINUE

    def _on_console_pressed(
        self, gesture: Gtk.GestureClick, n_press: int, _x: float, _y: float
    ) -> None:
        """A press closes it. Multi-press is ignored, the way CLOSE is:
        GTK fires `pressed` again for the second click of a double, and
        answering both would close a console the first press had already
        taken away."""
        if n_press > 1:
            return
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)
        self.clear_console()

    def clear_console(self) -> None:
        """Put the lines away.

        The window shrinks on what IT is currently adding, not on what
        the model reports changing. The model can already be empty — the
        clock's `tick` clears it before saying so — and asking the model
        instead left the strip at 330 px with an empty console inside it,
        logged as closed (measured 2026-08-26).
        """
        self.console.clear()
        if self._console_extra:
            self._console_extra = 0
            self._resize()
        if self._term is not None:
            self._term.reset(True, True)
        self._console_label.set_text("")
        self._console.set_visible(False)

    # ── the typed line ────────────────────────────────────────────────

    def prompt_open(self) -> bool:
        return self._prompt.get_visible()

    def toggle_prompt(self) -> None:
        """Open the line, or close it without sending."""
        self.set_prompt_open(not self.prompt_open())

    def set_prompt_open(self, open_: bool) -> None:
        self._prompt.set_visible(open_)
        self._prompt_extra = PROMPT_HEIGHT if open_ else 0
        # Cleared both ways. Clearing only on close left whatever a
        # previous open had collected — "manohola Jarvis", seen in a
        # screenshot 2026-08-26 — and a line that opens with somebody
        # else's half-sentence in it is worse than one that opens empty.
        self._prompt.set_text("")
        if open_:
            self._prompt.grab_focus()
        self._resize()

    def _on_prompt_activate(self, entry: Gtk.Entry) -> None:
        """Enter: send and stay open, or close if there was nothing.

        Sending used to close the line, and the user asked for the other
        thing (2026-08-26): "enviar un texto solo debe limpiar la caja
        no cerrarla". Talking to him is usually more than one sentence,
        and reopening between each is a gesture nobody wants. An empty
        Enter closes it, so there is still a way out from the keyboard —
        and looking away closes it too (see the focus controller).
        """
        text = entry.get_text().strip()
        if not text:
            self.set_prompt_open(False)
            return
        entry.set_text("")
        self.on_prompt(text)

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

        Then the SAME request a second time, and the reason is not the
        one it is easy to assume. Mutter constrains a move against the
        size it currently believes the window to be, and shrinking back
        from 900x480 to 900x96 the move to y=984 was read as "put a
        480-tall window at 984" — 384 px off the bottom of a 1080
        screen — so it was clamped to y=600 and the strip ended up
        floating in the middle of the desktop. Measured 2026-08-24 with
        `xwininfo -name Samantha`.

        What the repeat buys is ORDERING ON THE X CONNECTION, not GTK
        layout. Both requests go down the one connection `ewmh.py`
        holds, and mutter serves ConfigureRequests in arrival order, so
        by the time it constrains the second it has necessarily applied
        the size from the first. Writing this down because the first
        version of this comment said "by the idle the new size is in
        place", meaning GTK's layout — which is NOT what mutter
        constrains against, and which the idle does not wait for anyway:
        the frame clock is time-gated at priority 120 and an idle at
        priority 200 routinely runs first. The fix was right and the
        stated reason was wrong, which is exactly how the next person
        deletes the right line.

        And because "necessarily" is a claim about somebody else's
        window manager, `_verify` reads the geometry back and says so if
        it was not obeyed, instead of leaving the strip mispositioned
        and silent until the next photo.
        """
        self._band_extra = max(0, extra_height)
        self._resize()

    def _resize(self) -> None:
        """Apply the height both callers together are asking for."""
        if self._ewmh is None or self._xid is None or self._rect is None:
            return
        x, y, w, h = self._rect
        extra = self._band_extra + self._prompt_extra + self._console_extra
        wanted = (x, y - extra, w, h + extra)
        # What the strip is currently trying to be. A verify still in
        # flight for an older size must not fight a newer one.
        self._wanted = wanted
        self.set_default_size(w, h + extra)
        self._place(*wanted)
        GLib.idle_add(self._settle, wanted)
        self._update_input_region(extra, w, h)

    def _current_live_rect(self) -> tuple[float, float, float, float] | None:
        """Ask the band what it is showing, without re-deriving it.

        `self._band` is always the `PhotoArea` built in `__main__.py`,
        but it is stored here as a plain `Gtk.Widget` — `set_content`
        takes the same type for the wave, which has no `live_rect`. A
        band with no such method reads as "nothing to punch a hole
        for", not as a crash: this is a query, and the input region is
        allowed to lag a frame, never to raise.
        """
        band = self._band
        if band is None:
            return None
        live_rect = getattr(band, "live_rect", None)
        if live_rect is None:
            return None
        return live_rect()

    def _update_input_region(self, extra: int, w: int, h: int) -> None:
        """Punch a hole in the band for the desktop underneath it.

        Only a live view earns this (CLAUDE.md §12, 2026-08-25): a photo
        swallowing the whole band for fifteen seconds was an accepted
        trade, and a live view up to two minutes is what stopped that
        trade holding. `None` from `_current_live_rect` — nothing up, or
        a photo — restores the whole window, same as before this method
        existed.

        `live_rect()` is in the band widget's own coordinates. Those ARE
        window coordinates with no translation needed: the band is the
        first child of `self._frame`, a `Gtk.Box` with no margin or
        padding in `theme.CSS` (`samantha_widget/theme.py`), so its
        top-left sits exactly on the window's — confirmed against the
        drawing itself, `photo_area.py`'s `do_snapshot`, which paints
        `live_rect()` with no offset either. The wave's own strip sits
        below the band, at `y = extra`, `height = h` — the two numbers
        that describe where the band ends and the strip at rest begins.
        """
        if self._ewmh is None:
            return
        live_rect = self._current_live_rect()
        if live_rect is None:
            self._ewmh.set_input_region([])
            return
        lx, ly, lw, lh = live_rect
        rects = [
            (round(lx), round(ly), round(lw), round(lh)),
            (0, extra, w, h),
        ]
        self._ewmh.set_input_region(rects)

    def _place(self, x: int, y: int, w: int, h: int) -> bool:
        if self._ewmh is None or self._xid is None:
            return False  # GLib.SOURCE_REMOVE
        self._ewmh.move_resize(self._xid, x, y, w, h)
        self._ewmh.flush()
        return False  # GLib.SOURCE_REMOVE

    def _settle(self, wanted: tuple[int, int, int, int]) -> bool:
        if self._wanted != wanted:
            return False  # GLib.SOURCE_REMOVE — a newer size won
        self._place(*wanted)
        GLib.timeout_add(_VERIFY_MS, self._verify, wanted, _VERIFY_TRIES)
        return False  # GLib.SOURCE_REMOVE

    def _verify(self, wanted: tuple[int, int, int, int], tries: int) -> bool:
        """Read the geometry back, and re-place if it is not what was asked.

        Nothing did this before, and that is how a clamped shrink became
        invisible: the strip sat in the middle of the desktop until the
        next photo happened to resize it. A window manager is not
        obliged to obey; the least this can do is notice.
        """
        if self._ewmh is None or self._xid is None or self._wanted != wanted:
            return False  # GLib.SOURCE_REMOVE
        if not placement_is_wrong(self._ewmh.geometry(self._xid), wanted):
            return False  # GLib.SOURCE_REMOVE
        if tries <= 0:
            # Loud, because the alternative is a strip in the middle of
            # the screen and nothing anywhere saying why.
            print(
                f"la tira no quedó donde se pidió: {wanted}",
                file=sys.stderr,
                flush=True,
            )
            return False  # GLib.SOURCE_REMOVE
        self._place(*wanted)
        GLib.timeout_add(_VERIFY_MS, self._verify, wanted, tries - 1)
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
        self._wanted = (x, y, w, h)

        self._ewmh = Ewmh(xid=xid)
        # Two at a time. A third atom in one message is dropped silently
        # — that is the whole reason ewmh.py refuses more than two.
        self._ewmh.add_state(xid, "_NET_WM_STATE_ABOVE", "_NET_WM_STATE_SKIP_TASKBAR")
        self._ewmh.add_state(xid, "_NET_WM_STATE_SKIP_PAGER", "_NET_WM_STATE_STICKY")
        self._ewmh.move_resize(xid, x, y, w, h)
        self._ewmh.flush()
