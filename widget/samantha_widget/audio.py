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

# The band this visualiser covers. NOT the 80 Hz - 8 kHz of a general
# audio meter: everything drawn here is one woman's voice, and speech
# occupies a much narrower range than music does.
#
#   ~165-255 Hz  fundamental of a female voice
#   ~300-3500 Hz the formants that carry intelligibility
#   >4 kHz       sibilance only — /s/, /f/ — and nothing else
#
# With the wider range, the top half of the bars sat dead through every
# sentence, because there is simply no energy up there in speech. 150 Hz
# also puts the noise floor and mains hum below the first bar instead of
# giving them one of their own.
_BAND_LOW_HZ = 150.0
_BAND_HIGH_HZ = 4000.0

# The FFT runs over a power-of-two window of the most recent audio,
# NOT over the 12 ms write block. At 24 kHz a 288-sample block resolves
# 83 Hz per bin, which puts every band below ~400 Hz into the same bin —
# the first third of the bars then move as one. 1024 samples resolve
# 23 Hz and cover 43 ms, inside the 32-64 Hz refresh the technique is
# usually described with.
#   https://dlbeer.co.nz/articles/fftvis.html
_FFT_SIZE = 1024

# Frequency warping, gentler than the gamma=2 the general-audio article
# suggests: that value is there to squeeze several decades onto one
# screen, and 150 Hz - 4 kHz is under five octaves. Warping it that hard
# would crowd the formants — the part that actually moves when somebody
# talks — into the middle few bars.
_BAND_GAMMA = 1.5

# Magnitudes become decibels, because loudness is logarithmic and a
# linear bar spends its life near the floor. This window is what maps
# to "bar at the bottom" .. "bar at full height".
# Speech has a narrower dynamic range than music, and a synthesised
# voice narrower still — it arrives already levelled, with no quiet
# passages to preserve.
_DB_FLOOR = -66.0
_DB_CEILING = -18.0


def _band_edges(window_samples: int, rate: int) -> list[tuple[int, int]]:
    """FFT bin ranges for BAND_COUNT gamma-warped bands."""
    import numpy as np

    freqs = np.fft.rfftfreq(window_samples, 1 / rate)
    edges: list[tuple[int, int]] = []
    previous_stop = 0
    for i in range(BAND_COUNT):
        low = _warp(i / BAND_COUNT)
        high = _warp((i + 1) / BAND_COUNT)
        start = int(np.searchsorted(freqs, low))
        stop = int(np.searchsorted(freqs, high))
        # Every band must own at least one bin nobody else has. The
        # warped low bands are only a few Hz wide — narrower than one
        # bin at any window size worth using — so without this the first
        # eight bars carry the SAME number and move as one block, which
        # was measured at 34% of frames before this line existed.
        start = max(start, previous_stop)
        stop = max(stop, start + 1)
        start = min(start, len(freqs) - 1)
        stop = min(stop, len(freqs))
        previous_stop = stop
        edges.append((start, stop))
    return edges


def _warp(position: float) -> float:
    """Bar position 0..1 → frequency, gamma-warped."""
    span = _BAND_HIGH_HZ - _BAND_LOW_HZ
    return _BAND_LOW_HZ + span * (position**_BAND_GAMMA)


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
        # The last _FFT_SIZE samples, oldest first — the analysis window,
        # kept separate from the write block so the two can have
        # different sizes.
        self._recent = None

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
        """The newest audio → BAND_COUNT magnitudes, each 0..1.

        Follows the technique in dlbeer.co.nz/articles/fftvis.html: a
        power-of-two window, a Hamming taper, gamma-warped bands, and the
        PEAK of each band in decibels rather than its average — an
        average hides exactly the peaks that make the bars look like they
        belong to the sound. Time smoothing, which that article calls the
        single most important part, lives in BarsModel.
        """
        if self._edges is None:
            self._edges = _band_edges(_FFT_SIZE, OUTPUT_RATE)
            self._window = np.hamming(_FFT_SIZE)
            self._recent = np.zeros(_FFT_SIZE, dtype=np.float32)

        # Slide the newest block into the analysis window.
        take = min(len(samples), _FFT_SIZE)
        self._recent = np.concatenate((self._recent[take:], samples[-take:]))

        spectrum = np.abs(np.fft.rfft(self._recent * self._window))
        # Normalise so a full-scale sine reads as 1.0 regardless of size.
        spectrum = spectrum * (2.0 / _FFT_SIZE)

        out = []
        for start, stop in self._edges:
            band = spectrum[start:stop]
            peak = float(band.max()) if band.size else 0.0
            db = 20.0 * np.log10(peak + 1e-9)
            out.append(min(1.0, max(0.0, (db - _DB_FLOOR) / (_DB_CEILING - _DB_FLOOR))))
        return out
        self.level = 0.0
