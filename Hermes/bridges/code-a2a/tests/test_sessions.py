"""Which conversation belongs to which project. Pure state, one file."""

import json

import pytest
from sessions import MAX_AGE_SECONDS, Sessions

NOW = 1_000_000.0


@pytest.fixture
def store(tmp_path):
    return Sessions(tmp_path / "code-sessions.json")


def test_a_project_nobody_has_worked_in_has_no_session(store):
    assert store.get("/home/nexus/git/barndoor", NOW) is None


def test_what_is_remembered_comes_back(store):
    store.remember("/home/nexus/git/barndoor", "abc-123", NOW)
    assert store.get("/home/nexus/git/barndoor", NOW) == "abc-123"


def test_sessions_are_per_project(store):
    """Two projects are two conversations, never one."""
    store.remember("/git/a", "session-a", NOW)
    store.remember("/git/b", "session-b", NOW)
    assert store.get("/git/a", NOW) == "session-a"
    assert store.get("/git/b", NOW) == "session-b"


def test_a_stale_session_is_not_resumed(store):
    """Resuming last month's context is worse than starting over."""
    store.remember("/git/a", "vieja", NOW)
    assert store.get("/git/a", NOW + MAX_AGE_SECONDS - 1) == "vieja"
    assert store.get("/git/a", NOW + MAX_AGE_SECONDS + 1) is None


def test_forgetting_starts_the_next_run_from_nothing(store):
    store.remember("/git/a", "mala", NOW)
    store.forget("/git/a")
    assert store.get("/git/a", NOW) is None


def test_it_survives_the_bridge_restarting(tmp_path):
    path = tmp_path / "s.json"
    Sessions(path).remember("/git/a", "abc", NOW)
    assert Sessions(path).get("/git/a", NOW) == "abc"


def test_a_corrupt_store_is_an_empty_one_not_a_crash(tmp_path):
    """A bridge that will not answer is worse than one that forgets."""
    path = tmp_path / "s.json"
    path.write_text("{ esto no es json", encoding="utf-8")
    store = Sessions(path)
    assert store.get("/git/a", NOW) is None
    store.remember("/git/a", "nueva", NOW)
    assert json.loads(path.read_text(encoding="utf-8"))["/git/a"]["session_id"] == "nueva"


def test_an_unwritable_store_does_not_take_the_run_down(tmp_path):
    """Losing the session costs continuity; raising costs the work."""
    store = Sessions(tmp_path / "no" / "such" / "dir" / "s.json")
    (tmp_path / "no").write_text("soy un fichero, no un directorio", encoding="utf-8")
    store.remember("/git/a", "abc", NOW)  # must not raise


def test_an_empty_session_id_is_not_worth_remembering(store):
    store.remember("/git/a", "", NOW)
    assert store.get("/git/a", NOW) is None
