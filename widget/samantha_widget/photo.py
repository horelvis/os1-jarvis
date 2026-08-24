"""The photo band, as pure state. No GTK in here, on purpose.

`photo_area.py` is the GTK half; this is the half that can be tested
without a display, exactly the way `wave_model.py` sits under `wave.py`.
The names are inverted relative to that pair — the model is `photo.py`
and the widget is `photo_area.py` — because the model is the part every
other module and every test talks to.

What it decides, and nothing else: how tall the strip has to be right
now, which photos are in the band, and when they go away. It never
touches a file, so a path that has since been deleted is somebody
else's problem (`photo_area.py` skips it) rather than a crash.
"""

from __future__ import annotations

from dataclasses import dataclass

# Extra height the strip takes on top of the 96 the wave keeps.
#
# 114 → 900x210 for the band-plus-wave; 384 → 900x480, which puts a
# single 16:9 frame at 654x368, near enough the 640x360 the camera
# grabs to read as "native size".
THUMB = 114
NATIVE = 384

# It goes away on its own. A photo that stays is a window, and §1.5 of
# CLAUDE.md is that there are no windows here.
FADE_S = 15.0

# Two photos that arrive inside this window are one answer — "enséñame
# la casa" looks at every camera and pushes a frame per camera,
# milliseconds apart. Later than this and it is a new question.
BATCH_S = 2.0

# Beyond four they are too small to read, and four at 174 px wide
# already fill most of 900. The oldest of a batch is dropped rather
# than the strip growing wider.
MAX_PHOTOS = 4

# Room inside the band, and between two photos in it.
PAD = 8.0
GAP = 8.0

# What the cameras hand over: 16:9. The tiles are laid out to this
# rather than to each file's real size, so a batch is a tidy row even
# when one camera is a different resolution.
ASPECT = 16.0 / 9.0


@dataclass(frozen=True)
class Photo:
    """One frame on the band."""

    path: str
    camera: str


class PhotoModel:
    """Which photos the strip is showing, how tall it must be, and until when.

    Every method that can change the height returns True when it did, so
    the caller knows whether to spend an EWMH round-trip. The second
    photo of a batch returns False for exactly that reason.
    """

    def __init__(self) -> None:
        self.photos: list[Photo] = []
        self._enlarged = False
        # When the fade clock started, and when the last photo landed.
        # They are different clocks: a click restarts the fade without
        # extending the batch.
        self._since = 0.0
        self._last_show = 0.0

    # ── what the widget asks ──────────────────────────────────────────

    @property
    def visible(self) -> bool:
        return bool(self.photos)

    @property
    def height(self) -> int:
        """Extra pixels the strip needs above the wave, right now."""
        if not self.photos:
            return 0
        return NATIVE if self._enlarged else THUMB

    # ── what the world does to it ─────────────────────────────────────

    def show(self, path: str, camera: str, now: float) -> bool:
        """A photo arrived. True when the strip has to change size."""
        before = self.height
        if not self.photos or now - self._last_show > BATCH_S:
            # A new question. The previous batch does not linger next to
            # the answer to a different one.
            self.photos = []
            self._enlarged = False
            self._since = now
        self.photos.append(Photo(path=path, camera=camera))
        # Oldest first out: the last camera asked about is the one most
        # likely to be the one meant.
        del self.photos[:-MAX_PHOTOS]
        self._last_show = now
        return self.height != before

    def click(self, now: float) -> bool:
        """Enlarge the batch, or — the second time — put it away.

        There is no per-photo gesture. Picking one of four would be a
        UI, and the strip is not one; the whole row grows together.
        """
        if not self.photos:
            return False
        before = self.height
        if not self._enlarged:
            self._enlarged = True
            # Looking at it counts as interest: the fade starts again.
            self._since = now
        else:
            self.photos = []
            self._enlarged = False
        return self.height != before

    def tick(self, now: float) -> bool:
        """Let time pass. True when the strip has to change size."""
        if not self.photos:
            return False
        if now - self._since < FADE_S:
            return False
        self.photos = []
        self._enlarged = False
        return True


def tile_rects(
    width: float, height: float, count: int
) -> list[tuple[float, float, float, float]]:
    """Where `count` photos go inside a band `width` x `height`.

    Fitted to the width first and then clamped by the height, which is
    what makes the answers to the two awkward cases fall out on their
    own: four thumbnails shrink to fit the row instead of the strip
    growing wider, and a click with two photos enlarges them to the
    widest pair that fits 900 rather than to a native size that does
    not.
    """
    if count <= 0:
        return []
    usable_w = max(1.0, width - 2 * PAD)
    usable_h = max(1.0, height - 2 * PAD)

    tile_w = max(1.0, (usable_w - (count - 1) * GAP) / count)
    tile_h = tile_w / ASPECT
    if tile_h > usable_h:
        tile_h = usable_h
        tile_w = tile_h * ASPECT

    row_w = count * tile_w + (count - 1) * GAP
    x = (width - row_w) / 2
    y = (height - tile_h) / 2
    return [(x + i * (tile_w + GAP), y, tile_w, tile_h) for i in range(count)]


def hits(x: float, y: float, rects: list[tuple[float, float, float, float]]) -> bool:
    """Did a press at (x, y) land on one of these photos?

    The band is as wide as the strip and mostly transparent, so without
    this a press on empty air two centimetres from the picture would
    enlarge it — a thing happening where the user can see nothing to
    press. The photos are the only part of the strip that reacts to a
    pointer at all, and this is what keeps that true.
    """
    return any(rx <= x < rx + rw and ry <= y < ry + rh for rx, ry, rw, rh in rects)
