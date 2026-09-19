"""La mascota de JARVIS — SPIKE visual (2026-09-19).

Un overlay GTK4 flotante que dibuja al BÓXER de JARVIS y cambia de imagen
según el estado. El arte son ocho PNG (fondo transparente, 512x512),
uno por estado, en `assets/boxer/<estado>.png`.

NO hay plugin todavía: el estado se elige por entorno o se cicla, para
poder juzgarlo en pantalla antes de decidir. La textura se cambia por
estado, que es exactamente lo que hará el plugin al mandar `{"state":…}`.

Reutiliza `theme` (el CSS que mata la sombra) y `ewmh` (above +
skip-taskbar) de la tira, para que se coloque igual que ella.

Uso:
    cd widget
    DISPLAY=:0 PYTHONNOUSERSITE=1 PYTHONPATH=$PWD \
      ./.venv/bin/python ../docs/superpowers/spikes/2026-09-19-mascota/overlay.py

    MASCOTA_STATE=thinking    # fija una postura; sin ella, cicla cada 2,5 s
    MASCOTA_SIZE=180          # tamaño en píxeles (por defecto 170)
    MASCOTA_DIR=<ruta>        # carpeta de PNGs (por defecto ./assets/boxer)

Es un esbozo desechable. Si convence, sube a `mascota/` con su propio
paquete y su plugin de Hermes (ver
docs/superpowers/specs/2026-09-19-mascota.md).
"""

from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Gsk", "4.0")
gi.require_version("Graphene", "1.0")

from gi.repository import Gdk, GLib, Graphene, Gtk  # noqa: E402

try:
    gi.require_version("GdkX11", "4.0")
    from gi.repository import GdkX11  # noqa: E402
except (ValueError, ImportError):  # pragma: no cover
    GdkX11 = None  # type: ignore[assignment]

from jarvis_widget import theme  # noqa: E402
from jarvis_widget.ewmh import Ewmh  # noqa: E402

TITLE = "MASCOTA"
CYCLE_SECONDS = 2.5
MARGIN_X = 26
MARGIN_Y = 16

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

_HERE = Path(__file__).resolve().parent
_ASSETS = Path(os.environ.get("MASCOTA_DIR", _HERE / "assets" / "boxer"))
SIZE = int(os.environ.get("MASCOTA_SIZE", "170"))


class MascotArea(Gtk.Widget):
    def __init__(self) -> None:
        super().__init__()
        self._t = 0.0
        self._state = os.environ.get("MASCOTA_STATE", "")
        self._fixed = bool(self._state)
        self._textures: dict[str, object] = {}
        self._lock = threading.Lock()
        self._remote: str | None = None
        if not os.environ.get("MASCOTA_LOCAL"):
            threading.Thread(target=self._follow_remote, daemon=True).start()
        self.add_tick_callback(self._tick)

    @property
    def state(self) -> str:
        # El plugin manda; el ciclo es solo el modo sin gateway.
        with self._lock:
            if self._remote:
                return self._remote
        if self._fixed:
            return self._state
        return STATES[int(self._t / CYCLE_SECONDS) % len(STATES)]

    def _follow_remote(self) -> None:
        """Lee el estado del plugin (:8094) y reconecta sin descanso."""
        host, _, port = os.environ.get("MASCOTA_REMOTE", "127.0.0.1:8094").partition(":")
        address = (host or "127.0.0.1", int(port or "8094"))
        while True:
            try:
                with socket.create_connection(address, timeout=5) as sock:
                    # Bloqueante a partir de aquí: el servidor manda un
                    # latido cada 15 s y cierra al morir, así que no hace
                    # falta un timeout de lectura (y con él, el latido
                    # parecía una caída).
                    sock.settimeout(None)
                    stream = sock.makefile("r", encoding="utf-8")
                    print(f"mascota: conectada a {address[0]}:{address[1]}", flush=True)
                    for line in stream:
                        try:
                            snapshot = json.loads(line)
                        except ValueError:
                            continue
                        state = snapshot.get("state")
                        if state in STATES:
                            with self._lock:
                                self._remote = state
            except OSError:
                with self._lock:
                    self._remote = None
            time.sleep(3)

    def _texture(self, state: str):
        if state not in self._textures:
            path = _ASSETS / f"{state}.png"
            try:
                self._textures[state] = Gdk.Texture.new_from_filename(str(path))
            except Exception as exc:  # noqa: BLE001
                print(f"mascota: falta {path}: {exc}", file=sys.stderr, flush=True)
                self._textures[state] = None
        return self._textures[state]

    def _tick(self, _widget: Gtk.Widget, clock: Gdk.FrameClock) -> bool:
        t = clock.get_frame_time() / 1_000_000
        if getattr(self, "_last", None) is None:
            self._last = t
        dt = min(t - self._last, 0.05)
        self._last = t
        self._t += dt
        self.queue_draw()
        return True

    def do_snapshot(self, snapshot: Gtk.Snapshot) -> None:
        texture = self._texture(self.state)
        if texture is None:
            return
        w = float(self.get_width())
        h = float(self.get_height())
        if w <= 0 or h <= 0:
            return
        # Cuadrada y del mismo encuadre en todas, así no salta al cambiar
        # de estado. La textura ya trae el canal alfa.
        side = min(w, h)
        rect = Graphene.Rect()
        rect.init((w - side) / 2, (h - side) / 2, side, side)
        snapshot.append_texture(texture, rect)


