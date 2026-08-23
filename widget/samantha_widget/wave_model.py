"""The line, as arithmetic.

Samantha is a horizontal line, not an orb and not a spectrum
(CLAUDE.md §12, 2026-05). This module turns (state, level, time) into a
polyline; drawing it is Cairo's job and looking right is a screenshot's.

Nothing here imports gi, on purpose — it is the half of the wave that
can be tested with no display.
"""

from __future__ import annotations

import math
from enum import Enum


class WaveState(str, Enum):
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"


# How fast the drawn amplitude chases the requested one, per second.
# Attack is fast enough to feel immediate, decay slow enough that the
# line falls rather than drops.
_ATTACK = 9.0
_DECAY = 3.5

# Peak amplitude as a fraction of half the strip height.
_IDLE_GAIN = 0.05
_LIVE_GAIN = 0.85
_THINKING_GAIN = 0.45

_IDLE_BREATH_HZ = 0.18
_RIPPLE_HZ = 2.3
_PACKET_SECONDS = 1.6  # one crossing, left to right
_PACKET_WIDTH = 0.14  # as a fraction of the strip width


class WaveModel:
    def __init__(self) -> None:
        self.state = WaveState.IDLE
        self._level = 0.0  # requested, 0..1
        self._smoothed = 0.0  # drawn, 0..1
        self._t = 0.0

    def set_level(self, level: float) -> None:
        """Set the current RMS, 0..1. Values outside are clamped."""
        self._level = min(1.0, max(0.0, level))

    def advance(self, dt: float) -> None:
        self._t += dt
        target = self._level if self.state in _LIVE_STATES else 0.0
        rate = _ATTACK if target > self._smoothed else _DECAY
        # Exponential approach, framerate-independent: a dropped frame
        # changes the timing, never the shape.
        self._smoothed += (target - self._smoothed) * min(1.0, rate * dt)

    def points(
        self, width: float, height: float, count: int = 120
    ) -> list[tuple[float, float]]:
        centre = height / 2
        span = height / 2
        out: list[tuple[float, float]] = []
        for i in range(count + 1):
            u = i / count
            out.append((u * width, centre - span * self._displacement(u)))
        return out

    def _displacement(self, u: float) -> float:
        """Signed displacement at position u (0..1), in -1..1."""
        # Both ends are pinned so the line meets the edge of the strip
        # cleanly instead of ending in mid-air.
        edge = math.sin(math.pi * u)

        if self.state is WaveState.THINKING:
            head = (self._t / _PACKET_SECONDS) % 1.0
            d = (u - head) / _PACKET_WIDTH
            packet = math.exp(-d * d)
            carrier = math.sin(2 * math.pi * 6 * (u - head))
            return _THINKING_GAIN * edge * packet * carrier

        if self.state is WaveState.IDLE:
            breath = math.sin(2 * math.pi * _IDLE_BREATH_HZ * self._t)
            return _IDLE_GAIN * edge * breath * math.sin(2 * math.pi * 1.5 * u)

        # LISTENING and SPEAKING: two ripples at different rates so the
        # line reads as alive rather than as a single sine.
        ripple = 0.65 * math.sin(2 * math.pi * (3.0 * u - _RIPPLE_HZ * self._t))
        ripple += 0.35 * math.sin(2 * math.pi * (7.0 * u + 1.6 * self._t))
        return _LIVE_GAIN * edge * self._smoothed * ripple


_LIVE_STATES = frozenset({WaveState.LISTENING, WaveState.SPEAKING})
