"""The bridge mode wired: firehose in; console, voice and divert out.

Every test here drives `_run_bridge_mode` with a finite iterator, so the
loop ends on its own and nothing in this file can hang the suite. The one
thread it does start (the answer POST) is waited on with a bounded
`Event.wait`.
"""

import threading

import pytest

import Hermes.plugins.samantha_code as mod


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

    monkeypatch.setattr(mod, "_push", fake_push)
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
    return w


def _run(monkeypatch, wiring, events):
    """Drive one finite firehose through the dispatch loop."""
    monkeypatch.setattr(mod.client, "follow_events", lambda url, stop: iter(events))
    mod._run_bridge_mode(wiring.ctx, "http://bridge", threading.Event())


def _lines(wiring):
    return [text for text, flags in wiring.pushed if text]


def test_a_new_task_clears_the_console(monkeypatch, wiring):
    _run(monkeypatch, wiring, [{"event": "task", "taskId": "t1"}])
    assert wiring.pushed == [("", {"done": False, "reset": True})]


def test_milestones_reach_the_band_deduped(monkeypatch, wiring):
    _run(
        monkeypatch,
        wiring,
        [
            {"event": "milestone", "kind": "read", "taskId": "t1"},
            {"event": "milestone", "kind": "read", "taskId": "t1"},
            {"event": "milestone", "kind": "edit", "detail": "a.py", "taskId": "t1"},
        ],
    )
    assert _lines(wiring) == ["Leyendo el proyecto…\n", "Editando a.py\n"]


def test_a_new_task_forgets_what_the_last_one_said(monkeypatch, wiring):
    # The dedup must not swallow the first line of a run because the
    # previous run happened to end on the same one.
    _run(
        monkeypatch,
        wiring,
        [
            {"event": "milestone", "kind": "read", "taskId": "t1"},
            {"event": "task", "taskId": "t2"},
            {"event": "milestone", "kind": "read", "taskId": "t2"},
        ],
    )
    assert _lines(wiring) == ["Leyendo el proyecto…\n", "Leyendo el proyecto…\n"]


def test_a_question_shows_on_the_band_arms_the_divert_and_asks_out_loud(
    monkeypatch, wiring
):
    _run(
        monkeypatch,
        wiring,
        [{"event": "ask", "qkind": "question", "text": "¿A o B?", "taskId": "t1"}],
    )
    assert _lines(wiring) == ["? ¿A o B?\n"]
    assert wiring.adapter.divert_chat is not None
    assert len(wiring.ctx.injected) == 1
    assert "«¿A o B?»" in wiring.ctx.injected[0]


def test_a_checkpoint_is_spoken_and_stays_off_the_band(monkeypatch, wiring):
    _run(
        monkeypatch,
        wiring,
        [
            {
                "event": "ask",
                "qkind": "checkpoint",
                "text": "1 test pasa",
                "taskId": "t1",
            }
        ],
    )
    assert _lines(wiring) == []
    assert wiring.adapter.divert_chat is not None
    assert "«1 test pasa»" in wiring.ctx.injected[0]


def test_the_answer_goes_to_the_bridge_and_disarms_the_divert(monkeypatch, wiring):
    # NOTE: the dispatch loop logs and swallows anything raised out of
    # the iterator, so an `assert` in a generator body cannot fail a
    # test. Every one of these records instead, and asserts outside.
    took = []

    def events():
        yield {"event": "ask", "qkind": "gate", "text": "borrar x", "taskId": "t7"}
        # The user speaks: the adapter calls the hook that was just armed.
        took.append(wiring.adapter.divert_chat("sí, adelante"))

    monkeypatch.setattr(mod.client, "follow_events", lambda url, stop: events())
    mod._run_bridge_mode(wiring.ctx, "http://bridge", threading.Event())

    assert took == [True]
    assert wiring.landed.wait(5) is True
    assert wiring.answers == [("http://bridge", "t7", "sí, adelante")]
    assert wiring.adapter.divert_chat is None
    # The user's own words are echoed onto the band, so the console shows
    # both halves of the exchange.
    assert "→ sí, adelante\n" in _lines(wiring)


