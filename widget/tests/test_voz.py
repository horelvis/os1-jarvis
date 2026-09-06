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
