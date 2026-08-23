"""faster-whisper, loaded late and asked in Spanish.

CLAUDE.md §2.6 named large-v3-turbo back when STT was going to be
local; the 2026-05-13 decision moved it into the browser's Web Speech
API instead. With the browser gone, that decision goes with it and the
original one comes back.

Measured headroom on this box: the 4090 has 24564 MiB with ~5355 MiB
taken by CosyVoice. large-v3-turbo in float16 needs roughly 1.5-2 GB.

Loading takes seconds, so it happens on a background thread and the
strip is simply deaf until `ready`. An appliance does not show a
progress bar.
"""

from __future__ import annotations

import re

DEFAULT_MODEL = "large-v3-turbo"

# Whisper fills silence with the politeness it was trained on: video
# outros, subtitle credits, "gracias". A strip that listens all day
# meets these constantly, and each one would otherwise become a turn.
_HALLUCINATIONS = re.compile(
    r"^\W*(gracias(\s+por\s+ver.*)?|thank you|thanks for watching"
    r"|subt[ií]tulos?.*|¡?suscr[ií]bete.*|amara\.org.*)\W*$",
    re.IGNORECASE,
)


def clean(text: str) -> str:
    """Trim, and drop the phrases Whisper invents out of silence."""
    stripped = text.strip()
    if not stripped:
        return ""
    return "" if _HALLUCINATIONS.match(stripped) else stripped


class Transcriber:
    def __init__(self, model_name: str = DEFAULT_MODEL) -> None:
        self.model_name = model_name
        self._model = None

    @property
    def ready(self) -> bool:
        return self._model is not None

    def load(self) -> None:
        """Blocking. Call from a worker thread, never the GTK one."""
        from faster_whisper import WhisperModel

        self._model = WhisperModel(
            self.model_name, device="cuda", compute_type="float16"
        )

    def transcribe(self, pcm: bytes) -> str:
        """16 kHz mono int16 PCM in, Spanish text out. "" if not ready."""
        if self._model is None:
            return ""
        import numpy as np

        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        segments, _info = self._model.transcribe(
            audio,
            language="es",  # never auto-detect: she lives in Spanish
            beam_size=1,  # latency over correctness (CLAUDE.md §1.4)
            vad_filter=False,  # Silero already cut this to one utterance
        )
        return clean(" ".join(segment.text for segment in segments))
