from collections import Counter

import numpy as np

from jarvis_widget.medicion import (
    Muestra,
    centroide,
    centroides_loo,
    parsear_nombre,
    rango,
    sanear_condicion,
    siguiente_seq,
    tabla_confusion,
)
from jarvis_widget.voz import coseno


def _v(*xs: float) -> np.ndarray:
    return np.array(xs, dtype=np.float32)


def _m(
    persona: str, seq: int, vector: np.ndarray, condicion: str = "estandar"
) -> Muestra:
    return Muestra(persona, condicion, seq, vector, None)


# --------------------------------------------------------------------
# Leave-one-out: the property the whole measurement leans on
# --------------------------------------------------------------------


def test_leave_one_out_excludes_the_utterance_from_its_own_centroid():
    # Two orthogonal vectors as one person's only two samples. A
    # self-inclusive centroid would score utterance 1 against the mean of
    # BOTH vectors — cos((1,0), (0.5,0.5)) ~= 0.707 — inflating its own
    # similarity. Leave-one-out scores it against the OTHER vector alone,
    # which is exactly orthogonal to it: 0.0.
    m1 = _m("papa", 1, _v(1, 0))
    m2 = _m("papa", 2, _v(0, 1))
    indice = {"papa": [m1, m2]}

    centroides = centroides_loo(m1, indice)

    assert coseno(m1.vector, centroides["papa"]) == 0.0


def test_a_person_with_a_single_utterance_has_no_leave_one_out_centroid():
    # With only one sample, excluding it leaves nothing to build a
    # centroid from. Today's decision: that person is not a candidate for
    # their own utterance at all, rather than falling back to a centroid
    # that includes the very thing being scored.
    unica = _m("papa", 1, _v(1, 0))
    indice = {"papa": [unica]}

    assert centroides_loo(unica, indice) == {}


def test_a_person_with_zero_samples_in_the_index_is_skipped_not_crashed():
    # An index entry with an empty list must never reach `centroide([])`,
    # which raises on an empty stack. This should not happen from data
    # built by grouping real samples, but the function must degrade
    # rather than crash if it does — the same posture as `voz.Huellas`.
    m1 = _m("papa", 1, _v(1, 0))
    m2 = _m("papa", 2, _v(0, 1))
    indice = {"papa": [m1, m2], "marta": []}

    centroides = centroides_loo(m1, indice)

    assert set(centroides) == {"papa"}


# --------------------------------------------------------------------
# The confusion table: correct, casa, and wrong, counted separately
# --------------------------------------------------------------------


def test_tabla_confusion_on_no_samples_at_all_is_all_zero_rows():
    filas = tabla_confusion([], {}, [0.3, 0.5], 0.05)

    assert filas == [(0.3, 0, 0, 0, Counter()), (0.5, 0, 0, 0, Counter())]


def test_when_everybody_has_only_one_sample_nobody_can_be_confirmed():
    # No leave-one-out centroid exists for anybody, so every utterance
    # must fall back to `casa` rather than being scored against nothing.
    papa = _m("papa", 1, _v(1, 0))
    marta = _m("marta", 1, _v(0, 1))
    indice = {"papa": [papa], "marta": [marta]}

    ((_, correctas, rechazadas, equivocadas, _),) = tabla_confusion(
        [papa, marta], indice, [0.3], 0.05
    )

    assert (correctas, rechazadas, equivocadas) == (0, 2, 0)


def test_confusion_counts_at_a_floor_above_and_a_floor_below_every_score():
    # Two people, identical samples within each person and orthogonal
    # across: leave-one-out gives an own-score of exactly 1.0 and a
    # cross-score of exactly 0.0 for every utterance, by construction.
    papa1, papa2 = _m("papa", 1, _v(1, 0, 0)), _m("papa", 2, _v(1, 0, 0))
    marta1, marta2 = _m("marta", 1, _v(0, 1, 0)), _m("marta", 2, _v(0, 1, 0))
    muestras = [papa1, papa2, marta1, marta2]
    indice = {"papa": [papa1, papa2], "marta": [marta1, marta2]}

    # A floor above the maximum possible cosine (1.0): nobody can ever
    # clear it, so every utterance is refused — never guessed wrong.
    ((_, correctas, rechazadas, equivocadas, _),) = tabla_confusion(
        muestras, indice, [1.01], 0.05
    )
    assert (correctas, rechazadas, equivocadas) == (0, 4, 0)

    # A floor of 0.0: the own-score (1.0) beats the cross-score (0.0) by
    # the whole distance, so every utterance is attributed, correctly.
    ((_, correctas, rechazadas, equivocadas, _),) = tabla_confusion(
        muestras, indice, [0.0], 0.05
    )
    assert (correctas, rechazadas, equivocadas) == (4, 0, 0)


