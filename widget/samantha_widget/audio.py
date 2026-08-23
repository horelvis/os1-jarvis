"""PortAudio in and out. Two rates, no resampling.

In:  16 kHz mono int16, 512-sample frames — what Silero and Whisper want.
Out: 24 kHz mono int16 — samantha.tts.OUTPUT_SAMPLE_RATE, exactly.

PipeWire (with pipewire-pulse) is what is running on this box, so
PortAudio reaches it through the Pulse compatibility layer. The device
name is logged once at startup because the failure mode of picking the
wrong one is silence with no error — and on this machine silence is
what the input produces anyway, since there is no microphone plugged in.
"""

from __future__ import annotations

import queue
import threading

import sounddevice as sd

from .vad import FRAME_SAMPLES, INPUT_RATE

OUTPUT_RATE = 24000


def describe_devices() -> str:
    """One line naming the chosen devices. Log it; do not parse it."""
    try:
        return (
            f"in={sd.query_devices(kind='input')['name']!r} "
            f"out={sd.query_devices(kind='output')['name']!r}"
        )
    except Exception as exc:  # no audio at all is survivable, not fatal
        return f"no audio devices ({exc})"


class Microphone:
    """Always open, read from a thread of our own.

    NOT PortAudio's `callback=` mode, which is the obvious way to write
    this and kills the process. In callback mode PortAudio invokes the
    Python callback from its own realtime thread; with GTK running and
    other threads importing modules, that segfaults — reliably, with no
    traceback, somewhere inside an unrelated `import`. It took isolating
    the microphone to see that the crash was not about imports at all.

    A blocking `read()` on an ordinary Python thread does the same job
    with none of that: the frames arrive on a thread Python created and
    fully owns.
    """

    def __init__(self, on_frame) -> None:
        self._on_frame = on_frame
        self._stream: sd.RawInputStream | None = None
        self._thread: threading.Thread | None = None
        self._running = False

    def start(self) -> None:
        self._stream = sd.RawInputStream(
            samplerate=INPUT_RATE,
            blocksize=FRAME_SAMPLES,
            channels=1,
            dtype="int16",
        )
        self._stream.start()
        self._running = True
        self._thread = threading.Thread(
            target=self._pump, name="microphone", daemon=True
        )
        self._thread.start()

    def _pump(self) -> None:
        while self._running and self._stream is not None:
            try:
                frame, _overflowed = self._stream.read(FRAME_SAMPLES)
            except Exception:
                # An unplugged device should make her deaf, not dead.
                return
            self._on_frame(bytes(frame))

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None


class Player:
    """A queue feeding one output stream, with a level for the wave."""

    def __init__(self) -> None:
        self._queue: queue.Queue[bytes | None] = queue.Queue()
        self._stream: sd.RawOutputStream | None = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._playing = False
        self.level = 0.0

    def start(self) -> None:
        self._stream = sd.RawOutputStream(
            samplerate=OUTPUT_RATE, channels=1, dtype="int16"
        )
        self._stream.start()
        self._running = True
        self._thread = threading.Thread(target=self._pump, daemon=True)
        self._thread.start()

    def write(self, pcm: bytes) -> None:
        self._queue.put(pcm)

    def stop(self) -> None:
        """Drop everything queued. This is what barge-in feels like."""
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
        self.level = 0.0

    def close(self) -> None:
        self._running = False
        self._queue.put(None)
        if self._thread is not None:
            self._thread.join(timeout=2)
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    @property
    def busy(self) -> bool:
        """True while there is audio queued OR being written.

        `_playing` is why this is not just `not empty`: the last chunk
        leaves the queue before it reaches the speakers, and a gate that
        opened there would let her own final syllable back into the
        microphone.
        """
        return self._playing or not self._queue.empty()

    def _pump(self) -> None:
        import numpy as np

        while self._running:
            chunk = self._queue.get()
            if chunk is None:
                return
            self._playing = True
            try:
                samples = np.frombuffer(chunk, dtype=np.int16).astype(np.float32)
                if samples.size:
                    self.level = float(np.sqrt(np.mean((samples / 32768.0) ** 2)))
                if self._stream is not None:
                    self._stream.write(chunk)
            finally:
                self._playing = False
        self.level = 0.0
