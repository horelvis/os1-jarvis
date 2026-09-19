# mascota — el bóxer de JARVIS

El bóxer de JARVIS en el escritorio: un overlay GTK4 transparente,
siempre encima, abajo a la derecha y justo sobre la tira. Se mueve, y su
estado lo manda el plugin `jarvis-mascota` (`127.0.0.1:8094`).

Lo arranca `systemd/jarvis-mascota.service` (unidad de usuario, atada a
la sesión gráfica), así que está desde el login como la tira.

Diseño y decisiones: `docs/superpowers/specs/2026-09-19-mascota.md`.

## Correrlo a mano

```bash
cd widget
DISPLAY=:0 PYTHONNOUSERSITE=1 PYTHONPATH=$PWD \
  ./.venv/bin/python ../mascota/overlay.py
```

- Por defecto sigue el estado real del plugin; si no hay gateway,
  `MASCOTA_LOCAL=1` lo hace ciclar solo, y `MASCOTA_STATE=thinking` fija
  una postura.
- `MASCOTA_SIZE=180` (por defecto 170), `MASCOTA_DIR=<ruta>` para otro
  arte, `MASCOTA_REMOTE=host:puerto` para otro bus.
- Reutiliza `theme` (el CSS que mata la sombra) y `ewmh` (above +
  skip-taskbar) de la tira: por eso la unidad pone `PYTHONPATH=widget/`.

## Animación — dos caminos, y conviven

1. **Frames (arte).** Si existe `assets/boxer/<estado>/` con PNGs
   numerados, se reproducen como animación a `MASCOTA_FPS` (por defecto
   8). Es el camino «spritesheet» de los pets de Codex.
2. **Procedural.** Con un solo PNG por estado (lo que hay hoy), se mueve
   igual: respira, se balancea, rebota o se inclina con
   transformaciones GSK. Cada estado tiene su carácter —`working`
   bombea, `speaking` pulsa, `alert` brinca, `error` se deja caer—.
   El pivote está en los pies, así que inclinarse lee como estar de pie.

Los ocho estados: `idle`, `listening`, `thinking`, `speaking`,
`working`, `asking`, `error`, `alert`.

## Arte

`assets/boxer/<estado>.png` — 512×512, fondo transparente, mismo
encuadre en todos (si no, salta al cambiar de estado). Para animación por
frames, crear `assets/boxer/<estado>/` con `01.png`, `02.png`, … del
mismo encuadre.
