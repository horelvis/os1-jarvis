"""The task's life off the request thread, against a fake run.

Everything here drives Job/Bridge with a stubbed `events_for`, so no SDK,
no subprocess, no HTTP — the same split test_bridge_sdk.py uses. The last
section does use HTTP, because the firehose and the "one task at a time"
refusal only exist as request handling.
"""
import json
import queue
import socket
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

import server
import tasks
import worker
from stream import CONSOLE, VOICE, Event


class FakeProject:
    name = "demo"
    path = Path("/tmp/demo")


def _bridge(events):
    b = server.Bridge(Path("/tmp"), "claude", "http://t")
    b.events_for = lambda task, prompt, project, fresh=False: iter(events)  # type: ignore
    return b


def test_a_job_emits_milestones_and_parks_at_the_checkpoint():
    b = _bridge([
        Event(CONSOLE, "Editando a.py", kind="edit", detail="a.py"),
        Event(VOICE, "He arreglado a.py.", final=True),
    ])
    listener = b.subscribe()
    task = tasks.Task()
    job = worker.Job(b, task, "arregla a", FakeProject())
    job.start()
    seen = _drain_until(listener, "ask")
    assert {"event": "task", **_strip(seen[0])} == seen[0]
    assert any(p["event"] == "milestone" and p["kind"] == "edit" for p in seen)
    ask = seen[-1]
    assert ask["qkind"] == "checkpoint" and "He arreglado" in ask["text"]
    assert task.state == tasks.INPUT_REQUIRED


def test_yes_closes_the_checkpoint():
    b = _bridge([Event(VOICE, "Hecho.", final=True)])
    listener = b.subscribe()
    task = tasks.Task()
    job = worker.Job(b, task, "haz", FakeProject())
    job.start()
    _drain_until(listener, "ask")
    assert job.answer("vale") is True
    end = _drain_until(listener, "end")[-1]
    assert end["failed"] is False
    _wait(lambda: task.state == tasks.COMPLETED)


def test_checkpoint_times_out_and_says_so():
    b = _bridge([Event(VOICE, "Hecho.", final=True)])
    listener = b.subscribe()
    task = tasks.Task()
    job = worker.Job(b, task, "haz", FakeProject())
    job.checkpoint_timeout = 0.05
    job.start()
    _drain_until(listener, "ask")
    end = _drain_until(listener, "end")[-1]
    assert "solo" in end["summary"]  # «cerrado solo» — nobody answered
    _wait(lambda: task.state == tasks.COMPLETED)


def test_anything_but_yes_becomes_the_next_run():
    calls = []

    def fake_events(task, prompt, project, fresh=False):
        calls.append(prompt)
        yield Event(VOICE, f"Hecho: {prompt}.", final=True)

    b = server.Bridge(Path("/tmp"), "claude", "http://t")
    b.events_for = fake_events  # type: ignore
    listener = b.subscribe()
    task = tasks.Task()
    job = worker.Job(b, task, "haz A", FakeProject())
    job.start()
    _drain_until(listener, "ask")
    job.answer("ahora quita los prints")
    _drain_until(listener, "ask")  # the follow-up parks at its own checkpoint
    assert calls == ["haz A", "ahora quita los prints"]
    job.answer("sí")
    _drain_until(listener, "end")


def test_only_one_task_at_a_time():
    b = _bridge([Event(VOICE, "Hecho.", final=True)])
    t1 = tasks.Task(); b.tasks[t1.id] = t1
    t1.advance(tasks.WORKING)
    assert b.active() is t1
    t1.advance(tasks.COMPLETED)
    assert b.active() is None


# ── a failed run is not a completed task ──────────────────────────────


def test_a_run_that_failed_ends_the_task_failed():
    """The engine's ordinary failure does not raise: it yields a closing
    VOICE event with failed=True (sdk_runner._pump). The checkpoint must
    not turn that into a COMPLETED task."""
    b = _bridge([
        Event(VOICE, "No he podido ponerlo a trabajar.", final=True, failed=True),
    ])
    listener = b.subscribe()
    task = tasks.Task()
    job = worker.Job(b, task, "haz", FakeProject())
    job.start()
    _drain_until(listener, "ask")
    job.answer("sí")
    end = _drain_until(listener, "end")[-1]
    assert end["failed"] is True
    _wait(lambda: task.state == tasks.FAILED)


