# He gets a face — the 3D avatar, design

> **Status:** design, agreed with the user 2026-08-30. Rewritten the same
> evening after the spikes: two of its four original decisions did not
> survive contact with a screen, and the framing changed underneath all
> of them.
>
> **It reverses a hard rule of CLAUDE.md, at the user's decision.** §2.3
> and §3 say the project MUST NOT introduce "a browser / webview of any
> kind". This design embeds WebKitGTK. The reasoning is under "Why a
> webview" below. §2.3, §3 and §12 are updated when this ships, not
> before.

## The framing, which decides everything else

The user, closing the day: **"JARVIS no va a ser un producto comercial,
es para el hogar."**

That is not a footnote. The whole afternoon was spent measuring this
project against Unclaw — a commercial product built on Unreal Engine by
a computer-graphics studio — and the answer to "why can't we look like
that" is that they did not build a face renderer, they assembled Epic's,
and their founder does that for a living.

So the bar is not "does it match Unclaw". The bar is **"do I like having
it there"**, in one house, for one person. Everything below follows from
that, and it is why the expensive half of the problem is deliberately
not attempted.

## What is being built

A 3D character above the strip, always on screen, cut out on the desktop
with no box around it, whose mouth follows what JARVIS actually says.

Four decisions, and two of them changed today:

1. **It reacts live** — not pre-rendered loops. (Unchanged.)
2. **It is always there** — not something that rises for a turn.
   (Unchanged. This is the expensive one; see "What always-on costs".)
3. ~~**VRM**~~ → **glTF with ARKit blendshapes.** VRM was chosen for its
   normalised rig and its visemes, and rejected on sight: **the VRM
   ecosystem is overwhelmingly anime**, and the user's verdict on the
   reference model was "infantil, desechar esa opción". The format that
   keeps what VRM was chosen FOR without the house style is a plain glTF
   carrying the 52 ARKit blendshapes — Ready Player Me's avatars carry
   those **plus the Oculus visemes**, measured below.
4. **The avatar and a photo share the band** — the avatar shrinks to one
   side rather than disappearing while he shows you something.
   (Unchanged.)

## What was proven on screen, 2026-08-30

Not argued — run, on this machine, and looked at:

| | measured |
|---|---|
| WebKitGTK 6.0 for GTK4 | **already installed** (`libwebkitgtk-6.0-4` 2.52.3). No new system package. |
| WebGL2 inside it | available |
| Transparent WebView | works — the character is cut out, desktop visible through it |
| glTF with ARKit blendshapes | `half-body.glb` from `readyplayerme/visage`: **72 morph targets** — the 52 ARKit ones **plus Oculus visemes** (`viseme_PP`, `viseme_FF`, …) |
| Placement above the strip | (510, 600) 900×384, by the project's own `ewmh.py` |
| **VRAM cost of the render** | **~50 MiB** |

That last number is the one that reorders the priorities: **the render was
never the VRAM problem.** The expensive piece is whatever drives the face.

**The transparency trap, because it cost a measurement:**
`WebView.set_background_color(rgba(0,0,0,0))` alone is NOT enough. The
GTK window paints its own theme background behind it and the result is
an opaque grey block that looks exactly like a webview that cannot do
alpha. The CSS `theme.py` already applies to the strip has to cover the
window and the webview too.

## Why a webview, against the spec that forbids one

**There is no VRM — or glTF character — renderer for Python.** Measured
against PyPI: `vrm-loader` does not exist, `pygltflib` parses and draws
nothing, and `pyrender`/`panda3d`/`pyglet` each want to own a window and
cannot live inside a `Gtk.GLArea`.

So the question was never "webview or not", it was **who writes the
renderer**. Writing one ourselves means glTF parsing, GPU skinning, morph
targets and a skin shader in GLES — and that is before the parts that
make a character look alive.

**§12 had already left this door open**, on 2026-08-23, in the entry that
rejected Electron: it names "an embedded WebKitGTK for the visual half
with Python still owning the audio" as the cheaper path if the visualiser
outgrew GSK.

**And the argument that killed Electron does not carry.** That decision
turned on ONE process: Silero, Whisper, CosyVoice and playback share a
Python process, and Electron would have split the audio across an IPC. A
WebView is a GTK **widget inside the same program**. The audio does not
move.

