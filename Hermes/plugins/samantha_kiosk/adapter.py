"""The OS1 kiosk as a Hermes platform adapter.

Unlike every other in-tree adapter except `api_server`, this one LISTENS: it
starts an aiohttp server inside the gateway process and holds one WebSocket
to it. There is exactly one kiosk, so a second connection replaces the first
rather than being refused — a browser refresh must not lock the user out of
their own house.

The wire format is the frontend's existing one; see protocol.py.

Two things a reader should know before changing anything here:

* **Every test in tests/ runs against the shim below, not against Hermes.**
  The shim's job is "these tests run on a machine with no Hermes installed";
  its risk is that the shim can be WRONG about the real contract and nothing
  in the suite will say so. That is exactly how `send()` shipped returning
  `None` against a base class that declares `-> SendResult` and dereferences
  `result.success` unguarded — an AttributeError on every single reply, for
  weeks, with a green suite. When you touch a method the base class also
  declares, read the base class.
* **`Platform("samantha_kiosk")` only works inside a gateway.** `Platform` is
  an Enum; the member is created by `platform_registry.register`, so
  constructing a `KioskAdapter` in a bare REPL raises
  `ValueError: 'samantha_kiosk' is not a valid Platform`.
"""

from __future__ import annotations

import asyncio
import errno
import os
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional
from urllib.parse import urlsplit

from aiohttp import WSMsgType, web
from loguru import logger

from .protocol import ProtocolError, decode_client, done, error, token

try:
    from gateway.config import Platform
    from gateway.platforms.base import (
        BasePlatformAdapter,
        MessageEvent,
        MessageType,
        SendResult,
    )
except ImportError:  # pragma: no cover - only without Hermes installed
    from enum import Enum

    class Platform:  # type: ignore[no-redef]
        """Stand-in so these tests run on a machine with no Hermes."""

        def __init__(self, value: str) -> None:
            self.value = value

    class SessionSource:  # type: ignore[no-redef]
        """Stand-in mirroring the fields build_source() below fills in.

        The real one also resolves profile routing via a gateway runner;
        none of that exists without Hermes installed, so this just carries
        the attributes.
        """

        def __init__(self, **kwargs: Any) -> None:
            self.__dict__.update(kwargs)

    @dataclass
    class SendResult:  # type: ignore[no-redef]
        """Stand-in mirroring gateway.platforms.base.SendResult.

        Only the fields this adapter sets are listed; the real dataclass has
        more (raw_response, retry_after, continuation_message_ids, …), all
        defaulted. `success` is the one the base class reads without a guard
        in `_send_with_retry`, which is why `send()` must never return None.
        """

        success: bool
        message_id: Optional[str] = None
        error: Optional[str] = None
        retryable: bool = False

    class BasePlatformAdapter:  # type: ignore[no-redef]
        """Stand-in so these tests run on a machine with no Hermes."""

        def __init__(
            self, config: Optional[Dict[str, Any]] = None, platform: Any = None
        ) -> None:
            self.config = config or {}
            self.platform = platform

        def build_source(
            self,
            chat_id: str,
            chat_name: Optional[str] = None,
            chat_type: str = "dm",
            user_id: Optional[str] = None,
            user_name: Optional[str] = None,
            **_kwargs: Any,
        ) -> "SessionSource":
            return SessionSource(
                platform=self.platform,
                chat_id=str(chat_id),
                chat_name=chat_name,
                chat_type=chat_type,
                user_id=str(user_id) if user_id else None,
                user_name=user_name,
            )

        def _set_fatal_error(self, code: str, message: str, *, retryable: bool) -> None:
            """Stand-in for the real base's reconnect-watcher signal.

            The real one also flips `self._running` and writes a runtime
            status file for `hermes status`/`/platform resume`; neither
            exists without Hermes installed, so this just records the
            fields tests can assert on.
            """
            self._fatal_error_code = code
            self._fatal_error_message = message
            self._fatal_error_retryable = retryable

    class MessageType(Enum):  # type: ignore[no-redef]
        """Stand-in mirroring gateway.platforms.base.MessageType."""

        TEXT = "text"

    class MessageEvent:  # type: ignore[no-redef]
        """Stand-in mirroring gateway.platforms.base.MessageEvent."""

        def __init__(
            self,
            text: str,
            message_type: "MessageType" = None,
            source: Any = None,
            message_id: Optional[str] = None,
        ) -> None:
            self.text = text
            self.message_type = (
                message_type if message_type is not None else MessageType.TEXT
            )
            self.source = source
            self.message_id = message_id


