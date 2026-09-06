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
    # 3 s. This test is about the vector's shape, not its length, and
    # the duration floor rose to 2.2 s on 2026-09-06 — see
    # `test_an_utterance_under_the_measured_floor_is_refused`.
    v = locutor.vector(b"\x00\x00" * 48000)
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


def test_an_odd_length_buffer_does_not_raise():
    # A real caller in this codebase cannot produce this — PCM always
    # arrives as whole int16 samples — but the module's own promise is
    # that NOTHING escapes `vector()`, not "nothing plausible".
    locutor = Locutor.para_pruebas(FakeSesion())
    assert locutor.vector(b"\x00" * 32001) is None


def test_an_utterance_under_the_measured_floor_is_refused():
    """Calibrated 2026-09-06 against seven real utterances from the amo,
    embedded and compared with his own enrolled centroid:

        1.5 s -> 0.307      3.0 s -> 0.614
        2.0 s -> 0.446      3.8 s -> 0.652, 0.678
        2.3 s -> 0.635      5.5 s -> 0.746

    His OWN voice at 1.5 s scores 0.307 — the range a different person
    lives in for this model. Below roughly two seconds the embedding
    carries too little to tell him from a stranger, so refusing is the
    only honest answer: `None` here becomes `CASA` in `persona_de`,
    which means "not attributable" rather than a guess.
    """
    locutor = Locutor.para_pruebas(FakeSesion())

    # 2.0 s at 16 kHz — the longest utterance that measured below the floor.
    assert locutor.vector(b"\x00\x00" * 32000) is None
    # 2.3 s — the shortest that measured above it.
    assert locutor.vector(b"\x00\x00" * 36800) is not None
