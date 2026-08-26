"""Reading the bridge's stream, against the shapes it actually sends."""

from Hermes.plugins.samantha_code.sse import lines_of, state_of


def _update(text, destination=None, state="TASK_STATE_WORKING"):
    update = {
        "state": state,
        "message": {"parts": [{"kind": "text", "text": text}]},
    }
    if destination:
        update["metadata"] = {"destination": destination}
    return {"result": {"statusUpdate": update}}


def test_a_console_line_is_read_with_its_destination():
    assert lines_of(_update("· Bash: pytest -q", "console")) == (
        "console",
        "· Bash: pytest -q",
    )


def test_a_spoken_line_is_marked_voice():
    assert lines_of(_update("¿Borro los tests viejos?", "voice"))[0] == "voice"


def test_a_line_with_no_destination_goes_to_the_console():
    # The safe default: showing something that should have been said is
    # a smaller failure than saying something that should have been shown.
    assert lines_of(_update("algo"))[0] == "console"


def test_the_opening_task_carries_no_text():
    assert lines_of({"result": {"task": {"id": "1", "status": {}}}}) == ("", "")


def test_the_state_is_read_from_an_update():
    assert state_of(_update("x", state="TASK_STATE_FAILED")) == "TASK_STATE_FAILED"


def test_the_state_is_read_from_the_opening_task_too():
    event = {"result": {"task": {"status": {"state": "TASK_STATE_SUBMITTED"}}}}
    assert state_of(event) == "TASK_STATE_SUBMITTED"


def test_junk_is_not_an_error():
    assert lines_of({}) == ("", "")
    assert state_of({}) == ""
