"""The one flag: which task waits, and for what."""

from Hermes.plugins.samantha_code.pending import Pending


def test_starts_empty_and_round_trips():
    p = Pending()
    assert p.get() is None
    p.set("t1", "gate")
    assert p.get() == ("t1", "gate")
    p.clear()
    assert p.get() is None


def test_a_new_question_replaces_the_old():
    p = Pending()
    p.set("t1", "question")
    p.set("t1", "checkpoint")
    assert p.get() == ("t1", "checkpoint")
