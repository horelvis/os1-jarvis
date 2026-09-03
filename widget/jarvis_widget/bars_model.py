"""The equaliser, as arithmetic.

Bands in, bar heights out, with the smoothing that stops it looking
like static. Like wave_model.py, this imports no gi and no numpy-heavy
machinery: the FFT happens in the player, where the audio already is,
and what arrives here is a small list of magnitudes.

Bars rise and fall from the centre line, mirrored, so a strip lying
along the bottom edge of the screen reads as an object rather than as a
chart standing on the taskbar.
"""

from __future__ import annotations

import math

from .wave_model import WaveState

# Each band is drawn TWICE — mirrored about the centre — so the row
# holds 2 * BAND_COUNT bars. Speech energy lives in the low and mid
# bands, which packed them all against the left edge and left the right
# half dead; mirrored, the loud end sits in the middle and the quiet
# high end tapers off to both edges (user, 2026-08-23).
BAND_COUNT = 40

# Per second. A bar snaps up almost immediately and falls back slowly
# enough to be watchable — the asymmetry is what makes an equaliser look
# alive rather than jittery.
_ATTACK = 22.0
_DECAY = 6.0

# Fraction of half the strip height a full-scale band reaches.
_LIVE_GAIN = 0.92
_IDLE_GAIN = 0.06
_THINKING_GAIN = 0.55

# Below this the window holds no real sound, so auto-gain is switched
# off rather than amplifying the noise floor to full height.
_SILENCE_FLOOR = 0.04

# One travelling pulse per task in flight. Different speeds so two tasks
# never lock into step and read as one — they drift apart, cross, and
# separate again, which is what makes the count legible without counting.
_WORK_BASE_SECONDS = 2.2
_WORK_SPEED_SPREAD = 0.35
_WORK_PULSE_WIDTH = 0.10
_WORK_GAIN = 0.62
# Above this many, the pulses stop being countable and the row just looks
# busy — which is the honest reading of "she has a lot on".
MAX_VISIBLE_TASKS = 5

_IDLE_BREATH_HZ = 0.16
_PACKET_SECONDS = 1.6
_PACKET_WIDTH = 0.16


def _wrapped_distance(position: float, head: float) -> float:
    """Distance from `position` to `head` around a circle of length 1.

    A travelling pulse is a bump centred on `head`, and with a plain
    `position - head` the bump is CUT IN HALF at both ends of the row:
    as the centre approaches 1.0 the right half falls off the edge and
    the pulse vanishes mid-stride instead of leaving on one side and
    arriving on the other. Measuring the short way round the circle
    makes it continuous.
    """
    gap = abs(position - head)
    return min(gap, 1.0 - gap)


def mirror(values: list[float]) -> list[float]:
    """[a, b, c] -> [c, b, a, a, b, c]: index 0 lands beside the centre.

    Used by both visualisers, for the same reason in each: whatever is
    most interesting — the newest sound, or the loudest frequencies —
    belongs in the middle where the eye already is, not against one edge.
    """
    return values[::-1] + list(values)


class BarsModel:
    def __init__(self, band_count: int = BAND_COUNT) -> None:
        self.state = WaveState.IDLE
        self.task_count = 0
        self.band_count = band_count
        self._target = [0.0] * band_count
        self._drawn = [0.0] * band_count
        self._t = 0.0

    def set_bands(self, bands: list[float]) -> None:
        """Set the current per-band magnitudes, each 0..1."""
        for i in range(self.band_count):
            value = bands[i] if i < len(bands) else 0.0
            self._target[i] = min(1.0, max(0.0, value))

    def set_level(self, level: float) -> None:
        """Fallback for callers with no spectrum: one number, all bands.

        Shaped so the middle bands are tallest, because a flat block of
        equal bars does not read as sound.
        """
        level = min(1.0, max(0.0, level))
        for i in range(self.band_count):
            u = i / max(1, self.band_count - 1)
            self._target[i] = level * (0.45 + 0.55 * math.sin(math.pi * u))

    def advance(self, dt: float) -> None:
        self._t += dt
        for i in range(self.band_count):
            target = self._target[i] if self.state in _LIVE_STATES else 0.0
            rate = _ATTACK if target > self._drawn[i] else _DECAY
            self._drawn[i] += (target - self._drawn[i]) * min(1.0, rate * dt)

    def set_task_count(self, count: int) -> None:
        """How many things she has in flight right now."""
        self.task_count = max(0, int(count))

    def heights(self) -> list[float]:
        """Half-height of each bar, 0..1 of half the strip height."""
        if self.state is WaveState.WORKING:
            return self._working()
        if self.state is WaveState.THINKING:
            return self._packet()
        if self.state is WaveState.IDLE:
            return self._breath()
        # No auto-gain here, unlike the waveform: the bands already
        # arrive in decibels against a calibrated window, and
        # normalising them again would undo that and make quiet passages
        # look as loud as shouting.
        return mirror([_LIVE_GAIN * value for value in self._drawn])

    def _breath(self) -> list[float]:
        breath = 0.5 + 0.5 * math.sin(2 * math.pi * _IDLE_BREATH_HZ * self._t)
        return mirror([_IDLE_GAIN * breath] * self.band_count)

    def _working(self) -> list[float]:
        """One pulse per task, travelling at its own speed.

        Read left to right the row is a set of blips crossing at
        different rates; the number of them is the number of things she
        is doing. At zero tasks it falls back to the single thinking
        pulse, because "working on nothing" is just waiting.
        """
        tasks = min(self.task_count, MAX_VISIBLE_TASKS)
        if tasks <= 0:
            return self._packet()

        width = 2 * self.band_count
        out = [0.0] * width
        for task in range(tasks):
            # Each task is slower than the last, and starts further along.
            period = _WORK_BASE_SECONDS * (1.0 + _WORK_SPEED_SPREAD * task)
            head = ((self._t / period) + task / tasks) % 1.0
            for i in range(width):
                u = i / max(1, width - 1)
                d = _wrapped_distance(u, head) / _WORK_PULSE_WIDTH
                # Pulses add where they cross, so two tasks meeting make
                # a taller blip — but never taller than the strip.
                out[i] = min(1.0, out[i] + _WORK_GAIN * math.exp(-d * d))
        return out

    def _packet(self) -> list[float]:
        """Thinking: one travelling bump, drawn across the mirrored row."""
        width = 2 * self.band_count
        head = (self._t / _PACKET_SECONDS) % 1.0
        out = []
        for i in range(width):
            u = i / max(1, width - 1)
            d = _wrapped_distance(u, head) / _PACKET_WIDTH
            out.append(_THINKING_GAIN * math.exp(-d * d))
        return out


