"""The OS1 kiosk as a Hermes platform adapter.

Unlike every other in-tree adapter except `api_server`, this one LISTENS: it
starts an aiohttp server inside the gateway process, serves the built OS1
frontend, and holds one WebSocket to it. There is exactly one kiosk, so a
second connection replaces the first rather than being refused — a browser
refresh must not lock the user out of their own house.

The wire format is the frontend's existing one; see protocol.py.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from aiohttp import WSMsgType, web
from loguru import logger

from .protocol import ProtocolError, decode_client, done, error, token

try:
    from gateway.config import Platform
    from gateway.platforms.base import BasePlatformAdapter, MessageEvent, MessageType
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


# Spanish, in her voice — this reaches the screen.
_BAD_FRAME = "No te he entendido. ¿Me lo dices otra vez?"

# Env var names, declared in plugin.yaml's optional_env (Task 4) and
# exported by the manual acceptance test (Task 5). Config-dict keys stay
# the fallback so unit tests can construct an adapter without touching the
# process environment.
_ENV_PORT = "SAMANTHA_KIOSK_PORT"
_ENV_STATIC_ROOT = "SAMANTHA_KIOSK_STATIC_ROOT"


class KioskAdapter(BasePlatformAdapter):
    name = "samantha_kiosk"

    def __init__(self, config: Optional[Dict[str, Any]] = None, **kwargs: Any) -> None:
        del kwargs
        # The house pattern (plugins/platforms/irc/adapter.py:127-128): a
        # subclass builds its OWN Platform and passes it up, rather than
        # the registry doing it — build_source() below reads self.platform.
        platform = Platform("samantha_kiosk")
        super().__init__(config=config, platform=platform)
        cfg = config or {}

        # Environment first, then the config dict, then a default — the
        # house pattern (see plugins/platforms/irc/adapter.py's
        # `os.getenv("IRC_SERVER") or extra.get("server", "")`). Without
        # this, SAMANTHA_KIOSK_PORT / SAMANTHA_KIOSK_STATIC_ROOT would be
        # documented but silently ignored.
        static_root = os.getenv(_ENV_STATIC_ROOT) or cfg.get(
            "static_root", "frontend/dist"
        )
        self.static_root = Path(static_root).expanduser()

        raw_port = os.getenv(_ENV_PORT) or cfg.get("port", 7777)
        try:
            self._configured_port = int(raw_port)
        except (TypeError, ValueError):
            self._configured_port = 7777
        self.port = self._configured_port

        self._runner: Optional[web.AppRunner] = None
        self._site: Optional[web.TCPSite] = None
        self._ws: Optional[web.WebSocketResponse] = None

    async def connect(self, *, is_reconnect: bool = False) -> bool:
        del is_reconnect
        app = web.Application()
        app.router.add_get("/ws", self._ws_handler)
        # Vite's build emits index.html plus assets/, and index.html
        # references /assets/... — so three explicit routes, and no
        # catch-all static mount on "/" that would shadow /ws.
        app.router.add_static("/assets", str(self.static_root / "assets"))
        app.router.add_get("/", self._index)

        self._runner = web.AppRunner(app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, "127.0.0.1", self._configured_port)
        await self._site.start()
        self.port = self._actual_port()
        logger.info(f"samantha-kiosk: serving {self.static_root} on :{self.port}")
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

    async def _index(self, _request: web.Request) -> web.FileResponse:
        return web.FileResponse(self.static_root / "index.html")

    async def disconnect(self) -> None:
        if self._ws is not None and not self._ws.closed:
            await self._ws.close()
        self._ws = None
        if self._runner is not None:
            await self._runner.cleanup()
        self._runner = None
        self._site = None

    async def get_chat_info(self, chat_id: str) -> Dict[str, Any]:
        """The kiosk has exactly one chat — the screen it renders on."""
        del chat_id
        return {"name": "Kiosk", "type": "dm"}

    async def send(self, chat_id: str, content: str, **_kwargs: Any) -> None:
        """Hermes' reply, on its way to the screen."""
        del chat_id
        await self._push(token(content))
        await self._push(done(0))

    async def _push(self, payload: str) -> None:
        ws = self._ws
        if ws is None or ws.closed:
            logger.warning("samantha-kiosk: nothing connected, dropping a frame")
            return
        await ws.send_str(payload)

    async def _ws_handler(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)

        # Close the previous socket, then reassign — never the other way
        # around. Reassigning first would leave the old `_ws_handler`'s
        # `async for` still iterating a socket nothing points to anymore,
        # so its `.close()` races the new connection instead of completing
        # before it.
        previous = self._ws
        if previous is not None and not previous.closed:
            await previous.close()
        self._ws = ws

        async for msg in ws:
            if msg.type is not WSMsgType.TEXT:
                continue
            try:
                decoded = decode_client(msg.data)
            except ProtocolError as exc:
                logger.warning(f"samantha-kiosk: bad frame — {exc}")
                await ws.send_str(error(_BAD_FRAME))
                continue
            if decoded["type"] == "chat":
                await self._handle_chat(decoded["message"], decoded["user_id"])

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
        await self.handle_message(event)