**What the reversal costs, stated rather than discovered:** a browser
engine is part of the running system, with its own memory, update cadence
and attack surface, on a box whose §1.1 promise is that nothing said in
the room leaves it. The page is local and must load nothing over the
network — a property to enforce and test, not assume.

## The face, and the decision that replaced NVIDIA

The original design put NVIDIA's **Audio2Face-3D** here. It was measured
and then beaten:

| | NVIDIA Audio2Face-3D | **`unreal-audio2lipsync`** |
|---|---|---|
| Licence | Apache 2 samples; models under NVIDIA Open Model Licence; **NGC account required** | **MIT — code AND pre-trained weights** |
| Weights | container from NGC | `best.pt`, **43.7 MB**, on Hugging Face |
| VRAM | **~2.2 GB** (1 stream, fp16, RTX 4090 profile) | ~1.3–1.5 GB est. (HuBERT-Large + Transformer), **CPU fallback** |
| Delivery | Docker + gRPC | FastAPI sidecar |
| Output | ARKit blendshapes | ARKit blendshapes **+ the processed audio back** |

Both speak the same language as the model — 52 ARKit channels — so the
chain is a straight line. `unreal-audio2lipsync` wins on every axis that
matters here: smaller, MIT, no account, and it runs on the CPU if the GPU
is busy. Its README is explicit: *"Code and pre-trained weights: MIT — use
commercially, modify, redistribute."*

**Its Unreal half is not needed.** The repo ships a UE5 C++ plugin that
consumes the curves over LiveLink; our avatar already consumes ARKit
directly. We take the Python sidecar and ignore the rest.

**One property to design around, and it is not a detail:** it returns
curves for a **clip**, not a stream — audio in, curves plus the processed
audio out, deliberately together so there is no sync drift. JARVIS speaks
**clause by clause** (§2.8), so each clause becomes one inference. That
adds latency per clause, and §1.4 says latency wins. **The plan must
measure it before committing**, and the fallback is already built: the
`SpectrumAnalyser` written this morning drives the mouth from the voice's
own bands — cruder, free, and already in the process.

**`unreal-text2face`, the same author's upper-face model (brows, eyes,
head), is NOT available:** no published weights, and training needs the
Express4D dataset, which is behind a Google form. It is a nice-to-have,
not the mouth.

## What is deliberately not attempted

**Unreal-grade skin, hair and eyes.** Subsurface scattering, strand hair
and refractive eyes are engine features. Unclaw has them because it IS an
Unreal application, with Pixel Streaming and 15 GB of disk behind it.
Building that for one living room is out of proportion, and the user's
verdict after seeing both is the whole of the argument: **"la diferencia
es el motor."**

What today established is that the **performance** is separable from the
**render** — and the performance is the half available under MIT.

## Architecture

```
┌─ one Python process, GTK4 main loop ─────────────────────────┐
│  strip window, permanently 900x480                           │
│  ┌────────────────────────────────────────────────────────┐  │
│  │ band, 384 px                                           │  │
│  │  ┌──────────────────┐  ┌───────────────────────────┐   │  │
│  │  │ WebKit.WebView   │  │ PhotoArea                 │   │  │
│  │  │ transparent      │  │ (only while a photo or a  │   │  │
│  │  │ three.js + glTF  │  │  live view is up)         │   │  │
│  │  └──────────────────┘  └───────────────────────────┘   │  │
│  ├────────────────────────────────────────────────────────┤  │
│  │ wave 96 px: equaliser + the four switches (unchanged)  │  │
│  └────────────────────────────────────────────────────────┘  │
│  Silero · Whisper · CosyVoice · gateway — none of it moves   │
└──────────────────────────────────────────────────────────────┘
        │
        └── audio2lipsync sidecar (FastAPI), like CosyVoice already is
```

### The bridge, in two directions and both thin

**Python → page**, by `evaluate_javascript`:

- the turn's state (`idle` / `listening` / `thinking` / `speaking`);
- while he speaks, **the ARKit curves for the clause being played** —
  from the sidecar, or from `SpectrumAnalyser` if the sidecar's latency
  fails its measurement.

**Page → Python**: a "loaded"/"failed" signal and the avatar's bounding
box for the input region. Nothing else.

