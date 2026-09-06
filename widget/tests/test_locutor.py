import numpy as np

from jarvis_widget.locutor import Locutor


class FakeSesion:
    """Stands in for onnxruntime. The point of this test is the wrapper's
    behaviour around the model, not the model.

    Named `waveform` and 512-wide because that is what task 1 actually
    found: `pyannote/embedding`, ONNX, input `waveform`, output
    `embeddings` shaped `(batch, 512)` — see
    docs/superpowers/specs/2026-09-06-probe-locutor.md. The brief this
    test came from named the input `feats` and the output 192-wide,
    both from a candidate (CAM++) that was not chosen; a fake that lies
    about the real contract is worse than no fake at all.
    """

    def __init__(self, salida=None, revienta=False):
        self._salida = salida if salida is not None else np.ones((1, 512), np.float32)
        self._revienta = revienta

    def get_inputs(self):
        class E:
            name = "waveform"

        return [E()]

    def run(self, _outputs, _feed):
        if self._revienta:
            raise RuntimeError("el modelo ha explotado")
        return [self._salida]


def test_a_missing_model_is_not_ready_and_does_not_raise(tmp_path):
    locutor = Locutor(tmp_path / "no-existe.onnx")
    assert not locutor.listo
    assert locutor.vector(b"\x00\x00" * 16000) is None


def test_a_vector_comes_back_flat_and_float32():
    locutor = Locutor.para_pruebas(FakeSesion())
    v = locutor.vector(b"\x00\x00" * 16000)
    assert v is not None and v.ndim == 1 and v.dtype == np.float32


def test_a_model_that_raises_costs_the_utterance_and_nothing_else():
    # The audio thread calls this. An exception here would make him deaf
    # while looking perfectly healthy — the failure CLAUDE.md §2.8
    # records costing three days in August.
    locutor = Locutor.para_pruebas(FakeSesion(revienta=True))
    assert locutor.vector(b"\x00\x00" * 16000) is None
    assert locutor.vector(b"\x00\x00" * 16000) is None


def test_an_utterance_too_short_to_mean_anything_is_refused():
    locutor = Locutor.para_pruebas(FakeSesion())
    assert locutor.vector(b"\x00\x00" * 800) is None
