"""Tests for short-term ring-buffer memory."""

import pytest

from samantha.short_term import ShortTermBuffer


def test_append_and_retrieve(tmp_path):
    buf = ShortTermBuffer(tmp_path / "state.db", capacity=5)
    buf.append("user", "hola", user_id="u1")
    buf.append("samantha", "Hola. ¿Cómo va?", user_id="u1")
    entries = buf.list(user_id="u1")
    assert len(entries) == 2
    assert entries[0].role == "user"
    assert entries[0].text == "hola"
    assert entries[1].role == "samantha"
    assert entries[1].text == "Hola. ¿Cómo va?"


def test_ring_eviction(tmp_path):
    buf = ShortTermBuffer(tmp_path / "state.db", capacity=3)
    for i in range(5):
        buf.append("user", f"msg{i}", user_id="u1")
    entries = buf.list(user_id="u1")
    assert len(entries) == 3
    assert [e.text for e in entries] == ["msg2", "msg3", "msg4"]


def test_isolation_by_user(tmp_path):
    buf = ShortTermBuffer(tmp_path / "state.db", capacity=5)
    buf.append("user", "alice msg", user_id="alice")
    buf.append("user", "bob msg", user_id="bob")
    assert [e.text for e in buf.list(user_id="alice")] == ["alice msg"]
    assert [e.text for e in buf.list(user_id="bob")] == ["bob msg"]


def test_rejects_invalid_role(tmp_path):
    buf = ShortTermBuffer(tmp_path / "state.db", capacity=5)
    with pytest.raises(ValueError):
        buf.append("robot", "hi", user_id="u1")


def test_ids_are_unique_uuids(tmp_path):
    buf = ShortTermBuffer(tmp_path / "state.db", capacity=5)
    id1 = buf.append("user", "a", user_id="u1")
    id2 = buf.append("user", "b", user_id="u1")
    assert id1 != id2
    assert len(id1) == 36
