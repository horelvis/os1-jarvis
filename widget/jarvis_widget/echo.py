"""Taking his own voice back out of what the microphone heard.

The room has a speaker and a microphone in it, so the microphone hears
him. Until 2026-08-26 the answer was to stop listening while he spoke
(`JARVIS_WIDGET_MIC_GATE`), which works and costs the one thing the
user asked for: you cannot interrupt somebody who is not listening.

Acoustic echo cancellation is the proper fix and it is configured
(`~/.config/pipewire/pipewire.conf.d/99-echo-cancel.conf`). Measured
that evening, with the widget genuinely capturing from
`echo-cancel-source` and playing into `echo-cancel-sink` — verified in
`pw-link` — his own sentence still came back in the transcript, mixed
in with a real person's voice. The canceller helps; it does not clear.

So this is the second line, and it works on text rather than on audio,
which is where we have an unfair advantage: the widget knows exactly
what it just said. Anything in the transcript that matches a line he
spoke moments ago is his echo and is cut out; whatever else was said in
the room survives. The measured case, verbatim:

    said:  "Buenas tardes, señor. Le cuento algo un poco más largo…"
    heard: "Hey Jarvis, me llamo Rebeca. Buenas tardes señor, le cuento
            algo un poco más largo… Hey Jarvis, me llamo Rebeca."
    kept:  "Hey Jarvis, me llamo Rebeca. Hey Jarvis, me llamo Rebeca."

It cannot separate a person who says the same words at the same time,
and does not try. That trade buys back interruption.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

# How long a spoken line stays worth checking against. Long enough to
# cover a reply still coming back through the room, short enough that
# repeating him a minute later is heard as your own words.
MEMORY_SECONDS = 45.0

# How much of one of his lines has to appear in the transcript before
# that stretch is called an echo. Whisper mangles the tail of a line
# played through a speaker, so this is well under 1.0 — and high enough
# that an ordinary sentence sharing a few words with his does not match.
MATCH_RATIO = 0.6

# Below this many characters a line is not distinctive enough to match
# on: "Sí, señor." would eat a person saying the same.
MIN_LINE_CHARS = 12


def _fold(text: str) -> str:
    """Lowercase, unaccented, punctuation-free — for comparison only."""
    lowered = unicodedata.normalize("NFD", text.lower())
    stripped = "".join(c for c in lowered if unicodedata.category(c) != "Mn")
    return "".join(c if c.isalnum() or c.isspace() else " " for c in stripped)


@dataclass
class _Line:
    folded: str
    at: float


class EchoFilter:
    """What he said recently, and how to take it back out of what he heard."""

    def __init__(
        self,
        *,
        memory: float = MEMORY_SECONDS,
        ratio: float = MATCH_RATIO,
    ) -> None:
        self.memory = memory
        self.ratio = ratio
        self._lines: list[_Line] = []

    def spoke(self, text: str, now: float) -> None:
        """Remember a line he just said out loud."""
        # NOT collapsed: `_fold` maps one character to one character, so
        # an offset in the folded transcript is the same offset in the
        # original — which is what lets the cut keep accents and
        # punctuation. Collapsing here broke that alignment and left
        # fragments of his own line behind.
        folded = _fold(text)
        if len(folded.strip()) < MIN_LINE_CHARS:
            return
        self._lines.append(_Line(folded, now))
        self._forget(now)

    def _forget(self, now: float) -> None:
        self._lines = [ln for ln in self._lines if now - ln.at <= self.memory]

    def clean(self, heard: str, now: float) -> str:
        """`heard` with his own recent words cut out of it.

        Returns "" when the whole transcript was his — which is the
        common case, and the one that used to become a turn.
        """
        self._forget(now)
        if not heard.strip() or not self._lines:
            return heard

        # Work on the folded text to find WHERE the echo is, then cut the
        # same span out of the original, so what survives keeps its
        # accents and punctuation for the gateway.
        folded = _fold(heard)
        spans: list[tuple[int, int]] = []
        for line in self._lines:
            # Every matching block, not just the longest: a line coming
            # back through a room is transcribed with words dropped and
            # commas moved, so the longest single run can be a fraction
            # of it. What is cut is from the start of the first block to
            # the end of the last, once enough of the line is accounted
            # for in total.
            blocks = [
                b
                for b in SequenceMatcher(
                    None, folded, line.folded
                ).get_matching_blocks()
                if b.size > 3
            ]
            if not blocks:
                continue
            covered = sum(b.size for b in blocks)
            if covered < self.ratio * len(line.folded.strip()):
                continue
            spans.append((blocks[0].a, blocks[-1].a + blocks[-1].size))

        if not spans:
            return heard

        # Cut from the end so earlier offsets stay valid.
        kept = heard
        for start, end in sorted(spans, reverse=True):
            kept = kept[:start] + " " + kept[end:]
        return " ".join(kept.split())
