"""Where a turn starts and stops.

Two halves, deliberately separate: `UtteranceDetector` is the policy —
hysteresis, minimum length, the cap — and is pure enough to be tested
frame by frame with a scripted probe. `SileroDetector` is the model,
and is the only part that needs a file on disk and onnxruntime.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol

INPUT_RATE = 16000
FRAME_SAMPLES = 512
_FRAME_SECONDS = FRAME_SAMPLES / INPUT_RATE

# Silero v5 does not take the frame on its own: it wants the 64 samples
# BEFORE it as well, so the tensor handed to the model is 576 long.
#
# Getting this wrong is SILENT. With a bare 512 the model runs, returns
# numbers, and reports no speech ever. Measured against audio that
# Whisper transcribes word for word: a 512-sample window peaked at
# p=0.09 and called nothing speech, while the same audio at 576 peaked
# at 1.00 and called 76 of 136 frames speech. No error, no warning — the
# widget simply never hears anybody, which looks exactly like a dead
# microphone. It was found only because the microphone was faked.
_CONTEXT_SAMPLES = 64

_THRESHOLD = 0.5
_START_FRAMES = 3
_SILENCE_SECONDS = 0.7
_MIN_UTTERANCE_SECONDS = 0.4
_MAX_UTTERANCE_SECONDS = 30.0


class SpeechProbe(Protocol):
    def speech_probability(self, frame: bytes) -> float: ...


class UtteranceDetector:
    def __init__(self, probe: SpeechProbe) -> None:
        self._probe = probe
        self._buffer = bytearray()
        self._speech_run = 0
        self._silence_seconds = 0.0
        self._speech_seconds = 0.0
        self.speaking = False

    def reset(self) -> None:
        self._buffer.clear()
        self._speech_run = 0
        self._silence_seconds = 0.0
        self._speech_seconds = 0.0
        self.speaking = False

    def push(self, frame: bytes) -> bytes | None:
        is_speech = self._probe.speech_probability(frame) >= _THRESHOLD
        if is_speech:
            self._speech_seconds += _FRAME_SECONDS

        if not self.speaking:
            self._buffer += frame
            if is_speech:
                self._speech_run += 1
                if self._speech_run >= _START_FRAMES:
                    self.speaking = True
                    self._silence_seconds = 0.0
            else:
                self._speech_run = 0
                self._speech_seconds = 0.0
                self._buffer.clear()
            return None

        self._buffer += frame
        self._silence_seconds = (
            0.0 if is_speech else self._silence_seconds + _FRAME_SECONDS
        )

        if len(self._buffer) / 2 / INPUT_RATE >= _MAX_UTTERANCE_SECONDS:
            return self._emit(force=True)
        if self._silence_seconds >= _SILENCE_SECONDS:
            return self._emit()
        return None

    def _emit(self, *, force: bool = False) -> bytes | None:
        pcm = bytes(self._buffer)
        speech_seconds = self._speech_seconds
        self.reset()
        if not force and speech_seconds < _MIN_UTTERANCE_SECONDS:
            return None
        return pcm


DEFAULT_MODEL_PATH = Path.home() / ".samantha" / "models" / "silero_vad_16k_op15.onnx"


class SileroDetector:
    """Silero VAD over onnxruntime, on the CPU.

    ONNX rather than the `silero-vad` package's default path: that one
    reaches for torch, which is ~2 GB of dependency for a 1.2 MB model
    that runs in well under a millisecond per frame on a CPU core. Only
    the .onnx file is taken from the wheel; the package is not installed.

    The wheel ships FOUR models. This is the 16 kHz one, because every
    sample that reaches here is 16 kHz by construction (INPUT_RATE) and
    it is half the size of the general one.

    Signature, read off the file rather than assumed:
      IN   input [batch, sequence] float32
           state [2, batch, 128] float32
           sr    int64
      OUT  output [batch, 1] float32 · stateN float32

    The state is carried between frames. Dropping it makes every frame a
    fresh start, which reads as constant maybe-speech — a plausible
    failure with no error attached.
    """

    def __init__(self, model_path: str | os.PathLike[str] | None = None) -> None:
        import numpy as np
        import onnxruntime as ort

        self._np = np
        path = Path(model_path or os.getenv("SAMANTHA_VAD_MODEL") or DEFAULT_MODEL_PATH)
        if not path.is_file():
            raise FileNotFoundError(
                f"Silero VAD model not at {path} — see widget/README.md"
            )
        options = ort.SessionOptions()
        # One thread: this runs every 32 ms forever, and letting ORT spawn
        # a pool per session costs more in scheduling than the model costs
        # to run.
        options.inter_op_num_threads = 1
        options.intra_op_num_threads = 1
        self._session = ort.InferenceSession(str(path), sess_options=options)
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._sr = np.array(INPUT_RATE, dtype=np.int64)
        # The tail of the previous frame. Zeros for the first one, which
        # costs nothing — 64 samples is 4 ms.
        self._context = np.zeros(_CONTEXT_SAMPLES, dtype=np.float32)

    def reset(self) -> None:
        self._state = self._np.zeros((2, 1, 128), dtype=self._np.float32)
        self._context = self._np.zeros(_CONTEXT_SAMPLES, dtype=self._np.float32)

    def speech_probability(self, frame: bytes) -> float:
        audio = self._np.frombuffer(frame, dtype=self._np.int16)
        audio = audio.astype(self._np.float32) / 32768.0

        # 64 samples of context + this frame = the 576 the model wants.
        window = self._np.concatenate((self._context, audio)).reshape(1, -1)
        self._context = audio[-_CONTEXT_SAMPLES:].copy()

        out, self._state = self._session.run(
            None, {"input": window, "state": self._state, "sr": self._sr}
        )
        return float(out[0][0])
