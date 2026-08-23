"""The one colour, the geometry constants, and the CSS.

These are the numbers that get tuned by eye against a screenshot, so
they live together in one block rather than scattered through the
window code.
"""

from __future__ import annotations

# The exact background colour from the film (CLAUDE.md §10).
TERRACOTTA = "#d1684e"
# The wave, drawn on it. A single warm off-white; no second hue.
LINE = "#f6ece7"

STRIP_HEIGHT = 96
STRIP_MAX_WIDTH = 1100
SIDE_MARGIN = 48
BOTTOM_MARGIN = 48
CORNER_RADIUS = 18

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
  background-color: {TERRACOTTA};
  border-radius: {CORNER_RADIUS}px;
}}
"""
