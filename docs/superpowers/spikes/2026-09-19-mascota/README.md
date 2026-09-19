# Spike — la mascota (2026-09-19)

El **bóxer** de JARVIS como **overlay GTK4 flotante**, una imagen por
estado. El arte son ocho PNG con fondo transparente, 512×512, en
`assets/boxer/<estado>.png`, dibujados como textura y cambiados según el
estado. Es un esbozo desechable: **no hay plugin todavía** — el estado se
elige por entorno o se cicla.

Diseño y decisiones: `docs/superpowers/specs/2026-09-19-mascota.md`.

## Correrlo

```bash
cd widget
DISPLAY=:0 PYTHONNOUSERSITE=1 PYTHONPATH=$PWD \
  ./.venv/bin/python ../docs/superpowers/spikes/2026-09-19-mascota/overlay.py
```

- `MASCOTA_STATE=thinking` fija una postura. Sin ella, cicla cada 2,5 s.
- `MASCOTA_SIZE=180` cambia el tamaño (por defecto 170 px).
- `MASCOTA_DIR=<ruta>` apunta a otra carpeta de PNGs.
- Reutiliza `theme` (el CSS que mata la sombra) y `ewmh` (above +
  skip-taskbar) de la tira, así que se coloca encima y abajo a la
  derecha, justo sobre la tira.

## Estados

`idle`, `listening`, `thinking`, `speaking`, `working`, `asking`,
`error`, `alert` — un `<estado>.png` cada uno. El estado solo elige la
textura; no hay animación por encima (si se quiere parpadeo o vaivén,
va en el arte o en un frame extra por estado).

## Lo que se aprendió

- **El `application_id` es un candado.** Una instancia vieja que no murió
  retiene el nombre en el bus; la nueva sale al instante y `xwininfo`
  encuentra la ventana vieja. Matar restos antes de capturar.
- **Una `Gtk.ApplicationWindow` necesita referencia en Python** o se
  recolecta a los pocos segundos y la aplicación sale sola.
- **El arte manda.** Dibujar el personaje a mano con curvas dio un
  plátano; con las ocho imágenes del propietario se ve bien de un
  golpe. El vector solo si el arte es vector.
- El fondo de los PNG es transparente de verdad (alfa 0 en las
  esquinas) y el encuadre es el mismo en las ocho, así que **no salta**
  al cambiar de estado.

## Captura

```bash
ffmpeg -y -f x11grab -video_size 186x186 -i :0.0+1716,796 -frames:v 1 out.png
xwininfo -name MASCOTA   # ¿fotografiaste la mascota y no el escritorio?
```
