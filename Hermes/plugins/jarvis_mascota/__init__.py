"""JARVIS (mascota): el estado del bóxer, servido por loopback en :8094.

Este plugin es el **bus**, no la fuente. Quien conoce el turno es el
adaptador de la plataforma `jarvis`, que ya sabe cuándo el modelo piensa,
cuándo hay una herramienta abierta y cuándo hay respuesta; publica por
loopback y aquí solo se guarda y se reparte a quien escuche (el overlay).

Se habla por TCP y no por import a propósito: los plugins cargan como
nombres de módulo distintos (`hermes_plugins.*` frente a
`Hermes.plugins.*`), así que un bus importado no se compartiría. Un
puerto sí.

No habla, no razona y no guarda conversación. Mira y publica.
"""

from __future__ import annotations

import logging
import os

from .server import MascotServer
from .state import Hub

log = logging.getLogger(__name__)

_PORT = int(os.environ.get("JARVIS_MASCOTA_PORT", "8094"))

# El bus a nivel de módulo, por si algo EN ESTE MISMO módulo quiere
# publicar sin pasar por el puerto. El adaptador no lo usa (importa otro
# módulo); este es para el propio plugin y para los tests.
_HUB: Hub | None = None


def publish(state: str, detail: str = "") -> None:
    """Publica un estado en el bus en proceso. No-op si no está cargado."""
    if _HUB is not None:
        _HUB.set(state, detail)


def register(ctx) -> None:
    global _HUB
    hub = Hub()
    _HUB = hub
    server = MascotServer(hub, host="127.0.0.1", port=_PORT)
    try:
        server.start()
    except OSError as exc:
        # El puerto ocupado no debe tumbar el gateway, y tiene que sonar.
        log.warning(
            "jarvis-mascota: no pude escuchar en 127.0.0.1:%s (%s); "
            "la mascota se quedará quieta",
            _PORT,
            exc,
        )
    ctx.on_unload(server.stop)
    log.info("jarvis-mascota: sirviendo el estado en 127.0.0.1:%s", _PORT)
