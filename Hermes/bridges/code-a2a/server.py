"""An A2A server that hands the work to a coding assistant.

Stdlib only, like Hermes' own A2A plugin: `http.server` and `json`. A
bridge that needed a framework installed would be one more thing to keep
working on a machine that already runs four services.

    python server.py --port 9910 --root ~/git --assistant claude

**Method names are accepted in both spellings, and that is not
belt-and-braces.** The v1.0 specification names them `SendMessage` and
`SendStreamingMessage`; Hermes' client — the only client this has to
satisfy today — sends `message/send` and `message/stream`. Publishing
one and not the other is how two correct implementations fail to meet,
so both are answered.

**A task is answered at once and worked on afterwards** (SDK path
only — the CLI engine keeps v1's blocking send). `message/send` returns
with the task WORKING, `worker.Job` runs it on a thread of its own, and
what happens meanwhile goes out on `GET /events` — one loopback SSE
firehose, JSON per line, for the Hermes plugin to follow. An answer is
another `message/send` carrying the task's id: it reaches the question
the run is holding, or the checkpoint it parked at.

What it does NOT do, deliberately: authentication (it binds to
localhost) and push notifications. There is one task at a time; a second
one arriving while one runs is refused rather than queued, because the
user has one voice and could not tell two apart.
"""

from __future__ import annotations

import argparse
import json
import queue
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import card
import projects
import runner
import sdk_runner
import sessions
import tasks
import worker
from assistants import pick
from stream import CONSOLE, VOICE

# One spelling per operation, and the aliases that reach it.
METHODS = {
    "message/send": "send",
    "SendMessage": "send",
    "message/stream": "stream",
    "SendStreamingMessage": "stream",
    "tasks/get": "get",
    "GetTask": "get",
    "tasks/cancel": "cancel",
    "CancelTask": "cancel",
}

# JSON-RPC errors, by the numbers the specification gives them.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INTERNAL_ERROR = -32603

# How long the firehose stays quiet before saying something anyway. A
# proxy or a dead peer is only discovered by writing, and a comment line
# is what SSE has instead of a ping.
KEEPALIVE = 15.0


class Bridge:
    """The state a running bridge has: its config and its tasks."""

    def __init__(self, root: Path, assistant_name: str, url: str) -> None:
        self.root = root
        self.assistant = pick(assistant_name)
        self.url = url
        self.tasks: dict[str, tasks.Task] = {}
        # The runs that are happening RIGHT NOW, by task id. Only ever
        # holds live ones: this is what `tasks/cancel` reaches into, and
        # a finished run left here would answer "stopped" about work
        # that had already ended.
        self.runs: dict[str, sdk_runner.SdkRun] = {}
        # The task being worked on, off the request thread, by task id.
        self.jobs: dict[str, worker.Job] = {}
        # Everyone listening to `GET /events`. A queue each, so a slow
        # reader delays nobody — least of all the job doing the work.
        self.listeners: list[queue.Queue] = []
        self.sessions = sessions.Sessions()
        self.lock = threading.Lock()

    def card(self) -> dict:
        return card.build(self.url, self.assistant.name, str(self.root))

    def prepare(self, text: str) -> tuple[projects.Project | None, str]:
        """Which project this is about, and what to ask for.

        The project name stays IN the prompt: the assistant works better
        knowing what it was told, and stripping it would turn "en
        barndoor, arregla el log" into "arregla el log" with no subject.
        """
        try:
            project = projects.find_in(text, self.root)
        except projects.Ambiguous:
            project = None
        return project, text

    @property
    def stoppable(self) -> bool:
        """Whether work can be stopped and conversations continued.

        Only Claude Code, and only when its SDK is installed. OpenCode
        goes down the CLI path, where neither is expressible — which is
        why the bridge keeps both engines rather than replacing one.
        """
        return self.assistant.name == "claude" and sdk_runner.available()

    def events_for(self, task, prompt: str, project, *, fresh: bool = False):
        """Do the work, yielding what it says. Stoppable where it can be.

        Also where the session is kept: the id comes back at the end of
        a run and is written down against the project, so the next one
        continues instead of starting over. Written in a `finally` — an
        interrupted run has a session too, and losing it would mean
        "sigue con lo de antes" started from nothing after every stop.
        """
        if not self.stoppable:
            yield from runner.run(self.assistant, prompt, project.path)
            return
        resume = None if fresh else self.sessions.get(project.path, time.time())
        run = sdk_runner.start(prompt, project.path, resume=resume)
        with self.lock:
            self.runs[task.id] = run
        try:
            yield from run.events()
        finally:
            with self.lock:
                self.runs.pop(task.id, None)
            if run.session_id:
                self.sessions.remember(project.path, run.session_id, time.time())

    def stop(self, task_id: str) -> bool:
        """Reach into a running task and stop it. False if none is."""
        with self.lock:
            run = self.runs.get(task_id)
        return bool(run is not None and run.interrupt())

    # ── the firehose ──────────────────────────────────────────────────

    def emit(self, payload: dict) -> None:
        """Tell everyone listening. Never blocks: the queues are
        unbounded, and a job is not made to wait on a browser."""
        with self.lock:
            listeners = list(self.listeners)
        for channel in listeners:
            channel.put(payload)

    def subscribe(self) -> queue.Queue:
        channel: queue.Queue = queue.Queue()
        with self.lock:
            self.listeners.append(channel)
        return channel

    def unsubscribe(self, channel: queue.Queue) -> None:
        with self.lock:
            if channel in self.listeners:
                self.listeners.remove(channel)

    def active(self) -> tasks.Task | None:
        """The task in flight, if there is one. There is at most one."""
        with self.lock:
            for task in self.tasks.values():
                if not task.terminal:
                    return task
        return None


