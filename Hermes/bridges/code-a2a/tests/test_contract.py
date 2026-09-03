"""The firehose payload shapes, against the fixture both sides read.

The seam this closes: the bridge emits these payloads and the plugin
(`Hermes/plugins/jarvis_code`) renders them, in two processes with no
import across the gap and two test suites that each hand-wrote their own
copy of the keys. A rename here broke only the tests here; the plugin
stayed green against a shape nothing sent any more.

So `fixtures/firehose.json` is the written-down contract, and both
suites read it. This half asserts the bridge still emits exactly those
keys; the plugin's `tests/test_contract.py` asserts it still handles
exactly those payloads. A rename now has to pass through the fixture,
and changing the fixture fails the other side.
"""
import json
import queue
import time
from pathlib import Path

import server
import tasks
import worker
from stream import CONSOLE, VOICE, Event

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "firehose.json"


def contract() -> dict:
    """The payload shapes, minus the note to whoever opens the file."""
    return {k: v for k, v in json.loads(FIXTURE.read_text()).items() if k != "_why"}


class FakeProject:
    name = "demo"
    path = Path("/tmp/demo")


def _one_whole_life(bridge, job, listener) -> list[dict]:
    """Every payload one task emits, from `task` to `end`."""
    seen, deadline = [], time.monotonic() + 5.0
    answered = False
    job.start()
    while time.monotonic() < deadline:
        try:
            payload = listener.get(timeout=0.1)
        except queue.Empty:
            continue
        seen.append(payload)
        if payload.get("event") == "end":
            return seen
        if payload.get("qkind") == "checkpoint" and not answered:
            answered = True
            job.answer("sí")
    raise AssertionError(f"the task never ended; saw {seen}")


def test_every_payload_the_bridge_emits_has_the_shape_the_fixture_pins():
    b = server.Bridge(Path("/tmp"), "claude", "http://t")
    b.events_for = lambda task, prompt, project, fresh=False: iter(  # type: ignore
        [
            Event(CONSOLE, "Editando a.py", kind="edit", detail="a.py"),
            Event(CONSOLE, "", kind="gate", detail="git push"),
            Event(CONSOLE, "", kind="resolved"),
            Event(VOICE, "He arreglado a.py.", final=True),
        ]
    )
    listener = b.subscribe()
    job = worker.Job(b, tasks.Task(), "arregla a", FakeProject())

    seen = _one_whole_life(b, job, listener)

    shapes = contract()
    kinds = {p["event"] for p in seen}
    assert kinds == set(shapes), (
        f"the fixture pins {sorted(shapes)} and the bridge emitted {sorted(kinds)}"
    )
    for payload in seen:
        assert sorted(payload) == sorted(shapes[payload["event"]]), (
            f"{payload['event']} emitted {sorted(payload)}, "
            f"fixture says {sorted(shapes[payload['event']])}"
        )


def test_the_fixture_names_the_values_the_plugin_switches_on():
    """The keys are the contract, but three values are read as values.

    `qkind` picks which of the three prompts is injected, and `failed`
    and `stopped` pick which of the three closing lines the band shows.
    A fixture carrying a `qkind` nothing recognises would let both sides
    agree on a payload neither can act on.
    """
    shapes = contract()
    assert shapes["ask"]["qkind"] in ("question", "gate", "checkpoint")
    assert isinstance(shapes["end"]["failed"], bool)
    assert isinstance(shapes["end"]["stopped"], bool)
