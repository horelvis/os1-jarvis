"""The plugin's side of the loopback contract: ask the body, follow it.

`urllib` on purpose, the same choice `jarvis_code/client.py` makes: this
runs on a plugin thread, not on the gateway's event loop, and a blocking
read on a socket of its own is the whole design (§12, 2026-08-26 — the
live-camera lesson). Every method here is blocking; the handlers wrap the
calls in `asyncio.to_thread`.

Two things it deliberately does NOT do: it does not retry an action (the
bridge queues and the tool answers once), and it does not decide anything
about the world.
"""

from __future__ import annotations

import json
import time
import urllib.request
from collections.abc import Callable, Iterator
from urllib.parse import urlparse

from loguru import logger

DEFAULT_BRIDGE = "http://127.0.0.1:8095"

# A state read is cheap and a person is waiting; an action already has its
# own 30 s deadline inside the bridge, so the client waits a little past
# it before giving up. Both are overridable per call.
STATE_TIMEOUT = 5.0
ACTION_TIMEOUT = 35.0

# Reconnect backoff for the events follower: quick at first (a bridge
# restart), patient after (a bridge that is simply not installed on this
# box).
_BACKOFF_START = 1.0
_BACKOFF_CEILING = 30.0

# Yielded when a stream that WAS running went away. Not a bridge payload —
# named `event` so it arrives through the same door as every other one.
# The plugin needs it to tell "the body disconnected" from "nothing is
# happening", which otherwise look identical.
LOST = {"event": "lost"}


def _http_only(url: str) -> str:
    """Refuse anything but http(s). `urlopen` would happily speak `file:`."""
    scheme = urlparse(url).scheme
    if scheme not in ("http", "https"):
        raise ValueError(f"unsupported scheme: {scheme!r}")
    return url


class BridgeClient:
    """One connection's worth of state: the url and whether it answered."""

    def __init__(self, url: str = DEFAULT_BRIDGE) -> None:
        self.url = _http_only(url.rstrip("/"))
        self._up = False

    @property
    def up(self) -> bool:
        """Whether the last call reached the bridge. Read by `check_fn`.

        `check_fn` must be cheap and non-blocking — it runs while the
        model's tool list is being assembled — so this is a flag, not a
        probe. The plugin refreshes it on its own thread.
        """
        return self._up

    def state(self, timeout: float = STATE_TIMEOUT) -> dict:
        """The world snapshot. Raises on any failure; sets `up` either way."""
        try:
            payload = self._get("/state", timeout)
        except Exception:
            self._up = False
            raise
        self._up = True
        return payload

    def do(
        self, action: str, args: dict, timeout: float = ACTION_TIMEOUT
    ) -> dict:
        """Run one action and return the bridge's answer.

        The answer is the bridge's `{ok, said, error?, state?}`, or an
        error envelope if the HTTP call itself failed. It does not raise
        for a failed action — that is an answer, not an exception.
        """
        body = json.dumps({"action": action, "args": args}).encode()
        request = urllib.request.Request(
            f"{self.url}/do",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read() or b"{}")
        except Exception as exc:
            self._up = False
            logger.warning(f"jarvis-minecraft: la acción no llegó — {exc}")
            return {"ok": False, "error": "sin_puente"}
        self._up = True
        return payload if isinstance(payload, dict) else {"ok": False, "error": "raro"}

    def _get(self, path: str, timeout: float) -> dict:
        with urllib.request.urlopen(f"{self.url}{path}", timeout=timeout) as response:
            payload = json.loads(response.read() or b"{}")
        if not isinstance(payload, dict):
            raise ValueError("the bridge did not answer with an object")
        return payload


def follow_events(url: str, stop: Callable[[], bool]) -> Iterator[dict]:
    """Yield each event the body publishes. Reconnects; never raises out.

    Between connections it yields `LOST` — once per drop, and only for a
    stream that had actually been carrying something. The consumer needs
    it: a body that went away is not the same as a body at rest.

    Mirrors `jarvis_code/client.py`'s follower deliberately, including the
    logging discipline: the first failure of a run is a warning and so is
    every connected→disconnected transition; the rest are debug, because
    a warning per attempt on a box with no bridge would be a journal
    flood by the other route.
    """
    url = _http_only(url.rstrip("/"))
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
                        # otherwise reset the backoff and flap.
                        connected, complained = True, False
                        backoff = _BACKOFF_START
                        logger.info(f"jarvis-minecraft: siguiendo {url}/events")
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
        if connected:
            connected = False
            logger.warning(f"jarvis-minecraft: se ha cortado el puente — {why}")
            yield dict(LOST)
        elif not complained:
            complained = True
            logger.warning(f"jarvis-minecraft: el puente no responde — {why}")
        else:
            logger.debug(f"jarvis-minecraft: el puente sigue sin responder — {why}")
        if stop():
            return
        time.sleep(backoff)
        backoff = min(backoff * 2, _BACKOFF_CEILING)
