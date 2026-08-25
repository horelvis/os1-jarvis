"""H.264 in, the newest picture out. On its own thread.

Packets arrive on the asyncio thread. Decoding there — or worse, on the
GTK main loop — would stutter the wave, which is drawn on the frame
clock. So: a bounded queue, one thread, and a mailbox with a single
slot.

The real codec arrives as a callable, so the whole of this runs in a
test with no video and no PyAV in the room.
"""

from __future__ import annotations

import queue
import threading
from typing import Any, Callable, NamedTuple

from loguru import logger


class Frame(NamedTuple):
    """One decoded picture, ready to be wrapped in a Gdk.MemoryTexture."""

    data: bytes
    width: int
    height: int
    stride: int


# Roughly four seconds of substream video. Past this, nothing accumulates:
# the view closes. Video that falls further and further behind is worse
# than video that stops.
MAX_QUEUE = 100


def _make_pyav_codec(extradata: bytes) -> Any:
    """The real decoder. Imported here so a test never needs PyAV."""
    import av

    codec = av.CodecContext.create("h264", "r")
    if extradata:
        codec.extradata = extradata
    return _PyAvCodec(codec)


class _PyAvCodec:
    def __init__(self, codec: Any) -> None:
        self._codec = codec

    def decode(self, packet: bytes) -> list[Frame]:
        import av

        out: list[Frame] = []
        for frame in self._codec.decode(av.Packet(packet)):
            rgb = frame.to_ndarray(format="rgb24")
            out.append(
                Frame(
                    data=rgb.tobytes(),
                    width=frame.width,
                    height=frame.height,
                    stride=frame.width * 3,
                )
            )
        return out

    def close(self) -> None:
        self._codec = None


class LiveDecoder:
    """A decoder thread with a one-slot mailbox."""

    def __init__(
        self,
        on_overflow: Callable[[], None],
        *,
        make_codec: Callable[[bytes], Any] = _make_pyav_codec,
        max_queue: int = MAX_QUEUE,
    ) -> None:
        self._on_overflow = on_overflow
        self._make_codec = make_codec
        self._queue: queue.Queue[bytes | None] = queue.Queue(maxsize=max_queue)
        self._latest: Frame | None = None
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._codec: Any = None
        self._stopping = threading.Event()

    def start(self, extradata: bytes) -> None:
        self._stopping.clear()
        self._codec = self._make_codec(extradata)
        self._thread = threading.Thread(
            target=self._run, name="samantha-live-decode", daemon=True
        )
        self._thread.start()

    def feed(self, packet: bytes) -> None:
        """Hand a packet over. Never blocks the caller."""
        try:
            self._queue.put_nowait(packet)
        except queue.Full:
            # Do NOT drop the packet and carry on: an H.264 frame depends
            # on the ones before it, so a hole here yields broken pictures
            # rather than old ones. Falling this far behind is a closing
            # condition, and the caller decides what to say about it.
            self._on_overflow()

    def peek(self) -> Frame | None:
        with self._lock:
            return self._latest

    def take(self) -> Frame | None:
        """The newest decoded frame, once. None when there is nothing new."""
        with self._lock:
            frame, self._latest = self._latest, None
            return frame

    def stop(self) -> None:
        """Idempotent."""
        if self._thread is None and self._codec is None:
            return
        self._stopping.set()
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=1.0)
        codec, self._codec = self._codec, None
        if codec is not None:
            try:
                codec.close()
            except Exception:
                pass
        with self._lock:
            self._latest = None

    def _run(self) -> None:
        while not self._stopping.is_set():
            packet = self._queue.get()
            if packet is None:
                return
            try:
                frames = self._codec.decode(packet)
            except Exception as exc:
                # A broken packet is not worth the view, but it is worth
                # one line: this is the failure that otherwise looks like
                # a black band nobody can explain.
                logger.debug(f"live: packet not decoded — {exc}")
                continue
            for frame in frames:
                with self._lock:
                    self._latest = frame
