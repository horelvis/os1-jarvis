"""His name, heard rather than read.

Until 2026-08-26 the wake word was a filter over Whisper's transcript
(`wake.py`), and it worked, but it pays for itself twice: Whisper has to
transcribe everything the room says before anything can be discarded —
23.6 s of a television news bulletin, measured that afternoon — and it
depends on Whisper spelling the name right, which it does not (seven
spellings in one day).

This decides before Whisper runs. openWakeWord, the same engine Hermes
uses for its own wake word (`tools/wake_word.py`), with the `hey_jarvis`
model that ships inside the package — no download, no key, no audio
leaving the box. The user chose "Hey Jarvis" over an open-vocabulary
engine on 2026-08-26.

It is fed the SAME 512-sample frames the detector gets, from the same
thread, so there is no second microphone stream — the thing Hermes' own
module warns about, and the reason its version could not simply be
reused from the gateway.
"""

from __future__ import annotations

import time
from typing import Any, Protocol

# What Hermes uses, and for the same reasons: a score every frame is
# noisy, so a hit has to survive three of them in a row. Sensitivity is
# a threshold on the model's own 0-1 score.
DEFAULT_MODEL = "hey_jarvis"
SENSITIVITY = 0.6
CONFIRMATION_FRAMES = 3

# After firing, ignore the model for this long. The phrase is still in
# the buffer for the next few frames and would fire again and again;
# openWakeWord's scores decay rather than reset.
COOLDOWN_SECONDS = 2.0

# Samples per prediction. openWakeWord is built around 80 ms of audio and
# degrades quietly on anything smaller — measured 2026-08-26 on the same
# synthesised "Hey Jarvis": 0.052 peak at 512 samples against 0.359 at
# 1280. It does not fail, it just never scores. The microphone hands us
# 512-sample frames (the size Silero needs), so they are buffered here
# rather than changing the size everything else depends on.
CHUNK_SAMPLES = 1280


class Scorer(Protocol):
    """The part of openWakeWord's `Model` this needs. Fakeable in tests."""

    def predict(self, frame: Any) -> dict[str, float]: ...


class Hotword:
    """Did somebody just say his name out loud?

    `load()` blocks and belongs on a worker thread, like `stt.py`. Until
    it has run, `heard()` answers False and costs nothing — the strip is
    simply deaf to its own name for the first second, exactly as it is
    deaf to everything else while Whisper loads.
    """

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        *,
        sensitivity: float = SENSITIVITY,
        confirmations: int = CONFIRMATION_FRAMES,
        cooldown: float = COOLDOWN_SECONDS,
        chunk_samples: int = CHUNK_SAMPLES,
        now=time.monotonic,
    ) -> None:
        self.model_name = model_name
        self.sensitivity = sensitivity
        self.confirmations = confirmations
        self.cooldown = cooldown
        self._now = now
        self.chunk_bytes = chunk_samples * 2
        self._scorer: Scorer | None = None
        self._buffer = bytearray()
        self._run = 0
        self._quiet_until = 0.0
        # The last score over the threshold, for calibration: the model
        # is trained on English and the phrase is said in a Spanish
        # accent, so where to put `sensitivity` is a measurement.
        self.last_score = 0.0

    @property
    def ready(self) -> bool:
        return self._scorer is not None

    def model_path(self) -> str:
        """The bundled `.onnx` for this name.

        openWakeWord 0.4.0 takes PATHS, not names — `wakeword_models=`
        belongs to a later API and is silently forwarded into
        `AudioFeatures`, where it fails as an unexpected keyword. The
        models ship inside the package (`resources/models/`), so there
        is nothing to download and nothing to keep in `~/.jarvis`.
        """
        import glob
        import os

        import openwakeword

        root = os.path.join(
            os.path.dirname(openwakeword.__file__), "resources", "models"
        )
        found = sorted(glob.glob(os.path.join(root, f"{self.model_name}*.onnx")))
        if not found:
            raise FileNotFoundError(
                f"no bundled model for {self.model_name!r} in {root}"
            )
        return found[0]

    def load(self) -> None:
        """Blocking. Build the model — several seconds the first time."""
        from openwakeword.model import Model

        self._scorer = Model(wakeword_model_paths=[self.model_path()])

    def use(self, scorer: Scorer) -> None:
        """Inject a scorer. For tests, and for a model built elsewhere."""
        self._scorer = scorer

    def heard(self, frame: bytes) -> bool:
        """True on the frame that completes the phrase.

        Never raises: a wake word that throws on a malformed frame would
        take the microphone thread down with it, and the strip would go
        deaf with no error anybody sees.
        """
        if self._scorer is None:
            return False
        now = self._now()
        if now < self._quiet_until:
            # Drop what arrives during the cooldown rather than buffer
            # it: it is the tail of the phrase that just fired.
            self._buffer.clear()
            return False

        self._buffer += frame
        if len(self._buffer) < self.chunk_bytes:
            return False
        chunk = bytes(self._buffer[: self.chunk_bytes])
        del self._buffer[: self.chunk_bytes]

        try:
            import numpy as np

            scores = self._scorer.predict(np.frombuffer(chunk, dtype=np.int16))
        except Exception:
            return False
        if not scores:
            return False
        best = max(scores.values())
        # Recorded BEFORE the threshold, or calibration can only ever see
        # the hits it already accepts — which is how the first
        # measurement of a real voice came back empty (2026-08-26).
        self.last_score = best
        if best < self.sensitivity:
            self._run = 0
            return False
        self._run += 1
        if self._run < self.confirmations:
            return False
        self._run = 0
        self._quiet_until = now + self.cooldown
        return True
