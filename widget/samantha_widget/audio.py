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

import os
import queue
import sys
import threading
import time

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


class SpectrumAnalyser:
    """Audio in, BAND_COUNT magnitudes out. One per rate, stateful.

    Follows the technique in dlbeer.co.nz/articles/fftvis.html: a
    power-of-two window, a Hamming taper, gamma-warped bands, and the
    PEAK of each band in decibels rather than its average — an average
    hides exactly the peaks that make the bars look like they belong to
    the sound. Time smoothing, which that article calls the single most
    important part, lives in BarsModel.

    It holds the sliding window, so one instance belongs to one source.
    The two sources do not share a rate — the microphone is 16 kHz and
    the player 24 kHz — and the band edges are computed from it, which
    is the whole reason this takes `rate` rather than reading a
    constant.

    It exists as a class because for months only the PLAYER analysed
    anything: the microphone produced a single RMS, and the strip fell
    back to `BarsModel.set_level`, which moves every band together in a
    fixed arch. Reported 2026-08-30 as "una onda uniforme que nada tiene
    que ver con la voz", and that is exactly what it was.
    """

    def __init__(self, rate: int) -> None:
        self.rate = rate
        self._edges: list[tuple[int, int]] | None = None
        self._window = None
        # The last _FFT_SIZE samples, oldest first — the analysis
        # window, kept separate from the caller's block so the two can
        # have different sizes.
        self._recent = None

    def analyse(self, samples) -> list[float]:
        """Slide `samples` (float, -1..1) in, and read the bands out."""
        import numpy as np

        samples = np.asarray(samples, dtype=np.float32)
        if self._edges is None:
            self._edges = _band_edges(_FFT_SIZE, self.rate)
            self._window = np.hamming(_FFT_SIZE)
            self._recent = np.zeros(_FFT_SIZE, dtype=np.float32)

        take = min(len(samples), _FFT_SIZE)
        if take:
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
        # Whether the callback has already failed once. Anything raised
        # in there is a bug of ours, and a bug that repeats does so 31
        # times a second: one line, then silence.
        blamed = False
        while self._running and self._stream is not None:
            try:
                frame, _overflowed = self._stream.read(FRAME_SAMPLES)
            except Exception:
                # An unplugged device should make her deaf, not dead.
                return
            try:
                self._on_frame(bytes(frame))
            except Exception as exc:
                # The callback is called OUTSIDE the read's `try` on
                # purpose — a device that has gone away ends this thread,
                # and a frame we mishandled must not. Before 2026-09-01
                # nothing caught this at all: anything the callback
                # raised (a Vosk recognizer refusing to build, say) came
                # out here, ended the thread, and left him deaf while
                # every service around him looked healthy. The real guard
                # is at the call site — `VoskSwitch` in `__main__.py`,
                # which turns the feature off rather than the microphone
                # — and this is the backstop under it, so that no future
                # callback can cost the ears either.
                if not blamed:
                    blamed = True
                    print(
                        f"la captura falló y sigue escuchando: {exc!r}",
                        file=sys.stderr,
                        flush=True,
                    )

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None


# How long after the last block written his voice is still assumed to be
# in the room. Must exceed the between-clause synthesis gap (~0.36 s
# measured) plus PortAudio's output latency plus the acoustic trip.
# `SAMANTHA_WIDGET_AUDIBLE_TAIL` moves it for a room with different
# speakers; too short reopens the feedback loop, too long only means an
# interruption is judged on its words for a moment longer.
TAIL_SECONDS = float(os.environ.get("SAMANTHA_WIDGET_AUDIBLE_TAIL", "1.2"))


class Player:
    """A queue feeding one output stream, with a level for the wave."""

    def __init__(self) -> None:
        self._queue: queue.Queue[bytes | None] = queue.Queue()
        self._stream: sd.RawOutputStream | None = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._playing = False
        # When the last block was handed to PortAudio. `audible()` reads
        # it; nothing else should. 0.0 means he has not spoken yet, which
        # is far enough in the past to read as silent.
        self._last_block_at = 0.0
        self.level = 0.0
        # Per-band magnitudes of the block currently going out, 0..1.
        # Read by the GTK thread; a plain list assignment is atomic
        # enough for something redrawn 60 times a second.
        self.bands: list[float] = [0.0] * BAND_COUNT
        # One level per 20 ms block, oldest first — the waveform the
        # strip scrolls. Kept here because this is where the blocks are.
        self.history: list[float] = [0.0] * HISTORY_LEN
        self._analyser = SpectrumAnalyser(OUTPUT_RATE)

    def start(self) -> None:
        self._stream = sd.RawOutputStream(
            samplerate=OUTPUT_RATE,
            channels=1,
            dtype="int16",
            # Let PortAudio size its own buffer, and do NOT ask for low
            # latency. Both were set to keep the visualiser in step with
            # the sound, and both were wrong: this thread shares a CPU
            # with Silero, Whisper and GTK, and a 12 ms buffer empties
            # faster than it can be refilled. The audible result is
            # syllables dropping out of her speech, and the visible one
            # is the wave freezing while _pump blocks on a starved
            # write. A deeper buffer costs a few tens of milliseconds of
            # lag between the bars and the voice — nobody can see that,
            # and everybody can hear a missing vowel.
            blocksize=0,
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

        **This is about the QUEUE, not about the room.** `say()` waits on
        it clause by clause, so it must go False the moment a clause is
        written or he would speak with a pause after every phrase. For
        "is his voice still in the air", which is what a microphone gate
        needs, use `audible()`.
        """
        return self._playing or not self._queue.empty()

    def audible(self, now: float) -> bool:
        """Is his voice still reaching the microphone?

        `busy` answers a question about the queue and goes False between
        clauses — measured 2026-09-01 on the real player, a three-clause
        reply spent 0.70 s of its 2.70 s with `busy` False, in two gaps
        of ~0.36 s while CosyVoice synthesised the next clause. The
        speaker is still sounding through every one of those gaps.

        That mattered because the barge-in gate was written as
        `if player.busy and not detector.speaking`, so those gaps had NO
        gate at all: his own voice reached the detector, opened a turn,
        and `detector.speaking` then kept the gate bypassed for the whole
        remainder of the reply. The user met the result as a feedback
        loop — he transcribed himself and answered himself, with the GPU
        pinned at 94% for as long as it went on.

        The tail has to cover the synthesis gap plus PortAudio's own
        output latency plus the trip across the room. A frame inside it
        is not dropped, only JUDGED — `build_is_a_person` still lets a
        real interruption through on its words — so erring long costs
        nothing but a text comparison.
        """
        return self.busy or (now - self._last_block_at) < TAIL_SECONDS

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
                    # Stamped per BLOCK, not per clause: `write` returns
                    # when PortAudio takes the bytes, so this is the
                    # latest moment we know sound was still being handed
                    # to the speaker.
                    self._last_block_at = time.monotonic()
                    samples = np.frombuffer(block, dtype=np.int16).astype(np.float32)
                    if samples.size:
                        samples /= 32768.0
                        self.level = float(np.sqrt(np.mean(samples**2)))
                        self.bands = self._analyser.analyse(samples)
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
