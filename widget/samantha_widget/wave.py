"""The wave, drawn.

GSK rather than Cairo, and not for the reason the design predicted.

The design (spec §4) chose Cairo and dismissed GSK because GTK4 had no
comfortable arbitrary-path primitive. That stopped being true in GTK
4.14, which is what is installed here: `Gsk.PathBuilder` builds the
polyline and `Gtk.Snapshot.append_stroke` draws it, composited on the
GPU, with no rasterisation on the CPU at all.

What forced the question was a missing dependency. PyGObject cannot hand
a `cairo.Context` to a draw function without `gi._gi_cairo`, which ships
in the system package `python3-gi-cairo` — installed neither here nor,
presumably, on the appliance. The failure is
`TypeError: Couldn't find foreign struct converter for 'cairo.Context'`,
raised inside the draw callback, where GTK swallows it: the strip appears
and simply never draws its line.

GSK needs nothing that GTK4 itself does not already need. For a machine
that is supposed to boot into being Samantha, one fewer system package
to get right is worth more than Cairo's familiarity.

The tick callback, not a timer: it fires on the compositor's frame
clock, so the animation cannot drift out of step with the screen.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Gsk", "4.0")

from gi.repository import Gdk, Gsk, Gtk  # noqa: E402

from . import theme  # noqa: E402
from .wave_model import WaveModel, WaveState  # noqa: E402

_LINE_WIDTH = 2.0


class WaveArea(Gtk.Widget):
    def __init__(self) -> None:
        super().__init__()
        self.model = WaveModel()
        self._last_frame_us: int | None = None
        self._colour = Gdk.RGBA()
        self._colour.parse(theme.LINE)
        self.add_tick_callback(self._tick)

    def set_state(self, state: WaveState) -> None:
        self.model.state = state

    def _tick(self, _widget: Gtk.Widget, clock: Gdk.FrameClock) -> bool:
        now = clock.get_frame_time()  # microseconds
        if self._last_frame_us is not None:
            dt = (now - self._last_frame_us) / 1_000_000
            # A suspended laptop or a stalled compositor hands back a
            # gap of minutes. Advancing the model by that would teleport
            # the thinking packet; clamp to a couple of frames.
            self.model.advance(min(dt, 0.05))
        self._last_frame_us = now
        self.queue_draw()
        return True  # GLib.SOURCE_CONTINUE

    def do_snapshot(self, snapshot: Gtk.Snapshot) -> None:
        width = float(self.get_width())
        height = float(self.get_height())
        if width <= 0 or height <= 0:
            return

        builder = Gsk.PathBuilder()
        points = self.model.points(width, height)
        builder.move_to(*points[0])
        for x, y in points[1:]:
            builder.line_to(x, y)

        stroke = Gsk.Stroke.new(_LINE_WIDTH)
        stroke.set_line_cap(Gsk.LineCap.ROUND)
        stroke.set_line_join(Gsk.LineJoin.ROUND)
        snapshot.append_stroke(builder.to_path(), stroke, self._colour)
