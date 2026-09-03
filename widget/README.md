# jarvis-widget

JARVIS as a floating strip at the bottom of the screen. GTK4 on X11.

Design: `docs/superpowers/specs/2026-08-23-jarvis-widget-gtk4-design.md`

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

    DISPLAY=:0 \
    PYTHONNOUSERSITE=1 \
    PYTHONPATH=<repo> \
    .venv/bin/python -m jarvis_widget

`PYTHONPATH` is how the voice plugin's `tts.py` (CosyVoice) and Hermes' `markers.py`
are reached — the same mechanism `Hermes/run-gateway.sh` uses. Without
it she runs and is simply mute.

### Environment switches

| Variable | Effect |
|---|---|
| `JARVIS_WIDGET_STATE` | Freeze the wave in one state (`idle`, `listening`, `thinking`, `speaking`) and skip the voice loop. How each state gets photographed, since `xdotool` is not installed. |
| `JARVIS_WIDGET_NO_MIC=1` | Do not open the microphone. On a box with none plugged in, this is the difference between "she cannot hear" and "the process is broken". |
| `JARVIS_VAD_MODEL` | Path to `silero_vad_16k_op15.onnx` (default `~/.jarvis/models/`). |
| `JARVIS_WIDGET_FAKE_MIC` | Speak this INTO the widget: it is synthesised, resampled to 16 kHz and pushed through the real microphone path. Everything downstream — VAD, Whisper, the gateway, her reply — is real. |
| `JARVIS_WIDGET_SAY` | Say this once, three seconds after starting. The only way to hear her voice on a machine with no microphone. |
| `JARVIS_WIDGET_MIC_GATE=1` | Deafen the microphone while he speaks. **Not needed since 2026-08-26**: `echo.py` cuts his own words out of the transcript instead, so the microphone stays open and he can be interrupted. Keep it for a box where that filter is not enough. Off by default since 2026-08-25: it is what made interrupting him impossible, because `detector.speaking` had to be true before a frame could reach the detector, and only his own voice through the room could open that latch. Set it on a box with no echo cancellation, or he answers himself. |
| `JARVIS_WIDGET_DUMP` | Write every closed utterance to this directory as a WAV. When a transcription comes back as nonsense, nothing else tells you whether the audio was bad or the model was. |
| `JARVIS_WIDGET_PHOTO` | Show these photos (comma-separated paths) two seconds after starting, exactly as if the gateway had pushed them. The counterpart of `JARVIS_WIDGET_SAY` for the half of him you can see: the band, the click and the fade without needing a live turn. |
| `JARVIS_WIDGET_LIVE` | Feed the band this video file as if the gateway had pushed it. The counterpart of `JARVIS_WIDGET_PHOTO` for the half of him that moves — the decoder, the band and the input region, with no gateway and no camera. |
| `JARVIS_WIDGET_WAKE_WORD` | The name he answers to. `jarvis` by default; **empty turns the wake word off entirely**, which is how he behaved before 2026-08-26 — everything heard is for him. Matching is deliberately loose: Whisper renders it as "Carbis", "Harvish", "Jervis" and "Harvies", all measured, and an exact match would ignore four of five. |
| `JARVIS_WIDGET_STT_HINT` | What Whisper is told it has just heard, biasing what it hears next (`initial_prompt`). Defaults to his name plus the words this box says — git, Claude Code, commits, pytest. Set it to replace the sentence for a house that talks about other things; set it **empty** to turn the bias off. Measured 2026-08-27: without the vocabulary, «git» came back as «JIT», «JIP» and «Jeep», and two of three attempts to delegate a coding task died there. |
| `JARVIS_WIDGET_WAKE_WINDOW` | Seconds after he answers during which the next sentence needs no name (default 30). Each answer pushes it out; sentences inside it do not. |
| `JARVIS_WIDGET_BARGE_RMS` | How loud the room must be, while he is speaking, before a frame is looked at at all (default 0.01). Since 2026-09-01 this is a **silence floor and nothing else** — it separates sound from no sound, which any scalar can do. Whether a sound is a person or his own voice coming back is decided on WORDS, by `EchoFilter` against Vosk's live partial, and needs no calibration. It was 0.05 and was asked to make that distinction, which it cannot: with the speaker beside the microphone his echo measured 0.178, louder than the user's own voice at 0.054-0.088, and no value works — which is what «no se calla, sigue hablando» was. Raise it only if the room's own noise floor is above 0.01; `0` lets every frame through. |
| `JARVIS_WIDGET_TRACE_MIC=1` | Log what the microphone hears while HE is speaking. The instrument for the number above. |
| `JARVIS_WIDGET_SILENCE` | Seconds of quiet that end a turn (default 1.2). Lower cuts people off mid-sentence; higher makes him slower to answer. |
| `JARVIS_WIDGET_CONSOLE_LINGER` | Seconds the console stays up after the work finishes, before it puts itself away (default 60). A press on it closes it sooner; `0` makes it go the moment the run ends. |
| `JARVIS_WIDGET_CONSOLE_LINES` | How many lines the console keeps, and so how tall the strip gets while it is up (default 20 — about 430 px, the live camera's height). Ten until 2026-08-27, which was too short to read a tool's output in. |
| `JARVIS_WIDGET_SWITCHES` | Start with these switches already off: `mic`, `voice`, or both. Handy for photographing the struck-through glyphs; a press can also be sent for real with `tools/click.py`. |
| `JARVIS_WIDGET_VOSK_MODEL` | Where the Vosk model lives (default `~/.jarvis/models/vosk-model-small-es-0.42`). This is the second STT engine, and it never produces a word anybody reads — it decides when you have stopped talking and whether a sound is his own echo. **Absent, everything still works**: he falls back to waiting the full 1.2 s of silence, and the log says so once. |
| `JARVIS_WIDGET_ASK_SILENCE` | Seconds of quiet after which he asks himself whether your sentence is finished (default 0.35). The 1.2 s of `JARVIS_WIDGET_SILENCE` remains the floor: this only ever closes a turn EARLIER, never later. |
| `JARVIS_WIDGET_REMOTE_PORT` | Where the phone page listens (default 8443). The enrolment page is this plus one, over plain HTTP, because a certificate cannot be fetched over a connection that requires trusting it. |
| `JARVIS_WIDGET_REMOTE_NAME` | The name on the certificate (default `brain.local`; avahi is running, so mDNS resolves it). The certificate also carries the LAN IP, because client isolation breaks mDNS on some networks. |
| `JARVIS_WIDGET_REMOTE_HOST` | Override the LAN address if the routing-table guess is wrong. It is guessed by asking which source address would reach the outside, which never picks one of this box's twelve Docker bridges. |
| `JARVIS_WIDGET_ENROLMENT_SECONDS` | How long the enrolment page answers after `SIGUSR1` opens it (default 300). Not an arbitrary number: it is how long the shared secret sits readable, in cleartext, to anyone on the wifi with a browser — that page cannot ask for authentication, because it exists for the moment before a phone has any reason to trust this box. **A phone already enrolled never needs this window again**; it bounds only adding one. |
| `JARVIS_WIDGET_REMOTE_TOKEN` | Where the shared secret lives (default `~/.jarvis/remote.token`, 0600). Delete it to rotate; every phone then needs the link again. |
| `JARVIS_WIDGET_SHOW_QR=1` | Put the enrolment QR on the strip a few seconds after start. The QR itself is a plain LAN URL, no secret in it; what is short-lived is the enrolment WINDOW behind it (`remote.ENROLMENT_SECONDS`, 300 s), not the code on screen. `SIGUSR1` opens the same window with no flag and no restart — see the ritual below. |

### The models it needs

- **Silero VAD**: `~/.jarvis/models/silero_vad_16k_op15.onnx`, ~1.2 MB.
  Taken from the `silero-vad` wheel without installing it:
  `pip download silero-vad --no-deps` and unzip. The wheel ships four
  models; this is the 16 kHz one.
- **Whisper**: `large-v3-turbo`, downloaded automatically on first load
  (~1.5 GB, 81 s the first time, ~1 s after that). Needs the GPU: it
  sits at roughly 2.5 GB of VRAM alongside CosyVoice.
- **Vosk**: `vosk-model-small-es-0.42`, 39 MB, Apache 2.0. The
  endpointing model. Optional: without it he waits the full 1.2 s,
  exactly as he did before 2026-09-01.

      mkdir -p ~/.jarvis/models
      curl -sL -o /tmp/vosk-es.zip \
        https://alphacephei.com/vosk/models/vosk-model-small-es-0.42.zip
      unzip -q -d ~/.jarvis/models /tmp/vosk-es.zip

### Putting him on a phone

**It must be Safari.** Chrome (and every other browser on iOS — all of
them are WebKit underneath, by Apple's rule) downloads the enrolment
profile as a plain file with no install prompt, and nothing happens next.
Only Safari offers to install a configuration profile. This is the
mistake that costs the most time, so it goes first.

It is also **two separate installs, not one install plus a toggle** — in
the user's own words, after the first real attempt: *«había que hacer 2
pasos, instalar el perfil y luego el certificado.»* The profile is
installed first, from Settings; the certificate is trusted **separately**,
afterwards. Skipping the second step looks like it worked — the page
loads — right up until the microphone or the WebSocket needs the
connection actually trusted.

1. Point the phone's camera at the QR (`JARVIS_WIDGET_SHOW_QR=1` at
   start, or any time with
   `systemctl --user kill -s USR1 jarvis-widget.service` — no restart
   needed). **Open the link in Safari.**
2. **1 · Instalar el certificado** → Settings shows "Profile Downloaded"
   → Install. This installs the profile. It does not yet trust it.
3. Separately, find where this iOS version lets you trust an installed
   root certificate — look for **Certificate Trust Settings**, somewhere
   under Settings → General → About, or wherever your iOS puts it; the
   exact path has moved between versions and is not worth asserting here.
   Turn on **JARVIS Home CA**. iOS cannot be made to do this step from a
   profile — it is deliberately a human's decision.
4. **2 · Abrir JARVIS** → Share → Add to Home Screen.

**If it looks broken but the log shows it working, check the silent
switch.** A web page's audio obeys the iPhone's physical silent switch,
and Safari has its own volume on top of the system one — a native app
can override the switch, a page cannot. Muted and silent look identical
from across the room; the difference is a switch on the side of the
phone, not a bug.

Two minutes, once per phone. The certificate is issued for ten years.

## The cameras are not here any more

This program watched the house's cameras until 2026-08-24. It does not
now: `vision.py`, the camera thread and the `JARVIS_WIDGET_CAMERA`,
`JARVIS_WIDGET_CAMERA_RETRY` and `JARVIS_YOLO_MODEL` switches all
moved into the gateway, as the `jarvis-vision` plugin.

They went because the strip was the wrong owner. Watching has to survive
the widget being restarted, and a camera that sees somebody wants to
start a turn on its own — which is a thing the gateway can do and a
window on the desktop cannot.

Configuring them, the model file, and what the journal says when one is
off: **`Hermes/plugins/jarvis_vision/README.md`**. Nothing in this
directory needs to change to point a camera anywhere.

Running it from another directory — which is what systemd does — needs
the package actually installed, not merely present:

    .venv/bin/pip install -e .

Without it the service dies on every start with `No module named
jarvis_widget`, while running it by hand from this directory works
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
`Hermes/plugins/jarvis_vision/`; the strip is only ever handed a path
and opens it. To see all of this without a live turn — and without a
camera — point `JARVIS_WIDGET_PHOTO` at one or more image files.

## Test

    .venv/bin/python -m pytest -v
    .venv/bin/ruff check . && .venv/bin/ruff format --check .

## Verifying anything visual

Nothing about this program's appearance is provable from a test. Capture
the screen and look at it:

    ffmpeg -y -f x11grab -video_size 1920x1080 -i :0 -frames:v 1 /tmp/strip.png

## Cambiar la personalidad

`Hermes/jarvis-soul.md` es la identidad. Si la cambias y no notas nada:

    # por la tira, en este orden
    /new
    /approve

El prompt de sistema se fija cuando **nace la sesión**. Editar el
fichero, el `platform_hint` o la memoria no toca una sesión que ya
existe, y reiniciar el gateway tampoco: la sesión vive en `state.db` y
se reanuda tal cual. Hermes Desktop parece obedecer al instante sólo
porque abre una sesión propia.

### The four switches

At the right end of the strip, in the wave's own colour: his ears, his
voice, and the door.

| Glyph | Press |
|---|---|
| microphone | Stops listening. Frames are dropped rather than the stream closed — closing PortAudio from its own callback is the segfault §2.8 is written around. Press again to hear. |
| speaker | Stops him talking, at once, mid-sentence. He still listens. Clauses are dropped rather than queued, so unmuting never says a minute-old answer out loud. |
| line | Opens a line you type at him in. Enter sends and closes it, Escape closes it without sending. What it sends is a plain message — same session as the spoken path, minus the wake word and the echo filter. |
| cross | Closes him. **Two presses within three seconds** — the first arms it and the cross lights up. He comes back only with `systemctl --user start jarvis-widget`. |

To press one from a script — the strip has no keyboard shortcut and
`xdotool` is not installed here, but `libXtst` is:

```bash
DISPLAY=:0 xwininfo -name "JARVIS" | grep -E "Absolute|Width"
DISPLAY=:0 .venv/bin/python tools/click.py 1345 1032          # the typed line, at 900x96 centred
DISPLAY=:0 .venv/bin/python tools/type.py "hola" --enter      # and type into it
```
