"""The SSE follower and the answer POST, against a tiny local server."""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from Hermes.plugins.jarvis_code import client
from Hermes.plugins.jarvis_code.client import follow_events, send_answer


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


class _DropOnce(BaseHTTPRequestHandler):
    """Serves one event per connection, then closes it (HTTP/1.0's
    default) — simulating a stream that ends and must be reconnected
    to, with a different event on the second connection so a test can
    tell the two apart."""

    hits = 0

    def log_message(self, *a):  # noqa: A003
        pass

    def do_GET(self):
        _DropOnce.hits += 1
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        task_id = "t1" if _DropOnce.hits == 1 else "t2"
        self.wfile.write(f'data: {{"event": "task", "taskId": "{task_id}"}}\n\n'.encode())
        self.wfile.flush()


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


def test_follow_reconnects_once_the_stream_ends_and_yields_the_next_event(monkeypatch):
    # A short, fixed backoff — this test lets the generator run past the
    # end of one connection's stream into a real reconnect, and it must
    # stay bounded regardless of the module's real 1s/30s constants.
    monkeypatch.setattr(client, "_BACKOFF_START", 0.02)
    monkeypatch.setattr(client, "_BACKOFF_CEILING", 0.02)
    _DropOnce.hits = 0
    server = ThreadingHTTPServer(("127.0.0.1", 0), _DropOnce)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        seen = []
        # No early break: the first connection's stream must be allowed
        # to reach EOF on its own for the reconnect path to run at all.
        for payload in follow_events(url, stop=lambda: len(seen) >= 3):
            seen.append(payload)
            if len(seen) >= 3:
                break
        # `lost` between them: the stream that carried the first event
        # is not the one that carried the second, and the consumer has
        # to know (see `test_a_dropped_stream_tells_the_consumer...`).
        assert seen == [
            {"event": "task", "taskId": "t1"},
            {"event": "lost"},
            {"event": "task", "taskId": "t2"},
        ]
        assert _DropOnce.hits >= 2  # the second event came from a second connection
    finally:
        server.shutdown()


def test_follow_does_not_hang_against_an_unreachable_bridge_and_stops_promptly(monkeypatch):
    # No real server at all: every connection attempt fails immediately
    # (refused). A short, fixed backoff plus a stop() that flips after a
    # couple of failed attempts bounds the whole test to a few tens of
    # milliseconds — nowhere near the module's real 30s ceiling.
    monkeypatch.setattr(client, "_BACKOFF_START", 0.02)
    monkeypatch.setattr(client, "_BACKOFF_CEILING", 0.02)
    calls = {"n": 0}

    def stop():
        calls["n"] += 1
        return calls["n"] > 3

    started = time.monotonic()
    seen = list(follow_events("http://127.0.0.1:9", stop))
    elapsed = time.monotonic() - started

    assert seen == []
    assert elapsed < 5.0  # bounded — it must not hang


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


def test_a_bridge_that_never_answers_is_a_warning_the_first_time(
    monkeypatch, capture_logs
):
    # Bridge mode is the default, so a box with no
    # `jarvis-code-a2a.service` on it retries forever. Every attempt
    # at `debug` is a plugin that does nothing and says nothing at three
    # in the morning; a warning per attempt is the same journal flood by
    # the other route. So: the first one, then quiet.
    monkeypatch.setattr(client, "_BACKOFF_START", 0.01)
    monkeypatch.setattr(client, "_BACKOFF_CEILING", 0.01)
    calls = {"n": 0}

    def stop():
        calls["n"] += 1
        return calls["n"] > 6

    assert list(follow_events("http://127.0.0.1:9", stop)) == []

    logged = capture_logs.getvalue()
    assert logged.count("el puente no responde") == 1
    assert "WARNING" in logged


def test_losing_a_live_stream_is_a_warning_every_time(monkeypatch, capture_logs):
    # The other half: a transition from connected to disconnected always
    # says so, however many times it happens. A clean end of stream —
    # what `_DropOnce` does — raises nothing at all, which is why the
    # log line cannot live in the `except`.
    monkeypatch.setattr(client, "_BACKOFF_START", 0.01)
    monkeypatch.setattr(client, "_BACKOFF_CEILING", 0.01)
    _DropOnce.hits = 0
    server = ThreadingHTTPServer(("127.0.0.1", 0), _DropOnce)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        lost = []
        for payload in follow_events(url, stop=lambda: len(lost) >= 2):
            if payload.get("event") == "lost":
                lost.append(payload)
                if len(lost) >= 2:
                    break
        assert capture_logs.getvalue().count("se ha cortado el puente") == 2
    finally:
        server.shutdown()


class _AcceptsAndSaysNothing(BaseHTTPRequestHandler):
    """Opens `/events` with the right headers and closes without a line.

    Nothing raises: `urlopen` succeeds, the response iterator finishes
    empty, the `with` falls out. That branch used to log at no level at
    all and retry forever — the silent-at-three-in-the-morning case
    surviving in the one place nobody looked. The real bridge sends
    `: keepalive` within 15 s, so reaching this needs a foreign or
    half-dead listener on :9910, which is precisely when somebody wants
    to be told.
    """

    def log_message(self, *a):  # noqa: A003
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()


def test_a_listener_that_says_nothing_is_still_a_warning(monkeypatch, capture_logs):
    monkeypatch.setattr(client, "_BACKOFF_START", 0.01)
    monkeypatch.setattr(client, "_BACKOFF_CEILING", 0.01)
    server = ThreadingHTTPServer(("127.0.0.1", 0), _AcceptsAndSaysNothing)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    calls = {"n": 0}

    def stop():
        calls["n"] += 1
        return calls["n"] > 6

    try:
        assert list(follow_events(url, stop)) == []
        logged = capture_logs.getvalue()
        # Said once, not once per attempt: the same rule the refused
        # connection follows.
        assert logged.count("el puente no responde") == 1
        assert "WARNING" in logged
        # And never `lost`: nothing was ever being followed, so there
        # was no sight of the work to lose.
        assert "se ha cortado el puente" not in logged
    finally:
        server.shutdown()
