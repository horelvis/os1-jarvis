"""Render each wave state straight to a PNG, with no window involved.

A screenshot of the real strip is the honest check, but it needs a
session that is unlocked and a screen nobody has covered — during
development this fails constantly, and it fails by producing a
plausible image of something else. This renders the widget's own
snapshot to a texture offscreen, so the line either draws or it does
not, whatever the desktop is doing.

    python tools/render_wave.py /tmp/waves

It exercises the real code path: the same do_snapshot(), the same
GskPathBuilder, the same model. It cannot tell you whether the strip is
placed or on top — only a screenshot can.
"""

from __future__ import annotations

import sys
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gsk", "4.0")

from gi.repository import Gsk, Gtk  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis_widget import theme  # noqa: E402
from jarvis_widget.wave import WaveArea  # noqa: E402
from jarvis_widget.wave_model import WaveState  # noqa: E402

WIDTH = theme.STRIP_MAX_WIDTH
HEIGHT = theme.STRIP_HEIGHT

# Seconds of animation to run before drawing. The thinking packet
# crosses in 1.6 s, so a state photographed at t=0 shows nothing
# interesting; a third of the way in shows the packet mid-flight.
WARMUP = {
    WaveState.IDLE: 1.4,  # a quarter of the breath cycle
    WaveState.LISTENING: 1.0,
    WaveState.THINKING: 0.55,
    WaveState.SPEAKING: 1.0,
}


def render(state: WaveState, out: Path) -> None:
    area = WaveArea()
    area.set_state(state)
    if state in {WaveState.LISTENING, WaveState.SPEAKING}:
        area.model.set_level(0.7)

    # The tick callback needs a frame clock, which needs a window. Drive
    # the model by hand instead, at 60 fps, exactly as the clock would.
    for _ in range(int(WARMUP[state] * 60)):
        area.model.advance(1 / 60)

    snapshot = Gtk.Snapshot()
    # do_snapshot reads get_width()/get_height(), which are 0 for a
    # widget that was never allocated. Allocating it is what makes the
    # offscreen render draw the same geometry the real strip does.
    area.set_size_request(WIDTH, HEIGHT)
    area.allocate(WIDTH, HEIGHT, -1, None)
    area.do_snapshot(snapshot)

    node = snapshot.to_node()
    if node is None:
        raise SystemExit(f"{state.value}: nothing was drawn at all")

    renderer = Gsk.CairoRenderer()
    renderer.realize(None)
    texture = renderer.render_texture(node, None)
    texture.save_to_png(str(out))
    renderer.unrealize()
    print(f"{state.value:>10} -> {out}")


def main() -> int:
    out_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/waves")
    out_dir.mkdir(parents=True, exist_ok=True)
    for state in WaveState:
        render(state, out_dir / f"{state.value}.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
