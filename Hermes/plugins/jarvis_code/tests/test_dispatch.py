"""The bridge mode wired: firehose in; console, voice and divert out.

Every test here drives `_run_bridge_mode` with a finite iterator, so the
loop ends on its own and nothing in this file can hang the suite. The one
thread it does start (the answer POST) is waited on with a bounded
`Event.wait`.
"""

import threading

import Hermes.plugins.jarvis_code as mod


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
    # `armed` is read INSIDE the firehose: the loop disarms on its way
    # out, so after it there is deliberately nothing left armed.
    armed = []

    def events():
        yield {"event": "ask", "qkind": "question", "text": "¿A o B?", "taskId": "t1"}
        armed.append(wiring.adapter.divert_chat is not None)

    monkeypatch.setattr(mod.client, "follow_events", lambda url, stop: events())
    mod._run_bridge_mode(wiring.ctx, "http://bridge", threading.Event())

    assert _lines(wiring) == ["? ¿A o B?\n"]
    assert armed == [True]
    assert len(wiring.ctx.injected) == 1
    assert "«¿A o B?»" in wiring.ctx.injected[0]


def test_a_checkpoint_is_spoken_and_stays_off_the_band(monkeypatch, wiring):
    armed = []

    def events():
        yield {
            "event": "ask",
            "qkind": "checkpoint",
            "text": "1 test pasa",
            "taskId": "t1",
        }
        armed.append(wiring.adapter.divert_chat is not None)

    monkeypatch.setattr(mod.client, "follow_events", lambda url, stop: events())
    mod._run_bridge_mode(wiring.ctx, "http://bridge", threading.Event())

    assert _lines(wiring) == []
    assert armed == [True]
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


def test_a_new_task_forgets_a_question_the_old_one_left_open(monkeypatch, wiring):
    # The bridge restarted mid-question: `follow_events` reconnects and a
    # `task` arrives with the hook still armed against a dead taskId.
    # Without this, exactly one utterance is echoed to the band, POSTed
    # into «Nadie esperaba una respuesta.», and never becomes a turn.
    took = []

    def events():
        yield {"event": "ask", "qkind": "gate", "text": "borrar x", "taskId": "t1"}
        yield {"event": "task", "taskId": "t2"}
        took.append(wiring.adapter.divert_chat)

    monkeypatch.setattr(mod.client, "follow_events", lambda url, stop: events())
    mod._run_bridge_mode(wiring.ctx, "http://bridge", threading.Event())

    assert took == [None]
    assert wiring.answers == []


def test_a_swallowed_event_keeps_its_traceback(monkeypatch, wiring, capture_logs):
    # One warning line with no stack, in the loop that runs for the
    # gateway's whole life, is how a renamed key stays invisible.
    def boom(event):
        raise TypeError("render() got an unexpected keyword")

    monkeypatch.setattr(mod.hitos, "render", boom)
    _run(monkeypatch, wiring, [{"event": "milestone", "kind": "read", "taskId": "t1"}])

    logged = capture_logs.getvalue()
    assert "evento descartado" in logged
    assert "Traceback (most recent call last)" in logged
    assert "TypeError" in logged


# ── The strip's wake window, held while somebody waits. ──────────────


def test_a_question_tells_the_strip_to_keep_listening(monkeypatch, wiring):
    # Without this the answer is dropped by the strip: JARVIS spoke the
    # question, which opens a 30-second no-name window, and a gate waits
    # 300 s. Past 30 s there is no spoken sentence that can answer at
    # all — saying his name sets `wake`, which is never diverted.
    #
    # Recorded INSIDE the firehose, not after it: the loop shuts the
    # window on its way out (see `test_the_loop_ending_disarms...`), so
    # the last value is always False and the only place the open one
    # exists is while the question stands.
    held = []

    def events():
        yield {"event": "ask", "qkind": "gate", "text": "git push", "taskId": "t1"}
        held.append(wiring.asked[-1])

    monkeypatch.setattr(mod.client, "follow_events", lambda url, stop: events())
    mod._run_bridge_mode(wiring.ctx, "http://bridge", threading.Event())

    assert held == [True]


