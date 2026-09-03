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

import time
from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Gsk", "4.0")
gi.require_version("Graphene", "1.0")

from gi.repository import Gdk, Graphene, Gsk, Gtk  # noqa: E402

from . import theme  # noqa: E402
from .bars_model import BarsModel, WaveformModel  # noqa: E402
from .switches import CLOSE, SIZE as SWITCH_SIZE, Switches  # noqa: E402
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

# Breathing room inside the strip, as a fraction of it.
#
# Without these, a bar at full scale is exactly half the strip high and
# lands flush on the top and bottom edges, where it reads as CUT OFF
# rather than as loud — the WORKING pulses hit 1.0 routinely and looked
# clipped. The horizontal one keeps the first and last bar off the very
# edge for the same reason.
_VERTICAL_HEADROOM = 0.86
_HORIZONTAL_PAD_PX = 6.0

# The two switches (user, 2026-08-26). Drawn in the same colour as the
# wave and nothing else — no chrome, no border, no label. A sense that
# is ON is a solid glyph; one that is OFF is the same glyph dimmed, with
# a bar struck through it. Reading them costs a glance, which is the
# most a strip may ask for.
_SWITCH_ON = 0.85
_SWITCH_OFF = 0.28
# The themed icons, by switch and state. `-symbolic` on purpose: those
# are recoloured at paint time, so they arrive in the strip's own
# terracotta rather than in the theme's grey. The muted variants mean
# "off" needs no strike drawn over it.
_ICON_NAMES = {
    ("mic", True): "audio-input-microphone-symbolic",
    ("mic", False): "microphone-sensitivity-muted-symbolic",
    ("voice", True): "audio-volume-high-symbolic",
    ("voice", False): "audio-volume-muted-symbolic",
    ("text", True): "input-keyboard-symbolic",
    ("close", True): "window-close-symbolic",
}


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

        # His ears and his voice, and the only thing on the strip that
        # answers a press. `on_switch` is set by `__main__.py`, which is
        # the only place that knows how to actually stop a microphone.
        self.switches = Switches()
        # Themed icons, looked up on first paint (see `_icon`).
        self._icons: dict[str, object] = {}
        self.on_switch: Callable[[str, bool], None] = lambda _name, _on: None
        press = Gtk.GestureClick()
        press.connect("pressed", self._on_pressed)
        self.add_controller(press)

        self.add_tick_callback(self._tick)

    def set_state(self, state: WaveState) -> None:
        self.model.state = state
        self.bars.state = state
        self.waveform.state = state

    def set_level(self, level: float) -> None:
        self.model.set_level(level)
        self.bars.set_level(level)

    def set_task_count(self, count: int) -> None:
        """How many things she is doing, shown as one pulse each."""
        self.bars.set_task_count(count)

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

        self._snapshot_switches(snapshot, width, height)

    def _snapshot_columns(
        self,
        snapshot: Gtk.Snapshot,
        width: float,
        height: float,
        heights: list[float],
    ) -> None:
        centre = height / 2
        span = (height / 2) * _VERTICAL_HEADROOM
        # The switches get their own end of the strip. Drawing bars
        # under them makes both unreadable — measured by looking at it,
        # 2026-08-26 — and the wave losing a tenth of its width costs
        # nothing, because it has no left-to-right meaning.
        usable = max(
            1.0, width - 2 * _HORIZONTAL_PAD_PX - self._reserved(width, height)
        )
        slot = usable / len(heights)
        bar_width = max(_BAR_MIN_WIDTH_PX, slot * _BAR_FILL)
        # Centres each bar inside its own slot, so the row reads as
        # evenly spaced lines rather than as blocks butted together.
        offset = (slot - bar_width) / 2

        for i, value in enumerate(heights):
            half = max(_BAR_MIN_PX, value * span)
            rect = Graphene.Rect()
            # Mirrored about the centre line: a bar chart standing on the
            # bottom edge reads as a chart; this reads as an object.
            rect.init(
                _HORIZONTAL_PAD_PX + i * slot + offset,
                centre - half,
                bar_width,
                half * 2,
            )
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

    # ── the four switches ─────────────────────────────────────────────

    def _reserved(self, width: float, height: float) -> float:
        """Width the switches take at the right, or zero when there are none."""
        boxes = self.switches.boxes(width, height)
        if not boxes:
            return 0.0
        return width - boxes[0].x

    def _icon(self, name: str):
        """The themed icon for `name`, looked up once and kept.

        Real icons rather than rectangles drawn by hand (user,
        2026-08-26). They are `-symbolic`, so they are recoloured to the
        strip's terracotta at paint time instead of arriving grey.

        The display does not exist before the widget is realized, so the
        lookup happens on first paint and not in `__init__`.
        """
        if name in self._icons:
            return self._icons[name]
        icon = None
        try:
            display = self.get_display()
            if display is not None:
                theme = Gtk.IconTheme.get_for_display(display)
                icon = theme.lookup_icon(
                    name,
                    None,
                    int(SWITCH_SIZE),
                    1,
                    Gtk.TextDirection.NONE,
                    Gtk.IconLookupFlags.PRELOAD,
                )
        except Exception:
            # A missing icon theme costs the glyphs, never the wave.
            icon = None
        self._icons[name] = icon
        return icon

    def _snapshot_switches(
        self, snapshot: Gtk.Snapshot, width: float, height: float
    ) -> None:
        """Draw the four switches, each in the state it is in."""
        for box in self.switches.boxes(width, height):
            on = self.switches.is_on(box.name)
            name = _ICON_NAMES.get((box.name, on)) or _ICON_NAMES.get((box.name, True))
            if name is None:
                continue
            colour = Gdk.RGBA()
            colour.red, colour.green, colour.blue = (
                self._colour.red,
                self._colour.green,
                self._colour.blue,
            )
            if box.name == CLOSE and self.switches.armed(time.monotonic()):
                colour.alpha = 1.0
            else:
                colour.alpha = _SWITCH_ON if on else _SWITCH_OFF

            icon = self._icon(name)
            snapshot.save()
            snapshot.translate(Graphene.Point().init(box.x, box.y))
            try:
                if icon is None:
                    raise ValueError("no icon")
                icon.snapshot_symbolic(snapshot, box.size, box.size, [colour])
            except Exception:
                # No theme, or a paintable that is not symbolic: a plain
                # square still shows there is something to press.
                snapshot.append_color(
                    colour, Graphene.Rect().init(0, 0, box.size, box.size)
                )
            snapshot.restore()

    def _on_pressed(
        self, _gesture: Gtk.GestureClick, n_press: int, x: float, y: float
    ) -> None:
        if n_press > 1:
            # A double click emits `pressed` again with n_press=2, and
            # the close switch COUNTS presses — two of them shut him
            # down. Without this, double-clicking it skips the
            # confirmation entirely. Measured 2026-08-26: three
            # "interruptor" lines from one click.
            return
        action = self.switches.press(
            x,
            y,
            float(self.get_width()),
            float(self.get_height()),
            time.monotonic(),
        )
        # Always redraw: a first press on close changes nothing but the
        # picture, and that picture is the whole confirmation.
        self.queue_draw()
        if action is None:
            # The rest of the strip is not a button, and must not behave
            # like one. CLAUDE.md §1.5.
            return
        on = True if action == CLOSE else self.switches.is_on(action)
        self.on_switch(action, on)
