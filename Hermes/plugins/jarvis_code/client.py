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


# Yielded to the consumer when a stream that WAS running went away.
# Not a bridge payload — the bridge never sends this — and named
# `event` so it arrives through the same door every other payload does.
# It exists because the reconnect used to be invisible: `follow_events`
# swallowed it, so the dispatcher never learned the stream broke and a
# divert armed before the break stayed armed, waiting to eat exactly one
# sentence from a task nobody was running any more.
LOST = {"event": "lost"}


def follow_events(url: str, stop: Callable[[], bool]) -> Iterator[dict]:
    """Yield each firehose payload. Reconnects; never raises out.

    Between connections it yields `LOST` — once per drop, and only for a
    stream that had actually been carrying something. The consumer needs
    it: what it has on screen and what it has armed both belong to a
    stream that is gone.

    Logging is deliberately not all at `debug`. A box with no
    `jarvis-code-a2a.service` on it gets bridge mode by default and
    retries forever at a 30 s ceiling; every attempt failing in silence
    is a plugin that does nothing and says nothing at three in the
    morning. So the FIRST failure of a run of them is a warning, and so
    is every transition from connected to disconnected. The rest stay at
    `debug`, because a warning per attempt would be the same journal
    flood by the other route.
    """
    backoff = _BACKOFF_START
    connected = False
    complained = False
    while not stop():
        try:
            with urllib.request.urlopen(f"{url}/events", timeout=60) as response:
                for raw in response:
                    if not connected:
                        # On the first LINE, not on the open: a server
                        # that accepts and hangs up immediately would
                        # otherwise reset the backoff and flap, one
                        # `LOST` per second. A live stream sends
                        # keepalives, so any line proves it.
                        connected, complained = True, False
                        backoff = _BACKOFF_START
                        logger.info(f"jarvis-code: siguiendo {url}/events")
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
            why = "el puente ha cerrado el hilo"
        except Exception as exc:
            why = str(exc)
        # Everything said about the attempt is said HERE, out of both
        # branches, because neither of them owns the whole story: a
        # clean end of stream raises nothing at all, and a listener that
        # accepts the connection and closes it without sending a line
        # raises nothing either — that one left `connected` False and
        # logged at no level whatsoever, which is the silent-at-three-
        # in-the-morning case this is written against, surviving in the
        # one branch nobody looked at.
        if connected:
            connected = False
            logger.warning(f"jarvis-code: se ha cortado el puente — {why}")
            yield dict(LOST)
        elif not complained:
            complained = True
            logger.warning(f"jarvis-code: el puente no responde — {why}")
        else:
            logger.debug(f"jarvis-code: el puente sigue sin responder — {why}")
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
        logger.warning(f"jarvis-code: la respuesta no llegó al puente — {exc}")
        return False
    return isinstance(reply, dict) and "result" in reply