def test_a_second_utterance_in_flight_is_not_a_second_answer(monkeypatch, wiring):
    took = []

    def events():
        yield {"event": "ask", "qkind": "gate", "text": "borrar x", "taskId": "t7"}
        hook = wiring.adapter.divert_chat
        took.append(hook("sí"))
        # Pending was cleared before the POST left, deliberately: whatever
        # is said next is a turn, not a second answer.
        took.append(hook("y otra cosa"))

    monkeypatch.setattr(mod.client, "follow_events", lambda url, stop: events())
    mod._run_bridge_mode(wiring.ctx, "http://bridge", threading.Event())

    assert took == [True, False]
    assert wiring.landed.wait(5) is True
    assert [text for _url, _tid, text in wiring.answers] == ["sí"]


def test_resolved_and_end_put_the_divert_away(monkeypatch, wiring):
    armed = []

    def events():
        yield {"event": "ask", "qkind": "question", "text": "¿A?", "taskId": "t1"}
        armed.append(wiring.adapter.divert_chat is not None)
        yield {"event": "resolved", "taskId": "t1"}
        armed.append(wiring.adapter.divert_chat is not None)
        yield {"event": "ask", "qkind": "question", "text": "¿B?", "taskId": "t1"}
        armed.append(wiring.adapter.divert_chat is not None)
        yield {"event": "end", "taskId": "t1", "failed": False}

    monkeypatch.setattr(mod.client, "follow_events", lambda url, stop: events())
    mod._run_bridge_mode(wiring.ctx, "http://bridge", threading.Event())

    assert armed == [True, False, True]
    assert wiring.adapter.divert_chat is None
    assert wiring.pushed[-1] == ("", {"done": True, "reset": False})


def test_nothing_waiting_means_the_words_are_a_turn(monkeypatch, wiring):
    took = []

    def events():
        yield {"event": "ask", "qkind": "question", "text": "¿A?", "taskId": "t1"}
        hook = wiring.adapter.divert_chat
        yield {"event": "resolved", "taskId": "t1"}
        # The assistant answered its own question; a stale hook must not
        # swallow the next thing the user says.
        took.append(hook("hola"))

    monkeypatch.setattr(mod.client, "follow_events", lambda url, stop: events())
    mod._run_bridge_mode(wiring.ctx, "http://bridge", threading.Event())

    assert took == [False]
    assert wiring.answers == []


def test_one_bad_event_does_not_end_the_run(monkeypatch, wiring):
    def boom(event):
        if event.get("kind") == "edit":
            raise RuntimeError("x")
        return "Leyendo el proyecto…"

    monkeypatch.setattr(mod.hitos, "render", boom)
    _run(
        monkeypatch,
        wiring,
        [
            {"event": "milestone", "kind": "edit", "taskId": "t1"},
            {"event": "milestone", "kind": "read", "taskId": "t1"},
        ],
    )
    assert _lines(wiring) == ["Leyendo el proyecto…\n"]


def test_no_strip_connected_is_not_a_crash(monkeypatch, wiring):
    monkeypatch.setattr(mod, "_adapter", lambda: None)
    _run(
        monkeypatch,
        wiring,
        [{"event": "ask", "qkind": "question", "text": "¿A?", "taskId": "t1"}],
    )
    assert wiring.ctx.injected  # he still asks out loud


def test_the_bridge_setting_can_be_emptied_to_keep_the_legacy_follower():
    class _Ctx:
        def get_config(self, name):
            return "" if name == "bridge" else None

    assert mod._setting(_Ctx(), "bridge", mod.client.DEFAULT_BRIDGE) == ""


def test_a_ctx_with_no_config_at_all_falls_back_to_the_default():
    class _Ctx:
        def get_config(self, name):
            raise RuntimeError("no config in this gateway")

    assert (
        mod._setting(_Ctx(), "bridge", mod.client.DEFAULT_BRIDGE)
        == mod.client.DEFAULT_BRIDGE
    )


def test_the_end_is_written_on_the_band_before_the_console_closes(monkeypatch, wiring):
    # v1 ends with this line (`live.summarise`), and the checkpoint is
    # kept off the band on the stated grounds that the end line carries
    # it — but `hitos.render` returns None for `end`, so bridge mode has
    # to write it here or the console simply stops.
    _run(monkeypatch, wiring, [{"event": "end", "taskId": "t1", "failed": False}])
    assert wiring.pushed == [
        ("— terminado\n", {"done": False, "reset": False}),
        ("", {"done": True, "reset": False}),
    ]


def test_a_run_that_failed_says_so(monkeypatch, wiring):
    _run(monkeypatch, wiring, [{"event": "end", "taskId": "t1", "failed": True}])
    assert _lines(wiring) == ["— terminado con errores\n"]