def test_a_failed_run_nobody_closes_still_ends_failed():
    b = _bridge([Event(VOICE, "No he podido.", final=True, failed=True)])
    listener = b.subscribe()
    task = tasks.Task()
    job = worker.Job(b, task, "haz", FakeProject())
    job.checkpoint_timeout = 0.05
    job.start()
    _drain_until(listener, "ask")
    _drain_until(listener, "end")
    _wait(lambda: task.state == tasks.FAILED)


def test_the_checkpoint_can_be_answered_the_instant_it_is_announced():
    """The window between announcing the checkpoint and waiting on it.

    Widened deliberately: `emit` sleeps on the `ask` payload, so the
    answer lands exactly there. A Job that announces before it can
    listen tells the user nobody was waiting for the question it had
    just asked.
    """
    b = _bridge([Event(VOICE, "Hecho.", final=True)])
    listener = b.subscribe()
    task = tasks.Task()
    job = worker.Job(b, task, "haz", FakeProject())
    plain = b.emit

    def slow(payload):
        plain(payload)
        if payload.get("event") == "ask":
            time.sleep(0.2)

    b.emit = slow  # type: ignore
    job.start()
    _drain_until(listener, "ask")
    assert job.answer("vale") is True
    _drain_until(listener, "end")
    _wait(lambda: task.state == tasks.COMPLETED)


# ── the question the run itself holds ─────────────────────────────────


def test_an_answer_goes_to_the_held_question_first():
    """While the run is asking, an answer is the run's — not the
    checkpoint's. The checkpoint does not exist yet, but a Job that
    looked at it first would swallow the answer either way."""

    class HeldRun:
        pending = "question"
        pending_text = "¿de los dos, cuál?"

        def __init__(self):
            self.answered = ""

        def answer(self, text):
            self.answered = text
            return True

    b = _bridge([Event(VOICE, "Hecho.", final=True)])
    task = tasks.Task()
    run = HeldRun()
    b.runs[task.id] = run  # type: ignore
    job = worker.Job(b, task, "haz", FakeProject())
    assert job.answer("el primero") is True
    assert run.answered == "el primero"


def test_an_answer_nobody_waits_for_is_refused():
    b = _bridge([Event(VOICE, "Hecho.", final=True)])
    job = worker.Job(b, tasks.Task(), "haz", FakeProject())
    assert job.answer("sí") is False


def test_a_cancelled_job_does_not_report_success():
    b = _bridge([Event(VOICE, "Hecho.", final=True)])
    listener = b.subscribe()
    task = tasks.Task()
    job = worker.Job(b, task, "haz", FakeProject())
    job.start()
    _drain_until(listener, "ask")
    task.advance(tasks.CANCELED, "Lo dejo.")
    job.cancel()
    end = _drain_until(listener, "end")[-1]
    assert end["summary"] == "Lo dejo."
    assert task.state == tasks.CANCELED


def test_a_job_that_blows_up_ends_rather_than_dying():
    def boom(task, prompt, project, fresh=False):
        raise RuntimeError("nada")
        yield  # pragma: no cover - a generator, not a function

    b = server.Bridge(Path("/tmp"), "claude", "http://t")
    b.events_for = boom  # type: ignore
    listener = b.subscribe()
    task = tasks.Task()
    worker.Job(b, task, "haz", FakeProject()).start()
    end = _drain_until(listener, "end")[-1]
    assert end["failed"] is True
    _wait(lambda: task.state == tasks.FAILED)
    assert task.id not in b.jobs


# ── over HTTP: the firehose and the single slot ───────────────────────


def _serving(tmp_path, events, monkeypatch):
    """A real bridge on a real socket, with a fake engine behind it."""
    (tmp_path / "demo").mkdir(exist_ok=True)
    monkeypatch.setattr("sdk_runner.available", lambda: True)
    bridge = server.Bridge(tmp_path, "claude", "http://x")
    bridge.events_for = lambda task, prompt, project, fresh=False: iter(events)  # type: ignore
    handler = type("BoundHandler", (server.Handler,), {"bridge": bridge})
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, bridge


