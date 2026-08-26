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
| `SAMANTHA_WIDGET_MIC_GATE=1` | Deafen the microphone while he speaks. **Not needed since 2026-08-26**: `echo.py` cuts his own words out of the transcript instead, so the microphone stays open and he can be interrupted. Keep it for a box where that filter is not enough. Off by default since 2026-08-25: it is what made interrupting him impossible, because `detector.speaking` had to be true before a frame could reach the detector, and only his own voice through the room could open that latch. Set it on a box with no echo cancellation, or he answers himself. |
| `SAMANTHA_WIDGET_DUMP` | Write every closed utterance to this directory as a WAV. When a transcription comes back as nonsense, nothing else tells you whether the audio was bad or the model was. |
| `SAMANTHA_WIDGET_PHOTO` | Show these photos (comma-separated paths) two seconds after starting, exactly as if the gateway had pushed them. The counterpart of `SAMANTHA_WIDGET_SAY` for the half of him you can see: the band, the click and the fade without needing a live turn. |
| `SAMANTHA_WIDGET_LIVE` | Feed the band this video file as if the gateway had pushed it. The counterpart of `SAMANTHA_WIDGET_PHOTO` for the half of him that moves — the decoder, the band and the input region, with no gateway and no camera. |
| `SAMANTHA_WIDGET_WAKE_WORD` | The name he answers to. `jarvis` by default; **empty turns the wake word off entirely**, which is how he behaved before 2026-08-26 — everything heard is for him. Matching is deliberately loose: Whisper renders it as "Carbis", "Harvish", "Jervis" and "Harvies", all measured, and an exact match would ignore four of five. |
| `SAMANTHA_WIDGET_WAKE_WINDOW` | Seconds after he answers during which the next sentence needs no name (default 30). Each answer pushes it out; sentences inside it do not. |
| `SAMANTHA_WIDGET_BARGE_RMS` | How loud the room must be, while he is speaking, before a frame may start a turn (default 0.05). This is what lets you interrupt him without him interrupting himself: his own echo has to fall below it and your voice above it. **Calibrate it against the room, not the code** — with the speaker beside the microphone his echo measured 0.178, louder than a person, and no value works; moved apart at half volume it is 0.027-0.048 against a voice at 0.054-0.088. Set it to 0 to let every frame through. |
| `SAMANTHA_WIDGET_TRACE_MIC=1` | Log what the microphone hears while HE is speaking. The instrument for the number above. |
| `SAMANTHA_WIDGET_SILENCE` | Seconds of quiet that end a turn (default 1.2). Lower cuts people off mid-sentence; higher makes him slower to answer. |
| `SAMANTHA_WIDGET_SWITCHES` | Start with these switches already off: `mic`, `voice`, or both. Handy for photographing the struck-through glyphs; a press can also be sent for real with `tools/click.py`. |

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

## The strip grows for a photo

Since 2026-08-25 the strip is not always the same size. When he is asked
to look at a camera, the gateway pushes a `photo` frame down the
WebSocket that was already there, and a band appears **above** the wave
with the picture in it:

| | |
|---|---|
| At rest | `900x96` |
| A photo arrives | `900x210` — a 16:9 thumbnail, centred |
| Click the picture | `900x480`, and the fade timer starts again |
| Click it again | gone |
| Left alone | gone after 15 s |

Several photos at once — asking about the house looks at every camera —
are laid out left to right in one row, four at most, and the strip grows
once rather than wider.

**Only the picture answers a press.** The band is as wide as the strip
and almost all of it is transparent, so a press is hit-tested against the
tiles; a click on the empty air beside the photo does nothing, the same
as a click on the wave. **Known, and deliberately not fixed:** while a
photo is up, that transparent band still swallows pointer events over the
desktop underneath it — for those fifteen seconds, clicks beside the
picture do not reach whatever is behind. The honest fix is an X input
region set by hand, and it was judged riskier than the defect.

**The growth is upward and it is not GTK's.** The strip's bottom edge is
already flush against the screen, so letting GTK resize the toplevel puts
the extra height off the bottom of the display. `window.resize_to` moves
the top edge up by exactly as much as the window grew, through the same
EWMH placement call `_on_map` uses, and then reads the geometry back to
check the window manager obeyed — mutter constrains a move against the
size it still believes the window to be, which once left the strip
floating in the middle of the desktop after a shrink.

The JPEG itself is written by the gateway, in
`Hermes/plugins/samantha_vision/`; the strip is only ever handed a path
and opens it. To see all of this without a live turn — and without a
camera — point `SAMANTHA_WIDGET_PHOTO` at one or more image files.

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

### The three switches

At the right end of the strip, in the wave's own colour: his ears, his
voice, and the door.

| Glyph | Press |
|---|---|
| microphone | Stops listening. Frames are dropped rather than the stream closed — closing PortAudio from its own callback is the segfault §2.8 is written around. Press again to hear. |
| speaker | Stops him talking, at once, mid-sentence. He still listens. Clauses are dropped rather than queued, so unmuting never says a minute-old answer out loud. |
| cross | Closes him. **Two presses within three seconds** — the first arms it and the cross lights up. He comes back only with `systemctl --user start samantha-widget`. |

To press one from a script — the strip has no keyboard shortcut and
`xdotool` is not installed here, but `libXtst` is:

```bash
DISPLAY=:1 xwininfo -name "Samantha" | grep -E "Absolute|Width"
DISPLAY=:1 .venv/bin/python tools/click.py 1309 1032   # the microphone, at 900x96 centred
```
