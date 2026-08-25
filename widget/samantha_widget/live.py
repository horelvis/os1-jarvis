"""The live band, as pure state. No GTK in here, on purpose.

The twin of `photo.py`, and it follows the same convention: every method
that can change the height returns True when it did, so the caller knows
whether to spend an EWMH round-trip.
"""

from __future__ import annotations

from .photo import NATIVE

# A live view opens at the large size. A 114-pixel thumbnail of video is
# useless — you cannot see who is at the door in it — so unlike a photo
# there is no small state to grow out of.
LIVE_HEIGHT = NATIVE


class LiveModel:
    """Which live view the strip is showing, and how tall it must be."""

    def __init__(self) -> None:
        self.camera: str | None = None
        self.epoch: int | None = None
        self._since = 0.0

    @property
    def visible(self) -> bool:
        return self.camera is not None

    @property
    def height(self) -> int:
        """Extra pixels the strip needs above the wave, right now."""
        return LIVE_HEIGHT if self.camera is not None else 0

    def open(self, camera: str, epoch: int, now: float) -> bool:
        """A view started. True when the strip has to change size."""
        before = self.height
        self.camera = camera
        self.epoch = epoch
        self._since = now
        return self.height != before

    def close(self, epoch: int | None, now: float) -> bool:
        """A view ended. True when the strip has to change size.

        `epoch=None` means "whatever is up" — the socket dropped, and
        there is no frame to carry a number (spec §4.2). A close naming
        an older view is stale and changes nothing.
        """
        if self.camera is None:
            return False
        if epoch is not None and epoch != self.epoch:
            return False
        before = self.height
        self.camera = None
        self.epoch = None
        return self.height != before

    def accepts(self, epoch: int) -> bool:
        """Is this frame for the view that is up?"""
        return self.epoch is not None and epoch == self.epoch