def _post(httpd, method, params):
    import http.client

    host, port = httpd.server_address[0], httpd.server_address[1]
    conn = http.client.HTTPConnection(host, port, timeout=5)
    conn.request(
        "POST",
        "/",
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}),
        {"Content-Type": "application/json"},
    )
    body = json.loads(conn.getresponse().read())
    conn.close()
    return body


def _message(text, **extra):
    return {"message": {"parts": [{"kind": "text", "text": text}], **extra}}


def test_the_firehose_streams_and_keeps_alive(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "KEEPALIVE", 0.05)
    httpd, _bridge = _serving(
        tmp_path, [Event(VOICE, "Hecho.", final=True)], monkeypatch
    )
    sock = socket.create_connection(httpd.server_address, timeout=5)
    sock.sendall(b"GET /events HTTP/1.1\r\nHost: x\r\n\r\n")
    _read_until(sock, b"\r\n\r\n")  # the headers
    assert b": keepalive" in _read_until(sock, b": keepalive")

    _post(httpd, "message/send", _message("arregla demo"))
    payloads = _sse_until(sock, "ask")
    assert payloads[0]["event"] == "task" and payloads[0]["project"] == "demo"
    assert payloads[-1]["qkind"] == "checkpoint"
    sock.close()
    httpd.shutdown()


def test_send_returns_at_once_and_the_answer_closes_it(tmp_path, monkeypatch):
    httpd, bridge = _serving(
        tmp_path, [Event(VOICE, "Hecho.", final=True)], monkeypatch
    )
    listener = bridge.subscribe()
    result = _post(httpd, "message/send", _message("arregla demo"))["result"]
    assert result["status"]["state"] == tasks.WORKING
    _drain_until(listener, "ask")

    answered = _post(
        httpd, "message/send", _message("sí", taskId=result["id"])
    )["result"]
    assert answered["id"] == result["id"]
    _drain_until(listener, "end")
    _wait(lambda: bridge.tasks[result["id"]].state == tasks.COMPLETED)
    httpd.shutdown()


def test_a_second_task_while_one_runs_is_refused(tmp_path, monkeypatch):
    httpd, bridge = _serving(
        tmp_path, [Event(VOICE, "Hecho.", final=True)], monkeypatch
    )
    listener = bridge.subscribe()
    _post(httpd, "message/send", _message("arregla demo"))
    _drain_until(listener, "ask")
    second = _post(httpd, "message/send", _message("otra cosa en demo"))["result"]
    assert "Ya hay una tarea en marcha" in _said(second)
    httpd.shutdown()


def test_an_answer_that_nobody_awaits_says_so(tmp_path, monkeypatch):
    """A job between two waits — the question resolved, the checkpoint
    not up yet. The «sí» is refused out loud rather than swallowed."""
    httpd, bridge = _serving(
        tmp_path, [Event(VOICE, "Hecho.", final=True)], monkeypatch
    )
    task = tasks.Task()
    task.advance(tasks.WORKING, "En ello.")
    bridge.tasks[task.id] = task
    bridge.jobs[task.id] = worker.Job(bridge, task, "haz", FakeProject())  # not started
    late = _post(httpd, "message/send", _message("sí", taskId=task.id))["result"]
    assert _said(late) == "Nadie esperaba una respuesta."
    assert late["id"] == task.id
    httpd.shutdown()


def test_an_answer_reaches_the_task_by_its_context(tmp_path, monkeypatch):
    """An A2A client that knows the conversation and not the task id."""
    httpd, bridge = _serving(
        tmp_path, [Event(VOICE, "Hecho.", final=True)], monkeypatch
    )
    listener = bridge.subscribe()
    result = _post(
        httpd, "message/send", _message("arregla demo", contextId="charla")
    )["result"]
    _drain_until(listener, "ask")
    _post(httpd, "message/send", _message("sí", contextId="charla"))
    _drain_until(listener, "end")
    _wait(lambda: bridge.tasks[result["id"]].state == tasks.COMPLETED)
    httpd.shutdown()


