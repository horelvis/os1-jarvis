"""The one colour, the geometry constants, and the CSS.

These are the numbers that get tuned by eye against a screenshot, so
they live together in one block rather than scattered through the
window code.
"""

from __future__ import annotations

# The exact background colour from the film (CLAUDE.md §10).
TERRACOTTA = "#d1684e"
# The wave itself. Terracotta, now that there is no terracotta panel
# behind it to sit on: the one colour moved from the background to the
# line when the background went away.
LINE = TERRACOTTA

# What the strip is filled with. Transparent (user, 2026-08-23), so the
# desktop shows through and only the line is Samantha — she stops being
# a panel and becomes something drawn on the screen.
#
# This needs a compositing window manager, which GNOME is. Without one
# an RGBA visual is unavailable and the transparent area paints BLACK
# rather than falling back to something reasonable; set TERRACOTTA here
# to get the solid bar back.
BACKGROUND = "transparent"

# Which visualiser is drawn. All three are implemented and all three are
# driven by the same audio:
#   "bars"     — an equaliser: one bar per frequency band, via FFT.
#                Bars stay put and change height; nothing travels.
#   "waveform" — one bar per instant, newest in the MIDDLE and older
#                travelling out to both edges (user's choice 2026-08-23)
#   "line"     — the horizontal wave of CLAUDE.md §12
VISUALIZER = "bars"

STRIP_HEIGHT = 96
# A fixed width, centred (user, 2026-08-23). It went full-width earlier
# the same day and that was the wrong call: an equaliser stretched across
# 1854 px reads as a status bar, and the visualiser it was modelled on
# occupies a block in the middle of the frame. 0 restores full width.
STRIP_MAX_WIDTH = 900
SIDE_MARGIN = 0
BOTTOM_MARGIN = 0
# Square corners: a rounded rectangle reads as a window, and edge to
# edge there is nothing for the radius to round against anyway.
CORNER_RADIUS = 0

# GTK4 paints a shadow around the window even with decoration off — in a
# screenshot it reads as a grey halo, and a halo is what makes a thing
# look like a window instead of an object. Both the `decoration` node and
# the window node are cleared because which one carries the shadow
# depends on whether the compositor gave us client-side decorations.
CSS = f"""
window,
window.csd,
window.solid-csd {{
  background: transparent;
  box-shadow: none;
  border: none;
}}

window decoration {{
  box-shadow: none;
  border: none;
  margin: 0;
  background: transparent;
}}

.samantha-strip {{
  background-color: {BACKGROUND};
  border-radius: {CORNER_RADIUS}px;
}}
"""
