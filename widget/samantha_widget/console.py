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

import os

# How many lines are kept, and so how tall the strip can get: the height
# below is this times a line. Twenty since 2026-08-27, at the user's
# asking — ten was chosen so the strip would not become a panel, and
# what it actually produced was a terminal you could not read a tool's
# output in. Twenty lines at the measured ~20 px is about 430 px of
# strip, which is the live camera's 480 and no more.
MAX_LINES = int(os.environ.get("SAMANTHA_WIDGET_CONSOLE_LINES") or 20)

# One line, in pixels, at the console font size — and the room the
# frame takes around them. The strip grows by what the CONTENT needs up
# to MAX_LINES, rather than by a fixed block: three lines in a box sized
# for twenty is mostly empty box, and it showed (2026-08-26).
LINE_HEIGHT = 15
# The frame around the lines: 10 px of terminal padding top and bottom
# (theme.CSS), its border, and the margin under it. Measured by counting
# the lines that fit — 22 was one line short.
PADDING = 34
HEIGHT = LINE_HEIGHT * MAX_LINES + PADDING

# How long it stays up after the work has finished. There has to be a
# way out that costs nothing — a strip left at four times its height all
# afternoon because nobody clicked is worse than one that closes while
# you were still reading, since the work can be asked for again and the
# desktop underneath cannot. A minute is long enough to read the closing
# lines. A click closes it sooner (`photo_area` has done the same for a
# photo since 2026-08-25), and any new output cancels it: output means
# the run is alive, whatever the marker said.
LINGER_SECONDS = float(os.environ.get("SAMANTHA_WIDGET_CONSOLE_LINGER", "60"))

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
        # When the work said it was over, or None while it is running.
        # Not a countdown: the clock is read at each tick, so a widget
        # that was busy elsewhere does not lose the deadline.
        self.finished_at: float | None = None

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
        # Anything arriving means the run is alive. An `END` marker can
        # be followed by more output — a wrapper writing after the child
        # exits — and closing over the top of it would be a bug the user
        # sees as flicker.
        self.finished_at = None
        for raw in text.splitlines():
            line = raw.rstrip()
            if not line.strip():
                # Blank lines are most of a tool's output and none of
                # its meaning. Kept out so the lines kept are content.
                continue
            self.lines.append(line[:MAX_LINE_CHARS])
        del self.lines[: -self.max_lines]
        return self.height != before

    def finish(self, now: float) -> None:
        """The work is over. Start the clock that puts this away."""
        if self.lines:
            self.finished_at = now

    def tick(self, now: float) -> bool:
        """Let time pass. True when the strip has to change size."""
        if self.finished_at is None:
            return False
        if now - self.finished_at < LINGER_SECONDS:
            return False
        return self.clear()

    def clear(self) -> bool:
        """Put it away. True when the strip has to change size."""
        before = self.height
        self.lines = []
        self.finished_at = None
        return self.height != before

    def text(self) -> str:
        """The block to draw, oldest first."""
        return "\n".join(self.lines)
