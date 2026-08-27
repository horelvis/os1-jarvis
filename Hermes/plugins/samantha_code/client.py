"""The bridge's firehose, followed; and the one POST that answers it.

urllib on purpose: the gateway process already has aiohttp, but this
runs on a plugin THREAD, not the gateway's loop, and a blocking read on
a socket of its own is the whole design — nothing here may touch the
loop (§12, 2026-08-26, the live-camera lesson).
"""

from __future__ import annotations

import json
import time
import urllib.request
import uuid
from collections.abc import Callable, Iterator

from loguru import logger

DEFAULT_BRIDGE = "http://127.0.0.1:9910"

# Reconnect backoff: quick at first (a gateway restart), patient after
# (a bridge that is simply not installed on this box).
_BACKOFF_START = 1.0
_BACKOFF_CEILING = 30.0

_ANSWER_TIMEOUT = 10.0


def follow_events(url: str, stop: Callable[[], bool]) -> Iterator[dict]:
    """Yield each firehose payload. Reconnects; never raises out."""
    backoff = _BACKOFF_START
    while not stop():
        try:
            with urllib.request.urlopen(f"{url}/events", timeout=60) as response:
                logger.info(f"samantha-code: siguiendo {url}/events")
                backoff = _BACKOFF_START
                for raw in response:
                    if stop():
                        return
                    line = raw.decode("utf-8", errors="replace").strip()
                    if not line.startswith("data:"):
                        continue  # keepalives and blanks
                    try:
                        payload = json.loads(line[5:].strip())
                    except ValueError:
                        continue
                    if isinstance(payload, dict):
                        yield payload
        except Exception as exc:
            logger.debug(f"samantha-code: el puente no responde — {exc}")
        if stop():
            return
        time.sleep(backoff)
        backoff = min(backoff * 2, _BACKOFF_CEILING)


def send_answer(url: str, task_id: str, text: str) -> bool:
    """Deliver the user's answer to the bridge. False when it did not land."""
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "message/send",
            "params": {
                "message": {
                    "messageId": str(uuid.uuid4()),
                    "role": "ROLE_USER",
                    "taskId": task_id,
                    "parts": [{"kind": "text", "text": text}],
                }
            },
        },
        ensure_ascii=False,
    ).encode()
    request = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=_ANSWER_TIMEOUT) as response:
            reply = json.loads(response.read() or b"{}")
    except Exception as exc:
        logger.warning(f"samantha-code: la respuesta no llegó al puente — {exc}")
        return False
    return isinstance(reply, dict) and "result" in reply
