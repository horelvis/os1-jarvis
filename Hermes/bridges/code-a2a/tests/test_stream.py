"""What the assistant emits, against a recording of it actually emitting.

`fixtures/stream.jsonl` is 38 real events from `claude -p
--output-format stream-json` fixing a deliberately broken test on
2026-08-26. Testing the classifier against a hand-written idea of the
format would only pin what was imagined; this pins what arrived.
"""

from pathlib import Path

from stream import CONSOLE, VOICE, Event, classify, parse

FIXTURE = Path(__file__).parent / "fixtures" / "stream.jsonl"


def _events():
    out = []
    for line in FIXTURE.read_text(encoding="utf-8").splitlines():
        event = parse(line)
        if event is not None:
            out.extend(classify(event))
    return out


def test_the_recording_still_parses():
    assert len(FIXTURE.read_text(encoding="utf-8").splitlines()) == 38


def test_a_line_that_is_not_json_is_not_an_error():
    # The process writes warnings to stdout; a reader that raises on one
    # is a reader that dies in the first minute.
    assert parse("Warning: no stdin data received in 3s") is None
    assert parse("") is None
    assert parse("[1, 2]") is None


def test_almost_everything_goes_to_the_console():
    events = _events()
    assert sum(1 for e in events if e.destination == CONSOLE) > 15


def test_the_voice_hears_only_a_handful():
    # Three refusals and one result, out of 38 events.
    spoken = [e for e in _events() if e.destination == VOICE]
    assert len(spoken) == 4, [e.text[:40] for e in spoken]


def test_a_refusal_reaches_the_voice_because_the_work_has_stopped():
    spoken = [e for e in _events() if e.destination == VOICE]
    assert any(
        "permis" in e.text.lower() or "approval" in e.text.lower() for e in spoken
    )


def test_the_last_spoken_thing_is_the_result_and_it_is_final():
    spoken = [e for e in _events() if e.destination == VOICE]
    assert spoken[-1].final is True
    assert "bloqueada por permisos" in spoken[-1].text


def test_tool_calls_are_shown_but_never_said():
    events = _events()
    tools = [e for e in events if e.text.startswith("· ")]
    assert tools, "the recording has tool calls in it"
    assert all(e.destination == CONSOLE for e in tools)


def test_a_tool_line_says_what_it_is_doing():
    line = classify(
        {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "name": "Bash",
                        "input": {"command": "pytest -q", "description": "run"},
                    }
                ]
            },
        }
    )
    assert line == [Event(CONSOLE, "· Bash: pytest -q")]


def test_thinking_and_rate_limits_are_dropped():
    assert classify({"type": "system", "subtype": "thinking_tokens"}) == []
    assert classify({"type": "rate_limit_event"}) == []
    assert classify({"type": "system", "subtype": "init"}) == []


def test_a_failed_run_is_marked_failed():
    out = classify({"type": "result", "subtype": "error", "result": "se rompió"})
    spoken = [e for e in out if e.destination == VOICE][0]
    assert spoken.final and spoken.failed


def test_a_result_with_no_text_still_says_something():
    out = classify({"type": "result", "subtype": "success", "result": ""})
    spoken = [e for e in out if e.destination == VOICE][0]
    assert spoken.text.strip()


def test_the_final_summary_is_not_written_to_the_console_twice():
    """Claude Code's `result` repeats the assistant's last message.

    Writing both put the whole summary on the strip twice — seen in a
    screenshot 2026-08-26. The console gets a closing line; the words go
    to the voice, which is where they were always going.
    """
    events = _events()
    console = [e.text for e in events if e.destination == CONSOLE]
    spoken = [e.text for e in events if e.destination == VOICE]

    assert console[-1].startswith("— terminado")
    # The assistant's own message stays — it is what the work produced.
    # What must not happen is seeing it TWICE, which is what the result
    # echoing it used to cause. Compared on a slice: the console cuts
    # long lines and the voice does not.
    final = spoken[-1]
    echoes = [line for line in console if final[:40] in line]
    assert len(echoes) == 1, echoes


def test_a_failed_run_says_so_on_the_console_too():
    out = classify({"type": "result", "subtype": "error", "result": "se rompió"})
    console = [e.text for e in out if e.destination == CONSOLE]
    assert console == ["— terminado con errores"]
