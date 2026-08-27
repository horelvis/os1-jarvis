"""The SSE follower and the answer POST, against a tiny local server."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from Hermes.plugins.samantha_code.client import follow_events, send_answer


class _Fake(BaseHTTPRequestHandler):
    posts: list[dict] = []

    def log_message(self, *a):  # noqa: A003
        pass

    def do_GET(self):
        if self.path != "/events":
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        self.wfile.write(b": keepalive\n\n")
        self.wfile.write(b'data: {"event": "task", "taskId": "t1"}\n\n')
        self.wfile.write(b"data: not-json\n\n")
        self.wfile.write(b'data: {"event": "end", "taskId": "t1"}\n\n')
        self.wfile.flush()

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        _Fake.posts.append(body)
        out = json.dumps(
            {"jsonrpc": "2.0", "id": body.get("id"), "result": {"id": "t1"}}
        ).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)


def _server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Fake)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def test_follow_yields_json_payloads_and_skips_the_rest():
    server, url = _server()
    try:
        seen = []
        for payload in follow_events(url, stop=lambda: len(seen) >= 2):
            seen.append(payload)
            if len(seen) >= 2:
                break
        assert seen == [
            {"event": "task", "taskId": "t1"},
            {"event": "end", "taskId": "t1"},
        ]
    finally:
        server.shutdown()


def test_send_answer_posts_a_message_send_with_the_task_id():
    server, url = _server()
    try:
        _Fake.posts.clear()
        assert send_answer(url, "t1", "sí") is True
        sent = _Fake.posts[0]
        assert sent["method"] == "message/send"
        message = sent["params"]["message"]
        assert message["taskId"] == "t1"
        assert message["parts"][0]["text"] == "sí"
    finally:
        server.shutdown()


def test_send_answer_is_false_when_nobody_listens():
    assert send_answer("http://127.0.0.1:9", "t1", "sí") is False
