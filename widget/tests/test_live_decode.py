"""The decoder thread: newest wins, and a queue that refuses to grow.

The real PyAV decoder is injected, so these run with no video, no codec
and no GPU.
"""

import threading
import time

from samantha_widget.live_decode import MAX_QUEUE, Frame, LiveDecoder


class _Codec:
    """A decoder that turns each packet into one frame named after it."""

    def __init__(self) -> None:
        self.closed = False

    def decode(self, packet: bytes):
        return [Frame(data=packet, width=4, height=4, stride=12)]

    def close(self) -> None:
        self.closed = True


def _decoder(**kwargs):
    return LiveDecoder(make_codec=lambda _extradata: _Codec(), **kwargs)


def _wait_for(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_a_fed_packet_comes_back_as_a_frame():
    dec = _decoder(on_overflow=lambda: None)
    dec.start(b"")
    try:
        dec.feed(b"one")
        # Fixed from the brief: `dec.take() is not None or False) or True`
        # cannot ever fail — the trailing `or True` makes the assertion
        # unconditional. Wait for a real frame and check its content.
        assert _wait_for(lambda: dec.peek() is not None)
        frame = dec.peek()
        assert frame is not None
        assert frame.data == b"one"
    finally:
        dec.stop()


def test_the_mailbox_keeps_only_the_newest():
    # Dropping happens AFTER decoding: an H.264 frame depends on the ones
    # before it, so dropping packets gives broken pictures, not old ones.
    dec = _decoder(on_overflow=lambda: None)
    dec.start(b"")
    try:
        for packet in (b"one", b"two", b"three"):
            dec.feed(packet)
        assert _wait_for(lambda: (dec.peek() or Frame(b"", 0, 0, 0)).data == b"three")
        assert dec.take().data == b"three"
        assert dec.take() is None
    finally:
        dec.stop()


def test_an_overflowing_queue_calls_back_instead_of_growing():
    fired = threading.Event()
    blocked = threading.Event()

    class _Slow(_Codec):
        def decode(self, packet: bytes):
            blocked.wait(2.0)
            return super().decode(packet)

    dec = LiveDecoder(make_codec=lambda _x: _Slow(), on_overflow=fired.set)
    dec.start(b"")
    try:
        for _ in range(MAX_QUEUE + 10):
            dec.feed(b"packet")
        assert fired.wait(2.0), "an unbounded queue is a memory leak with a view on it"
    finally:
        blocked.set()
        dec.stop()


def test_stop_is_idempotent_and_closes_the_codec():
    codec = _Codec()
    dec = LiveDecoder(make_codec=lambda _x: codec, on_overflow=lambda: None)
    dec.start(b"")
    dec.stop()
    dec.stop()
    assert codec.closed is True