_LIVE_STATES = frozenset({WaveState.LISTENING, WaveState.SPEAKING})


# How many bars the waveform keeps — and therefore how many are drawn.
# At one block per 12 ms this is a bit under two seconds of audio
# scrolling across the strip, dense enough to read as a waveform rather
# than as a bar chart.
HISTORY_LEN = 150


class WaveformModel:
    """A scrolling waveform: one bar per instant, not per frequency.

    The equaliser answers "which frequencies are sounding now"; this
    answers "how loud was it, just now, and a moment before that" — which
    is the shape people recognise from audio editors, and the one the
    user pointed at. It is also the cheaper of the two: no FFT, just the
    level that the player already computes for every 20 ms block.

    The newest sound is in the MIDDLE, and older sound travels outwards
    to both edges, mirrored. Scrolling right-to-left was tried first and
    rejected (user, 2026-08-23): sideways travel reads as a chart being
    dragged past you, while growing from the centre reads as something
    the strip itself is doing.

    One consequence worth knowing: each bar is drawn twice, so the
    visible history is half of `length`.
    """

    def __init__(self, length: int = HISTORY_LEN) -> None:
        self.state = WaveState.IDLE
        self.length = length
        self._history = [0.0] * length
        self._t = 0.0

    def push(self, level: float) -> None:
        self._history.append(min(1.0, max(0.0, level)))
        del self._history[0]

    def set_history(self, history: list[float]) -> None:
        """Replace the whole window at once.

        The player owns the history — it is the only thing that sees
        every 20 ms block — so the widget copies it rather than being
        fed sample by sample from another thread.
        """
        if not history:
            return
        window = history[-self.length :]
        pad = self.length - len(window)
        self._history = [0.0] * pad + [min(1.0, max(0.0, v)) for v in window]

    def clear(self) -> None:
        self._history = [0.0] * self.length

    def advance(self, dt: float) -> None:
        self._t += dt

    def set_task_count(self, count: int) -> None:
        """How many things she has in flight right now."""
        self.task_count = max(0, int(count))

    def heights(self) -> list[float]:
        if self.state is WaveState.WORKING:
            return self._working()
        if self.state is WaveState.THINKING:
            head = (self._t / _PACKET_SECONDS) % 1.0
            out = []
            for i in range(self.length):
                u = i / max(1, self.length - 1)
                d = _wrapped_distance(u, head) / _PACKET_WIDTH
                out.append(_THINKING_GAIN * math.exp(-d * d))
            return out
        if self.state is WaveState.IDLE:
            breath = 0.5 + 0.5 * math.sin(2 * math.pi * _IDLE_BREATH_HZ * self._t)
            return [_IDLE_GAIN * breath] * self.length
        # Auto-gain, the way an audio editor draws a clip: scale to the
        # loudest bar currently on screen, so a normal speaking voice
        # fills the strip instead of hugging the centre line. Recorded
        # speech peaks around 0.3-0.5 of full scale and drawing it
        # literally looks like a flat line with bumps.
        loudest = max(self._history)
        # Below the floor there is nothing but noise, and normalising it
        # would turn silence into a wall of bars.
        gain = _LIVE_GAIN / loudest if loudest >= _SILENCE_FLOOR else _LIVE_GAIN
        return self._mirror([min(1.0, gain * v) for v in self._history])

    def _mirror(self, values: list[float]) -> list[float]:
        """Newest in the middle, older outwards, symmetric.

        `values` is oldest-first, so the newest samples are at the end;
        they land either side of the centre and walk outwards as they
        age.
        """
        half = self.length // 2
        newest_first = values[::-1]
        out = [0.0] * self.length
        for i in range(half):
            value = newest_first[i] if i < len(newest_first) else 0.0
            out[half + i] = value
            out[half - 1 - i] = value
        return out
