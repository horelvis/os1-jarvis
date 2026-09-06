from jarvis_widget import lecturas


def test_every_passage_is_a_reasonable_length_to_read_aloud():
    for pasaje in lecturas.LECTURAS:
        palabras = pasaje.split()
        assert 8 <= len(palabras) <= 18, pasaje


def test_no_passage_repeats():
    assert len(set(lecturas.LECTURAS)) == len(lecturas.LECTURAS)


def test_elegir_returns_the_requested_count():
    assert len(lecturas.elegir(3)) == 3
    assert lecturas.elegir(0) == []


def test_elegir_returns_distinct_passages_when_enough_exist():
    elegidas = lecturas.elegir(5)
    assert len(set(elegidas)) == 5
    assert all(p in lecturas.LECTURAS for p in elegidas)


def test_elegir_never_raises_for_more_than_exist():
    n = len(lecturas.LECTURAS) + 7
    elegidas = lecturas.elegir(n)
    assert len(elegidas) == n
    assert all(p in lecturas.LECTURAS for p in elegidas)


def test_elegir_never_raises_for_a_negative_count():
    assert lecturas.elegir(-3) == []
