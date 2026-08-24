# samantha-widget

Samantha as a floating strip at the bottom of the screen. GTK4 on X11.

Design: `docs/superpowers/specs/2026-08-23-samantha-widget-gtk4-design.md`

## Setup

    python3 -m venv --system-site-packages .venv
    .venv/bin/pip install -e ".[dev]"

`--system-site-packages` is required: PyGObject and the GTK4 typelib
come from the system (`python3-gi`, `gir1.2-gtk-4.0`), not from pip.
Without the flag, `import gi` fails and nothing here runs.

That flag has a second, less obvious effect: **pip treats packages
already installed system-wide as satisfied**, so `pip install pytest`
can be a no-op that leaves the venv quietly depending on the system's
copy. Use `--ignore-installed` for anything that must be pinned here:

    .venv/bin/pip install --ignore-installed pytest

(Doing that prints a warning about `langfuse` wanting an older
`packaging`. It is a system package, unrelated to this one, and it is
only visible at all because of `--system-site-packages`.)

## The venv is a minefield, and here is the map

`--system-site-packages` is required (PyGObject and the GTK4 typelib are
system packages), and it drags in two problems that both fail silently:

1. **pip treats system/user packages as satisfying a requirement**, so
   `pip install numpy` can be a no-op. Check with `pip list --local`,
   which shows only what the venv itself holds, and force what matters:

       .venv/bin/pip install --ignore-installed -e ".[dev]"

2. **`~/.local/lib` is visible too**, and a different numpy / anyio /
   websockets living there gets loaded instead of the venv's. Mixing the
   two crashes the process inside an unrelated `import`, with no
   traceback. Always run with:

       PYTHONNOUSERSITE=1

## Run

    DISPLAY=:1 \
    PYTHONNOUSERSITE=1 \
    PYTHONPATH=<repo>/backend:<repo> \
    .venv/bin/python -m samantha_widget

`PYTHONPATH` is how `samantha.tts` (CosyVoice) and Hermes' `markers.py`
are reached — the same mechanism `Hermes/run-gateway.sh` uses. Without
it she runs and is simply mute.

### Environment switches

| Variable | Effect |
|---|---|
| `SAMANTHA_WIDGET_STATE` | Freeze the wave in one state (`idle`, `listening`, `thinking`, `speaking`) and skip the voice loop. How each state gets photographed, since `xdotool` is not installed. |
| `SAMANTHA_WIDGET_NO_MIC=1` | Do not open the microphone. On a box with none plugged in, this is the difference between "she cannot hear" and "the process is broken". |
| `SAMANTHA_VAD_MODEL` | Path to `silero_vad_16k_op15.onnx` (default `~/.samantha/models/`). |
| `SAMANTHA_WIDGET_FAKE_MIC` | Speak this INTO the widget: it is synthesised, resampled to 16 kHz and pushed through the real microphone path. Everything downstream — VAD, Whisper, the gateway, her reply — is real. |
| `SAMANTHA_WIDGET_SAY` | Say this once, three seconds after starting. The only way to hear her voice on a machine with no microphone. |
| `SAMANTHA_WIDGET_DUMP` | Write every closed utterance to this directory as a WAV. When a transcription comes back as nonsense, nothing else tells you whether the audio was bad or the model was. |
| `SAMANTHA_WIDGET_PHOTO` | Show these photos (comma-separated paths) two seconds after starting, exactly as if the gateway had pushed them. The counterpart of `SAMANTHA_WIDGET_SAY` for the half of him you can see: the band, the click and the fade without needing a live turn. |

### The models it needs

- **Silero VAD**: `~/.samantha/models/silero_vad_16k_op15.onnx`, ~1.2 MB.
  Taken from the `silero-vad` wheel without installing it:
  `pip download silero-vad --no-deps` and unzip. The wheel ships four
  models; this is the 16 kHz one.
- **Whisper**: `large-v3-turbo`, downloaded automatically on first load
  (~1.5 GB, 81 s the first time, ~1 s after that). Needs the GPU: it
  sits at roughly 2.5 GB of VRAM alongside CosyVoice.

## The cameras are not here any more

This program watched the house's cameras until 2026-08-24. It does not
now: `vision.py`, the camera thread and the `SAMANTHA_WIDGET_CAMERA`,
`SAMANTHA_WIDGET_CAMERA_RETRY` and `SAMANTHA_YOLO_MODEL` switches all
moved into the gateway, as the `samantha-vision` plugin.

They went because the strip was the wrong owner. Watching has to survive
the widget being restarted, and a camera that sees somebody wants to
start a turn on its own — which is a thing the gateway can do and a
window on the desktop cannot.

Configuring them, the model file, and what the journal says when one is
off: **`Hermes/plugins/samantha_vision/README.md`**. Nothing in this
directory needs to change to point a camera anywhere.

Running it from another directory — which is what systemd does — needs
the package actually installed, not merely present:

    .venv/bin/pip install -e .

Without it the service dies on every start with `No module named
samantha_widget`, while running it by hand from this directory works
fine, because then the current directory is on sys.path.

## Test

    .venv/bin/python -m pytest -v
    .venv/bin/ruff check . && .venv/bin/ruff format --check .

## Verifying anything visual

Nothing about this program's appearance is provable from a test. Capture
the screen and look at it:

    ffmpeg -y -f x11grab -video_size 1920x1080 -i :1 -frames:v 1 /tmp/strip.png

## Cambiar la personalidad

`Hermes/jarvis-soul.md` es la identidad. Si la cambias y no notas nada:

    # por el kiosko, en este orden
    /new
    /approve

El prompt de sistema se fija cuando **nace la sesión**. Editar el
fichero, el `platform_hint` o la memoria no toca una sesión que ya
existe, y reiniciar el gateway tampoco: la sesión vive en `state.db` y
se reanuda tal cual. Hermes Desktop parece obedecer al instante sólo
porque abre una sesión propia.
