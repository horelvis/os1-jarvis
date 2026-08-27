"""Firehose payloads → the exact lines the band shows."""

from Hermes.plugins.samantha_code.hitos import Dedup, render


def test_each_milestone_kind_has_its_line():
    assert render({"event": "milestone", "kind": "read", "detail": "", "text": ""}) == "Leyendo el proyecto…"
    assert render({"event": "milestone", "kind": "edit", "detail": "vad.py", "text": ""}) == "Editando vad.py"
    assert render({"event": "milestone", "kind": "tests", "detail": "", "text": ""}) == "Pasando los tests…"
    assert render({"event": "milestone", "kind": "run", "detail": "git", "text": ""}) == "Ejecutando: git"
    assert render({"event": "milestone", "kind": "note", "detail": "Voy al VAD.", "text": ""}) == "Voy al VAD."


def test_test_outcomes_speak_spanish():
    line = render({"event": "milestone", "kind": "tests_out", "detail": "12 passed, 2 failed", "text": ""})
    assert line == "Tests: 12 pasan, 2 fallan"


def test_test_outcomes_translate_errors_plural_and_leave_singular_alone():
    plural = render({"event": "milestone", "kind": "tests_out", "detail": "3 passed, 1 errors", "text": ""})
    assert plural == "Tests: 3 pasan, 1 errores"
    singular = render({"event": "milestone", "kind": "tests_out", "detail": "1 error", "text": ""})
    assert singular == "Tests: 1 error"


def test_unknown_kinds_fall_back_to_the_text():
    assert render({"event": "milestone", "kind": "novel", "detail": "", "text": "algo"}) == "algo"
    assert render({"event": "milestone", "kind": "novel", "detail": "", "text": ""}) is None


def test_questions_are_marked_and_checkpoints_stay_off_the_band():
    assert render({"event": "ask", "qkind": "question", "text": "¿A o B?"}) == "? ¿A o B?"
    assert render({"event": "ask", "qkind": "gate", "text": "git push"}) == "? Quiere: git push"
    assert render({"event": "ask", "qkind": "checkpoint", "text": "Hecho."}) is None


def test_other_events_render_nothing():
    for ev in ("task", "resolved", "end"):
        assert render({"event": ev}) is None


def test_dedup_drops_only_consecutive_repeats():
    d = Dedup()
    assert d.feed("a") == "a"
    assert d.feed("a") is None
    assert d.feed("b") == "b"
    assert d.feed("a") == "a"


def test_a_raw_line_is_printed_exactly_as_it_arrived():
    # The user, 2026-08-27: «deja de filtrar». A raw line is already the
    # assistant's own words; putting a wording of ours over the top of
    # it is the filtering he asked to stop.
    line = "• Bash(pytest -q)"
    assert render({"event": "milestone", "kind": "raw", "text": line}) == line


def test_a_raw_line_with_no_text_is_dropped():
    assert render({"event": "milestone", "kind": "raw", "text": ""}) is None