# Spanish, in her voice — these reach the screen. See docs/personality.md:
# short, spoken, no apology-for-being-software, no "ERROR:".
_BAD_FRAME = "No te he entendido. ¿Me lo dices otra vez?"
_TURN_LOST = "Algo se ha quedado a medias. ¿Me lo repites?"

# Env var names, declared in plugin.yaml's optional_env (Task 4) and
# exported by the manual acceptance test (Task 5). Config-dict keys stay
# the fallback so unit tests can construct an adapter without touching the
# process environment.
_ENV_PORT = "SAMANTHA_KIOSK_PORT"
_ENV_TURN_TIMEOUT = "SAMANTHA_KIOSK_TURN_TIMEOUT"

# Authorization, read by gateway/authz_mixin.py via the registry entry that
# __init__.py's register() declares. Kept here so the name lives next to the
# other two and register() cannot drift from the adapter.
ENV_ALLOWED_USERS = "SAMANTHA_KIOSK_ALLOWED_USERS"
ENV_ALLOW_ALL_USERS = "SAMANTHA_KIOSK_ALLOW_ALL_USERS"

# The user id the OS1 frontend sends. Pinned by `frontend/src/net/wsClient.ts:80`
# (`userId = "primary"`); if that default ever changes, this must change with
# it or every turn is dropped by the authorization gate.
DEFAULT_USER_ID = "primary"

# How long a turn may stay open before the kiosk apologises for it.
#
# The gateway answers asynchronously: `handle_message()` returns as soon as it
# has spawned the background task, and the reply comes back later through
# `send()`. So nothing downstream of this adapter is obliged to ever close the
# loop — and the review of this plan traced ten distinct ways a turn can end
# in silence (unauthorized user, session-key mismatch, an unwired message
# handler, a socket that is open in Python but dead on the wire, …). The
# frontend has no timeout of its own: `wsClient.chat()` never settles, `busy`
# stays true, and because the STT commit is gated on `busy`, VOICE input dies
# too. Only a page reload recovers.
#
# 90 s: measured warm turns are seconds, and the long tail is an agentic turn
# with several tool calls, which stays comfortably inside a minute. Far enough
# above a real turn that the apology never pre-empts a reply that was coming;
# far enough below "the user has given up and is reaching for the power
# button". `HERMES_AGENT_TIMEOUT` (default 1800 s) is NOT the number to match —
# that is an idle-session reaper, not a per-turn budget.
_TURN_TIMEOUT_DEFAULT = 90.0


@dataclass
class _Turn:
    """One accepted `chat` frame, tracked until exactly one frame closes it.

    Invariant this whole mechanism exists to hold: every accepted `chat`
    frame ends in exactly one `done` or one `error`. `settled` is what makes
    it *exactly* one — the watchdog and `send()` race on the same flag.
    """

    turn_id: str
    watchdog: Optional[asyncio.Task] = field(default=None, repr=False)
    settled: bool = False
    timed_out: bool = False