def _fresh(params: dict) -> bool:
    """Whether the caller asked to start the conversation over.

    A resumed session carrying a bad assumption is worse than no
    session, because it is invisible from the outside — so there has to
    be a way to say "from scratch" without deleting a file by hand.
    """
    meta = params.get("metadata")
    return bool(isinstance(meta, dict) and meta.get("fresh"))


def _ending(task, spoken: str, failed: bool) -> tuple[str, str]:
    """The state a finished run leaves the task in, and what to say.

    A task someone cancelled is already terminal by the time the run
    unwinds, and overwriting that with COMPLETED would report success
    for work that was stopped. The cancel wins.
    """
    if task.state == tasks.CANCELED:
        return tasks.CANCELED, spoken or "Lo he dejado, señor."
    return (
        tasks.FAILED if failed else tasks.COMPLETED,
        spoken or "Terminado.",
    )


class Handler(BaseHTTPRequestHandler):
    bridge: Bridge  # set on the server class

    # ── plumbing ──────────────────────────────────────────────────────

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        print(f"[a2a] {fmt % args}", file=sys.stderr)

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _error(self, request_id, code: int, text: str) -> None:
        self._send_json(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": code, "message": text},
            }
        )

    # ── discovery ─────────────────────────────────────────────────────

    def do_GET(self) -> None:  # noqa: N802
        # Both paths: v1.0 clients read the first, pre-1.0 the second.
        if self.path in ("/.well-known/agent-card.json", "/.well-known/agent.json"):
            self._send_json(self.bridge.card())
            return
        if self.path == "/events":
            self._events()
            return
        self.send_response(404)
        self.end_headers()

    def _events(self) -> None:
        """Everything that happens, to whoever is listening.

        One JSON object per `data:` line — a task starting, a milestone,
        a question, its resolution, an ending — so the plugin renders its
        own words instead of parsing ours. It is not the A2A protocol and
        does not pretend to be: it is loopback, one direction, and the
        strip's console is what it is for.
        """
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        channel = self.bridge.subscribe()
        try:
            while True:
                try:
                    payload = channel.get(timeout=KEEPALIVE)
                except queue.Empty:
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
                    continue
                line = json.dumps(payload, ensure_ascii=False)
                self.wfile.write(f"data: {line}\n\n".encode())
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass  # the listener went away; that is how it unsubscribes
        finally:
            self.bridge.unsubscribe(channel)

    # ── the one endpoint ──────────────────────────────────────────────

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        try:
            request = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            self._error(None, PARSE_ERROR, "not JSON")
            return
        if not isinstance(request, dict):
            self._error(None, INVALID_REQUEST, "expected an object")
            return

        request_id = request.get("id")
        operation = METHODS.get(str(request.get("method")))
        params = request.get("params") or {}

        if operation is None:
            self._error(request_id, METHOD_NOT_FOUND, str(request.get("method")))
            return
        try:
            if operation == "send":
                self._send(request_id, params)
            elif operation == "stream":
                self._stream(request_id, params)
            elif operation == "get":
                self._get(request_id, params)
            elif operation == "cancel":
                self._cancel(request_id, params)
        except Exception as exc:  # pragma: no cover - defensive
            self._error(request_id, INTERNAL_ERROR, f"{type(exc).__name__}: {exc}")

    # ── the operations ────────────────────────────────────────────────

    def _task_for(self, params: dict) -> tuple[tasks.Task, str, str]:
        message = params.get("message") or {}
        text = tasks.text_of(message)
        task = tasks.Task(context_id=str(message.get("contextId") or ""))
        with self.bridge.lock:
            self.bridge.tasks[task.id] = task
        return task, text, str(message.get("contextId") or "")

    def _refuse(self, task: tasks.Task, why: str) -> dict:
        task.advance(tasks.FAILED, why)
        return task.as_dict()

    def _send(self, request_id, params: dict) -> None:
        """Take the work, or take an answer to work already going.

        Whichever it is, this returns immediately. The one thing an HTTP
        handler must never do here is wait on a run: the caller is
        JARVIS, mid-turn, with a user listening.
        """
        message = params.get("message") or {}
        job = self._job_for(message)
        if job is not None:
            self._answer(request_id, job, tasks.text_of(message))
            return
        if not self.bridge.stoppable:
            # OpenCode has no questions to answer and no way to be
            # stopped, so v1's synchronous send is still the whole of
            # what it can do.
            self._send_blocking(request_id, params)
            return
        self._accept(request_id, params)

    def _job_for(self, message: dict) -> worker.Job | None:
        """The job this message is answering, if it is answering one.

        By task id, which is what the plugin sends back; or by the
        context of the task waiting in INPUT_REQUIRED, which is how an
        A2A client that only knows the conversation reaches it.
        """
        job = self.bridge.jobs.get(str(message.get("taskId") or ""))
        if job is not None:
            return job
        context = str(message.get("contextId") or "")
        active = self.bridge.active()
        if (
            context
            and active is not None
            and active.state == tasks.INPUT_REQUIRED
            and context == active.context_id
        ):
            return self.bridge.jobs.get(active.id)
        return None

    def _answer(self, request_id, job: worker.Job, text: str) -> None:
        payload = job.task.as_dict()
        if not text or not job.answer(text):
            # The moment passed — said out loud rather than swallowed,
            # or the user repeats himself into a silence.
            payload["status"]["message"] = tasks.message(
                "Nadie esperaba una respuesta."
            )
        self._send_json({"jsonrpc": "2.0", "id": request_id, "result": payload})

    def _accept(self, request_id, params: dict) -> None:
        task, text, _context = self._task_for(params)
        if not text:
            self._send_json(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": self._refuse(task, "No he entendido qué hay que hacer."),
                }
            )
            return
        if self.bridge.active() not in (None, task):
            self._send_json(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": self._refuse(
                        task,
                        "Ya hay una tarea en marcha. "
                        "Dígame si es una respuesta o si la dejo.",
                    ),
                }
            )
            return
        project, prompt = self.bridge.prepare(text)
        if project is None:
            self._send_json(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": self._refuse(
                        task,
                        "No sé en qué proyecto trabajar. Dígame el nombre y lo retomo.",
                    ),
                }
            )
            return
        task.advance(tasks.WORKING, f"Trabajando en {project.name}.")
        job = worker.Job(self.bridge, task, prompt, project, fresh=_fresh(params))
        self.bridge.jobs[task.id] = job
        # The answer is what the caller asked for — the task, WORKING —
        # taken BEFORE the job starts. `as_dict()` reads live state, and
        # a run that finishes while this is being serialised would
        # otherwise report a state the caller never asked about.
        accepted = task.as_dict()
        job.start()
        self._send_json({"jsonrpc": "2.0", "id": request_id, "result": accepted})

    def _send_blocking(self, request_id, params: dict) -> None:
        """v1: do the work inside the request. The CLI engine's path."""
        task, text, _context = self._task_for(params)
        if not text:
            self._send_json(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": self._refuse(task, "No he entendido qué hay que hacer."),
                }
            )
            return

        project, prompt = self.bridge.prepare(text)
        if project is None:
            self._send_json(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": self._refuse(
                        task,
                        "No sé en qué proyecto trabajar. Dígame el nombre y lo retomo.",
                    ),
                }
            )
            return

        task.advance(tasks.WORKING, f"Trabajando en {project.name}.")
        events = list(
            self.bridge.events_for(task, prompt, project, fresh=_fresh(params))
        )
        result = runner.Run(events=events, returncode=0)
        task.advance(*_ending(task, result.spoken, result.failed))
        # Everything shown, as one artifact: the console lines the caller
        # may or may not want to read.
        task.artifacts = [
            {
                "artifactId": tasks.new_id(),
                "name": "salida",
                "parts": [
                    {
                        "kind": "text",
                        "text": "\n".join(
                            e.text for e in result.events if e.destination == CONSOLE
                        ),
                    }
                ],
            }
        ]
        self._send_json({"jsonrpc": "2.0", "id": request_id, "result": task.as_dict()})

    def _stream(self, request_id, params: dict) -> None:
        """Server-sent events: the Task first, then updates, then close.

        The specification is explicit about the order — "the stream MUST
        begin with the Task object… MUST close when the task reaches a
        terminal state" — and that is what makes the console on the
        strip possible: every line the assistant writes goes out as it
        is written instead of at the end.
        """
        task, text, _context = self._task_for(params)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        def emit(payload: dict) -> None:
            self.wfile.write(
                f"data: {json.dumps({'jsonrpc': '2.0', 'id': request_id, 'result': payload}, ensure_ascii=False)}\n\n".encode()
            )
            self.wfile.flush()

        emit({"task": task.as_dict()})
        project, prompt = self.bridge.prepare(text)
        if project is None:
            emit(
                {"statusUpdate": self._refuse(task, "No sé en qué proyecto trabajar.")}
            )
            return

        emit(
            {
                "statusUpdate": task.advance(
                    tasks.WORKING, f"Trabajando en {project.name}."
                )
            }
        )
        spoken = ""
        failed = False
        for event in self.bridge.events_for(
            task, prompt, project, fresh=_fresh(params)
        ):
            if event.destination == VOICE:
                spoken = event.text
                failed = failed or event.failed
            # Every line goes out, marked with where it belongs, so the
            # caller can show the console ones and say the spoken ones.
            emit(
                {
                    "statusUpdate": {
                        "state": tasks.WORKING,
                        "timestamp": tasks.now(),
                        "message": tasks.message(event.text),
                        "metadata": {"destination": event.destination},
                    }
                }
            )
        emit({"statusUpdate": task.advance(*_ending(task, spoken, failed))})

    def _get(self, request_id, params: dict) -> None:
        task = self.bridge.tasks.get(
            str(params.get("id") or params.get("taskId") or "")
        )
        if task is None:
            self._error(request_id, INVALID_REQUEST, "no such task")
            return
        self._send_json({"jsonrpc": "2.0", "id": request_id, "result": task.as_dict()})

    def _cancel(self, request_id, params: dict) -> None:
        task = self.bridge.tasks.get(
            str(params.get("id") or params.get("taskId") or "")
        )
        if task is None:
            self._error(request_id, INVALID_REQUEST, "no such task")
            return
        # Actually stop it. Until 2026-08-26 this only moved the task to
        # CANCELED while the assistant carried on working to the end —
        # the protocol saying one thing and the machine doing another.
        job = self.bridge.jobs.get(task.id)
        stopped = self.bridge.stop(task.id)
        task.advance(
            tasks.CANCELED,
            "Lo dejo." if stopped or job is not None else "No había nada trabajando.",
        )
        # A job parked at its checkpoint has no run to interrupt: it is
        # waiting on a queue, and would hold the single slot for the
        # whole 600 s of a task that is already CANCELED.
        if job is not None:
            job.cancel()
        self._send_json({"jsonrpc": "2.0", "id": request_id, "result": task.as_dict()})


def serve(host: str, port: int, root: Path, assistant: str) -> None:
    url = f"http://{host}:{port}"
    handler = type("BoundHandler", (Handler,), {"bridge": Bridge(root, assistant, url)})
    server = ThreadingHTTPServer((host, port), handler)
    print(
        f"[a2a] {handler.bridge.assistant.name} sobre {root} en {url}",
        file=sys.stderr,
    )
    server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9910)
    parser.add_argument("--root", default=str(projects.DEFAULT_ROOT))
    parser.add_argument("--assistant", default="")
    args = parser.parse_args()
    serve(args.host, args.port, Path(args.root).expanduser(), args.assistant)


if __name__ == "__main__":
    main()
