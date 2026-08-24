"""The GTK half of the photo band: a texture, and a click on it.

GSK only. Cairo does not work on this machine — PyGObject needs
`gi._gi_cairo` from `python3-gi-cairo`, which is not installed, and the
`TypeError` it raises is swallowed inside the draw callback, so the
strip appears and never draws (CLAUDE.md §2.3, and `wave.py`'s
docstring). `Gdk.Texture` + `Gtk.Snapshot.append_texture` needs neither.

State lives in `photo.py`, which imports no `gi` and is therefore
testable. Everything here is the part that cannot be: loading a file,
laying a texture into a snapshot, and hearing a button press.
"""

from __future__ import annotations

import sys
import time
from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Graphene", "1.0")

from gi.repository import Gdk, GLib, Graphene, Gtk  # noqa: E402

from .photo import PhotoModel, hits, tile_rects  # noqa: E402

# How often the band asks whether it is time to fade. Four times a
# second: nobody can see the difference against a 15 s timer, and it is
# far cheaper than the frame clock, which a zero-height widget cannot be
# relied on to receive anyway.
_TICK_MS = 250


class PhotoArea(Gtk.Widget):
    """The band above the wave. Zero pixels tall until there is something in it."""

    def __init__(self, on_resize: Callable[[int], None]) -> None:
        super().__init__()
        self.model = PhotoModel()
        self._on_resize = on_resize
        # path → texture, or None for a file that could not be loaded.
        # Cached both ways: retrying a missing file every frame would
        # hammer the disk at 60 Hz for as long as the band is up.
        self._textures: dict[str, Gdk.Texture | None] = {}
        self.set_size_request(-1, 0)
        self.set_vexpand(False)

        # The gesture is on THIS widget, not on the window: a click
        # anywhere else on the strip — on the wave, on the transparent
        # part — must go on doing nothing at all.
        gesture = Gtk.GestureClick()
        gesture.connect("pressed", self._on_pressed)
        self.add_controller(gesture)

        GLib.timeout_add(_TICK_MS, self._on_tick)

    # ── what the gateway does to it ───────────────────────────────────

    def show_photo(self, path: str, camera: str) -> None:
        if self.model.show(path, camera, time.monotonic()):
            self._apply()
        else:
            self.queue_draw()

    # ── what the user does to it ──────────────────────────────────────

    def _on_pressed(
        self, gesture: Gtk.GestureClick, _n: int, x: float, y: float
    ) -> None:
        if not self.model.visible:
            return
        rects = tile_rects(
            float(self.get_width()), float(self.get_height()), len(self._loadable())
        )
        if not hits(x, y, rects):
            # The band spans the whole strip and is almost all
            # transparent. Only the picture itself answers a press.
            return
        # Claimed so the press stops here. The strip has nothing else
        # that listens, and it is to stay that way.
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)
        if self.model.click(time.monotonic()):
            self._apply()

    def _on_tick(self) -> bool:
        if self.model.tick(time.monotonic()):
            self._apply()
        return True  # GLib.SOURCE_CONTINUE

    def _apply(self) -> None:
        height = self.model.height
        self.set_size_request(-1, height)
        self._forget_unused()
        self._on_resize(height)
        self.queue_draw()

    def _forget_unused(self) -> None:
        live = {p.path for p in self.model.photos}
        for path in list(self._textures):
            if path not in live:
                del self._textures[path]

    # ── drawing ───────────────────────────────────────────────────────

    def _texture(self, path: str) -> Gdk.Texture | None:
        if path not in self._textures:
            try:
                self._textures[path] = Gdk.Texture.new_from_filename(path)
            except Exception as exc:
                # The file was deleted, or the spool was cleaned between
                # the push and the draw. A missing photo is a photo that
                # is not shown, never a strip that dies.
                print(f"foto ilegible {path}: {exc}", file=sys.stderr, flush=True)
                self._textures[path] = None
        return self._textures[path]

    def _loadable(self) -> list[Gdk.Texture]:
        """The photos that actually opened, in order.

        A file that has gone — the spool prunes, and the strip is not
        told — is skipped rather than left as a hole, so the row of
        three that was pushed reads as a row of three.
        """
        found = (self._texture(photo.path) for photo in self.model.photos)
        return [texture for texture in found if texture is not None]

    def do_snapshot(self, snapshot: Gtk.Snapshot) -> None:
        width = float(self.get_width())
        height = float(self.get_height())
        if width <= 0 or height <= 0 or not self.model.visible:
            return

        textures = self._loadable()
        if not textures:
            return

        for texture, (x, y, w, h) in zip(
            textures, tile_rects(width, height, len(textures))
        ):
            rect = Graphene.Rect()
            rect.init(x, y, w, h)
            snapshot.append_texture(texture, rect)
