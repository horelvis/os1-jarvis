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

from .live import LiveModel  # noqa: E402
from .live_decode import LiveDecoder  # noqa: E402
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
        self.live = LiveModel()
        self._decoder = LiveDecoder(on_overflow=self._on_overflow)
        # The newest decoded picture, built on the main thread from
        # whatever the decoder thread last produced. None until the
        # first frame of a view arrives.
        self._live_texture: Gdk.Texture | None = None
        self._on_resize = on_resize
        # path → texture, or None for a file that could not be loaded.
        # Cached both ways: retrying a missing file every frame would
        # hammer the disk at 60 Hz for as long as the band is up.
        self._textures: dict[str, Gdk.Texture | None] = {}
        # The height the window has actually been told about. Compared
        # against, so a batch's second photo does not spend a second
        # EWMH round-trip on a size that has not changed.
        self._applied = 0
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
        self.model.show(path, camera, time.monotonic())
        # `_apply` decides whether the size actually changed. It cannot
        # be left to the model's return value any more: the model does
        # not know that a file failed to open, and the height depends on
        # that (see `_wanted_height`).
        self._apply()

    def live_open(
        self, camera: str, epoch: int, extradata: bytes, width: int, height: int
    ) -> None:
        """A live view started. Runs on the GTK thread (via idle_add).

        `width`/`height` are the stream's nominal size, carried through
        for anyone who logs this; the tile itself is laid out to the
        band's fixed 16:9, the same as a photo, not to the video's real
        aspect. Any view already up — a different camera, or a retry of
        this one — is torn down first: a new epoch means a new decoder.
        """
        self._decoder.stop()
        self._live_texture = None
        self.live.open(camera, epoch, time.monotonic())
        self._decoder.start(extradata)
        self._apply()

    def live_frame(self, epoch: int, packet: bytes) -> None:
        """A packet arrived. NOT on the GTK thread — see the module docstring.

        Deliberately does nothing with `_apply` or `queue_draw`: `feed`
        must never block, and neither can this.
        """
        if not self.live.accepts(epoch):
            return
        self._decoder.feed(packet)

    def live_end(self, epoch: int, reason: str) -> None:
        """A view ended. Runs on the GTK thread (via idle_add or `_on_overflow`)."""
        if not self.live.close(epoch, time.monotonic()):
            # Nothing was up, or this named a view that already ended —
            # in either case there is nothing here to tear down, and a
            # newer view (if any) must be left running.
            return
        self._decoder.stop()
        self._live_texture = None
        self._apply()

    def live_rect(self) -> tuple[float, float, float, float] | None:
        """Where the live picture is drawn, in this widget's own coordinates.

        None while there is no view up. `do_snapshot` paints exactly this
        rectangle; a caller outside the widget (Task 11's X11 input
        region) reads it from here rather than recomputing it, because
        two computations of the same rectangle drift, and the symptom is
        clicks landing next to the picture instead of on it.
        """
        if not self.live.visible:
            return None
        width = float(self.get_width())
        height = float(self.get_height())
        if width <= 0 or height <= 0:
            return None
        return tile_rects(width, height, 1)[0]

    def _on_overflow(self) -> None:
        """The decoder fell too far behind to keep up.

        Called from whichever thread was feeding it a packet — the
        gateway's asyncio thread in real use, never the GTK thread — so
        closing has to cross back through `idle_add` like every other
        GTK-bound call the gateway triggers.
        """
        epoch = self.live.epoch
        if epoch is not None:
            GLib.idle_add(self.live_end, epoch, "atascado")

    # ── what the user does to it ──────────────────────────────────────

    def _on_pressed(
        self, gesture: Gtk.GestureClick, _n: int, x: float, y: float
    ) -> None:
        if self.live.visible:
            # There is no per-photo gesture here either: a click ON the
            # picture is the only thing this row answers, and for a live
            # view it means one thing — close it. This is the way out
            # spec §9.4 leans on, on a box with no microphone.
            rect = self.live_rect()
            if rect is not None and hits(x, y, [rect]):
                gesture.set_state(Gtk.EventSequenceState.CLAIMED)
                epoch = self.live.epoch
                if epoch is not None:
                    self.live_end(epoch, "click")
            return
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
        # PyGObject reads a raised callback as SOURCE_REMOVE, so an
        # exception in here does not cost one tick — it costs the fade
        # forever, and the band stays up with the strip grown around it.
        # `_apply` reaches all the way out to X through `resize_to`,
        # which is a long way for nothing to go wrong.
        try:
            if self.model.tick(time.monotonic()):
                self._apply()
        except Exception as exc:
            print(
                f"la banda falló al desvanecerse: {exc!r}", file=sys.stderr, flush=True
            )

        frame = self._decoder.take()
        if frame is not None:
            # Built here, on the main thread, from the plain buffer the
            # decoder thread produced. `Gdk.MemoryTexture.new` does not
            # copy, so this is cheap even at 25 Hz.
            self._live_texture = Gdk.MemoryTexture.new(
                frame.width,
                frame.height,
                Gdk.MemoryFormat.R8G8B8,
                GLib.Bytes.new(frame.data),
                frame.stride,
            )
            self.queue_draw()

        return True  # GLib.SOURCE_CONTINUE

    def _wanted_height(self) -> int:
        """How tall the band should be, given what can actually be drawn.

        `PhotoModel.height` is the answer for photos that exist. A push
        whose file has already gone would otherwise grow the strip by
        114 px of nothing and hold it there for the full fifteen
        seconds — the failure that is worse than not showing the photo,
        because it is visible and says nothing.

        A live view has no such failure mode — it needs no file — so it
        is not gated the same way. The two cannot fight over the
        window's height: whichever wants more wins.
        """
        photo_height = self.model.height if self._loadable() else 0
        return max(photo_height, self.live.height)

    def _apply(self) -> None:
        self._forget_unused()
        height = self._wanted_height()
        self.set_size_request(-1, height)
        if height != self._applied:
            self._applied = height
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
        if width <= 0 or height <= 0:
            return

        if self.live.visible and self._live_texture is not None:
            # Same geometry the photo row uses for a single tile — this
            # is also exactly what `live_rect` hands to a caller outside
            # the widget, so the two never disagree about where the
            # picture is.
            x, y, w, h = tile_rects(width, height, 1)[0]
            rect = Graphene.Rect()
            rect.init(x, y, w, h)
            snapshot.append_texture(self._live_texture, rect)
            return

        if not self.model.visible:
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
