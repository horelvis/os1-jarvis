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

# ── Raw, the way Claude Code shows it. «Deja de filtrar» ─────────────

from milestones import (  # noqa: E402
    BULLET,
    CORNER,
    MAX_LINE,
    result_line,
    text_line,
    tool_line,
)


def test_the_glyphs_are_ones_the_console_font_actually_has():
    """Claude Code's own `⏺` and `⎿` are in neither Ubuntu Sans Mono nor
    DejaVu Sans Mono on this box — `fc-list :charset=23fa` finds two
    fonts and neither is monospaced. A missing glyph is substituted from
    another font at another width, which is what the first capture of
    the strip showed. These two are in it, measured the same way.
    """
    assert (BULLET, CORNER) == ("•", "└")


def test_a_tool_call_shows_its_salient_argument():
    assert tool_line("Bash", {"command": "pytest -q"}) == f"{BULLET} Bash(pytest -q)"
    # A path is its basename: the console is 900 px wide and the
    # directory is the same one every time.
    assert tool_line("Read", {"file_path": "/home/x/p/calc.py"}) == (
        f"{BULLET} Read(calc.py)"
    )
    assert tool_line("Grep", {"pattern": "def suma"}) == f"{BULLET} Grep(def suma)"


def test_a_tool_call_with_nothing_worth_showing_is_just_its_name():
    assert tool_line("Skill", {}) == f"{BULLET} Skill"
    assert tool_line("Skill", "no soy un dict") == f"{BULLET} Skill"


def test_a_heredoc_keeps_its_first_line_instead_of_collapsing():
    # Measured on the strip: a multi-line command arrived as one
    # unreadable run of collapsed newlines filling the whole width.
    line = tool_line("Bash", {"command": "cd /p && python3 - <<'EOF'\nx = 1\nEOF"})
    assert line == f"{BULLET} Bash(cd /p && python3 - <<'EOF' (+2 líneas))"


def test_what_the_assistant_says_is_not_cut_to_its_first_sentence():
    # This is the filtering that stopped: `note()` kept the first
    # sentence and dropped the rest.
    said = text_line("Voy a mirar calc.py. Luego escribo el test.")
    assert said == f"{BULLET} Voy a mirar calc.py. Luego escribo el test."


def test_markdown_a_plain_console_cannot_draw_is_stripped():
    assert text_line("**RED** — escribo el test") == f"{BULLET} RED — escribo el test"
    assert text_line("__negrita__") == f"{BULLET} negrita"
    assert text_line("### Cambios") == f"{BULLET} Cambios"


def test_backticks_are_kept_because_they_are_all_that_marks_code():
    said = text_line("falla por `ImportError: cannot import name 'multiplica'`")
    assert "`ImportError: cannot import name 'multiplica'`" in said


def test_a_long_line_is_cut_rather_than_wrapped():
    assert len(text_line("x" * 500)) <= MAX_LINE
    assert text_line("x" * 500).endswith("…")
    assert len(tool_line("Bash", {"command": "y" * 500})) <= MAX_LINE
    assert len(result_line("z" * 500)) <= MAX_LINE


def test_a_result_is_indented_under_the_call_it_belongs_to():
    # The indent is the only thing tying a result to its call, and
    # collapsing whitespace over the whole line ate it once already.
    assert result_line("3 passed") == f"  {CORNER} 3 passed"
    assert result_line("primera\nsegunda\ntercera") == (
        f"  {CORNER} primera (+2 líneas)"
    )


def test_a_result_of_nothing_writes_nothing():
    assert result_line("") == ""
    assert result_line("   ") == ""
    assert text_line("   ") == ""