### The input region

An always-on 900×480 window swallows every pointer event over that
rectangle unless told otherwise, and `window.py::_update_input_region`
already narrows it for a live view through `XShapeCombineRectangles`.
The avatar joins that path.

**The box first, the mask only if measured to be needed.**
`XShapeCombineMask` — following the alpha pixel by pixel, already bound
in `ewmh.py` and never used — is better and costs pulling a mask out of
the webview every frame.

## What always-on costs

**§1.5 is dented, and the user chose it knowingly.** "No window to focus,
nothing to click" described a 96-pixel strip.

**The band was built to be transitory.** `photo.py` has `FADE_S = 15` and
the live view a 120 s ceiling, and both return the window to 96 px. The
avatar needs a mode that sets a permanent floor and never expires.

**Sharing the band.** Two things the plan must answer: what happens with
a batch of four camera thumbnails (`MAX_PHOTOS = 4`), and whether the
avatar's minimum size leaves the picture worth looking at.

**GPU.** The render measured ~50 MiB. The sidecar is the cost, and it has
a CPU fallback. Neither is the 15 GB the LLM holds — which is the real
budget conversation, and a separate one.

## Assets and dependencies

- **No new Python packages** for the widget. WebKit is a system package
  already installed.
- **`three.js` vendored into the repo**, not from a CDN: §1.1 says nothing
  here should need the network. **The dependency chain is not obvious and
  each link only appears when it fails** — measured today, in this order:
  `build/three.module.js` is NOT the bundle (it imports `three.core.js`);
  `GLTFLoader` needs the `jsm/loaders/` + `jsm/utils/` directory layout;
  a KTX2-textured model additionally needs `KTX2Loader`, `WorkerPool`,
  `basis_transcoder` (.js and .wasm), `ktx-parse`, `zstddec` and
  `ColorSpaces`; and a meshopt-compressed one needs `MeshoptDecoder`.
  **Prefer a model that needs none of them** — the Ready Player Me
  avatar uses neither.
- **One new directory, `widget/samantha_widget/avatar/`** — inside the
  package that exists, not a new top level (§3).
- **The `.glb` lives in `~/.samantha/avatar/`**, out of git.
- **The sidecar gets its own venv**, like the code bridge did: torch is
  not going anywhere near the widget's environment.

## Traps to carry into the plan

Every one of these cost a round today:

- **The bounding box is useless for framing a half-body avatar.** Measured:
  1.647 wide against 0.470 tall — the arms dominate it. Frame from the
  **`Head` bone**, which is stable across Ready Player Me avatars, and
  measure the camera distance against the **face plane** (`box.max.z`),
  not the box centre in z. Against the centre the camera lands a third
  too close and cuts the chin off.
- **WebKit caches the page** even when the file changes. Append a
  cache-busting parameter or you are looking at the previous version.
- **`Gtk.Application(application_id=…)`** with a stale instance alive
  forwards over D-Bus and **exits 0 with no output**. For a throwaway
  window, no id.
- **ES modules do not load from `file://`** — opaque origin, CORS. The
  page needs a real origin: a loopback server, or WebKit's own
  `register_uri_scheme`, which is the production answer.

## Testing and verification

**Nothing about the appearance is provable by a test** (§2.3), and the
instrument is `ffmpeg -f x11grab` plus `xwininfo -name "JARVIS"`. The
display is `:0` (fixed 2026-08-30, commit 5c259e2).

**And the harness cannot show the user a picture.** Claude Code's
terminal does not render images: a screenshot in a reply is seen by
nobody. Anything visual has to end up **on the user's screen** — a live
window — or in their browser. Half a session was lost to this.

What IS testable in pure Python:

- the bridge's payload: turn state and curves in, JS call out;
- the input-region arithmetic;
- the band's split geometry: avatar plus one photo, avatar plus four,
  avatar alone;
- that the page requests **nothing over the network** — asserted, since
  it is a §1.1 property.

## Out of scope, deliberately

- Unreal-grade rendering (see "What is deliberately not attempted").
- `unreal-text2face` upper-face performance, until its weights exist.
- Choosing the character. Any glTF with ARKit blendshapes while the
  plumbing is built.
- Gaze that follows the user.
- Replacing the wave. The equaliser and the four switches stay.