class KioskAdapter(BasePlatformAdapter):
    name = "samantha_kiosk"

    def __init__(self, config: Optional[Dict[str, Any]] = None, **kwargs: Any) -> None:
        del kwargs
        # The house pattern (plugins/platforms/irc/adapter.py:127-128): a
        # subclass builds its OWN Platform and passes it up, rather than
        # the registry doing it — build_source() below reads self.platform.
        # NOTE: this only resolves inside a gateway; see the module docstring.
        platform = Platform("samantha_kiosk")
        super().__init__(config=config, platform=platform)

        # `adapter_factory` is called with a PlatformConfig, NOT a dict
        # (gateway/platform_registry.py:685) — which is why
        # plugins/platforms/irc/adapter.py:130 reads `config.extra`. Calling
        # `.get()` on a PlatformConfig raises AttributeError inside
        # create_adapter's `except Exception`, which logs once and returns
        # None: the platform simply never comes up, and the screen is blank
        # with no error frame to explain it. The unit tests construct with a
        # plain dict, so both shapes are accepted.
        if isinstance(config, dict):
            cfg: Dict[str, Any] = config
        else:
            cfg = getattr(config, "extra", None) or {}

        # Environment first, then the config dict, then a default — the
        # house pattern (see plugins/platforms/irc/adapter.py's
        # `os.getenv("IRC_SERVER") or extra.get("server", "")`). Without
        # this, SAMANTHA_KIOSK_PORT would be documented but silently ignored.
        raw_port = os.getenv(_ENV_PORT) or cfg.get("port", 7777)
        try:
            self._configured_port = int(raw_port)
        except (TypeError, ValueError):
            self._configured_port = 7777
        self.port = self._configured_port

        raw_timeout = os.getenv(_ENV_TURN_TIMEOUT) or cfg.get(
            "turn_timeout", _TURN_TIMEOUT_DEFAULT
        )
        try:
            self.turn_timeout = float(raw_timeout)
        except (TypeError, ValueError):
            self.turn_timeout = _TURN_TIMEOUT_DEFAULT
        if self.turn_timeout <= 0:
            # A zero or negative budget would fire the apology before the
            # gateway had a chance; treat it as "misconfigured" rather than
            # "disabled" — an appliance with no watchdog is the bug.
            self.turn_timeout = _TURN_TIMEOUT_DEFAULT

        self._runner: Optional[web.AppRunner] = None
        self._site: Optional[web.TCPSite] = None
        self._ws: Optional[web.WebSocketResponse] = None
        # At most one open turn: the frontend serialises input behind `busy`,
        # and a second `chat` frame supersedes the first rather than queueing.
        # One slot, one task — nothing here grows with uptime.
        self._turn: Optional[_Turn] = None

    async def connect(self, *, is_reconnect: bool = False) -> bool:
        del is_reconnect
        # Clear any fatal state from a PREVIOUS connect() attempt before
        # trying again — a reused adapter instance (`/platform resume`, or a
        # reconnect path that doesn't build a fresh adapter) must be able to
        # come back once the operator has fixed the underlying problem. This
        # used to live at the end of disconnect(), which looks equivalent but
        # is not: the gateway's startup path calls disconnect() and THEN
        # reads has_fatal_error (gateway/run.py:12985-12986) to decide
        # whether a failed connect() is retryable, so clearing it in
        # disconnect() erased the signal before anyone read it — the fatal
        # path silently degraded into "retry forever", which is the exact
        # failure mode it exists to prevent. Clearing here instead means the
        # flags are live for as long as they need to be (from the failed
        # connect() until the next attempt) and never during the window a
        # caller might read them.
        self._fatal_error_code = None
        self._fatal_error_message = None
        self._fatal_error_retryable = None

        app = web.Application()
        # This port serves exactly one route, /ws — no static frontend, by
        # design. The OS1 web UI is retired; JARVIS (widget/) is the client
        # now, and it only ever speaks the WebSocket protocol in protocol.py.
        app.router.add_get("/ws", self._ws_handler)

        self._runner = web.AppRunner(app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, "127.0.0.1", self._configured_port)
        try:
            await self._site.start()
        except OSError as exc:
            await self._runner.cleanup()
            self._runner = None
            self._site = None
            if getattr(exc, "errno", None) == errno.EADDRINUSE:
                # A port conflict is a configuration error, not a transient
                # blip — another process holds the port for its lifetime.
                # A bare `return False` here would make the gateway's
                # reconnect watcher treat it as retryable and loop forever
                # at the backoff cap, leaking a connection attempt each
                # retry (api_server.py's own history, #52132/#38803).
                # Non-retryable drops it from the reconnect queue; the
                # operator recovers by freeing the port or setting
                # SAMANTHA_KIOSK_PORT, then `/platform resume samantha_kiosk`.
                self._set_fatal_error(
                    "samantha_kiosk_port_in_use",
                    f"Port {self._configured_port} already in use. Set "
                    f"SAMANTHA_KIOSK_PORT to a different value, then "
                    f"`/platform resume samantha_kiosk`.",
                    retryable=False,
                )
            logger.error(
                f"samantha-kiosk: could not bind 127.0.0.1:"
                f"{self._configured_port}: {exc}"
            )
            return False
        self.port = self._actual_port()
        logger.info(f"samantha-kiosk: serving /ws on :{self.port}")
        return True

    def _actual_port(self) -> int:
        # port 0 means "any free port"; the tests rely on discovering it.
        # `AppRunner.addresses` is the public API for this (BaseRunner
        # property in aiohttp/web_runner.py) — reaching into
        # `site._server.sockets` also works on the installed 3.14.1/3.14.3,
        # but that path is a private attribute two layers deep, so the
        # documented property is used instead.
        addresses = self._runner.addresses if self._runner is not None else []
        if addresses:
            return int(addresses[0][1])
        return self._configured_port

    async def disconnect(self) -> None:
        self._abandon_turn()
        if self._ws is not None and not self._ws.closed:
            await self._ws.close()
        self._ws = None
        if self._runner is not None:
            await self._runner.cleanup()
        self._runner = None
        self._site = None
        # Fatal-error state is intentionally NOT cleared here — see the
        # comment at the top of connect(). The gateway's startup path (and
        # the secondary-profile reconnect path) calls disconnect() and then
        # reads has_fatal_error to decide whether the connect() that just
        # failed should be retried; clearing the flags here would erase that
        # signal before it's read.

    async def get_chat_info(self, chat_id: str) -> Dict[str, Any]:
        """The kiosk has exactly one chat — the screen it renders on."""
        del chat_id
        return {"name": "Kiosk", "type": "dm"}

    async def send(
        self,
        chat_id: str,
        content: str,
        reply_to: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "SendResult":
        """Hermes' reply, on its way to the screen.

        MUST return a SendResult. `BasePlatformAdapter.send` declares
        `-> SendResult` and `_send_with_retry` reads `result.success` with no
        guard, so returning None raises AttributeError inside Hermes on every
        reply — which aborts `_process_message_background` into its
        `except BaseException`, reports FAILURE to `on_processing_complete`
        for turns that actually succeeded, skips delivery bookkeeping, and
        makes the retry path dead code. It also pushes Hermes' own English
        error text onto the OS1 screen as a second token/done pair.
        """
        del chat_id, reply_to, metadata
        turn = self._turn

        if turn is not None and turn.timed_out:
            # The watchdog already told the user this turn was lost. Pushing
            # the late reply now would land a stray token/done pair on a
            # socket where the frontend may have re-armed its handlers for
            # the NEXT turn — the reply would be appended to the wrong bubble
            # and its `done` would resolve the wrong promise. Report the
            # failure instead; non-retryable, because retrying delivers the
            # same stale reply.
            self._turn = None
            logger.warning(
                f"samantha-kiosk: dropping a reply that arrived after the "
                f"{self.turn_timeout:.0f}s watchdog already closed the turn"
            )
            # The error string MUST read as a timeout to
            # BasePlatformAdapter._send_with_retry (base.py:5566,
            # `_is_timeout_error`): that is the one branch that returns the
            # failure as-is. Every other branch either retries (delivering
            # the same stale reply into the wrong bubble) or falls through to
            # a plain-text fallback send — which calls back into this same
            # send() with turn already None, so it isn't caught by the
            # `turn.timed_out` guard above and gets pushed to the screen: a
            # stray, English "(Response formatting failed, plain text:)"
            # message after the user already got Samantha's own apology.
            # Dropping the reply is still the right call — see the comment
            # above — this just keeps Hermes from working around the drop.
            return SendResult(
                success=False,
                error=(
                    "kiosk turn timed out waiting for a reply; the watchdog "
                    "already closed it"
                ),
                retryable=False,
            )

        delivered = await self._push(token(content)) and await self._push(done(0))
        if not delivered:
            # Nobody is listening — a browser mid-refresh, or a socket that
            # died between the frontend's frame and this reply. `retryable`
            # is exactly the signal for that (base.py:2479); the base class
            # backs off and tries again, which is a free rescue for the
            # reconnect case instead of a silently lost reply. The turn stays
            # open on purpose so the watchdog still owns it.
            return SendResult(
                success=False,
                error="samantha-kiosk: no kiosk connected",
                retryable=True,
            )

        if turn is not None and not turn.settled:
            self._settle(turn)
        return SendResult(success=True, message_id=turn.turn_id if turn else None)

    async def _push(self, payload: str) -> bool:
        """Write one frame to the kiosk. False means it did not get there."""
        ws = self._ws
        if ws is None or ws.closed:
            logger.warning("samantha-kiosk: nothing connected, dropping a frame")
            return False
        try:
            await ws.send_str(payload)
        except (ConnectionResetError, RuntimeError) as exc:
            # aiohttp raises ConnectionResetError on a socket that died
            # underneath us and RuntimeError when the transport is already
            # closing. Neither may propagate: _push is called from send()
            # (whose caller is Hermes) and from the watchdog (whose caller is
            # nobody), and an exception in either place is a silent turn.
            logger.warning(f"samantha-kiosk: frame not delivered — {exc}")
            return False
        return True

    # ── turn lifecycle ────────────────────────────────────────────────────
    #
    # The guarantee: every accepted `chat` frame ends in exactly one `done`
    # or one `error`. Nothing downstream provides that — the gateway answers
    # asynchronously and has ten ways to answer with silence — so the adapter,
    # which is the layer that knows a turn was accepted, provides it here.

    def _open_turn(self) -> _Turn:
        # A new turn supersedes whatever was still open: one kiosk, one
        # screen, and the frontend only sends again once the previous turn
        # settled or the user reloaded.
        self._abandon_turn()
        turn = _Turn(turn_id=str(uuid.uuid4()))
        self._turn = turn
        turn.watchdog = asyncio.create_task(self._watch_turn(turn))
        return turn

    def _abandon_turn(self) -> None:
        """Drop the open turn without answering it (supersede / shutdown)."""
        previous = self._turn
        self._turn = None
        if previous is not None and previous.watchdog is not None:
            previous.watchdog.cancel()

    def _settle(self, turn: _Turn, *, keep_slot: bool = False) -> None:
        """Mark a turn answered and stand the watchdog down.

        `keep_slot` is how the watchdog leaves its verdict where a late
        `send()` can still find it. Clearing the slot there would let the
        stale reply through as if it were a fresh turn, which is precisely
        the frame that lands in the wrong bubble.
        """
        turn.settled = True
        if not keep_slot and self._turn is turn:
            self._turn = None
        watchdog = turn.watchdog
        if watchdog is not None and watchdog is not asyncio.current_task():
            watchdog.cancel()

    async def _watch_turn(self, turn: _Turn) -> None:
        """Say something out loud if a turn never comes back."""
        try:
            await asyncio.sleep(self.turn_timeout)
        except asyncio.CancelledError:
            return
        if turn.settled or self._turn is not turn:
            return
        turn.timed_out = True
        self._settle(turn, keep_slot=True)
        logger.warning(
            f"samantha-kiosk: no reply within {self.turn_timeout:.0f}s for turn "
            f"{turn.turn_id} — telling the user instead of leaving the screen "
            f"stuck (check the gateway log for authorization, session-key or "
            f"dispatch warnings)"
        )
        await self._push(error(_TURN_LOST))

    # ── transport ─────────────────────────────────────────────────────────

    def _origin_is_the_kiosk(self, origin: str) -> bool:
        """Whether an `Origin` header may open the kiosk socket.

        WebSockets are not subject to the same-origin policy, so without this
        any page in any browser on this machine could open ws://127.0.0.1/ws,
        assert a `user_id`, and talk to an agent with tool access — and, worse
        than the usual CSWSH, the one-kiosk swap below means the hostile page
        EVICTS the real kiosk rather than merely eavesdropping.

        An absent Origin is allowed: non-browser clients (the acceptance-test
        WebSocket client, curl, a future native shell) do not send one, and
        those are not the attacker this check is about. Browsers always do.
        """
        if not origin:
            return True
        try:
            parsed = urlsplit(origin)
        except ValueError:
            return False
        if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            return False
        default_port = 443 if parsed.scheme == "https" else 80
        return (parsed.port or default_port) == self.port

    async def _ws_handler(self, request: web.Request) -> web.WebSocketResponse:
        origin = request.headers.get("Origin", "")
        if not self._origin_is_the_kiosk(origin):
            logger.warning(
                f"samantha-kiosk: refusing a WebSocket from origin {origin!r}"
            )
            raise web.HTTPForbidden()

        # heartbeat: a browser killed without a FIN (X restart, Chromium
        # crash, a laptop lid) otherwise leaves this handler blocked on
        # `async for` forever and `self._ws` pointing at a socket that is
        # open in Python and dead on the wire — every reply then vanishes
        # into it silently, and shutdown blocks on the handler. The ping
        # turns that into a normal close.
        ws = web.WebSocketResponse(heartbeat=30)
        await ws.prepare(request)

        # Swap the reference first, then close the old socket — never the
        # other way around, because `close()` awaits: a third near-simultaneous
        # connection would otherwise read a `previous` that is already marked
        # `.closed` (aiohttp marks that synchronously, ahead of its own await),
        # skip closing it, and get its own swap overwritten when this handler
        # resumes. Swapping in one step closes that window. See
        # test_concurrent_reconnects_dont_clobber_the_newest_socket, which
        # carries the full mechanism.
        previous, self._ws = self._ws, ws
        if previous is not None and not previous.closed:
            await previous.close()

        try:
            async for msg in ws:
                if msg.type is not WSMsgType.TEXT:
                    continue
                try:
                    decoded = decode_client(msg.data)
                except ProtocolError as exc:
                    logger.warning(f"samantha-kiosk: bad frame — {exc}")
                    await self._push(error(_BAD_FRAME))
                    continue
                if decoded["type"] == "chat":
                    await self._handle_chat(decoded["message"], decoded["user_id"])
        finally:
            # In a finally because an exception in the loop body would
            # otherwise leave self._ws pointing at a socket whose handler has
            # died — the next reply would be written into it and lost with no
            # log line at all.
            if self._ws is ws:
                self._ws = None
        return ws

    async def _handle_chat(self, message: str, user_id: str) -> None:
        source = self.build_source(
            chat_id="kiosk",
            chat_name="Kiosk",
            chat_type="dm",
            user_id=user_id,
            user_name=user_id,
        )
        event = MessageEvent(
            text=message,
            message_type=MessageType.TEXT,
            source=source,
            message_id=str(uuid.uuid4()),
        )
        turn = self._open_turn()
        try:
            # Returns as soon as the gateway has spawned its background task;
            # the reply comes back later through send(). The watchdog armed
            # above is what makes "later" bounded.
            await self.handle_message(event)
        except Exception as exc:
            logger.error(f"samantha-kiosk: dispatch failed — {exc}")
            if not turn.settled:
                self._settle(turn)
                await self._push(error(_TURN_LOST))
