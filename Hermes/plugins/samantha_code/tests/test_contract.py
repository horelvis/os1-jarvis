"""The firehose payloads, rendered — against the fixture both sides read.

The other half of `Hermes/bridges/code-a2a/tests/test_contract.py`. That
one asserts the bridge still EMITS exactly these keys; this one asserts
the plugin still HANDLES exactly these payloads, reading its inputs from
the same file rather than from a hand-written copy of them.

Why it is worth a file of its own: the two processes share no import,
by design (`hitos.py`: "two processes, two vocabularies, no import
across the seam"). That is the right call for the wording and it left
the payload keys with nothing pinning them at all — a rename on the
bridge broke only the bridge's tests.
"""

import json
import threading
from pathlib import Path

import pytest

import Hermes.plugins.samantha_code as mod

FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "bridges"
    / "code-a2a"
    / "tests"
    / "fixtures"
    / "firehose.json"
)


def contract() -> dict:
    return {k: v for k, v in json.loads(FIXTURE.read_text()).items() if k != "_why"}


def test_the_fixture_is_where_the_bridge_keeps_it():
    # A moved fixture must fail loudly here rather than quietly stop
    # being read: a test that silently covers nothing is worse than the
    # gap it was written to close.
    assert FIXTURE.is_file(), f"no firehose contract at {FIXTURE}"


@pytest.mark.parametrize("kind", sorted(contract()))
def test_the_plugin_acts_on_every_payload_the_bridge_emits(kind, monkeypatch, wiring):
    """Each payload does something: a line, a prompt, or a state change.

    Not "does not crash" — the dispatch loop swallows exceptions on
    purpose, so a payload it cannot read is silently dropped and a test
    that only watched for a raise would pass on a renamed key.
    """
    payload = contract()[kind]
    monkeypatch.setattr(
        mod.client, "follow_events", lambda url, stop: iter([dict(payload)])
    )
    mod._run_bridge_mode(wiring.ctx, "http://bridge", threading.Event())

    lines = [text for text, _flags in wiring.pushed if text]
    if kind == "task":
        assert wiring.pushed == [("", {"done": False, "reset": True})]
    elif kind == "milestone":
        assert lines == [f"Editando {payload['detail']}\n"]
    elif kind == "ask":
        assert lines == [f"? Quiere: {payload['text']}\n"]
        assert wiring.asked[-1] is True
        assert f"«{payload['text']}»" in wiring.ctx.injected[0]
    elif kind == "resolved":
        assert wiring.asked[-1] is False
        assert lines == []
    elif kind == "end":
        assert lines == ["— terminado\n"]
        assert wiring.pushed[-1] == ("", {"done": True, "reset": False})
    else:  # pragma: no cover - a new event kind with nobody rendering it
        raise AssertionError(f"the fixture grew {kind!r} and nothing handles it")


def test_the_three_qkinds_each_have_a_prompt_of_their_own():
    # The fixture pins one `qkind`; all three have to reach a prompt, or
    # a question is relayed with a gate's wording and the user is asked
    # for permission to answer something.
    assert len({mod.voz.prompt_for(q, "X") for q in ("question", "gate", "checkpoint")}) == 3
    assert contract()["ask"]["qkind"] in ("question", "gate", "checkpoint")
