"""Tests for the profile facade over Memory."""

from samantha.memory import Memory
from samantha.profile import (
    complete_onboarding,
    delete_profile,
    get_profile,
    is_onboarded,
)


def _six_answers() -> list[dict]:
    return [
        {"q": "¿Cómo te llamo?", "a": "Bob"},
        {"q": "¿Cómo estás hoy?", "a": "regular"},
        {"q": "¿Qué te gusta hacer?", "a": "salir a correr"},
        {"q": "Cuéntame algo que te haya hecho ilusión",
         "a": "encontré un café nuevo"},
        {"q": "¿Algo que te ronde la cabeza?", "a": "mi color favorito es el azul"},
        {"q": "¿Directa o cuidadosa?", "a": "directa"},
    ]


def _make_mem(tmp_path):
    # Tiny short-term ring so onboarding answers rotate into long-term-only
    # state by the end of complete_onboarding. recall() excludes short-term
    # entries (they're already in the conversation window), so without this
    # the tests below couldn't find the just-inserted answers via recall.
    return Memory(persist_dir=str(tmp_path / "mem"), short_term_capacity=2)


def test_not_onboarded_initially(tmp_path):
    mem = _make_mem(tmp_path)
    assert is_onboarded(mem) is False
    assert get_profile(mem) is None


def test_complete_onboarding_sets_facts(tmp_path):
    mem = _make_mem(tmp_path)
    profile = complete_onboarding(mem, name="Horelvis", answers=_six_answers())
    assert profile["name"] == "Horelvis"
    assert profile["onboarding_completed_at"] > 0
    assert len(profile["answers"]) == 6


def test_onboarding_persists_across_reopen(tmp_path):
    mem1 = _make_mem(tmp_path)
    complete_onboarding(mem1, name="Alice", answers=_six_answers())
    del mem1
    mem2 = _make_mem(tmp_path)
    assert is_onboarded(mem2) is True
    profile = get_profile(mem2)
    assert profile["name"] == "Alice"


def test_onboarding_answers_become_user_memory_chunks(tmp_path):
    mem = _make_mem(tmp_path)
    complete_onboarding(mem, name="Bob", answers=_six_answers())
    results = mem.recall("color favorito", k=10)
    expected_substrings = ["azul", "café", "correr"]
    matched = any(
        any(s.lower() in r.text.lower() for s in expected_substrings)
        for r in results
    )
    assert matched, f"recall returned {[r.text for r in results]}"


def test_delete_profile_removes_facts_only(tmp_path):
    mem = _make_mem(tmp_path)
    complete_onboarding(mem, name="Carlos", answers=_six_answers())
    delete_profile(mem)
    assert is_onboarded(mem) is False
    results = mem.recall("color favorito", k=10)
    assert results, "user memory chunks must survive profile deletion"
