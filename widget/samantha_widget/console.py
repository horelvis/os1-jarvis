"""What the assistant is doing, as lines on the strip.

Pure state, no GTK — the split `photo.py` and `wave_model.py` already
make. `window.py` draws what this decides.

The user's idea, 2026-08-26: *"podemos abrir una terminal estilo las
cámaras para la salida de Claude Code"*. The band above the wave already
grows for a photo and for a live camera; this is the same gesture for
text. Nothing new appears on the desktop and no window is opened — it
grows when there is something to show and goes away when there is not.

Two things it deliberately is not:

- **Not a scrollback.** It holds the last few lines and drops the rest.
  Somewhere to glance, not somewhere to read backwards; a history is a
  window, and §1.5 says this is not one.
- **Not interactive.** Nothing is typed into it. The instruction goes in
  through the strip's own line (`window.py`'s entry); this only shows
  what came back.
"""

from __future__ import annotations

# How many lines are kept. Ten is about what fits in the height below
# without the strip becoming a panel, and about as far back as a glance
# is worth.
MAX_LINES = 10

# One line, in pixels, at the console font size — and the room the
# frame takes around them. The strip grows by what the CONTENT needs up
# to MAX_LINES, rather than by a fixed block: three lines in a box sized
# for ten is mostly empty box, and it showed (2026-08-26).
LINE_HEIGHT = 15
# The frame around the lines: 10 px of terminal padding top and bottom
# (theme.CSS), its border, and the margin under it. Measured by counting
# the lines that fit — 22 was one line short.
PADDING = 34
HEIGHT = LINE_HEIGHT * MAX_LINES + PADDING

# Longer than this and a line is cut: a single 4,000-character blob from
# a tool would otherwise push everything else out of the window and wrap
# into a wall.
MAX_LINE_CHARS = 200


class Console:
    """The last few lines of whatever is working, and whether to show them."""

    def __init__(self, max_lines: int = MAX_LINES) -> None:
        self.max_lines = max_lines
        self.lines: list[str] = []
        # Overwritten with the terminal's real character height once
        # there is one to ask (see `window.write_console`). The constant
        # is only the guess used before the widget exists.
        self.line_height = LINE_HEIGHT

    @property
    def visible(self) -> bool:
        return bool(self.lines)

    @property
    def height(self) -> int:
        """Extra pixels the strip needs for this, right now.

        Grows with the content to a ceiling: what is on screen is what
        there is to see, and the strip goes back down when it is put
        away.
        """
        if not self.lines:
            return 0
        return min(len(self.lines), self.max_lines) * self.line_height + PADDING

    def write(self, text: str) -> bool:
        """Add lines. True when the strip has to change size.

        Accepts a blob with newlines in it, because that is what a
        process hands over: splitting is this module's job rather than
        every caller's.
        """
        before = self.height
        for raw in text.splitlines():
            line = raw.rstrip()
            if not line.strip():
                # Blank lines are most of a tool's output and none of
                # its meaning. Kept out so ten lines are ten of content.
                continue
            self.lines.append(line[:MAX_LINE_CHARS])
        del self.lines[: -self.max_lines]
        return self.height != before

    def clear(self) -> bool:
        """Put it away. True when the strip has to change size."""
        before = self.height
        self.lines = []
        return self.height != before

    def text(self) -> str:
        """The block to draw, oldest first."""
        return "\n".join(self.lines)
