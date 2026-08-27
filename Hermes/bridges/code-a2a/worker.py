"""One task's life, off the request thread.

`message/send` used to do the work inside the HTTP request; now it
accepts and returns, and this runs the task: milestones out on the
firehose, the run's questions surfaced, and — the spec's third moment —
an ending that parks in INPUT_REQUIRED as a checkpoint instead of
closing, so «¿lo doy por bueno?» is a real question with a real answer.

Nothing here imports the SDK, or `http.server`. A Job is a thread, a
queue and a state machine, which is why the tests can drive whole
conversations in milliseconds against a stubbed `events_for`.
"""

from __future__ import annotations

import queue
import threading

import tasks
from answers import assent
from stream import VOICE

# An unanswered checkpoint closes itself — the work is done either way,
# and a task that waits forever pins the single-task slot (spec: 600 s).
CHECKPOINT_TIMEOUT = 600.0

# What is said when it closed itself.
_CLOSED_ALONE = "He cerrado la tarea yo solo; nadie contestó."

# Put on the checkpoint channel by `cancel()`. A cancelled task is
# terminal already; this only wakes the wait so the thread can end.
_CANCELED = object()


class Job:
    """The background execution and conversation loop of one task."""

    def __init__(self, bridge, task, prompt: str, project, *, fresh: bool = False):
        self.bridge = bridge
        self.task = task
        self.prompt = prompt
        self.project = project
        self.fresh = fresh
        self.checkpoint_timeout = CHECKPOINT_TIMEOUT
        self._checkpoint: queue.Queue = queue.Queue()
        # Whether an answer has anywhere to go, and the lock that makes
        # opening and shutting that window atomic against `answer()`,
        # which is called from the HTTP thread.
        self._at_checkpoint = False
        self._lock = threading.Lock()

    # ── the three things the outside does to it ───────────────────────

    def start(self) -> None:
        threading.Thread(target=self._run, name="code-job", daemon=True).start()

    def answer(self, text: str) -> bool:
        """Route an answer to whoever waits: the run's held question or
        the checkpoint. False when nobody does.

        The run comes first. While it holds an `AskUserQuestion` there is
        no checkpoint yet, but a Job that looked at its own queue first
        would still be the wrong shape — the question that is open now is
        always the one being answered.
        """
        run = self.bridge.runs.get(self.task.id)
        if run is not None and run.pending is not None:
            return run.answer(text)
        with self._lock:
            if not self._at_checkpoint:
                return False
            self._checkpoint.put(text)
            return True

    def cancel(self) -> None:
        """Wake a checkpoint wait so a cancelled task's thread can end.

        `Bridge.stop` reaches a running SdkRun; nothing reached a job
        parked at its checkpoint, which would then sit there for the
        whole 600 s holding the single slot of a task already CANCELED.
        """
        self._checkpoint.put(_CANCELED)

    # ── the life ──────────────────────────────────────────────────────

    def _emit(self, payload: dict) -> None:
        self.bridge.emit({"taskId": self.task.id, **payload})

    def _run(self) -> None:
        self._emit({"event": "task", "project": self.project.name})
        prompt, fresh = self.prompt, self.fresh
        try:
            while True:
                summary, failed = self._one_run(prompt, fresh)
                if self.task.state == tasks.CANCELED:
                    self._emit(
                        {
                            "event": "end",
                            "failed": False,
                            "summary": _stopped(self.task),
                        }
                    )
                    return
                self.task.advance(tasks.INPUT_REQUIRED, summary)
                # Listening BEFORE asking. The other order tells the user
                # nobody was waiting for the question he has just heard —
                # the answer arrives in the gap and finds the window shut.
                with self._lock:
                    self._at_checkpoint = True
                self._emit({"event": "ask", "qkind": "checkpoint", "text": summary})
                try:
                    reply = self._checkpoint.get(timeout=self.checkpoint_timeout)
                except queue.Empty:
                    reply = None
                with self._lock:
                    if reply is None:
                        # The window shuts here, and shuts atomically: an
                        # answer accepted at the buzzer is taken rather
                        # than left in a queue nobody reads again.
                        try:
                            reply = self._checkpoint.get_nowait()
                        except queue.Empty:
                            pass
                    self._at_checkpoint = False
                self._emit({"event": "resolved"})
                if self.task.state == tasks.CANCELED or reply is _CANCELED:
                    self._emit(
                        {
                            "event": "end",
                            "failed": False,
                            "summary": _stopped(self.task),
                        }
                    )
                    return
                # The engine's ordinary failure does not raise: it
                # yields a closing event with `failed` set, so the
                # `except` below never sees it and only this carries it
                # into the task's state. Reporting COMPLETED for work
                # that failed is what `server._ending` exists to prevent.
                closing = tasks.FAILED if failed else tasks.COMPLETED
                if reply is None:
                    self.task.advance(closing, summary)
                    self._emit(
                        {"event": "end", "failed": failed, "summary": _CLOSED_ALONE}
                    )
                    return
                if assent(str(reply)):
                    self.task.advance(closing, summary)
                    self._emit({"event": "end", "failed": failed, "summary": summary})
                    return
                # Anything else is the next instruction of the same
                # session — the SDK resumes it via sessions.py.
                prompt, fresh = str(reply), False
                self.task.advance(tasks.WORKING, "Sigo con ello.")
        except Exception as exc:  # noqa: BLE001 — a job must not die silent
            self.task.advance(tasks.FAILED, "No he podido con ello.")
            self._emit({"event": "end", "failed": True, "summary": f"falló: {exc}"})
        finally:
            self.bridge.jobs.pop(self.task.id, None)

    def _one_run(self, prompt: str, fresh: bool) -> tuple[str, bool]:
        """One pass of the assistant, as milestones and questions.

        What comes back is the spoken closing line and whether it failed;
        everything else has already gone out on the firehose by then.
        """
        summary, failed = "", False
        for event in self.bridge.events_for(
            self.task, prompt, self.project, fresh=fresh
        ):
            if event.kind in ("question", "gate"):
                self._emit({"event": "ask", "qkind": event.kind, "text": event.detail})
            elif event.kind == "resolved":
                self._emit({"event": "resolved"})
            elif event.destination == VOICE and event.final:
                summary, failed = event.text, event.failed
            elif event.text:
                self._emit(
                    {
                        "event": "milestone",
                        "kind": event.kind,
                        "detail": event.detail,
                        "text": event.text,
                    }
                )
        return summary or "Terminado.", failed


def _stopped(task) -> str:
    """What a cancelled task says: whatever `tasks/cancel` already said."""
    said = (task.last_message or {}).get("parts") or []
    if said and said[0].get("text"):
        return str(said[0]["text"])
    return "Lo he dejado, señor."
