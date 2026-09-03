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
# desktop shows through and only the line is JARVIS — she stops being
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

.jarvis-strip {{
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
.jarvis-console-frame {{
  overflow: hidden;
}}

.jarvis-console-frame vte-terminal {{
  padding: 10px 12px;
}}

.jarvis-console-frame {{
  background-color: rgba(20, 12, 14, 0.92);
  margin: 0 16px 6px 16px;
  border-radius: 8px;
  border: 1px solid rgba(209, 104, 78, 0.35);
}}

.jarvis-console {{
  font-family: "Iosevka", "JetBrains Mono", monospace;
  font-size: 12px;
  color: #cbbfba;
  padding: 8px 12px;
}}

.jarvis-prompt {{
  font-size: 15px;
  margin: 0 16px 8px 16px;
}}

.jarvis-prompt,
.jarvis-prompt > text {{
  /* Dark, so the field belongs to the strip instead of being a white
     hole in it — terracotta text on white was what the theme gave and
     it does not go together (user, 2026-08-26). The theme still draws
     the border and the focus ring, so it still reads as the real entry
     it is. */
  background-color: #1b1013;
  background-image: none;
}}

.jarvis-prompt > text {{
  /* White, not terracotta. The colour is the strip's signature and it
     belongs to the wave and the icons; in a dark field at 15px it is
     just hard to read (user, 2026-08-26). The caret keeps it — one
     terracotta detail, where it helps you find the cursor. */
  color: #f2ece9;
  caret-color: {TERRACOTTA};
}}

.jarvis-prompt > text > placeholder {{
  color: #f2ece9;
  opacity: 0.35;
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


# The card's stylesheet, and it is WEB css rather than GTK's: since
# 2026-09-03 the card is drawn by WebKitGTK (§12), so this is what goes
# inside the document `ficha_html.a_html` builds. It carries the same
# values the console's GTK panel does — the same panel colour, the same
# terracotta border, the same radius — because a card that looked like
# something else would read as a different application landing on the
# strip.
FICHA_CSS = f"""
  html, body {{ margin: 0; padding: 0; background: transparent; }}
  body {{
    font-family: "Inter Tight", system-ui, sans-serif;
    font-size: 18px; color: #f7f2ef;
    background: rgba(26, 17, 19, 0.97);
    border: 1px solid rgba(209, 104, 78, 0.45);
    border-radius: 10px;
    padding: 18px 20px;
    box-sizing: border-box;
  }}
  h1, h2, h3 {{
    font-family: "Cormorant Garamond", Georgia, serif;
    font-weight: 600; font-size: 24px; color: #f7f2ef;
    margin: 0 0 10px 0; line-height: 1.15;
  }}
  p {{ font-size: 15px; color: #e0d6d1; margin: 0 0 10px 0; }}
  code {{ font-family: "JetBrains Mono", monospace; font-size: 14px;
          color: #e8b6a5; background: rgba(209,104,78,0.12);
          padding: 1px 5px; border-radius: 3px; }}
  img {{ max-width: 100%; border-radius: 6px; display: block;
         margin: 0 0 10px 0; }}
  ul, ol {{ margin: 0; padding: 0; list-style: none; }}
  li {{ margin: 0 0 9px 0; }}
  /* markdown-it wraps a list item in <p> when the list is "loose" —
     items separated by blank lines, which is what a paginated card
     produces. A block there puts the counter on its own line. */
  li p {{ display: inline; margin: 0; }}

  /* The answer set. Lettered for a question — "la b" spoken out loud
     needs something on screen to point at — and numbered for a
     syllabus, where the order is the content. */
  .opciones li, .plan li {{
    background: rgba(209, 104, 78, 0.10);
    border-radius: 6px; padding: 8px 12px;
    counter-increment: opcion;
  }}
  .opciones li::before, .plan li::before {{
    font-family: "JetBrains Mono", monospace;
    font-size: 14px; color: {TERRACOTTA};
    margin-right: 10px;
  }}
  .opciones li::before {{ content: counter(opcion, lower-alpha) ". "; }}
  .plan li::before {{ content: counter(opcion, decimal) ". "; }}
  body {{ counter-reset: opcion; }}

  /* One colour, not two (§1.3): the right answer is terracotta, a wrong
     one is dimmer and struck through. Green and red would be a second
     and a third. */
  .correcta {{ color: {TERRACOTTA}; font-weight: 600; }}
  .fallada {{ color: #97847d; text-decoration: line-through; }}
  .apagada {{ color: #7b6a64; }}

  .fuente {{ font-size: 12px; color: #8d7c75; margin: 4px 0 0 0; }}
"""
