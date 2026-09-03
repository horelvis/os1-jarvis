import asyncio
import threading
import time

import pytest

from Hermes.plugins.jarvis_voice.bridge import _ACLOSE_TIMEOUT_S, iter_sync


def _agen_factory(chunks, delay=0.0):
    async def agen():
        for c in chunks:
            if delay:
                await asyncio.sleep(delay)
            yield c

    return agen


def test_yields_every_chunk_in_order():
    out = list(iter_sync(_agen_factory([b"a", b"b", b"c"])))
    assert out == [b"a", b"b", b"c"]


def test_empty_stream_yields_nothing():
    assert list(iter_sync(_agen_factory([]))) == []


def test_exception_propagates_to_caller():
    async def agen():
        yield b"a"
        raise RuntimeError("cosyvoice exploded")

    with pytest.raises(RuntimeError, match="cosyvoice exploded"):
        list(iter_sync(lambda: agen()))


def test_early_stop_joins_the_worker_thread():
    # Barge-in: the consumer stops after one chunk. No thread may leak.
    #
    # A shallow check like `threading.active_count() <= before + 1` passes
    # even when the worker is wedged forever: `thread.join(timeout=2.0)`
    # returns after the timeout whether or not the thread actually died,
    # and a leaked worker only ever holds the count where it already was
    # (it never grows past `before + 1`), so that bound can't tell a real
    # exit from a hang. Assert the worker is gone by name instead.
    #
    # A single-slot queue with no artificial delay is a deliberate, near-
    # deterministic reproduction: the producer keeps the queue topped up
    # as fast as it can, so the instant the consumer takes one chunk and
    # walks away, the worker is almost always mid-`put` (or holding one
    # buffered, unconsumed item) — exactly the state that exposes a
    # blocking (no-timeout) put on the shutdown path. Looping catches the
    # rare interleaving where that race doesn't line up on a single try.
    for _ in range(20):
        it = iter_sync(_agen_factory([b"a"] * 200), queue_size=1)
        assert next(it) == b"a"
        it.close()
        # it.close()'s finally already does thread.join(timeout=2.0)
        # synchronously, so the thread is gone (or truly leaked) by now.
        leaked = [t for t in threading.enumerate() if t.name == "samantha-tts"]
        assert not leaked, f"samantha-tts worker thread(s) still alive: {leaked}"


def test_hanging_aclose_does_not_leak_the_worker_thread():
    # aclose() has no caller-side timeout protecting it (unlike the read
    # loop, which real CosyVoice bounds via httpx — see bridge.py's
    # module docstring). A generator whose aclose() hangs forever must
    # still let the worker thread exit, bounded by _ACLOSE_TIMEOUT_S.
    class _HangingAcloseAgen:
        def __init__(self, chunks):
            self._it = iter(chunks)

        def __aiter__(self):
            return self

        async def __anext__(self):
            try:
                return next(self._it)
            except StopIteration:
                raise StopAsyncIteration

        async def aclose(self):
            await asyncio.sleep(999)  # simulates a wedged close

    it = iter_sync(lambda: _HangingAcloseAgen([b"a", b"b", b"c"]))
    assert next(it) == b"a"

    start = time.monotonic()
    it.close()
    elapsed = time.monotonic() - start

    assert elapsed < _ACLOSE_TIMEOUT_S + 0.5, f"close() took {elapsed:.2f}s"
    leaked = [t for t in threading.enumerate() if t.name == "samantha-tts"]
    assert not leaked, f"samantha-tts worker thread(s) still alive: {leaked}"


def test_event_loop_creation_failure_still_releases_the_consumer(monkeypatch):
    # The worker allocates a fresh event loop per clause (fds: selector +
    # self-pipe). If that allocation raises, the consumer must see the
    # exception, not block forever on an unbounded out.get().
    import Hermes.plugins.jarvis_voice.bridge as bridge

    def _boom():
        raise OSError("too many open files")

    monkeypatch.setattr(bridge.asyncio, "new_event_loop", _boom)

    result: list[object] = []

    def consume():
        try:
            list(iter_sync(_agen_factory([b"a"])))
        except BaseException as exc:  # noqa: BLE001 — recorded for the assert
            result.append(exc)

    consumer = threading.Thread(target=consume, daemon=True)
    consumer.start()
    consumer.join(timeout=5.0)

    assert not consumer.is_alive(), "consumer blocked forever on out.get()"
    assert result and isinstance(result[0], OSError)