def test_the_window_shuts_again_when_the_question_resolves(monkeypatch, wiring):
    _run(
        monkeypatch,
        wiring,
        [
            {"event": "ask", "qkind": "gate", "text": "git push", "taskId": "t1"},
            {"event": "resolved", "taskId": "t1"},
        ],
    )
    assert wiring.asked[-1] is False


def test_the_window_shuts_when_the_run_ends(monkeypatch, wiring):
    _run(
        monkeypatch,
        wiring,
        [
            {"event": "ask", "qkind": "checkpoint", "text": "listo", "taskId": "t1"},
            {"event": "end", "taskId": "t1", "failed": False},
        ],
    )
    assert wiring.asked[-1] is False


def test_answering_shuts_the_window_with_the_divert(monkeypatch, wiring):
    # The two must never disagree: a window held open with nothing to
    # divert to is him answering the room.
    def events():
        yield {"event": "ask", "qkind": "gate", "text": "git push", "taskId": "t7"}
        wiring.adapter.divert_chat("sí")

    monkeypatch.setattr(mod.client, "follow_events", lambda url, stop: events())
    mod._run_bridge_mode(wiring.ctx, "http://bridge", threading.Event())

    assert wiring.landed.wait(5) is True
    assert wiring.asked[-1] is False
    assert wiring.adapter.divert_chat is None


# ── Losing the stream. The task runs on; our sight of it does not. ───


def test_losing_the_stream_says_so_on_the_band_and_disarms_the_divert(
    monkeypatch, wiring
):
    # The spec's requirement, which existed only in the spec: "stream
    # drops → the plugin retries with backoff and the band says «he
    # perdido de vista el trabajo» while the task runs on". And the half
    # it does not mention: a divert armed before the break clears only on
    # the next `task` event, which may never come — a bridge stopped and
    # not restarted left it armed indefinitely, waiting to eat exactly
    # one sentence.
    took = []

    def events():
        yield {"event": "task", "taskId": "t1"}
        yield {"event": "ask", "qkind": "gate", "text": "git push", "taskId": "t1"}
        yield {"event": "lost"}
        took.append(wiring.adapter.divert_chat)

    monkeypatch.setattr(mod.client, "follow_events", lambda url, stop: events())
    mod._run_bridge_mode(wiring.ctx, "http://bridge", threading.Event())

    assert took == [None]
    assert wiring.asked[-1] is False
    assert "— he perdido de vista el trabajo\n" in _lines(wiring)
    assert wiring.answers == []


def test_losing_a_stream_with_no_run_on_it_says_nothing(monkeypatch, wiring):
    # Bridge mode is the default, so a box with no bridge on it
    # reconnects forever. A console opening by itself every 30 seconds to
    # report that it lost sight of nothing is the noise this branch
    # exists to remove.
    _run(monkeypatch, wiring, [{"event": "lost"}])
    assert _lines(wiring) == []


def test_a_flapping_stream_does_not_repeat_the_line(monkeypatch, wiring):
    # The branch's own hard rule: never the same line twice in a row.
    _run(
        monkeypatch,
        wiring,
        [
            {"event": "task", "taskId": "t1"},
            {"event": "lost"},
            {"event": "lost"},
        ],
    )
    assert _lines(wiring) == ["— he perdido de vista el trabajo\n"]


def test_the_run_ending_stops_it_being_worth_a_line(monkeypatch, wiring):
    _run(
        monkeypatch,
        wiring,
        [
            {"event": "task", "taskId": "t1"},
            {"event": "end", "taskId": "t1", "failed": False},
            {"event": "lost"},
        ],
    )
    assert "— he perdido de vista el trabajo\n" not in _lines(wiring)


# ── The closing line, written once. ──────────────────────────────────


