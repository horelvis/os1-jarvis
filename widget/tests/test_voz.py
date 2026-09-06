import numpy as np

from jarvis_widget.personas import CASA
from jarvis_widget.voz import PISO_POR_DEFECTO, Huellas, coseno


def _v(*xs: float) -> np.ndarray:
    return np.array(xs, dtype=np.float32)


def test_cosine_is_one_for_the_same_direction_and_zero_for_a_right_angle():
    assert coseno(_v(1, 0), _v(2, 0)) == 1.0
    assert coseno(_v(1, 0), _v(0, 1)) == 0.0


def test_a_zero_vector_is_similar_to_nothing_and_does_not_divide_by_zero():
    assert coseno(_v(0, 0), _v(1, 0)) == 0.0


def test_the_nearest_person_wins_when_it_clears_the_floor():
    huellas = Huellas({"papa": _v(1, 0), "marta": _v(0, 1)})
    assert huellas.quien(_v(0.9, 0.1), piso=0.5) == "papa"
    assert huellas.quien(_v(0.1, 0.9), piso=0.5) == "marta"


def test_below_the_floor_nobody_is_recognised():
    huellas = Huellas({"papa": _v(1, 0)})
    assert huellas.quien(_v(0, 1), piso=0.5) == CASA


def test_an_empty_store_recognises_nobody_rather_than_crashing():
    assert Huellas({}).quien(_v(1, 0), piso=0.5) == CASA


def test_two_people_too_close_together_is_reported_rather_than_guessed():
    # Sisters. If the best and the second-best are within `margen`, he
    # does not know which, and saying `casa` is the honest answer.
    huellas = Huellas({"marta": _v(1, 0.02), "lucia": _v(1, 0.0)})
    assert huellas.quien(_v(1, 0.01), piso=0.5, margen=0.05) == CASA


def test_the_default_floor_is_a_number_somebody_chose():
    assert 0.0 < PISO_POR_DEFECTO < 1.0


def test_a_shape_mismatch_is_similar_to_nothing_and_does_not_raise():
    # A centroid stored by one embedding model has a different width than
    # a query from another. This is a shape mismatch, not a bug in the
    # caller, and it must degrade to CASA, never raise.
    huellas = Huellas({"papa": _v(1, 0, 0)})  # 3-dimensional centroid
    assert huellas.quien(_v(1, 0), piso=0.5) == CASA  # 2-dimensional query


def test_a_nan_vector_is_similar_to_nothing_and_answers_casa():
    # A non-finite embedding can appear on the audio path. It is neither
    # zero nor a valid direction, and must degrade to CASA. Before the
    # fix, NaN compared False to every threshold, so quien fell through to
    # returning a person even though coseno said it was garbage.
    huellas = Huellas({"papa": _v(1, 0), "marta": _v(0, 1)})
    assert huellas.quien(np.array([np.nan, 0], dtype=np.float32), piso=0.5) == CASA


def test_the_floor_admits_his_real_speech_and_still_refuses_a_stranger():
    """The placeholder floor was 0.6 and said so in its own comment.
    Measured 2026-09-06 against seven real utterances from the amo, the
    MEAN of his own speech against his enrolled centroid was 0.583 —
    below the floor. More than half his turns were answered `CASA`,
    which is what made `emparejar` refuse the owner of the house.

    0.45 is where those measurements put it: it admits everything from
    2.3 s upward (0.614 at worst) and still sits well above the 0.0-0.3
    band a different speaker occupies for this model.
    """
    import numpy as np

    from jarvis_widget.voz import PISO_POR_DEFECTO, Huellas

    centroide = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    huellas = Huellas({"orelvis": centroide})

    # 0.614 — his worst passing utterance. Must be attributed.
    casi = np.array([0.614, 0.789, 0.0], dtype=np.float32)
    assert huellas.quien(casi) == "orelvis"

    # 0.307 — his own 1.5 s utterance, and a stranger's range. Must not.
    lejos = np.array([0.307, 0.952, 0.0], dtype=np.float32)
    assert huellas.quien(lejos) == CASA

    assert PISO_POR_DEFECTO == 0.45