def test_the_cli_path_still_answers_synchronously(tmp_path, monkeypatch):
    """OpenCode cannot be asked anything, so v1's blocking send stays."""
    monkeypatch.setattr("sdk_runner.available", lambda: False)
    (tmp_path / "demo").mkdir(exist_ok=True)
    bridge = server.Bridge(tmp_path, "claude", "http://x")
    bridge.events_for = lambda task, prompt, project, fresh=False: iter(  # type: ignore
        [Event(CONSOLE, "linea"), Event(VOICE, "Hecho.", final=True)]
    )
    handler = type("BoundHandler", (server.Handler,), {"bridge": bridge})
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    result = _post(httpd, "message/send", _message("arregla demo"))["result"]
    assert result["status"]["state"] == tasks.COMPLETED
    assert _said(result) == "Hecho."
    httpd.shutdown()


# ── helpers ───────────────────────────────────────────────────────────


def _said(task_dict):
    return task_dict["status"]["message"]["parts"][0]["text"]


def _read_until(sock, marker, timeout=3.0):
    buffer, deadline = b"", time.monotonic() + timeout
    while time.monotonic() < deadline:
        if marker in buffer:
            return buffer
        buffer += sock.recv(4096)
    raise AssertionError(f"never saw {marker!r}; saw {buffer!r}")


def _sse_until(sock, event, timeout=3.0):
    buffer, out, deadline = b"", [], time.monotonic() + timeout
    while time.monotonic() < deadline:
        for line in buffer.split(b"\n"):
            if line.startswith(b"data: "):
                payload = json.loads(line[6:])
                if payload not in out:
                    out.append(payload)
        if out and out[-1].get("event") == event:
            return out
        buffer += sock.recv(4096)
    raise AssertionError(f"never saw {event!r}; saw {out}")


def _drain_until(listener, event, timeout=2.0):
    seen, deadline = [], time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            payload = listener.get(timeout=0.1)
        except queue.Empty:
            continue
        seen.append(payload)
        if payload.get("event") == event:
            return seen
    raise AssertionError(f"never saw {event!r}; saw {seen}")


def _strip(p):
    return {k: v for k, v in p.items() if k in ("event", "taskId", "project")}


def _wait(cond, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return
        time.sleep(0.02)
    raise AssertionError("condition never held")


# ── What a run's own closing line does to the firehose ────────────────


def test_the_runs_closing_console_line_goes_out_as_it_is_written():
    """`sdk_runner._closing` puts «— terminado» on the queue itself.

    Every other test in this file drives a synthetic event list that
    omits it, which is how the duplicate on the band survived a review:
    the plugin writes the same line again at `end`, and when the
    checkpoint times out the two are adjacent. Pinned here so the
    plugin's own test has something real to be a copy of.
    """
    b = _bridge([
        Event(CONSOLE, "Editando a.py", kind="edit", detail="a.py"),
        Event(CONSOLE, "— terminado"),
        Event(VOICE, "He arreglado a.py.", final=True),
    ])
    listener = b.subscribe()
    job = worker.Job(b, tasks.Task(), "arregla a", FakeProject())
    job.start()
    seen = _drain_until(listener, "ask")

    closing = [p for p in seen if p.get("text") == "— terminado"]
    assert closing, f"the closing line never reached the firehose: {seen}"
    assert closing[0]["event"] == "milestone"
    assert closing[0]["kind"] == ""


def test_a_stopped_run_says_stopped_rather_than_finished():
    b = _bridge([Event(VOICE, "Hecho.", final=True)])
    listener = b.subscribe()
    task = tasks.Task()
    job = worker.Job(b, task, "haz", FakeProject())
    job.start()
    _drain_until(listener, "ask")
    task.advance(tasks.CANCELED, "Lo dejo.")
    job.cancel()
    end = _drain_until(listener, "end")[-1]

    assert end["stopped"] is True
    assert end["failed"] is False


def test_an_ordinary_ending_is_not_a_stop():
    b = _bridge([Event(VOICE, "Hecho.", final=True)])
    listener = b.subscribe()
    job = worker.Job(b, tasks.Task(), "haz", FakeProject())
    job.checkpoint_timeout = 0.05
    job.start()
    _drain_until(listener, "ask")
    end = _drain_until(listener, "end")[-1]

    assert end["stopped"] is False
