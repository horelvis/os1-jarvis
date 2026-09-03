"""JARVIS — the strip on the desktop — as a Hermes platform adapter.

Unlike every other in-tree adapter except `api_server`, this one LISTENS: it
starts an aiohttp server inside the gateway process and holds one WebSocket
to it. There is exactly one strip, so a second connection replaces the first
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
* **`Platform("jarvis")` only works inside a gateway.** `Platform` is
  an Enum; the member is created by `platform_registry.register`, so
  constructing a `JarvisAdapter` in a bare REPL raises
  `ValueError: 'jarvis' is not a valid Platform`.
"""

from __future__ import annotations

import asyncio
import errno
import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Optional
from urllib.parse import urlsplit

from aiohttp import WSMsgType, web
from loguru import logger

from .protocol import (
    ProtocolError,
    asking,
    console,
    decode_client,
    done,
    error,
    ficha,
    live,
    live_end,
    live_frame,
    photo,
    silence,
    token,
)

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

# Env var names, declared in plugin.yaml's optional_env. Config-dict keys
# stay the fallback so unit tests can construct an adapter without
# touching the process environment.
_ENV_PORT = "JARVIS_PORT"
_ENV_TURN_TIMEOUT = "JARVIS_TURN_TIMEOUT"

# Authorization, read by gateway/authz_mixin.py via the registry entry that
# __init__.py's register() declares. Kept here so the name lives next to the
# other two and register() cannot drift from the adapter.
ENV_ALLOWED_USERS = "JARVIS_ALLOWED_USERS"
ENV_ALLOW_ALL_USERS = "JARVIS_ALLOW_ALL_USERS"

# There WAS a `_LEGACY_ENV` map here until 2026-09-03, translating the
# four names these variables had while the platform was called
# samantha_kiosk. It went with the clean cut: the old names stop working
# the same day, by the user's decision. Nothing on this box ever set
# them — verified 2026-08-28 across every unit and drop-in — and the
# failure mode if some unseen machine did is the safe one: a missing
# allowlist stops him answering rather than opening him up.


def _env(name: str) -> str | None:
    """The variable, or None. Never raises.

    A thin wrapper now that there is no legacy name to fall through to,
    and kept rather than inlined because `register()` drives
    authorization through it: one place to read an environment variable
    is one place to change when that stops being true.

    `or None` preserves the old behaviour for the empty string: a
    variable set to `""` reads as unset. That was load-bearing when it
    chose between two names and is merely consistent now.
    """
    return os.getenv(name) or None


# The user id the strip sends. It was pinned by the OS1 frontend's
# `wsClient.ts` until that tree was deleted on 2026-09-03; the strip
# (`gateway.py`) is the only sender now, and if its default ever changes
# this must change with it or every turn is dropped by the
# authorization gate.
DEFAULT_USER_ID = "primary"

# How long a turn may stay open before the strip apologises for it.
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


