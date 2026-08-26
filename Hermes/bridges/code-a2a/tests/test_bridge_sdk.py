"""Stopping a run, and continuing a conversation.

The engine itself needs the assistant installed, so what is tested here
is the part that decides: which session is handed to a run, what happens
to it afterwards, and whether `tasks/cancel` reaches anything. A fake
run stands in for the SDK — it records what it was given and reports
being stopped.
"""

import tasks
from stream import CONSOLE, Event
from server import Bridge, _ending, _fresh
from sessions import Sessions

NOW = 1_000_000.0


class FakeRun:
    """A run that never runs. Records what it was handed."""

    def __init__(self, session_id="nueva-sesion", resume=None):
        self.session_id = session_id
        self.resume = resume
        self.stopped = False
        self.yielded = False

    def events(self):
        """Yields more than once, so a `next()` leaves it mid-run.

        A fake that ends at the first line would unregister itself
        before anything could try to stop it — which says nothing about
        the bridge and would have hidden whether `stop` works at all.
        """
        self.yielded = True
        yield Event(CONSOLE, "trabajando")
        yield Event(CONSOLE, "sigo")

    def interrupt(self):
        self.stopped = True
        return True


def bridge_with(tmp_path, monkeypatch, run=None):
    """A bridge whose engine is a fake, and whose store is temporary."""
    bridge = Bridge(tmp_path, "claude", "http://x")
    bridge.sessions = Sessions(tmp_path / "s.json")
    made = run if run is not None else FakeRun()

    def fake_start(prompt, cwd, *, resume=None):
        made.resume = resume
        return made

    monkeypatch.setattr("sdk_runner.start", fake_start)
    monkeypatch.setattr("sdk_runner.available", lambda: True)
    return bridge, made


class Project:
    def __init__(self, path):
        self.path = path
        self.name = "proyecto"


# ── continuing ────────────────────────────────────────────────────────


def test_the_first_run_in_a_project_resumes_nothing(tmp_path, monkeypatch):
    bridge, run = bridge_with(tmp_path, monkeypatch)
    task = tasks.Task()
    list(bridge.events_for(task, "haz algo", Project(tmp_path / "p")))
    assert run.resume is None


def test_the_next_run_continues_the_conversation(tmp_path, monkeypatch):
    """This is the whole point: 'seguimos con lo de esta mañana'."""
    project = Project(tmp_path / "p")
    bridge, first = bridge_with(tmp_path, monkeypatch)
    list(bridge.events_for(tasks.Task(), "haz algo", project))

    second = FakeRun()
    monkeypatch.setattr("sdk_runner.start", lambda p, c, *, resume=None: (
        setattr(second, "resume", resume) or second))
    list(bridge.events_for(tasks.Task(), "sigue", project))
    assert second.resume == "nueva-sesion"


def test_asking_for_a_fresh_start_drops_the_session(tmp_path, monkeypatch):
    project = Project(tmp_path / "p")
    bridge, _ = bridge_with(tmp_path, monkeypatch)
    list(bridge.events_for(tasks.Task(), "haz algo", project))

    second = FakeRun()
    monkeypatch.setattr("sdk_runner.start", lambda p, c, *, resume=None: (
        setattr(second, "resume", resume) or second))
    list(bridge.events_for(tasks.Task(), "de cero", project, fresh=True))
    assert second.resume is None


def test_a_stopped_run_still_keeps_its_session(tmp_path, monkeypatch):
    """Or 'sigue con lo de antes' would start over after every stop."""
    project = Project(tmp_path / "p")
    bridge, run = bridge_with(tmp_path, monkeypatch)
    task = tasks.Task()
    events = bridge.events_for(task, "algo largo", project)
    next(events, None)  # start it, then abandon it
    events.close()
    assert bridge.sessions.get(project.path, NOW) == "nueva-sesion"


def test_projects_do_not_share_a_conversation(tmp_path, monkeypatch):
    bridge, _ = bridge_with(tmp_path, monkeypatch)
    list(bridge.events_for(tasks.Task(), "a", Project(tmp_path / "uno")))
    other = FakeRun()
    monkeypatch.setattr("sdk_runner.start", lambda p, c, *, resume=None: (
        setattr(other, "resume", resume) or other))
    list(bridge.events_for(tasks.Task(), "b", Project(tmp_path / "dos")))
    assert other.resume is None


# ── stopping ──────────────────────────────────────────────────────────


def test_a_running_task_can_be_stopped(tmp_path, monkeypatch):
    bridge, run = bridge_with(tmp_path, monkeypatch)
    task = tasks.Task()
    events = bridge.events_for(task, "algo largo", Project(tmp_path / "p"))
    next(events, None)
    assert bridge.stop(task.id) is True
    assert run.stopped


def test_stopping_a_task_that_finished_says_so(tmp_path, monkeypatch):
    """False, not an exception: nothing was running to stop."""
    bridge, _ = bridge_with(tmp_path, monkeypatch)
    task = tasks.Task()
    list(bridge.events_for(task, "algo", Project(tmp_path / "p")))
    assert bridge.stop(task.id) is False


def test_stopping_an_unknown_task_is_not_a_crash(tmp_path, monkeypatch):
    bridge, _ = bridge_with(tmp_path, monkeypatch)
    assert bridge.stop("no-existe") is False


# ── what the task ends up saying ──────────────────────────────────────


def test_a_cancelled_task_is_not_reported_as_completed():
    """The cancel wins: the run unwinds after it and would say success."""
    task = tasks.Task()
    task.advance(tasks.CANCELED, "Lo dejo.")
    state, _ = _ending(task, "todo listo", failed=False)
    assert state == tasks.CANCELED


def test_an_ordinary_run_completes():
    state, text = _ending(tasks.Task(), "hecho", failed=False)
    assert (state, text) == (tasks.COMPLETED, "hecho")


def test_a_failed_run_fails():
    state, _ = _ending(tasks.Task(), "", failed=True)
    assert state == tasks.FAILED


def test_fresh_is_off_unless_asked_for():
    assert _fresh({}) is False
    assert _fresh({"metadata": {}}) is False
    assert _fresh({"metadata": {"fresh": True}}) is True