class MascotWindow(Gtk.ApplicationWindow):
    def __init__(self, app: Gtk.Application) -> None:
        super().__init__(application=app)
        self.set_title(TITLE)
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_default_size(SIZE, SIZE)
        self._area = MascotArea()
        self.set_child(self._area)
        self._ewmh: Ewmh | None = None
        self.connect("map", self._on_map)

    def _on_map(self, _widget: Gtk.Widget) -> None:
        provider = Gtk.CssProvider()
        provider.load_from_data(theme.CSS.encode("utf-8"), -1)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )
        surface = self.get_surface()
        if GdkX11 is None or not isinstance(surface, GdkX11.X11Surface):
            print("mascota: sin X11, se dibuja pero no se coloca", file=sys.stderr)
            return
        xid = surface.get_xid()
        monitor = Gdk.Display.get_default().get_monitor_at_surface(surface)
        g = monitor.get_geometry()
        x = g.x + g.width - SIZE - MARGIN_X
        # Justo encima de la tira, que ocupa STRIP_HEIGHT abajo.
        y = g.y + g.height - theme.STRIP_HEIGHT - SIZE - MARGIN_Y
        self._ewmh = Ewmh(xid=xid)
        self._ewmh.add_state(xid, "_NET_WM_STATE_ABOVE", "_NET_WM_STATE_SKIP_TASKBAR")
        self._ewmh.add_state(xid, "_NET_WM_STATE_SKIP_PAGER", "_NET_WM_STATE_STICKY")
        self._ewmh.move_resize(xid, x, y, SIZE, SIZE)
        self._ewmh.flush()


class MascotApp(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id="com.os1jarvis.Mascota.Spike")

    def do_activate(self) -> None:
        # La referencia es obligatoria: sin ella la ventana se recolecta y
        # la aplicación sale sola a los pocos segundos.
        self._win = MascotWindow(self)
        self._win.present()
        area = self._win.get_child()
        print(f"mascota: arte en {_ASSETS} ({SIZE}px)", flush=True)

        def _report() -> bool:
            print(f"mascota: {area.state}", flush=True)
            return True

        _report()
        GLib.timeout_add_seconds(int(CYCLE_SECONDS), _report)


if __name__ == "__main__":
    if os.environ.get("MASCOTA_STATE"):
        print(f"mascota: estado fijo {os.environ['MASCOTA_STATE']}", flush=True)
    raise SystemExit(MascotApp().run([]))
