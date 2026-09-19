"""El estado de la mascota, como dato puro.

Sin red, sin `gi`, sin hilos: lo que se puede testear con un intérprete y
nada más. El servidor y los hooks lo usan, pero no viven aquí.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable

# Los ocho del arte (`assets/boxer/<estado>.png`) y de la spec.
STATES = (
    "idle",
    "listening",
    "thinking",
    "speaking",
    "working",
    "asking",
    "error",
    "alert",
)


@dataclass
class Snapshot:
    state: str = "idle"
    detail: str = ""
    since: float = field(default_factory=time.time)

    def as_dict(self) -> dict:
        return {"state": self.state, "detail": self.detail, "ts": self.since}


class Hub:
    """El estado actual y quiénes lo escuchan.

    Publicar avisa a cada suscriptor con el snapshot nuevo. Sin sockets:
    el servidor se suscribe como uno más, y así una caída de red nunca
    toca la lógica de estado.
    """

    def __init__(self, initial: str = "idle") -> None:
        self._lock = threading.Lock()
        self._snapshot = Snapshot(state=initial if initial in STATES else "idle")
        self._subscribers: list[Callable[[dict], None]] = []

    def subscribe(self, callback: Callable[[dict], None]) -> Callable[[], None]:
        """Añade un suscriptor y le entrega el estado actual de inmediato.

        Devuelve la función para darse de baja.
        """
        with self._lock:
            self._subscribers.append(callback)
            current = self._snapshot.as_dict()
        try:
            callback(current)
        except Exception:  # un suscriptor roto no tumba a los demás
            pass

        def unsubscribe() -> None:
            with self._lock:
                if callback in self._subscribers:
                    self._subscribers.remove(callback)

        return unsubscribe

    def set(self, state: str, detail: str = "") -> None:
        """Publica un estado. Un nombre desconocido cae a `idle`."""
        if state not in STATES:
            state = "idle"
        detail = detail or ""
        with self._lock:
            if self._snapshot.state == state and self._snapshot.detail == detail:
                return  # nada nuevo que decir
            self._snapshot = Snapshot(state=state, detail=detail)
            subscribers = list(self._subscribers)
            snapshot = self._snapshot.as_dict()
        for callback in subscribers:
            try:
                callback(snapshot)
            except Exception:
                pass

    @property
    def current(self) -> dict:
        with self._lock:
            return self._snapshot.as_dict()
