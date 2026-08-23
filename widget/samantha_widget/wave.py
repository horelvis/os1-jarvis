"""What you see on the strip: an equaliser, or the line it replaced.

GSK rather than Cairo, and not for the reason the design predicted.

The design (spec §4) chose Cairo and dismissed GSK because GTK4 had no
comfortable arbitrary-path primitive. That stopped being true in GTK
4.14, which is what is installed here. What forced the question was a
missing dependency: PyGObject cannot hand a `cairo.Context` to a draw
function without `gi._gi_cairo`, from the system package
`python3-gi-cairo` — installed neither here nor, presumably, on the
appliance. The failure is a `TypeError` raised inside the draw callback,
where GTK swallows it: the strip appears and never draws.

Bars need even less than the line did — `append_color` takes a rectangle
and a colour, with no path involved at all.

The tick callback, not a timer: it fires on the compositor's frame
clock, so the animation cannot drift out of step with the screen.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Gsk", "4.0")
gi.require_version("Graphene", "1.0")

from gi.repository import Gdk, Graphene, Gsk, Gtk  # noqa: E402

from . import theme  # noqa: E402
from .bars_model import BarsModel, WaveformModel  # noqa: E402
from .wave_model import WaveModel, WaveState  # noqa: E402

_LINE_WIDTH = 2.0
# Of each bar's slot; the rest is the gap. Low, because thick bars read
# as a chart and thin ones read as light (user, 2026-08-23).
_BAR_FILL = 0.22
# Never thinner than a hairline, whatever the screen width divides into.
_BAR_MIN_WIDTH_PX = 2.0
# Even a silent band keeps this many pixels, so the equaliser reads as a
# row of bars at rest rather than as an empty strip.
_BAR_MIN_PX = 1.5


class WaveArea(Gtk.Widget):
    def __init__(self) -> None:
        super().__init__()
        # Both models are kept: `theme.VISUALIZER` chooses which one is
        # drawn, and the wave is not dead code — it is the fallback if
        # the equaliser ever stops suiting the room.
        self.model = WaveModel()
        self.bars = BarsModel()
        self.waveform = WaveformModel()
        self._last_frame_us: int | None = None
        self._colour = Gdk.RGBA()
        self._colour.parse(theme.LINE)
        self.add_tick_callback(self._tick)

    def set_state(self, state: WaveState) -> None:
        self.model.state = state
        self.bars.state = state
        self.waveform.state = state

    def set_level(self, level: float) -> None:
        self.model.set_level(level)
        self.bars.set_level(level)

    def set_bands(self, bands: list[float]) -> None:
        self.bars.set_bands(bands)

    def set_history(self, history: list[float]) -> None:
        """The player's rolling per-block levels — the waveform itself."""
        self.waveform.set_history(history)

    def _tick(self, _widget: Gtk.Widget, clock: Gdk.FrameClock) -> bool:
        now = clock.get_frame_time()  # microseconds
        if self._last_frame_us is not None:
            dt = (now - self._last_frame_us) / 1_000_000
            # A suspended laptop or a stalled compositor hands back a
            # gap of minutes. Advancing the model by that would teleport
            # the thinking packet; clamp to a couple of frames.
            dt = min(dt, 0.05)
            self.model.advance(dt)
            self.bars.advance(dt)
            self.waveform.advance(dt)
        self._last_frame_us = now
        self.queue_draw()
        return True  # GLib.SOURCE_CONTINUE

    def do_snapshot(self, snapshot: Gtk.Snapshot) -> None:
        width = float(self.get_width())
        height = float(self.get_height())
        if width <= 0 or height <= 0:
            return

        if theme.VISUALIZER == "waveform":
            self._snapshot_columns(snapshot, width, height, self.waveform.heights())
        elif theme.VISUALIZER == "bars":
            self._snapshot_columns(snapshot, width, height, self.bars.heights())
        else:
            self._snapshot_line(snapshot, width, height)

    def _snapshot_columns(
        self,
        snapshot: Gtk.Snapshot,
        width: float,
        height: float,
        heights: list[float],
    ) -> None:
        centre = height / 2
        span = height / 2
        slot = width / len(heights)
        bar_width = max(_BAR_MIN_WIDTH_PX, slot * _BAR_FILL)
        # Centres each bar inside its own slot, so the row reads as
        # evenly spaced lines rather than as blocks butted together.
        offset = (slot - bar_width) / 2

        for i, value in enumerate(heights):
            half = max(_BAR_MIN_PX, value * span)
            rect = Graphene.Rect()
            # Mirrored about the centre line: a bar chart standing on the
            # bottom edge reads as a chart; this reads as an object.
            rect.init(i * slot + offset, centre - half, bar_width, half * 2)
            snapshot.append_color(self._colour, rect)

    def _snapshot_line(
        self, snapshot: Gtk.Snapshot, width: float, height: float
    ) -> None:
        builder = Gsk.PathBuilder()
        points = self.model.points(width, height)
        builder.move_to(*points[0])
        for x, y in points[1:]:
            builder.line_to(x, y)

        stroke = Gsk.Stroke.new(_LINE_WIDTH)
        stroke.set_line_cap(Gsk.LineCap.ROUND)
        stroke.set_line_join(Gsk.LineJoin.ROUND)
        snapshot.append_stroke(builder.to_path(), stroke, self._colour)
