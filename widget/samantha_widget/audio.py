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

from .bars_model import BAND_COUNT, HISTORY_LEN
from .vad import FRAME_SAMPLES, INPUT_RATE

OUTPUT_RATE = 24000

# The player writes in blocks this size and republishes `level` after
# each one. CosyVoice hands over chunks of half a second or more; taking
# one RMS per chunk makes the wave lurch twice a second and land ahead of
# the sound, because the level is read before the audio is even in the
# buffer. 20 ms is short enough to follow syllables.
# 12 ms rather than 20: the waveform draws one bar per block, so this is
# also its horizontal resolution, and the reference the user pointed at
# is dense — many thin bars, not few fat ones.
_LEVEL_BLOCK_MS = 12
_LEVEL_BLOCK_SAMPLES = OUTPUT_RATE * _LEVEL_BLOCK_MS // 1000
_LEVEL_BLOCK_BYTES = _LEVEL_BLOCK_SAMPLES * 2

# Speech lives between roughly these two. Going lower wastes bars on
# rumble the speakers cannot produce; going higher wastes them on
# sibilance that barely moves.
_BAND_LOW_HZ = 80.0
_BAND_HIGH_HZ = 8000.0
# Full-scale reference for a band's magnitude. Speech at a normal level
# lands well under 1.0 without it, and the bars barely leave the floor.
_BAND_REFERENCE = 12.0


def _band_edges(block_samples: int, rate: int) -> list[tuple[int, int]]:
    """FFT bin ranges for BAND_COUNT logarithmically-spaced bands.

    Logarithmic because hearing is: linear bands put three quarters of
    the bars above 3 kHz, where speech has almost nothing, and the
    equaliser looks dead while somebody is talking.
    """
    import numpy as np

    freqs = np.fft.rfftfreq(block_samples, 1 / rate)
    edges: list[tuple[int, int]] = []
    ratio = (_BAND_HIGH_HZ / _BAND_LOW_HZ) ** (1 / BAND_COUNT)
    low = _BAND_LOW_HZ
    for _ in range(BAND_COUNT):
        high = low * ratio
        start = int(np.searchsorted(freqs, low))
        stop = max(start + 1, int(np.searchsorted(freqs, high)))
        edges.append((start, min(stop, len(freqs))))
        low = high
    return edges


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
        # Per-band magnitudes of the block currently going out, 0..1.
        # Read by the GTK thread; a plain list assignment is atomic
        # enough for something redrawn 60 times a second.
        self.bands: list[float] = [0.0] * BAND_COUNT
        # One level per 20 ms block, oldest first — the waveform the
        # strip scrolls. Kept here because this is where the blocks are.
        self.history: list[float] = [0.0] * HISTORY_LEN
        self._edges: list[tuple[int, int]] | None = None
        self._window = None

    def start(self) -> None:
        self._stream = sd.RawOutputStream(
            samplerate=OUTPUT_RATE,
            channels=1,
            dtype="int16",
            blocksize=_LEVEL_BLOCK_SAMPLES,
            # The wave is driven by what has just been written, so the
            # buffer's depth IS the lag between the line and the sound.
            # Ask for the smallest the device will give.
            latency="low",
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
                # Block by block, so `level` tracks the syllables rather
                # than the whole clause, and so it is published as each
                # block goes in rather than once for all of them.
                for start in range(0, len(chunk), _LEVEL_BLOCK_BYTES):
                    block = chunk[start : start + _LEVEL_BLOCK_BYTES]
                    if self._stream is None:
                        break
                    self._stream.write(block)
                    samples = np.frombuffer(block, dtype=np.int16).astype(np.float32)
                    if samples.size:
                        samples /= 32768.0
                        self.level = float(np.sqrt(np.mean(samples**2)))
                        self.bands = self._analyse(samples, np)
                        # PEAK for the waveform, not RMS. RMS is the
                        # average and it flattens speech into a smooth
                        # blob; the peak keeps the spikes and quiet gaps
                        # that make a waveform look like one.
                        peak = float(np.abs(samples).max())
                        self.history = [*self.history[1:], peak]
            finally:
                self._playing = False
                self.level = 0.0
                self.bands = [0.0] * BAND_COUNT

    def _analyse(self, samples, np) -> list[float]:
        """One block of audio → BAND_COUNT magnitudes, each 0..1."""
        if self._edges is None or len(samples) != len(self._window):
            self._edges = _band_edges(len(samples), OUTPUT_RATE)
            # Hann, so a block boundary in the middle of a vowel does not
            # smear energy across every band.
            self._window = np.hanning(len(samples))

        spectrum = np.abs(np.fft.rfft(samples * self._window))
        out = []
        for start, stop in self._edges:
            band = spectrum[start:stop]
            magnitude = float(band.max()) if band.size else 0.0
            out.append(min(1.0, magnitude / _BAND_REFERENCE))
        return out
        self.level = 0.0