class JarvisAdapter(BasePlatformAdapter):
    name = "jarvis"

    def __init__(self, config: Optional[Dict[str, Any]] = None, **kwargs: Any) -> None:
        del kwargs
        # The house pattern (plugins/platforms/irc/adapter.py:127-128): a
        # subclass builds its OWN Platform and passes it up, rather than
        # the registry doing it — build_source() below reads self.platform.
        # NOTE: this only resolves inside a gateway; see the module docstring.
        platform = Platform("jarvis")
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
        # this, JARVIS_PORT would be documented but silently ignored.
        raw_port = _env(_ENV_PORT) or cfg.get("port", 7777)
        try:
            self._configured_port = int(raw_port)
        except (TypeError, ValueError):
            self._configured_port = 7777
        self.port = self._configured_port

        raw_timeout = _env(_ENV_TURN_TIMEOUT) or cfg.get(
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

        # While the code assistant waits for an answer, jarvis_code
        # sets this; the next unnamed input is the answer and goes to
        # the bridge instead of opening a turn. Deterministic on
        # purpose: the model that fills tool args with {} (§12,
        # 2026-08-26) never touches the reply. A frame with
        # "wake": true was addressed by name and always reaches JARVIS.
        self.divert_chat: Optional[Callable[[str], bool]] = None

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
                # JARVIS_PORT, then `/platform resume jarvis`.
                self._set_fatal_error(
                    "jarvis_port_in_use",
                    f"Port {self._configured_port} already in use. Set "
                    f"JARVIS_PORT to a different value, then "
                    f"`/platform resume jarvis`.",
                    retryable=False,
                )
            logger.error(
                f"jarvis: could not bind 127.0.0.1:{self._configured_port}: {exc}"
            )
            return False
        self.port = self._actual_port()
        logger.info(f"jarvis: serving /ws on :{self.port}")
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
        # Set when a strip connects; see the websocket handler below.
        self.loop: asyncio.AbstractEventLoop | None = None
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
        """The strip has exactly one chat — the screen it renders on."""
        del chat_id
        return {"name": "JARVIS", "type": "dm"}

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
                f"jarvis: dropping a reply that arrived after the "
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
                    "the turn timed out waiting for a reply; the watchdog "
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
                error="jarvis: no strip connected",
                retryable=True,
            )

        if turn is not None and not turn.settled:
            self._settle(turn)
        return SendResult(success=True, message_id=turn.turn_id if turn else None)

    async def _push(self, payload: str) -> bool:
        """Write one frame to the strip. False means it did not get there."""
        ws = self._ws
        if ws is None or ws.closed:
            logger.warning("jarvis: nothing connected, dropping a frame")
            return False
        try:
            await ws.send_str(payload)
        except (ConnectionResetError, RuntimeError) as exc:
            # aiohttp raises ConnectionResetError on a socket that died
            # underneath us and RuntimeError when the transport is already
            # closing. Neither may propagate: _push is called from send()
            # (whose caller is Hermes) and from the watchdog (whose caller is
            # nobody), and an exception in either place is a silent turn.
            logger.warning(f"jarvis: frame not delivered — {exc}")
            return False
        return True

    async def push_photo(self, path: str, camera: str) -> bool:
        """Show a photo on the strip. False when it could not be shown.

        The path is validated against the snapshot directory before it is
        sent: the strip opens whatever it is handed, and this socket is an
        unauthenticated local listener. The vision plugin is imported here,
        lazily, rather than at module load: `jarvis` is the strip's
        platform and must keep working on a box where `jarvis_vision` is
        absent, broken, or simply not installed — a missing camera plugin
        must never be the reason the strip goes mute.
        """
        try:
            from Hermes.plugins.jarvis_vision.snapshot import snapshot_dir
        except ImportError as exc:
            logger.warning(f"jarvis: jarvis_vision unavailable — {exc}")
            return False

        try:
            resolved = Path(path).resolve(strict=True)
            resolved.relative_to(snapshot_dir().resolve())
        except (OSError, ValueError, RuntimeError):
            # OSError: missing file, permission, or any other filesystem
            # failure surfaced by resolve(strict=True). ValueError: resolved
            # lands outside snapshot_dir(), from relative_to(). RuntimeError:
            # a symlink cycle (`resolve(strict=True)` raises this, not
            # OSError, on CPython) — reachable through our own bug in the
            # spool, not an attacker, but this method must never raise
            # regardless of cause.
            logger.warning(f"jarvis: refusing photo outside the spool: {path!r}")
            return False
        return await self._push(photo(str(resolved), camera))

    async def push_ficha(
        self,
        md: str,
        tipo: str,
        *,
        fuente: str = "",
        correcta: str = "",
        elegida: str = "",
    ) -> bool:
        """Draw a card on the strip. False when it could not be drawn.

        Every image reference in the document is validated against the
        teacher's own spool before anything goes on the wire — NOT
        against the cameras' snapshot directory. One holds pictures of
        the inside of this house and the other a diagram of the present
        perfect; sharing a spool is the path the 2026-08-25 decision
        exists not to open.

        A reference that does not resolve costs the reference, never the
        card: it is dropped from the document and the question is still
        asked. The teacher plugin is imported lazily for the same reason
        `jarvis_vision` is — a missing plugin must never be why the
        strip goes mute.
        """
        try:
            from Hermes.plugins.jarvis_teacher.imagen import spool_dir
        except ImportError as exc:
            logger.warning(f"jarvis: jarvis_teacher unavailable — {exc}")
            return False

        try:
            from Hermes.plugins.jarvis_teacher.markdown import (
                imagenes,
                quitar_imagen,
            )
        except ImportError as exc:
            logger.warning(f"jarvis: jarvis_teacher unavailable — {exc}")
            return False

        limpio = md
        for referencia in imagenes(md):
            try:
                resolved = Path(referencia).resolve(strict=True)
                resolved.relative_to(spool_dir().resolve())
            except (OSError, ValueError, RuntimeError):
                # OSError: the file is gone. ValueError: it resolves
                # outside the spool. RuntimeError: a symlink cycle. Each
                # costs that one reference; the loop goes on, because a
                # card with two images must not lose the good one to the
                # bad one.
                logger.warning(
                    f"jarvis: refusing image outside the spool: {referencia!r}"
                )
                # The reference goes out of the document entirely, the
                # way a download that failed does — pointing it at ""
                # left `![alt]()` behind, which the strip draws as
                # literal text and charges a picture's height for. The
                # one visible outcome of this check looked like a bug.
                limpio = quitar_imagen(limpio, referencia)
        try:
            frame = ficha(
                limpio, tipo, fuente=fuente, correcta=correcta, elegida=elegida
            )
        except ProtocolError as exc:
            # An unknown tipo is a bug in the caller, not in what the
            # user asked for — same rule as everywhere else in this
            # method: this method must never raise into a turn.
            logger.warning(f"jarvis: refusing to draw a ficha — {exc}")
            return False
        return await self._push(frame)

    async def _push_bytes(self, payload: bytes) -> bool:
        """Write one binary frame to the strip. False means it did not land.

        The text twin of this is `_push`. They are separate because
        aiohttp has separate methods, and because a video frame that
        cannot be delivered must be as quiet as a dropped photo: this is
        called up to 25 times a second and a warning per frame would
        drown the journal in the first minute of a camera going away.
        """
        ws = self._ws
        if ws is None or ws.closed:
            return False
        try:
            await ws.send_bytes(payload)
        except (ConnectionResetError, RuntimeError) as exc:
            logger.debug(f"jarvis: live frame not delivered — {exc}")
            return False
        return True

    async def push_console(
        self, text: str, *, done: bool = False, reset: bool = False
    ) -> bool:
        """Write lines into the strip's terminal. False when nothing took it."""
        return await self._push(console(text, done=done, reset=reset))

    async def push_asking(self, open_: bool) -> bool:
        """Tell the strip whether something waits for the user's answer.

        False when nothing took it, which is not a failure worth acting
        on: a strip that is not connected cannot be holding a window
        open either.
        """
        return await self._push(asking(open_))

    async def push_live_open(
        self, camera: str, epoch: int, extradata: bytes, width: int, height: int
    ) -> bool:
        """Tell the strip a live view is starting."""
        return await self._push(live(camera, epoch, extradata, width, height))

    async def push_live_frame(self, epoch: int, packet: bytes) -> bool:
        """One access unit. False when it did not land, never an exception."""
        try:
            payload = live_frame(epoch, packet)
        except ProtocolError as exc:
            logger.warning(f"jarvis: refusing a live frame — {exc}")
            return False
        return await self._push_bytes(payload)

    async def push_live_close(self, epoch: int, reason: str) -> bool:
        """Tell the strip the view ended, and why."""
        try:
            payload = live_end(epoch, reason)
        except ProtocolError as exc:
            logger.warning(f"jarvis: refusing a live_end — {exc}")
            return False
        return await self._push(payload)

    # ── turn lifecycle ────────────────────────────────────────────────────
    #
    # The guarantee: every accepted `chat` frame ends in exactly one `done`
    # or one `error`. Nothing downstream provides that — the gateway answers
    # asynchronously and has ten ways to answer with silence — so the adapter,
    # which is the layer that knows a turn was accepted, provides it here.

    def _open_turn(self) -> _Turn:
        # A new turn supersedes whatever was still open: one strip, one
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
            f"jarvis: no reply within {self.turn_timeout:.0f}s for turn "
            f"{turn.turn_id} — telling the user instead of leaving the screen "
            f"stuck (check the gateway log for authorization, session-key or "
            f"dispatch warnings)"
        )
        await self._push(error(_TURN_LOST))

    # ── transport ─────────────────────────────────────────────────────────

    def _origin_is_the_strip(self, origin: str) -> bool:
        """Whether an `Origin` header may open the strip's socket.

        WebSockets are not subject to the same-origin policy, so without this
        any page in any browser on this machine could open ws://127.0.0.1/ws,
        assert a `user_id`, and talk to an agent with tool access — and, worse
        than the usual CSWSH, the one-strip swap below means the hostile page
        EVICTS the real strip rather than merely eavesdropping.

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
        if not self._origin_is_the_strip(origin):
            logger.warning(f"jarvis: refusing a WebSocket from origin {origin!r}")
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
        # The loop this handler runs on is the gateway's own, and it
        # keeps running between turns — unlike the loop a turn brings
        # with it. `jarvis_vision` schedules live frames from the
        # watcher thread and needs one that will still be alive when it
        # does; see `LiveSession.open`.
        self.loop = asyncio.get_running_loop()
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
                    logger.warning(f"jarvis: bad frame — {exc}")
                    await self._push(error(_BAD_FRAME))
                    continue
                if decoded["type"] == "chat":
                    if self._should_divert(decoded):
                        # The words went to the code assistant, so no
                        # turn was opened and nothing will answer them.
                        # The strip is already showing him thinking:
                        # settle it, and say nothing — JARVIS did not
                        # hear this and must not reply to it.
                        await self._push(silence())
                        continue
                    await self._handle_chat(decoded["message"], decoded["user_id"])
        finally:
            # In a finally because an exception in the loop body would
            # otherwise leave self._ws pointing at a socket whose handler has
            # died — the next reply would be written into it and lost with no
            # log line at all.
            if self._ws is ws:
                self._ws = None
        return ws

    def _should_divert(self, decoded: Dict[str, Any]) -> bool:
        """Whether this chat frame is an answer for the code assistant.

        Synchronous and total: it never awaits and never raises, because
        it sits directly in the read loop of the one socket the strip
        has. A hook that blew up here would take the socket with it and
        the strip would go mute for reasons nothing explains.
        """
        divert = self.divert_chat
        if divert is None or decoded.get("wake"):
            return False
        try:
            return bool(divert(decoded["message"]))
        except Exception as exc:  # noqa: BLE001 — the turn outranks the hook
            logger.warning(f"jarvis: divert failed — {exc}")
            return False

    async def _handle_chat(self, message: str, user_id: str) -> None:
        source = self.build_source(
            chat_id="jarvis",
            chat_name="JARVIS",
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
            logger.error(f"jarvis: dispatch failed — {exc}")
            if not turn.settled:
                self._settle(turn)
                await self._push(error(_TURN_LOST))
