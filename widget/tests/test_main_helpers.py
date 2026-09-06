# ── who asked for an enrolment: the console or a voice ────────────────


def test_a_console_request_is_marked_as_one(tmp_path):
    """`tools/enrolar.py` needs a shell on this box, and that shell IS
    the gate — it always was, before there was a spoken way in. The
    widget's amo check exists for the SPOKEN path, and applying it to
    the signal itself locked the operator out of his own machine
    (found 2026-09-06, minutes after shipping it)."""
    import json

    from jarvis_widget.__main__ import pendiente_de_alta

    ruta = tmp_path / "enrolamiento.json"
    ruta.write_text(json.dumps({"persona": "hore", "origen": "consola"}))

    assert pendiente_de_alta(ruta) == ("hore", "consola")


def test_a_spoken_request_is_marked_as_one(tmp_path):
    import json

    from jarvis_widget.__main__ import pendiente_de_alta

    ruta = tmp_path / "enrolamiento.json"
    ruta.write_text(json.dumps({"persona": "nata", "origen": "voz"}))

    assert pendiente_de_alta(ruta) == ("nata", "voz")


def test_an_unmarked_request_is_treated_as_spoken(tmp_path):
    """The strict path is the default. An older file, a hand-written
    one, or anything that lost its marking gets the amo check rather
    than the console's free pass."""
    import json

    from jarvis_widget.__main__ import pendiente_de_alta

    ruta = tmp_path / "enrolamiento.json"
    ruta.write_text(json.dumps({"persona": "nata"}))

    assert pendiente_de_alta(ruta) == ("nata", "voz")


def test_a_missing_request_is_nobody_and_still_strict(tmp_path):
    from jarvis_widget.__main__ import pendiente_de_alta
    from jarvis_widget.personas import CASA

    assert pendiente_de_alta(tmp_path / "no-existe.json") == (CASA, "voz")
