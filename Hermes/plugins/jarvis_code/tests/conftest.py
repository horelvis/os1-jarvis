"""Shared fixtures for the plugin's tests.

`capture_logs` exists because of a real defect: this plugin swallows
exceptions in two places on purpose (the dispatch loop must survive one
bad event, and an injection must not take the follower with it), and a
swallowed exception with no stack is invisible. The fixture is how
"keeps its traceback" becomes something a test can assert.

`wiring` is here rather than in `test_dispatch.py` because two modules
drive the dispatch loop now — that one and `test_contract.py`, which
reads the payloads it feeds from the fixture the bridge's own suite
reads.
"""

import io
import threading

import pytest
from loguru import logger

import Hermes.plugins.jarvis_code as mod


@pytest.fixture
def capture_logs():
    """Everything loguru writes during one test, tracebacks included."""
    sink = io.StringIO()
    handler = logger.add(sink, level="DEBUG", backtrace=True, diagnose=False)
    try:
        yield sink
    finally:
        logger.remove(handler)


class _FakeAdapter:
    def __init__(self) -> None:
        self.divert_chat = None


class _FakeCtx:
    def __init__(self) -> None:
        self.injected: list[str] = []

    def inject_message(self, text, **kwargs):
        self.injected.append(text)
        return True


@pytest.fixture
def wiring(monkeypatch):
    """A gateway made of lists: pushes, injections and one fake adapter."""
    pushed: list[tuple[str, dict]] = []
    adapter = _FakeAdapter()
    answers: list[tuple[str, str, str]] = []
    landed = threading.Event()

    def fake_push(text, *, done=False, reset=False):
        pushed.append((text, {"done": done, "reset": reset}))

    def fake_send_answer(url, task_id, text):
        answers.append((url, task_id, text))
        landed.set()
        return True

    asked: list[bool] = []

    monkeypatch.setattr(mod, "_push", fake_push)
    monkeypatch.setattr(mod, "_push_asking", asked.append)
    monkeypatch.setattr(mod, "_adapter", lambda: adapter)
    monkeypatch.setattr(mod.client, "send_answer", fake_send_answer)

    class Wiring:
        pass

    w = Wiring()
    w.pushed = pushed
    w.adapter = adapter
    w.answers = answers
    w.landed = landed
    w.ctx = _FakeCtx()
    w.asked = asked
    return w
