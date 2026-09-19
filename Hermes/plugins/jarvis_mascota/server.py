"""El puerto loopback del estado de la mascota: NDJSON, solo loopback.

Una línea JSON por estado, empujada al conectar y en cada cambio. TCP a
secas en vez de WebSocket a propósito: el overlay es un cliente que solo
lee líneas, y no hace falta un protocolo mayor para eso. 127.0.0.1
siempre — nunca 0.0.0.0.
"""

from __future__ import annotations

import json
import logging
import queue
import socketserver
import threading
from typing import Optional

from .state import Hub

log = logging.getLogger(__name__)

# Cada cuánto reenviar el estado actual sin que haya cambiado. Es un
# latido: además de mantener viva la conexión, es lo que detecta a un
# cliente que se fue (el `sendall` falla) y libera su hilo.
_KEEPALIVE_SECONDS = 15.0

# `speaking` se revierte solo: quien lo publica (el adaptador) no mide el
# audio, y quedarse hablando para siempre sería peor que volver a quieto.
_SPEAKING_SECONDS = 5.0


class _Handler(socketserver.BaseRequestHandler):
    """Un cliente puede ESCUCHAR (recibe estados) o PUBLICAR (manda uno).

    Bidireccional a propósito: así el adaptador de la tira publica por
    loopback sin importar este módulo. Los dos plugins cargan como
    nombres distintos (`hermes_plugins.*` vs `Hermes.plugins.*`), y un
    bus importado no se compartiría; un puerto sí.
    """

    def handle(self) -> None:
        hub: Hub = self.server.hub  # type: ignore[attr-defined]
        outbox: queue.Queue[dict] = queue.Queue(maxsize=8)
        stop = threading.Event()

        def push(snapshot: dict) -> None:
            try:
                outbox.put_nowait(snapshot)
            except queue.Full:
                pass  # un cliente lento no debe frenar a nadie

        def read_published() -> None:
            """Un editor manda líneas `{"state": …}`; se aplican al bus."""
            try:
                for line in self.request.makefile("r", encoding="utf-8"):
                    try:
                        message = json.loads(line)
                    except ValueError:
                        continue
                    state = message.get("state")
                    if state:
                        hub.set(state, message.get("detail", ""))
                        if state == "speaking":
                            previous = getattr(self.server, "_speaking_timer", None)
                            if previous is not None:
                                previous.cancel()
                            timer = threading.Timer(
                                _SPEAKING_SECONDS, lambda: hub.set("idle")
                            )
                            timer.daemon = True
                            timer.start()
                            self.server._speaking_timer = timer  # type: ignore[attr-defined]
            except OSError:
                pass
            finally:
                stop.set()  # el cliente se fue: el escritor también para

        unsubscribe = hub.subscribe(push)
        threading.Thread(target=read_published, name="mascota-read", daemon=True).start()
        try:
            while not stop.is_set():
                try:
                    snapshot = outbox.get(timeout=_KEEPALIVE_SECONDS)
                except queue.Empty:
                    snapshot = hub.current
                self.request.sendall((json.dumps(snapshot) + "\n").encode("utf-8"))
        except (BrokenPipeError, ConnectionResetError, TimeoutError, OSError):
            pass
        finally:
            unsubscribe()


class MascotServer:
    """El servidor de hilos, con arranque y parada limpias."""

    def __init__(self, hub: Hub, host: str = "127.0.0.1", port: int = 8094) -> None:
        self.hub = hub
        self.host = host
        self.port = port
        self._server: Optional[socketserver.ThreadingTCPServer] = None
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        server = socketserver.ThreadingTCPServer((self.host, self.port), _Handler)
        server.daemon_threads = True
        server.allow_reuse_address = True
        server.hub = self.hub  # type: ignore[attr-defined]
        self._server = server
        self._thread = threading.Thread(
            target=server.serve_forever, name="jarvis-mascota", daemon=True
        )
        self._thread.start()
        log.info("jarvis-mascota: escuchando en %s:%s", self.host, self.port)

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
