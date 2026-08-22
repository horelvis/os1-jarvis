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
        {"q": "Cuéntame algo que te haya hecho ilusión", "a": "encontré un café nuevo"},
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
    matched = any(any(s.lower() in r.text.lower() for s in expected_substrings) for r in results)
    assert matched, f"recall returned {[r.text for r in results]}"


def test_delete_profile_removes_facts_only(tmp_path):
    mem = _make_mem(tmp_path)
    complete_onboarding(mem, name="Carlos", answers=_six_answers())
    delete_profile(mem)
    assert is_onboarded(mem) is False
    results = mem.recall("color favorito", k=10)
    assert results, "user memory chunks must survive profile deletion"


def test_complete_onboarding_writes_big_five_facts(tmp_path):
    """Each Big Five answer (Q1..Q5) is promoted to a kind=big5_{dim} fact."""
    from samantha.profile import BIG5_BY_INDEX

    mem = _make_mem(tmp_path)
    complete_onboarding(mem, name="Dana", answers=_six_answers())

    for idx, dim in BIG5_BY_INDEX.items():
        fact = mem.get_fact(f"big5_{dim}")
        assert fact is not None, f"big5_{dim} (slot {idx}) should be set"
        # value is the raw answer text
        expected_answer = _six_answers()[idx]["a"]
        assert fact["value"] == expected_answer.strip()


def test_delete_profile_removes_big_five_facts(tmp_path):
    """delete_profile must wipe every Big Five fact too — not just name."""
    from samantha.profile import BIG5_FACT_KINDS

    mem = _make_mem(tmp_path)
    complete_onboarding(mem, name="Eli", answers=_six_answers())
    delete_profile(mem)
    for kind in BIG5_FACT_KINDS:
        assert mem.get_fact(kind) is None, f"{kind} survived delete_profile"


def test_delete_profile_removes_multiple_historical_fact_versions(tmp_path):
    """delete_profile must remove all historical versions of profile facts, not just the latest."""
    mem = _make_mem(tmp_path)
    mem.set_fact("name", "Oldest Alice")
    mem.set_fact("name", "Older Alice")
    mem.set_fact("name", "Current Alice")

    delete_profile(mem)

    assert mem.get_fact("name") is None

    # Verify no facts remain in the database at all for 'name'
    res = mem._collection.get(
        where={
            "$and": [
                {"user_id": "primary"},
                {"role": "fact"},
                {"kind": "name"},
            ]
        }
    )
    assert not res.get("ids")


def test_memory_remember_with_extra_metadata(tmp_path):
    mem = Memory(persist_dir=str(tmp_path / "mem"))
    mem.remember("user", "respuesta uno", extra_metadata={"onboarding_slot": 3})
    items = mem.get_chunks({"onboarding_slot": {"$gte": 0}})
    assert len(items) == 1
    doc, meta = items[0]
    assert doc == "respuesta uno"
    assert meta["onboarding_slot"] == 3


def test_remember_rejects_reserved_extra_metadata_keys(tmp_path):
    """extra_metadata must not be able to override role/timestamp/user_id."""
    import pytest

    mem = Memory(persist_dir=str(tmp_path / "mem"))
    with pytest.raises(ValueError):
        mem.remember(
            "user",
            "texto",
            extra_metadata={"role": "samantha", "user_id": "otro", "onboarding_slot": 2},
        )
    # A call with only non-reserved keys still succeeds.
    chunk_id = mem.remember("user", "texto ok", extra_metadata={"onboarding_slot": 2})
    assert chunk_id != ""
    items = mem.get_chunks({"onboarding_slot": {"$gte": 0}})
    assert len(items) == 1
    doc, meta = items[0]
    assert doc == "texto ok"
    assert meta["role"] == "user"
    assert meta["user_id"] == "primary"
    assert meta["onboarding_slot"] == 2


def test_answers_survive_slow_onboarding_writes(tmp_path, monkeypatch):
    """Recovery must not depend on the ±5 s window. Simulate slow
    embedding: every clock read during onboarding advances a minute,
    spreading the chunks far beyond any timestamp window."""
    import itertools

    from samantha import memory as memory_mod

    mem = _make_mem(tmp_path)

    base = 1_800_000_000
    counter = itertools.count()
    # Patches time.time globally (memory.py and profile.py share the
    # stdlib module); monkeypatch restores it on teardown.
    monkeypatch.setattr(memory_mod.time, "time", lambda: base + 60 * next(counter))

    complete_onboarding(mem, name="Bob", answers=_six_answers())
    profile = get_profile(mem)
    assert profile is not None
    assert len(profile["answers"]) == 6


def test_legacy_profiles_recover_via_timestamp_window(tmp_path):
    """Profiles stored before the slot tag existed (plain chunks + a
    marker fact in the same second) must still recover their answers."""
    import time

    mem = _make_mem(tmp_path)
    for entry in _six_answers():
        mem.remember("user", f"[Q] {entry['q']} → [A] {entry['a']}")
    mem.set_fact("name", "Bob", text="El usuario se llama Bob")
    mem.set_fact("onboarding_completed_at", int(time.time()), text="Onboarding completado")

    profile = get_profile(mem)
    assert profile is not None
    assert len(profile["answers"]) == 6
