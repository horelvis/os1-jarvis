"""Milestones, not commands — the spec's table, as executable rules.

The dedup rules are the product decision: one "read" per reading phase,
one "edit" per file, never the same milestone twice in a row.
"""
import json
from pathlib import Path

from milestones import Milestone, Milestones, plain

FIXTURE = Path(__file__).parent / "fixtures" / "stream.jsonl"


def test_reading_is_one_milestone_per_phase_not_per_file():
    m = Milestones()
    assert m.feed("Read", {"file_path": "/x/a.py"}) == Milestone("read")
    assert m.feed("Grep", {"pattern": "foo"}) is None
    assert m.feed("Read", {"file_path": "/x/b.py"}) is None
    # A non-read tool ends the phase; the next read starts a new one.
    assert m.feed("Bash", {"command": "ls"}) == Milestone("run", "ls")
    assert m.feed("Read", {"file_path": "/x/c.py"}) == Milestone("read")


def test_editing_is_one_milestone_per_file():
    m = Milestones()
    assert m.feed("Edit", {"file_path": "/x/vad.py"}) == Milestone("edit", "vad.py")
    assert m.feed("Edit", {"file_path": "/x/vad.py"}) is None
    assert m.feed("Write", {"file_path": "/x/stt.py"}) == Milestone("edit", "stt.py")


def test_tests_are_recognised_and_their_outcome_follows():
    m = Milestones()
    assert m.feed("Bash", {"command": "pytest tests -q"}) == Milestone("tests")
    out = m.result("12 passed in 0.5s")
    assert out == Milestone("tests_out", "12 passed")


def test_a_result_with_no_tests_before_it_is_nothing():
    m = Milestones()
    m.feed("Bash", {"command": "ls"})
    assert m.result("12 passed in 0.5s") is None


def test_other_bash_shows_the_first_word_only():
    m = Milestones()
    assert m.feed("Bash", {"command": "ruff check . && ls"}) == Milestone("run", "ruff")


def test_notes_take_the_first_sentence_and_never_repeat():
    m = Milestones()
    assert m.note("Voy a mirar el VAD. Luego los tests.") == Milestone(
        "note", "Voy a mirar el VAD."
    )
    assert m.note("Voy a mirar el VAD. Otra vez.") is None  # same first sentence


def test_never_the_same_milestone_twice_in_a_row():
    m = Milestones()
    assert m.feed("Bash", {"command": "git diff"}) == Milestone("run", "git")
    assert m.feed("Bash", {"command": "git status"}) is None
    assert m.feed("Bash", {"command": "pytest -q"}) == Milestone("tests")


def test_plain_renders_every_kind():
    assert plain(Milestone("read")) == "Leyendo el proyecto…"
    assert plain(Milestone("edit", "vad.py")) == "Editando vad.py"
    assert plain(Milestone("tests")) == "Pasando los tests…"
    assert plain(Milestone("tests_out", "12 passed")) == "Tests: 12 passed"
    assert plain(Milestone("run", "git")) == "Ejecutando: git"
    assert plain(Milestone("note", "Hola.")) == "Hola."


def test_the_recorded_run_produces_no_consecutive_duplicates():
    """The real recording of 2026-08-26, through the real rules."""
    m = Milestones()
    lines: list[Milestone] = []
    for raw in FIXTURE.read_text().splitlines():
        try:
            event = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(event, dict) or event.get("type") != "assistant":
            continue
        for block in event.get("message", {}).get("content", []) or []:
            if not isinstance(block, dict):
                continue
            out = None
            if block.get("type") == "tool_use":
                out = m.feed(block.get("name", "?"), block.get("input") or {})
            elif block.get("type") == "text" and str(block.get("text", "")).strip():
                out = m.note(str(block["text"]))
            if out:
                lines.append(out)
    assert lines, "the fixture should produce something"
    assert all(a != b for a, b in zip(lines, lines[1:]))
