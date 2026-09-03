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

/* The line you type at him in. Terracotta text on the desktop showing
   through, like everything else here: it is part of the strip, not a
   dialog that landed on it. */
/* The typed line is a real `Gtk.Entry`, and since 2026-08-26 it LOOKS
   like one: the theme paints the field, the border and the focus ring,
   and this only sets the colour of the text and how much room it takes.
   An earlier version stripped all of that to match the strip, and the
   result read as something drawn rather than something you type in —
   "¿no puedes usar un input box real?" */
/* The lines something working is writing. Monospaced, dim, and dark —
   it is a thing to glance at, not to read. */
/* Padding inside the terminal and rounded corners that actually clip
   it: VTE draws its own background, so without `overflow: hidden` the
   frame's radius is a rounded border over a square black block. */
.samantha-console-frame {{
  overflow: hidden;
}}

.samantha-console-frame vte-terminal {{
  padding: 10px 12px;
}}

.samantha-console-frame {{
  background-color: rgba(20, 12, 14, 0.92);
  margin: 0 16px 6px 16px;
  border-radius: 8px;
  border: 1px solid rgba(209, 104, 78, 0.35);
}}

.samantha-console {{
  font-family: "Iosevka", "JetBrains Mono", monospace;
  font-size: 12px;
  color: #cbbfba;
  padding: 8px 12px;
}}

.samantha-prompt {{
  font-size: 15px;
  margin: 0 16px 8px 16px;
}}

.samantha-prompt,
.samantha-prompt > text {{
  /* Dark, so the field belongs to the strip instead of being a white
     hole in it — terracotta text on white was what the theme gave and
     it does not go together (user, 2026-08-26). The theme still draws
     the border and the focus ring, so it still reads as the real entry
     it is. */
  background-color: #1b1013;
  background-image: none;
}}

.samantha-prompt > text {{
  /* White, not terracotta. The colour is the strip's signature and it
     belongs to the wave and the icons; in a dark field at 15px it is
     just hard to read (user, 2026-08-26). The caret keeps it — one
     terracotta detail, where it helps you find the cursor. */
  color: #f2ece9;
  caret-color: {TERRACOTTA};
}}

.samantha-prompt > text > placeholder {{
  color: #f2ece9;
  opacity: 0.35;
}}

.samantha-ficha {{
  background-color: rgba(26, 17, 19, 0.97);
  margin: 0 16px 6px 16px;
  border-radius: 10px;
  border: 1px solid rgba(209, 104, 78, 0.45);
  padding: 18px 20px;
}}

.samantha-ficha-encabezado {{
  font-family: "Cormorant Garamond", Georgia, serif;
  font-size: 24px;
  color: #f7f2ef;
  padding-bottom: 6px;
}}

.samantha-ficha-parrafo {{
  font-family: "Inter Tight", sans-serif;
  font-size: 15px;
  color: #e0d6d1;
}}

.samantha-ficha-opcion {{
  font-family: "Inter Tight", sans-serif;
  font-size: 18px;
  color: #f7f2ef;
  background-color: rgba(209, 104, 78, 0.10);
  border-radius: 6px;
  padding: 8px 12px;
}}

.samantha-ficha-correcta {{ color: #d1684e; font-weight: 600; }}
.samantha-ficha-fallada {{ color: #97847d; text-decoration: line-through; }}
.samantha-ficha-apagada {{ color: #7b6a64; }}

.samantha-ficha-fuente {{
  font-family: "Inter Tight", sans-serif;
  font-size: 12px;
  color: #8d7c75;
}}

"""


# The console, when it is a real terminal (VTE). Given to the widget
# directly rather than through CSS: VTE paints its own background over
# anything a stylesheet says.
CONSOLE_BACKGROUND = "#170f11"
CONSOLE_FOREGROUND = "#d8ccc6"
CONSOLE_FONT = "monospace 10"
# Point size and line spacing, applied over whatever font is chosen.
CONSOLE_FONT_POINTS = 10.5
CONSOLE_LINE_SCALE = 1.15
