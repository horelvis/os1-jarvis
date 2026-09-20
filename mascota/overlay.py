"""La mascota de JARVIS — el bóxer en el escritorio.

Un overlay GTK4 flotante, transparente y siempre encima que dibuja al
bóxer y **lo anima**. Dos fuentes de movimiento, y conviven:

1. **Frames** (arte): si existe `assets/boxer/<estado>/` con PNGs
   numerados, se reproducen como una animación a `MASCOTA_FPS` (por
   defecto 8). Es el camino «spritesheet» de los pets de Codex.
2. **Procedural**: con un solo PNG por estado, se mueve igual — respira,
   se balancea, rebota, se inclina — con transformaciones GSK. Cada
   estado tiene su carácter: `working` bombea, `speaking` pulsa como si
   hablara, `alert` da un brinco, `error` se deja caer.

El estado lo publica el plugin `jarvis-mascota` en `127.0.0.1:8094`; si
no hay gateway, `MASCOTA_LOCAL=1` lo hace ciclar solo.

Uso:
    cd widget
    DISPLAY=:0 PYTHONNOUSERSITE=1 PYTHONPATH=$PWD \
      ./.venv/bin/python ../mascota/overlay.py
"""

from __future__ import annotations

import json
import math
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

from gi.repository import Gdk, GLib, Graphene, Gsk, Gtk  # noqa: E402

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
# 12 fps y 36 frames por estado = los 3 s originales. Coincide con la
# extracción (`fps=12`) para que la animación dure lo que duraba.
MASCOTA_FPS = float(os.environ.get("MASCOTA_FPS", "12"))

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


def motion(state: str, t: float) -> tuple[float, float, float, float, float]:
    """Movimiento procedural de un estado: (dx, dy, scale_x, scale_y, grados).

    Es lo que da vida a un PNG quieto. Los números son pequeños a
    propósito: la mascota acompaña, no baila. El pivote está en los pies
    (lo pone quien dibuja), así que inclinarse lee como estar de pie.
    """
    tau = math.tau
    breathe = math.sin(tau * 0.25 * t)
    sway = math.sin(tau * 0.15 * t)
    if state == "idle":
        return (0.6 * sway, 0.8 * breathe, 1 + 0.008 * breathe, 1 - 0.012 * breathe, 0.4 * sway)
    if state == "listening":
        return (0.0, -2.0, 1.0, 1.0, 1.6 * math.sin(tau * 0.35 * t))
    if state == "thinking":
        return (0.0, 0.5 * breathe, 1.0, 1.0, 2.6 * math.sin(tau * 0.22 * t))
    if state == "speaking":
        pulse = math.sin(tau * 6.0 * t)
        return (0.0, -0.6, 1 + 0.018 * pulse, 1 + 0.010 * pulse, 0.0)
    if state == "working":
        return (0.0, -1.8 * abs(math.sin(tau * 1.4 * t)), 1.0, 1.0, 0.0)
    if state == "asking":
        return (0.0, -2.2 * abs(math.sin(tau * 1.8 * t)), 1.0, 1.0, 1.2 * math.sin(tau * 0.9 * t))
    if state == "error":
        return (0.0, 1.6, 1.0, 0.99, -1.0)
    if state == "alert":
        return (0.0, -3.2 * abs(math.sin(tau * 2.5 * t)), 1.0, 1.0, 0.0)
    return (0.0, 0.0, 1.0, 1.0, 0.0)


class MascotArea(Gtk.Widget):
    def __init__(self) -> None:
        super().__init__()
        self._t = 0.0
        self._state = os.environ.get("MASCOTA_STATE", "")
        self._fixed = bool(self._state)
        self._frames: dict[str, list] = {}
        self._lock = threading.Lock()
        self._remote: str | None = None
        if not os.environ.get("MASCOTA_LOCAL"):
            threading.Thread(target=self._follow_remote, daemon=True).start()
        self.add_tick_callback(self._tick)

    @property
    def state(self) -> str:
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
                    sock.settimeout(None)  # el latido de 15 s cubre la liveness
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

    def _load_frames(self, state: str) -> list:
        """Los PNGs de un estado: una carpeta secuencia, o un solo fichero."""
        if state in self._frames:
            return self._frames[state]
        frames: list = []
        folder = _ASSETS / state
        candidates: list[Path] = []
        if folder.is_dir():
            candidates = sorted(folder.glob("*.png"))
        else:
            single = _ASSETS / f"{state}.png"
            if single.is_file():
                candidates = [single]
        for path in candidates:
            try:
                frames.append(Gdk.Texture.new_from_filename(str(path)))
            except Exception as exc:  # noqa: BLE001
                print(f"mascota: no pude cargar {path}: {exc}", file=sys.stderr, flush=True)
        if not frames:
            print(f"mascota: sin arte para «{state}» en {_ASSETS}", file=sys.stderr, flush=True)
        else:
            print(f"mascota: {state}: {len(frames)} frames", flush=True)
        self._frames[state] = frames
        return frames

    def _tick(self, _widget: Gtk.Widget, clock: Gdk.FrameClock) -> bool:
        t = clock.get_frame_time() / 1_000_000
        if getattr(self, "_last", None) is None:
            self._last = t
        dt = min(t - self._last, 0.05)  # un portátil suspendido no teletransporta
        self._last = t
        self._t += dt
        self.queue_draw()
        return True

    def do_snapshot(self, snapshot: Gtk.Snapshot) -> None:
        state = self.state
        frames = self._load_frames(state)
        if not frames:
            return
        w = float(self.get_width())
        h = float(self.get_height())
        if w <= 0 or h <= 0:
            return
        texture = frames[int(self._t * MASCOTA_FPS) % len(frames)]

        side = min(w, h)
        x = (w - side) / 2
        y = (h - side) / 2
        if len(frames) > 1:
            # El vídeo ya trae el movimiento. Sumarle el procedural encima
            # lo deforma y lo hace parecer mal reproducido.
            dx, dy, sx, sy, degrees = 0.0, 0.0, 1.0, 1.0, 0.0
        else:
            dx, dy, sx, sy, degrees = motion(state, self._t)

        # Pivote en los pies, no en el centro: un perro sentado se inclina
        # sobre el suelo, no sobre su ombligo.
        px, py = w / 2, y + side * 0.92
        transform = Gsk.Transform.new()
        transform = transform.translate(Graphene.Point().init(px + dx, py + dy))
        transform = transform.rotate(degrees)
        transform = transform.scale(sx, sy)
        transform = transform.translate(Graphene.Point().init(-px, -py))

        rect = Graphene.Rect()
        rect.init(x, y, side, side)
        snapshot.save()
        snapshot.transform(transform)
        snapshot.append_texture(texture, rect)
        snapshot.restore()


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
        super().__init__(application_id="com.os1jarvis.Mascota")

    def do_activate(self) -> None:
        # La referencia es obligatoria: sin ella la ventana se recolecta y
        # la aplicación sale sola a los pocos segundos.
        self._win = MascotWindow(self)
        self._win.present()
        area = self._win.get_child()
        print(f"mascota: arte en {_ASSETS} ({SIZE}px, {MASCOTA_FPS:g} fps)", flush=True)

        def _report() -> bool:
            print(f"mascota: {area.state}", flush=True)
            return True

        _report()
        GLib.timeout_add_seconds(int(CYCLE_SECONDS), _report)


if __name__ == "__main__":
    if os.environ.get("MASCOTA_STATE"):
        print(f"mascota: estado fijo {os.environ['MASCOTA_STATE']}", flush=True)
    raise SystemExit(MascotApp().run([]))
