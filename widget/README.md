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

### The models it needs

- **Silero VAD**: `~/.samantha/models/silero_vad_16k_op15.onnx`, ~1.2 MB.
  Taken from the `silero-vad` wheel without installing it:
  `pip download silero-vad --no-deps` and unzip. The wheel ships four
  models; this is the 16 kHz one.
- **Whisper**: `large-v3-turbo`, downloaded automatically on first load
  (~1.5 GB, 81 s the first time, ~1 s after that). Needs the GPU: it
  sits at roughly 2.5 GB of VRAM alongside CosyVoice.

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