def test_a_wrong_attribution_is_counted_separately_from_a_refusal():
    # `ana` is built to be a BAD witness for herself: her two samples
    # point in opposite directions, so leaving either one out scores the
    # other against it at cos = -1.0. `beto`'s two samples are identical,
    # so his centroid is a clean (1, 0) — closer to `ana`'s first
    # utterance than `ana`'s own leave-one-out centroid is.
    ana1, ana2 = _m("ana", 1, _v(1, 0)), _m("ana", 2, _v(-1, 0))
    beto1, beto2 = _m("beto", 1, _v(1, 0)), _m("beto", 2, _v(1, 0))
    muestras = [ana1, ana2, beto1, beto2]
    indice = {"ana": [ana1, ana2], "beto": [beto1, beto2]}

    # ana1: own LOO score -1.0, beto's centroid 1.0 -> wrongly "beto".
    # ana2: own LOO score -1.0, beto's centroid -1.0 too, but -1.0 is
    #       below the floor regardless of the tie -> refused as casa.
    # beto1, beto2: own LOO score 1.0 against ana's centroid, which is
    #       the zero vector (her two samples cancel) -> correctly "beto".
    ((_, correctas, rechazadas, equivocadas, ejemplos),) = tabla_confusion(
        muestras, indice, [0.3], 0.05
    )

    assert (correctas, rechazadas, equivocadas) == (2, 1, 1)
    assert ejemplos == Counter({("ana", "beto"): 1})


# --------------------------------------------------------------------
# centroide: the plain mean
# --------------------------------------------------------------------


def test_centroide_is_the_mean_of_its_vectors():
    assert list(centroide([_v(1, 0), _v(3, 0)])) == [2.0, 0.0]


# --------------------------------------------------------------------
# The filename convention: round trip and next-free-index
# --------------------------------------------------------------------


def test_sanear_condicion_then_parsear_nombre_round_trips():
    for cruda, seq in [("Con la tele encendida", 3), ("  cansado  ", 12), ("", 1)]:
        condicion = sanear_condicion(cruda)
        stem = f"papa__{seq:03d}__{condicion}"
        assert parsear_nombre(stem) == ("papa", seq, condicion)


def test_sanear_condicion_never_returns_empty():
    assert sanear_condicion("") == "estandar"
    assert sanear_condicion("   ") == "estandar"
    assert sanear_condicion("¡¡¡???") == "estandar"


def test_parsear_nombre_rejects_anything_that_does_not_match():
    assert parsear_nombre("sin-separador") is None
    assert parsear_nombre("papa__1__estandar") is None  # seq needs 3 digits
    assert parsear_nombre("") is None


def test_siguiente_seq_starts_at_one_for_a_directory_that_does_not_exist(tmp_path):
    assert siguiente_seq(tmp_path, "papa") == 1


def test_siguiente_seq_finds_the_next_free_index_with_gaps_in_the_sequence(tmp_path):
    vectores = tmp_path / "vectores"
    vectores.mkdir()
    for nombre in (
        "papa__001__estandar.npy",
        "papa__003__tele.npy",
        "papa__007__susurro.npy",
    ):
        (vectores / nombre).write_bytes(b"")

    assert siguiente_seq(tmp_path, "papa") == 8


def test_siguiente_seq_is_scoped_to_one_person(tmp_path):
    vectores = tmp_path / "vectores"
    vectores.mkdir()
    (vectores / "papa__005__estandar.npy").write_bytes(b"")
    (vectores / "marta__009__estandar.npy").write_bytes(b"")

    assert siguiente_seq(tmp_path, "papa") == 6
    assert siguiente_seq(tmp_path, "marta") == 10
    assert siguiente_seq(tmp_path, "otro") == 1


def test_rango_is_inclusive_of_both_ends():
    assert rango(0.30, 0.40, 0.05) == [0.30, 0.35, 0.40]
