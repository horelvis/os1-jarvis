"""Which project a sentence is about.

The names arrive through speech recognition, so this is the wake word's
problem again — with the opposite bias. `wake.py` guesses generously
because being ignored is its worst failure; here the worst failure is
opening the wrong repository, which writes files, so a close call is
refused rather than guessed.
"""

import pytest

import projects


@pytest.fixture()
def root(tmp_path):
    for name in ("os1-samantha", "barndoor", "jarvis", "jarvis-os", "LightRAG"):
        (tmp_path / name).mkdir()
    (tmp_path / ".hidden").mkdir()
    (tmp_path / "loose.txt").write_text("not a project")
    return tmp_path


def test_the_projects_are_the_directories(root):
    assert [p.name for p in projects.available(root)] == [
        "barndoor",
        "jarvis",
        "jarvis-os",
        "LightRAG",
        "os1-samantha",
    ]


def test_an_exact_name_resolves(root):
    assert projects.resolve("barndoor", root).name == "barndoor"


def test_case_and_punctuation_do_not_matter(root):
    assert projects.resolve("LIGHTRAG", root).name == "LightRAG"
    assert projects.resolve("os1 samantha", root).name == "os1-samantha"


def test_something_whisper_mangled_still_resolves(root):
    # "os1-samantha" spoken and transcribed.
    assert projects.resolve("os uno samantha", root).name == "os1-samantha"


def test_a_name_that_is_nothing_like_a_project_is_none(root):
    assert projects.resolve("comprar pan", root) is None


def test_two_close_names_are_a_question_not_a_guess(root):
    # "jarvis" and "jarvis-os" are one edit apart; picking one would
    # write files into the wrong repository.
    with pytest.raises(projects.Ambiguous):
        projects.resolve("jarvi", root)


def test_the_longest_name_wins_inside_a_sentence(root):
    found = projects.find_in("en jarvis-os, arregla el arranque", root)
    assert found.name == "jarvis-os"


def test_a_sentence_with_no_project_finds_nothing(root):
    assert projects.find_in("arregla el test que falla", root) is None


def test_the_root_is_the_boundary(root):
    assert projects.inside(root, root / "barndoor")
    assert not projects.inside(root, root.parent)
    assert not projects.inside(root, root / ".." / "etc")


def test_a_missing_root_is_empty_not_an_error(tmp_path):
    assert projects.available(tmp_path / "nope") == []
