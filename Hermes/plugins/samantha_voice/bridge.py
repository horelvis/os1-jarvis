"""Run an async byte generator on a worker loop and yield synchronously.

Hermes' StreamingTTSProvider.stream() is a sync Iterator[bytes]; our
CosyVoice client is async. This must never touch the gateway's event
loop, and must shut the worker down when the consumer stops early —
which is what a barge-in looks like from here.

Every `queue.Queue.put` the worker makes — for a chunk, for a re-raised
exception, and for the shutdown sentinel — goes through `_put_or_abandon`,
which polls `stop` instead of blocking indefinitely. A plain blocking put
is exactly the failure mode a barge-in triggers: the consumer takes one
chunk and walks away, leaving a full, undrained queue, and a blind put
against that queue never returns. One leaked thread per interruption is
not tolerable on a device meant to run for weeks.
"""

from __future__ import annotations

import asyncio
import queue
import threading
from typing import AsyncIterator, Callable, Iterator

_SENTINEL = object()
_POLL_INTERVAL = 0.1


def _put_or_abandon(out: "queue.Queue", item: object, stop: threading.Event) -> None:
    """Put `item` on `out`, retrying until it fits or `stop` is set.

    Used for chunks, the re-raised exception, and the sentinel alike, so
    none of them can pin the worker thread against an abandoned queue.
    Giving up drops `item` silently — by the time `stop` is set the
    consumer has already left and nothing will ever read it again.
    """
    while not stop.is_set():
        try:
            out.put(item, timeout=_POLL_INTERVAL)
            return
        except queue.Full:
            continue


def iter_sync(
    agen_factory: Callable[[], AsyncIterator[bytes]],
    queue_size: int = 8,
) -> Iterator[bytes]:
    """Yield the bytes produced by `agen_factory()` on a worker thread.

    The bounded queue applies backpressure so synthesis does not race
    ahead of playback. Exceptions raised inside the generator are
    re-raised in the consumer's thread.
    """
    out: queue.Queue = queue.Queue(maxsize=queue_size)
    stop = threading.Event()

    def runner() -> None:
        async def pump() -> None:
            # `agen_factory()` runs outside the try/finally: if it raises
            # (the generator never even starts), there is nothing to
            # close and the exception should propagate untouched.
            agen = agen_factory()
            try:
                async for chunk in agen:
                    if stop.is_set():
                        return
                    _put_or_abandon(out, chunk, stop)
                    if stop.is_set():
                        return
            finally:
                # An early return/break above leaves `agen` un-exhausted;
                # aclose() releases whatever it's holding (e.g. an open
                # HTTP stream to CosyVoice) instead of waiting on GC.
                # Swallow errors from aclose() itself so they never mask
                # a real exception already propagating out of the loop.
                aclose = getattr(agen, "aclose", None)
                if aclose is not None:
                    try:
                        await aclose()
                    except BaseException:
                        pass

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(pump())
        except BaseException as exc:  # surfaced to the consumer below
            _put_or_abandon(out, exc, stop)
        finally:
            try:
                loop.close()
            finally:
                _put_or_abandon(out, _SENTINEL, stop)

    thread = threading.Thread(target=runner, name="samantha-tts", daemon=True)
    thread.start()

    try:
        while True:
            item = out.get()
            if item is _SENTINEL:
                return
            if isinstance(item, BaseException):
                raise item
            yield item
    finally:
        stop.set()
        thread.join(timeout=2.0)
