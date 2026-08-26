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

What it does NOT do, deliberately: authentication (it binds to
localhost), push notifications, and multi-turn input. A task is one
request and one answer; when the assistant needs a decision, that comes
back as text for JARVIS to say out loud, and the user's reply arrives as
the next task.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import card
import projects
import runner
import tasks
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


class Bridge:
    """The state a running bridge has: its config and its tasks."""

    def __init__(self, root: Path, assistant_name: str, url: str) -> None:
        self.root = root
        self.assistant = pick(assistant_name)
        self.url = url
        self.tasks: dict[str, tasks.Task] = {}
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
        self.send_response(404)
        self.end_headers()

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
        result = runner.collect(self.bridge.assistant, prompt, project.path)
        state = tasks.FAILED if result.failed else tasks.COMPLETED
        task.advance(state, result.spoken or "Terminado.")
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
        for event in runner.run(self.bridge.assistant, prompt, project.path):
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
        emit(
            {
                "statusUpdate": task.advance(
                    tasks.FAILED if failed else tasks.COMPLETED, spoken or "Terminado."
                )
            }
        )

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
        task.advance(tasks.CANCELED, "Cancelado.")
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
