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
| `SAMANTHA_WIDGET_CAMERA` | An RTSP URL, or any file PyAV can open. A recording works exactly as a live camera does, which is how the vision path is tested while the cameras are off. |
| `SAMANTHA_WIDGET_CAMERA_RETRY` | Seconds before reopening a camera that ended or failed (default 30). `0` gives up when the stream ends — what you want for a recording. |
| `SAMANTHA_YOLO_MODEL` | Path to `yolov9-t-320.onnx` (default `~/.samantha/models/`). |
| `SAMANTHA_WIDGET_FAKE_MIC` | Speak this INTO the widget: it is synthesised, resampled to 16 kHz and pushed through the real microphone path. Everything downstream — VAD, Whisper, the gateway, her reply — is real. |
| `SAMANTHA_WIDGET_SAY` | Say this once, three seconds after starting. The only way to hear her voice on a machine with no microphone. |
| `SAMANTHA_WIDGET_DUMP` | Write every closed utterance to this directory as a WAV. When a transcription comes back as nonsense, nothing else tells you whether the audio was bad or the model was. |

### The models it needs

- **Silero VAD**: `~/.samantha/models/silero_vad_16k_op15.onnx`, ~1.2 MB.
  Taken from the `silero-vad` wheel without installing it:
  `pip download silero-vad --no-deps` and unzip. The wheel ships four
  models; this is the 16 kHz one.
- **Whisper**: `large-v3-turbo`, downloaded automatically on first load
  (~1.5 GB, 81 s the first time, ~1 s after that). Needs the GPU: it
  sits at roughly 2.5 GB of VRAM alongside CosyVoice.
- **YOLOv9**: `~/.samantha/models/yolov9-t-320.onnx`, 8 MB. Copied from
  BarnDoor's `frigate-config/models/`; that repo's
  `scripts/build-yolov9-onnx.sh` is what produced it.

## The cameras

Borrowed from [BarnDoor](../../barndoor) — the RTSP layout of the house's
cameras and the YOLO model — and nothing else: no Frigate, no MQTT, no
second agent. It needs no new dependency, since onnxruntime is already
here for the VAD and PyAV came in with faster-whisper.

    SAMANTHA_WIDGET_CAMERA=rtsp://user:pass@192.168.100.142:554/h264Preview_01_sub

Point it at the **sub-stream**: 4K frames cost time to decode and YOLO
scales everything to 320 px anyway.

When something is worth mentioning she is *told*, not made to recite —
the prompt asks for one short line in her own words and forbids
mentioning cameras or detections. What reaches you is hers:

    cámara: alguien
    ← Oye. Hay alguien fuera de casa.

"Worth mentioning" is the hard half, and the rules come from BarnDoor's
`agent/rules.py`, which had already been run against these cameras:
detections under **0.7** are ignored, the same label is not repeated
within **180 s**, and a person between 23:00 and 07:00 overrides that
silence — the second time somebody is in the garden at 3am is more worth
saying than the first. Only people: a parked car would talk all night.

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
