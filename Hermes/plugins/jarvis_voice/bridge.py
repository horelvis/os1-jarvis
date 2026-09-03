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

Two other places could stall `pump()` and, with it, the cleanup that
`thread.join()` is waiting on: the read loop (`async for chunk in agen`)
and `agen.aclose()`.

- The read loop is deliberately left unguarded here. For the real
  client (`samantha.tts.stream`), every `httpx` read is already bounded
  by `config.timeout_s` (default 60s — see
  `Hermes/plugins/jarvis_voice/tts.py`), so a wedged connection raises instead of
  hanging forever. That bound is per-read, not a whole-body cap — a
  server dribbling one byte every few seconds would never trip it —
  but that's a property of the producer's own timeout configuration,
  not something this generic thread/queue adapter can guess at
  (`agen_factory` need not be CosyVoice at all). The drip-feed gap
  belongs in `tts.py`'s response handling, not here.
- `aclose()` has no such caller-side protection — it sits entirely on
  bridge.py's own cleanup path, so it gets an explicit timeout below.
"""

from __future__ import annotations

import asyncio
import queue
import threading
from typing import AsyncIterator, Callable, Iterator

_SENTINEL = object()
_POLL_INTERVAL = 0.1
_ACLOSE_TIMEOUT_S = 1.0  # comfortably under the consumer's 2s join budget


def _put_or_abandon(out: queue.Queue, item: object, stop: threading.Event) -> None:
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
                # HTTP stream to CosyVoice) instead of waiting on GC. This
                # is the cleanup path — it must never hang, and unlike the
                # read loop above, nothing upstream bounds it — so wrap it
                # in its own timeout. Swallow both a timeout and any other
                # error from aclose() itself so neither can mask a real
                # exception already propagating out of the loop.
                aclose = getattr(agen, "aclose", None)
                if aclose is not None:
                    try:
                        await asyncio.wait_for(aclose(), timeout=_ACLOSE_TIMEOUT_S)
                    except BaseException:
                        pass

        # `new_event_loop()` is INSIDE the try on purpose: it allocates
        # file descriptors (selector + self-pipe) and this runs once per
        # clause, per turn, for weeks — under fd exhaustion it raises.
        # Outside the try, that exception would kill the thread before
        # the `finally` below ever put the sentinel, and the consumer's
        # unbounded `out.get()` would block forever.
        loop = None
        try:
            loop = asyncio.new_event_loop()
            loop.run_until_complete(pump())
        except BaseException as exc:  # surfaced to the consumer below
            _put_or_abandon(out, exc, stop)
        finally:
            try:
                if loop is not None:
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
