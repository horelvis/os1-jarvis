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

import os
import re

DEFAULT_MODEL = "large-v3-turbo"

# The words this box says that Whisper does not expect a living room to
# say. Handed to the decoder as part of its `initial_prompt`, which is
# the same mechanism that fixed his name on 2026-08-26 — and the file
# already argues for it: the fix belongs where the word is decoded, not
# where it is compared.
#
# Measured 2026-08-27, delegating a coding task out loud: "git" came
# back as "JIT", "JIP" and "Jeep", and "Claude Code" as "Cloud Code" and
# "CloudCoder". Two of the three attempts died there, and the third
# created a folder called `Jeep`.
#
# It is a SENTENCE and not a word list on purpose: `initial_prompt` is
# read as preceding speech, so prose biases the decoder the way a word
# salad does not. Keep it short — it is decoded before every utterance.
VOCABULARY = (
    "Hablamos de git, GitHub, Claude Code, commits, ramas, "
    "repositorios, tests con pytest y carpetas de proyecto."
)


def build_hint(wake_word: str = "") -> str:
    """What Whisper is told it has just heard, to bias what it hears next.

    His name first, because being ignored is the one failure a wake word
    cannot afford; then the vocabulary. `SAMANTHA_WIDGET_STT_HINT`
    replaces the whole thing — a different house says different words,
    and an empty value turns the bias off entirely.
    """
    override = os.environ.get("SAMANTHA_WIDGET_STT_HINT")
    if override is not None:
        return override.strip()
    name = f"Hola {wake_word.capitalize()}. " if wake_word else ""
    return f"{name}{VOCABULARY}"


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
    def __init__(self, model_name: str = DEFAULT_MODEL, *, hint: str = "") -> None:
        self.model_name = model_name
        # Words this box expects to hear, handed to the decoder as its
        # `initial_prompt`. It exists for exactly one word: his name.
        # Measured 2026-08-26, before it — "Jarvis, ¿qué día es hoy?"
        # came back as "Carbis", "Harvish", "Jervis", "Harvies", "Ya
        # viste", "ya Luis" and "¿Y har visto". A wake word cannot be
        # matched out of that reliably, however loose the comparison,
        # so the fix belongs where the word is decoded rather than where
        # it is compared.
        self.hint = hint
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
            # Biases the decoder towards the words this house uses. Kept
            # to one short sentence: a long prompt is context the model
            # spends attention on, and it can start echoing it.
            initial_prompt=self.hint or None,
        )
        return clean(" ".join(segment.text for segment in segments))
