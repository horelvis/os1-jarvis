"""The answer plumbing of a run, tested without the SDK in the room.

`_pre_tool` is a coroutine over plain state (gates + queues), so it runs
under asyncio.run with no client. The SDK-driven paths stay covered by
test_bridge_sdk.py and by the human validation task.
"""

import asyncio
import queue

import answers


def test_assent_recognises_yes_and_only_yes():
    for yes in ("sí", "Si", "vale", "ok", "dale", "de acuerdo", "sí, hazlo"):
        assert answers.assent(yes)
    for no in ("no", "espera", "mejor no", "cámbialo a B", ""):
        assert not answers.assent(no)


import sdk_runner
from stream import Event


def _run() -> sdk_runner.SdkRun:
    return sdk_runner.SdkRun("da igual", cwd=".")


def test_answer_with_nothing_pending_is_false():
    assert _run().answer("sí") is False


def test_a_gate_denied_by_timeout_says_the_user_was_away():
    run = _run()
    run.gate_timeout = 0.05
    out = asyncio.run(
        run._pre_tool(
            {"tool_name": "Bash", "tool_input": {"command": "git push"}}, "t1", None
        )
    )
    decision = out["hookSpecificOutput"]
    assert decision["permissionDecision"] == "deny"
    assert "no está" in decision["permissionDecisionReason"]
    assert run.pending is None
    kinds = _drain_kinds(run)
    assert "gate" in kinds and "resolved" in kinds


def test_a_gate_answered_yes_is_allowed():
    run = _run()

    async def scenario():
        task = asyncio.ensure_future(
            run._pre_tool(
                {"tool_name": "Bash", "tool_input": {"command": "git push"}}, "t1", None
            )
        )
        await asyncio.sleep(0.01)
        assert run.pending == "gate"
        assert run.answer("sí") is True
        return await task

    out = asyncio.run(scenario())
    assert out == {}  # allowed: the hook stays silent
    assert run.pending is None


def test_a_gate_answered_no_carries_the_users_words():
    run = _run()

    async def scenario():
        task = asyncio.ensure_future(
            run._pre_tool(
                {"tool_name": "Bash", "tool_input": {"command": "git push"}}, "t1", None
            )
        )
        await asyncio.sleep(0.01)
        run.answer("no, todavía no")
        return await task

    out = asyncio.run(scenario())
    decision = out["hookSpecificOutput"]
    assert decision["permissionDecision"] == "deny"
    assert "no, todavía no" in decision["permissionDecisionReason"]


def test_an_ordinary_tool_passes_without_a_word():
    run = _run()
    out = asyncio.run(
        run._pre_tool(
            {"tool_name": "Bash", "tool_input": {"command": "pytest -q"}}, "t1", None
        )
    )
    assert out == {}
    assert _drain_kinds(run) == []


def test_silence_while_pending_does_not_kill_the_run(monkeypatch):
    """The silence guard must not count a held question as a hang.

    `_pump` is stubbed to a no-op: this test is about the queue-wait
    logic inside `events()`, not about actually driving the SDK (which
    is not installed in this venv). The queue is therefore driven by
    hand — nothing pushes to it until the test does.
    """
    monkeypatch.setattr(sdk_runner, "SILENCE_TIMEOUT", 0.05)
    run = _run()
    run.pending = "question"
    run._pump = lambda: None  # no-op: nothing but this test touches the queue

    import threading
    import time

    thread = threading.Thread(target=lambda: list(run.events()), daemon=True)
    thread.start()

    time.sleep(sdk_runner.SILENCE_TIMEOUT * 3)
    assert thread.is_alive()
    assert run.failed is False

    run.pending = None
    run._queue.put(sdk_runner._DONE)
    thread.join(timeout=2)
    assert not thread.is_alive()


def _drain_kinds(run) -> list[str]:
    kinds = []
    while True:
        try:
            item = run._queue.get_nowait()
        except queue.Empty:
            return kinds
        if isinstance(item, Event):
            kinds.append(item.kind)
