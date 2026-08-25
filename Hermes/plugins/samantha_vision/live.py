"""One live view: which camera, since when, and the one way out.

The tap runs on the watcher thread and the pushes are coroutines living
on the gateway's loop, so this class is the seam between the two.

It holds no lock, and more than the epoch crosses threads unlocked:
`camera`, `_started`, `_keyframe_seen` and `_loop` are all written by
`open()`/`close()` on the gateway thread and read by `_on_packet` on the
watcher thread. That is tolerable not because the reads and writes
cannot race, but because of what a stale read can do: every tap
installed by `open()` is bound to the camera it was opened for (see
`_bind_tap`), so a packet arriving from a camera that has stopped being
"the" view is dropped by comparing that bound name against `self.camera`
— before it can touch `self.epoch` or reach a push. The epoch stamps a
push that already knows it is talking about the right camera; it does
not decide that on its own. (An earlier version of this docstring
claimed the epoch alone was enough. It was not — a packet already in
flight when a view switched could be stamped with the NEW epoch and
pushed as if it belonged to it. Binding the camera into the tap is what
actually closes that.)

What the tap does when it decides a frame should go out is schedule a
coroutine — it never awaits.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Callable, Coroutine

from loguru import logger

from .cameras import redact

# How long a view may stay up with nobody closing it. OURS, and a guess:
# it is NOT one of BarnDoor's four calibrated constants (180, 0.7, 23:00,
# 07:00) and must not be filed beside them. It exists because closing
# depends on him hearing you, and this box has no microphone plugged in
# (CLAUDE.md §4) — without it, one misheard sentence feeds a window all
# night.
CEILING_SECONDS = 120.0

PushOpen = Callable[[str, int, bytes, int, int], Coroutine[Any, Any, bool]]
PushFrame = Callable[[int, bytes], Coroutine[Any, Any, bool]]
PushClose = Callable[[int, str], Coroutine[Any, Any, bool]]


class LiveSession:
    """The one live view there is. Never raises at its callers."""

    def __init__(
        self,
        fleet: Any,
        push_open: PushOpen,
        push_frame: PushFrame,
        push_close: PushClose,
        *,
        now: Callable[[], float] = time.monotonic,
        ceiling: float = CEILING_SECONDS,
    ) -> None:
        self._fleet = fleet
        self._push_open = push_open
        self._push_frame = push_frame
        self._push_close = push_close
        self._now = now
        self._ceiling = ceiling

        self.camera: str | None = None
        self.epoch = 0
        self.expired = False
        self._started = 0.0
        self._keyframe_seen = False
        self._loop: asyncio.AbstractEventLoop | None = None

    async def open(
        self, camera: str, *, extradata: bytes, size: tuple[int, int]
    ) -> bool:
        """Start a view. False when the strip did not take it.

        A second view closes the first rather than refusing: he was asked
        for the garage while the entrance was up, and answering "no" to
        that would be a worse answer than doing it.
        """
        if self.camera is not None:
            await self.close("asked")

        self.epoch += 1
        width, height = size
        try:
            opened = await self._push_open(camera, self.epoch, extradata, width, height)
        except Exception as exc:
            # Believing the push promises never to raise is not the same
            # as depending on it (tool.py's `mirar` makes the same call).
            # A view is never worth crashing a turn over.
            logger.warning(f"samantha-vision: live_open not delivered — {redact(exc)}")
            return False
        if not opened:
            # No strip, no view. Opening one anyway would leave a decoder
            # feeding a socket nobody is reading.
            return False

        self.camera = camera
        self.expired = False
        self._started = self._now()
        self._keyframe_seen = False
        self._loop = asyncio.get_running_loop()
        self._fleet.set_tap(camera, self._bind_tap(camera))
        return True

    async def close(self, reason: str) -> bool:
        """End the view. False when there was nothing to end."""
        camera, self.camera = self.camera, None
        if camera is None:
            return False
        self._fleet.clear_tap(camera)
        try:
            await self._push_close(self.epoch, reason)
        except Exception as exc:
            logger.warning(f"samantha-vision: live_end not delivered — {redact(exc)}")
        return True

    # -- the watcher thread --------------------------------------------

    def _bind_tap(self, camera: str) -> Callable[[bytes, bool], None]:
        """Close over the camera THIS tap was opened for.

        `cameras.py` now resolves `self._taps` live, per packet, rather
        than snapshotting it once when a stream opens — so `clear_tap`
        and a fresh `set_tap` both take effect immediately, on a
        connection already running. That closes the window where a
        reconnect was the only thing that ever picked up a change. It
        does not close the narrower one where a packet from the OLD
        camera is already inside `_watch`'s demux loop, past the point
        where it reads `self._taps`, when `close()`/`open()` switch the
        view — the comparison in `_on_packet` is what catches that one.
        """

        def _tap(packet: bytes, keyframe: bool) -> None:
            self._on_packet(camera, packet, keyframe)

        return _tap

    def _on_packet(self, camera: str, packet: bytes, keyframe: bool) -> None:
        """Called on the watcher thread, up to 25 times a second.

        `camera` is the one this tap was bound to at `open()` time, not
        whatever `self.camera` happens to hold when this runs — a packet
        from a view that has already been switched away from is dropped
        here, before it can touch the epoch or reach a push.
        """
        if camera != self.camera:
            return

        if self._now() - self._started > self._ceiling:
            self.expired = True
            self._schedule(self.close("timeout"))
            return

        # H.264 can only be entered at a keyframe. Sending before one is
        # how a restream shows a few tenths of a second of green.
        if not self._keyframe_seen:
            if not keyframe:
                return
            self._keyframe_seen = True

        self._schedule(self._push_frame(self.epoch, packet))

    def _schedule(self, coro: Coroutine[Any, Any, bool]) -> None:
        """Hand a coroutine to the gateway's loop from the watcher thread."""
        loop = self._loop
        if loop is None or loop.is_closed():
            # No loop to run it on — most often the gateway shutting
            # down mid-delivery. Close it rather than leak it: an
            # unawaited coroutine warns loudly the next time the
            # garbage collector runs, and always at the wrong moment.
            coro.close()
            return
        try:
            asyncio.run_coroutine_threadsafe(coro, loop)
        except RuntimeError as exc:
            logger.debug(f"samantha-vision: live frame not scheduled — {exc}")
            coro.close()
