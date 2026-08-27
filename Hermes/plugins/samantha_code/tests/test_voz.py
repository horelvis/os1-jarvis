"""What gets injected, and how stubbornly."""

import pytest

from Hermes.plugins.samantha_code import voz


def test_each_kind_has_a_prompt_that_carries_the_text_as_a_labelled_value():
    for kind in ("question", "gate", "checkpoint"):
        prompt = voz.prompt_for(kind, "¿A o B?")
        assert "«¿A o B?»" in prompt
        assert "asistente de código" in prompt


def test_an_unknown_kind_falls_back_to_the_question_wording():
    assert voz.prompt_for("nonsense", "algo") == voz.prompt_for("question", "algo")


@pytest.fixture
def _no_waiting(monkeypatch):
    """Bound this test's time: the real delays are 1+3+5 seconds."""
    monkeypatch.setattr(voz, "RETRY_DELAYS", (0.0, 0.0, 0.0))


def test_deliver_retries_on_false_and_stops_on_true(_no_waiting):
    calls = []

    def inject(text, **kwargs):
        calls.append(kwargs.get("session_key"))
        return len(calls) >= 2

    assert voz.deliver(inject, "hola") is True
    assert len(calls) == 2
    assert calls[0] == voz.KIOSK_SESSION_KEY


def test_deliver_gives_up_after_the_last_delay(_no_waiting):
    calls = []

    def inject(text, **kwargs):
        calls.append(text)
        return False

    assert voz.deliver(inject, "hola") is False
    assert len(calls) == len(voz.RETRY_DELAYS)


def test_an_injection_that_raises_costs_the_prompt_and_nothing_else(_no_waiting):
    def inject(text, **kwargs):
        raise RuntimeError("gateway going down")

    assert voz.deliver(inject, "hola") is False


def test_an_injection_that_raises_keeps_its_traceback(_no_waiting, capture_logs):
    def inject(text, **kwargs):
        raise TypeError("inject_message() got an unexpected keyword")

    voz.deliver(inject, "hola")
    logged = capture_logs.getvalue()
    assert "la inyección falló" in logged
    assert "Traceback (most recent call last)" in logged
