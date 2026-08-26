"""Reading a Server-Sent Events stream, with nothing but the stdlib.

The bridge (`Hermes/bridges/code-a2a/`) answers `message/stream` with
SSE, because the A2A specification says a streaming response is "a
sequence of StreamResponse objects" and that is how the JSON-RPC binding
delivers them. Hermes' own A2A client does not read those — `a2a_call`
uses `message/send` and waits — so this is the small piece that does.

Deliberately not `httpx` or `aiohttp`: this runs inside the gateway,
which already has both, but a reader this size does not justify picking
one and inheriting its retry semantics. What it needs is a socket that
yields lines, and `urllib` gives one.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from urllib import request


def events(url: str, payload: dict, timeout: float) -> Iterator[dict]:
    """POST `payload` and yield each `data:` object as it arrives.

    The generator ends when the server closes the stream, which per the
    specification happens when the task reaches a terminal state. A line
    that is not JSON is skipped rather than raised on: SSE allows
    comments and keep-alives, and a reader that dies on one dies in the
    first long task.
    """
    req = request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
        method="POST",
    )
    with request.urlopen(req, timeout=timeout) as response:
        for raw in response:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            body = line[5:].strip()
            if not body:
                continue
            try:
                yield json.loads(body)
            except ValueError:
                continue


def lines_of(event: dict) -> tuple[str, str]:
    """The text of one StreamResponse, and where it belongs.

    Returns `(destination, text)`, where destination is what the bridge
    marked it with — "console" or "voice" — or "" when the event carries
    no text at all (the opening Task, for instance).
    """
    result = event.get("result") or {}
    update = result.get("statusUpdate") or {}
    message = update.get("message") or {}
    parts = message.get("parts") or []
    text = " ".join(
        str(p.get("text", "")) for p in parts if isinstance(p, dict)
    ).strip()
    if not text:
        return "", ""
    destination = (update.get("metadata") or {}).get("destination") or "console"
    return str(destination), text


def state_of(event: dict) -> str:
    """The task state this event reports, or ''."""
    result = event.get("result") or {}
    update = result.get("statusUpdate") or result.get("task") or {}
    status = update.get("status") if "status" in update else update
    return str((status or {}).get("state") or "")