def test_the_end_line_is_not_written_twice(monkeypatch, wiring):
    # `sdk_runner._closing` puts «— terminado» on the run's queue as a
    # CONSOLE event with `kind=""`; `worker._one_run` has no case for it
    # and forwards it as a milestone, whose `text` this renders. Then
    # `end` writes the same line again. With a checkpoint that timed out
    # the two are adjacent — the hard rule this branch exists to enforce,
    # broken by the branch.
    _run(
        monkeypatch,
        wiring,
        [
            {"event": "milestone", "kind": "", "detail": "", "text": "— terminado"},
            {"event": "ask", "qkind": "checkpoint", "text": "listo", "taskId": "t1"},
            {"event": "end", "taskId": "t1", "failed": False, "stopped": False},
        ],
    )
    assert _lines(wiring) == ["— terminado\n"]
    assert wiring.pushed[-1] == ("", {"done": True, "reset": False})


def test_a_run_that_was_stopped_does_not_claim_it_finished(monkeypatch, wiring):
    _run(
        monkeypatch,
        wiring,
        [
            {"event": "milestone", "kind": "", "detail": "", "text": "— parado"},
            {"event": "end", "taskId": "t1", "failed": False, "stopped": True},
        ],
    )
    assert _lines(wiring) == ["— parado\n"]


# ── The loop's own way out. ──────────────────────────────────────────


def test_the_loop_ending_disarms_the_divert_and_shuts_the_window(
    monkeypatch, wiring
):
    # The one route out that did not go through `_set_divert`: the loop
    # stops with a question outstanding — `stop` set on unload, or the
    # outer `except`. The strip recovers on its own at the wake hold's
    # 900 s cap; the ADAPTER never does. `divert_chat` would stay armed
    # against a dispatcher that has stopped, waiting to eat the next
    # unnamed sentence inside an answered window.
    _run(
        monkeypatch,
        wiring,
        [{"event": "ask", "qkind": "gate", "text": "git push", "taskId": "t1"}],
    )
    assert wiring.adapter.divert_chat is None
    assert wiring.asked[-1] is False


def test_a_follower_that_blows_up_still_disarms_the_divert(monkeypatch, wiring):
    # The same guarantee down the failing path, which is the one that
    # leaves a stale hook without anybody noticing.
    def events():
        yield {"event": "ask", "qkind": "question", "text": "¿A o B?", "taskId": "t1"}
        raise RuntimeError("el puente se ha ido")

    monkeypatch.setattr(mod.client, "follow_events", lambda url, stop: events())
    mod._run_bridge_mode(wiring.ctx, "http://bridge", threading.Event())

    assert wiring.adapter.divert_chat is None
    assert wiring.asked[-1] is False


# ── The bounded chain, said out loud. ────────────────────────────────


def test_a_bounded_follow_up_is_spoken_and_leaves_nothing_waiting(
    monkeypatch, wiring
):
    # A run born from a checkpoint answer closes instead of parking at a
    # checkpoint of its own (`worker.py`, D4). There is no question to
    # relay — so without this the user asks for work out loud and never
    # hears that it was done.
    _run(
        monkeypatch,
        wiring,
        [
            {
                "event": "end",
                "taskId": "t1",
                "failed": False,
                "stopped": False,
                "chained": True,
                "summary": "Quitados los prints.",
            }
        ],
    )
    assert len(wiring.ctx.injected) == 1
    assert "«Quitados los prints.»" in wiring.ctx.injected[0]
    # A statement, not a question: nothing is waiting for an answer, so
    # nothing may be armed and the strip's window stays shut.
    assert wiring.adapter.divert_chat is None
    assert True not in wiring.asked


def test_an_ordinary_ending_is_not_spoken(monkeypatch, wiring):
    # The closing line on the band is the whole of what an ordinary end
    # says. The checkpoint already had the voice.
    _run(
        monkeypatch,
        wiring,
        [
            {
                "event": "end",
                "taskId": "t1",
                "failed": False,
                "stopped": False,
                "chained": False,
                "summary": "Hecho.",
            }
        ],
    )
    assert wiring.ctx.injected == []
