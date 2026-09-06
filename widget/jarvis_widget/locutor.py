"""An utterance becomes a vector, or nothing at all.

The impure half of speaker identification. `voz.py` (task 2) is pure —
handed vectors, it never sees audio and never loads a model, which is
what lets it be tested exhaustively without a microphone in the room.
This module exists only to be as thin as possible around the one thing
`voz.py` cannot do on its own: turn PCM into a vector by running it
through `pyannote/embedding`, exported to ONNX
(`docs/superpowers/specs/2026-09-06-probe-locutor.md`).

The input contract, from that probe: raw 16 kHz mono float32 audio,
input named `waveform`, shape `(batch, frames)`, both dimensions
symbolic; output named `embeddings`, shape `(batch, 512)`. Below roughly
4,800 samples (0.30 s) the graph itself raises inside a `Conv` node
rather than returning a meaningless vector — a useful safety property,
but this module refuses earlier than that anyway (`_MINIMO_SEGUNDOS`),
because speaker identification below a second is guesswork and this
project's typical utterance is short.

**The vector this returns is NOT L2-normalized** — the graph does not
normalize it (measured norms ran roughly 1600-2200) — and this module
must not normalize it either. `voz.coseno` normalizes both sides itself,
which is where that belongs; handing back something pre-normalized here
would be a second, silent normalization hiding behind the first.

Loaded lazily and never at import (CLAUDE.md §2.8): the microphone
thread calls `.vector()`, and nothing in this module may raise into it.
A missing model file, one onnxruntime refuses, or one that raises once
asked to run must cost this utterance's speaker identification, never
the microphone. See `vad.SileroDetector` for how a model is loaded and
held in this codebase, and `stt.Transcriber` / `stt.py:127` for the
int16-to-float32 conversion reused here unchanged.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from loguru import logger

if TYPE_CHECKING:
    import numpy as np

ENV_MODELO = "JARVIS_WIDGET_LOCUTOR_MODEL"

DEFAULT_MODEL_PATH = Path.home() / ".jarvis" / "models" / "pyannote_embedding.onnx"

_SAMPLE_RATE = 16000

# Speaker identification below a second is guesswork, independent of
# what the graph itself will accept (measured floor: 0.30 s — see the
# module docstring). This project's typical utterance is short enough
# that the margin above the graph's own floor matters.
_MINIMO_SEGUNDOS = 1.0
_MINIMO_MUESTRAS = int(_MINIMO_SEGUNDOS * _SAMPLE_RATE)


class _Sesion(Protocol):
    def get_inputs(self) -> list: ...
    def run(self, output_names: list[str] | None, feed: dict) -> list: ...


class Locutor:
    """`pyannote/embedding` over onnxruntime: PCM in, a 512-wide vector out.

    `listo` is False, and `vector()` always None, for anything short of
    a session that loaded and ran cleanly — a missing file, one
    onnxruntime refuses at load time, or one that raises once it is
    asked to run. None of those may raise into the caller.
    """

    def __init__(self, model_path: str | os.PathLike[str] | None = None) -> None:
        self._session: _Sesion | None = None
        self._input_name = "waveform"
        self._logged_failure = False

        path = Path(model_path or os.getenv(ENV_MODELO) or DEFAULT_MODEL_PATH)
        try:
            import onnxruntime as ort

            if not path.is_file():
                raise FileNotFoundError(f"speaker model not at {path}")
            options = ort.SessionOptions()
            # One utterance at a time, from one thread: a pool per
            # session costs more in scheduling than the model costs to
            # run (same reasoning as vad.SileroDetector).
            options.inter_op_num_threads = 1
            options.intra_op_num_threads = 1
            session = ort.InferenceSession(str(path), sess_options=options)
        except Exception as exc:
            logger.error(f"speaker embedding model not usable at {path}: {exc!r}")
            return

        self._session = session
        self._input_name = session.get_inputs()[0].name

    @classmethod
    def para_pruebas(cls, sesion: _Sesion) -> "Locutor":
        """Build a `Locutor` around an already-made session.

        Exists so the tests need no model file on disk: `sesion` stands
        in for `onnxruntime.InferenceSession` entirely.
        """
        locutor = cls.__new__(cls)
        locutor._session = sesion
        locutor._input_name = sesion.get_inputs()[0].name
        locutor._logged_failure = False
        return locutor

    @property
    def listo(self) -> bool:
        return self._session is not None

    def vector(self, pcm: bytes) -> "np.ndarray | None":
        """16 kHz mono int16 PCM in, a (512,) float32 vector out, or None.

        None for: no model loaded, an utterance shorter than
        `_MINIMO_SEGUNDOS`, or the model raising when asked to run.
        Never raises.
        """
        if self._session is None:
            return None

        import numpy as np

        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        if audio.shape[0] < _MINIMO_MUESTRAS:
            return None

        try:
            (salida,) = self._session.run(
                None, {self._input_name: audio[np.newaxis, :]}
            )
        except Exception as exc:
            # Logged once per Locutor, not once per utterance: a model
            # that has started raising keeps raising, and filling the
            # journal with the same traceback tells nobody anything new
            # (CLAUDE.md §2.8, VoskSwitch in __main__.py — the same
            # invariant applied here).
            if not self._logged_failure:
                logger.error(f"speaker embedding failed: {exc!r}")
                self._logged_failure = True
            return None

        return np.asarray(salida, dtype=np.float32).reshape(-1)
