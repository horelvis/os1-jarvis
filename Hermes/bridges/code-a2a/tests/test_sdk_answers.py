"""The answer plumbing of a run, tested without the SDK in the room.

`_pre_tool` is a coroutine over plain state (gates + queues), so it runs
under asyncio.run with no client. The SDK-driven paths stay covered by
test_bridge_sdk.py and by the human validation task.
"""

import asyncio
import queue
import time

import answers


def test_assent_recognises_yes_and_only_yes():
    for yes in ("sí", "Si", "vale", "ok", "dale", "de acuerdo", "sí, hazlo"):
        assert answers.assent(yes)
    for no in ("no", "espera", "mejor no", "cámbialo a B", ""):
        assert not answers.assent(no)


import sdk_runner
from stream import CONSOLE, Event


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


# ── the held question (case (a) of the spec) ────────────────────────────

_ASK = {
    "tool_name": "AskUserQuestion",
    "tool_input": {
        "questions": [
            {
                "question": "¿Lo despliego ahora?",
                "header": "Despliegue",
                "options": [
                    {"label": "Sí, ahora", "description": "en producción"},
                    {"label": "Mañana", "description": "cuando esté revisado"},
                ],
                "multiSelect": False,
            }
        ]
    },
}


def test_a_question_is_held_and_the_answer_reaches_the_model():
    run = _run()

    async def scenario():
        task = asyncio.ensure_future(run._pre_tool(_ASK, "t1", None))
        await asyncio.sleep(0.01)
        assert run.pending == "question"
        assert "¿Lo despliego ahora?" in run.pending_text
        assert run.answer("mañana por la mañana") is True
        return await task

    out = asyncio.run(scenario())
    decision = out["hookSpecificOutput"]
    assert decision["permissionDecision"] == "deny"
    assert "mañana por la mañana" in decision["permissionDecisionReason"]
    assert run.pending is None
    assert _drain_kinds(run) == ["question", "resolved"]


def test_a_question_is_not_subject_to_the_gates_timeout():
    """The spec: a gate expires at 300 s, a held question never does."""
    run = _run()
    run.gate_timeout = 0.01

    async def scenario():
        task = asyncio.ensure_future(run._pre_tool(_ASK, "t1", None))
        await asyncio.sleep(0.1)  # ten times the gate's patience
        assert run.pending == "question"
        run.answer("sí, adelante")
        return await task

    out = asyncio.run(scenario())
    assert "sí, adelante" in out["hookSpecificOutput"]["permissionDecisionReason"]


def test_question_text_reads_the_shape_the_probe_measured():
    assert (
        sdk_runner._question_text(_ASK["tool_input"])
        == "¿Lo despliego ahora? (Sí, ahora / Mañana)"
    )


def test_question_text_without_options_is_just_the_question():
    assert (
        sdk_runner._question_text({"questions": [{"question": "¿Sigo?"}]}) == "¿Sigo?"
    )


def test_question_text_falls_back_to_the_raw_arguments():
    text = sdk_runner._question_text({"otra": "forma"})
    assert "otra" in text and len(text) <= 200


# ── I2: an answer belongs to one question only ──────────────────────────


def test_a_second_answer_does_not_authorise_the_next_gate():
    """Said twice to one gate, the extra "sí" must die with it."""
    run = _run()
    run.gate_timeout = 0.05
    push = {"tool_name": "Bash", "tool_input": {"command": "git push"}}
    wipe = {"tool_name": "Bash", "tool_input": {"command": "rm -rf build"}}

    async def scenario():
        first = asyncio.ensure_future(run._pre_tool(push, "t1", None))
        await asyncio.sleep(0.01)
        # Both land while the gate is still up: the loop cannot resolve
        # it until this coroutine yields, so neither is a race.
        assert run.answer("sí") is True
        assert run.answer("sí") is True
        assert await first == {}
        return await run._pre_tool(wipe, "t2", None)

    out = asyncio.run(scenario())
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "no está" in out["hookSpecificOutput"]["permissionDecisionReason"]


def test_an_answer_arriving_after_the_gate_expired_is_refused():
    run = _run()
    run.gate_timeout = 0.05
    out = asyncio.run(
        run._pre_tool(
            {"tool_name": "Bash", "tool_input": {"command": "git push"}}, "t1", None
        )
    )
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert run.answer("sí") is False


# ── C1: an interrupt releases whatever is being asked ───────────────────


class _FakeClient:
    """Enough of a ClaudeSDKClient for `interrupt()` to reach."""

    def __init__(self) -> None:
        self.stopped = False

    async def interrupt(self) -> None:
        self.stopped = True


def test_interrupt_does_not_wait_out_the_gates_timeout():
    """The gate's patience is 300 s; a stop must not cost 300 s."""
    run = _run()  # gate_timeout stays at the spec's 300 s

    async def scenario():
        run._loop = asyncio.get_running_loop()
        run._client = _FakeClient()
        task = asyncio.ensure_future(
            run._pre_tool(
                {"tool_name": "Bash", "tool_input": {"command": "git push"}}, "t1", None
            )
        )
        await asyncio.sleep(0.01)
        assert run.pending == "gate"
        # interrupt() is called from the HTTP thread, never from here.
        await asyncio.to_thread(run.interrupt)
        return await asyncio.wait_for(task, timeout=2)

    out = asyncio.run(scenario())
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert run.pending is None
    assert run.interrupted is True


def test_interrupt_frees_a_held_question_and_ends_the_run():
    """The whole of C1: no waiter left behind, and `events()` returns.

    `_pump` is replaced by a fake drive loop that awaits one held
    question, because the SDK is not installed in this venv. It runs
    under `asyncio.run` exactly as the real one does — which is what
    makes the assertion worth something: `asyncio.run` joins the default
    executor before returning, so a hook thread still blocked on an
    answer would keep `_DONE` off the queue and `events()` alive.
    """
    import threading

    run = _run()
    asked = threading.Event()

    def pump() -> None:
        async def drive() -> None:
            run._loop = asyncio.get_running_loop()
            run._client = _FakeClient()
            asked.set()
            await run._pre_tool(_ASK, "t1", None)
            run._queue.put(Event(CONSOLE, "— parado"))

        try:
            asyncio.run(drive())
        finally:
            run._queue.put(sdk_runner._DONE)

    run._pump = pump
    seen: list[Event] = []
    thread = threading.Thread(target=lambda: seen.extend(run.events()), daemon=True)
    thread.start()

    assert asked.wait(2)
    deadline = time.monotonic() + 2
    while run.pending is None and time.monotonic() < deadline:
        time.sleep(0.005)
    assert run.pending == "question"

    assert run.interrupt() is True
    thread.join(timeout=5)
    assert not thread.is_alive()  # events() terminated, no thread left waiting
    assert run.pending is None
    assert [e.kind for e in seen if e.kind] == ["question", "resolved"]
