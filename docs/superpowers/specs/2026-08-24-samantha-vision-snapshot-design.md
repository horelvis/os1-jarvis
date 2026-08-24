# samantha-vision: the photo on demand

> **Status:** shipped 2026-08-25, and running. It was written as a design
> with nothing built, and that header is kept below the line; what is
> here now describes live code, with two overrides taken during
> execution. **The tool lives in a toolset called `camaras`, not
> `vision`** — §4.3 defers to the plugin spec's §6.2, which said
> `vision`, and that name is Hermes' own, carrying `vision_analyze`, an
> image tool this text-only box cannot serve. **The no-answer sentence
> lost the word "cámara"** — our own string had handed him a word
> CLAUDE.md §1 forbids him to say. CLAUDE.md §12 (2026-08-25, two
> entries) and PROGRESS.md carry what it cost.
>
> Its predecessor, `2026-08-24-samantha-vision-plugin-design.md`, shipped
> on 2026-08-24 and IS running; where this file refers to the watcher,
> the cameras or the alert, it is describing live code.

## 1. Goal

You ask — "enséñame la entrada" — and the photo appears above the strip
for a few seconds. That is the whole feature.

Two things it is deliberately **not**:

- **Not video.** A still, taken when asked. Live streaming was considered
  and dropped: it costs a second decoder, continuous bandwidth, and a
  window that no longer goes away.
- **Not "what do you see?"** The LLM is text-only — Qwen3.8-27B does not
  look at images. He can *show* you the entrance and he can *tell* you
  somebody is there, because YOLO gives him eight labels. He cannot tell
  you the person is wearing a red jacket. A VLM would fix that and does
  not fit in VRAM (see §2).

## 2. What was decided, and by whom

Every one of these is a human decision taken during brainstorming on
2026-08-24. They are recorded with their reasons because each one closed
off a cheaper or more obvious path.

| Decision | Made by | Why the alternative lost |
|---|---|---|
| A still on demand, not live video | user | Bandwidth, a second decoder, and a window that stays |
| The plugin produces the frame | user | It already decodes for YOLO; the JPEG is an encode away |
| Photo on the strip; alerts away arrive as **text only** | user | See §3 — this is the decision the architecture rests on |
| The photo appears **over** the strip, not in a notification or a window | user | A GNOME notification was cheaper; a window contradicts §1.5 |
| Thumbnail by default, native size on click | user | 320×180 keeps the strip a strip; 640×360 answers "who is it?" |
| It fades on its own | user | Nothing to close, no state that can hang |
| **Frigate is not integrated** | user | "Lo paré porque consumía demasiado" — measured, not preference |

**On Frigate, because it will be asked again.** BarnDoor's Frigate
already does snapshots, clips, zones and 30 days of event history over
HTTP, and its UI is a camera grid. It is the better answer to the
*history* question (`revisar`, §6.3 of the plugin spec). It is not
available: measured 2026-08-24, VRAM sat at 20,951 of 24,564 MiB
(llama-server 15.3 GB, CosyVoice 5.3 GB), leaving ~1 GB once Whisper
loads. Our YOLO runs on **CPU** and costs zero VRAM; Frigate's uses ONNX
on the GPU plus `preset-nvidia` decoding. The user had already stopped it
for that reason.

## 3. The decision the architecture rests on

The photo reaches the strip and **nothing else**.

The first design routed it through Hermes' `MEDIA:` convention — a tool
result containing `MEDIA:/path.jpg` is turned into an attachment by any
platform adapter that implements it (telegram, discord, slack, whatsapp
and others in this pinned Hermes do). That was elegant: one mechanism,
both surfaces.

It was rejected once the user chose text-only for the away path, and the
reason generalises. `MEDIA:` is a *platform* convention: its purpose is
that any adapter can render it. A tool that emits it has no say in where
the turn is delivered, so a photo of the inside of the house would leave
the machine on any turn that happened to be routed to Telegram. The
property "images never leave this box" would then be a configuration
accident rather than a fact.

So:

- **The model's answer is words.** "En la entrada hay alguien." It goes
  wherever the turn goes — the strip at home, Telegram when away. Text,
  always. There is nothing visual in it to leak.
- **The photo travels on a separate channel**, from the plugin to the
  strip, over the loopback WebSocket those two processes already share.
  No adapter other than the kiosk ever sees it.

The privacy property becomes **structural rather than conventional**:
not "we configured the platforms correctly" but "there is no path by
which an image reaches a third party". This mirrors the guarantee that
makes CLAUDE.md §1's "he is told, not made to recite" hold — Hermes'
injection API only accepts a user message, so reciting is not something
we avoid, it is something the API cannot express.

**Cost, accepted explicitly:** the strip and Telegram no longer share a
mechanism. Two paths to maintain instead of one. That separation *is*
the feature, not an accident of it.

### 3.1 The alert never shows a photo

Worth stating because it surprises people: when a camera notices somebody
and he mentions it unprompted, **no photo appears** — not on the strip,
not anywhere. The photo is a side effect of the `mirar` handler, and an
alert does not call `mirar`.

That follows from the user's split (alert -> text, wherever you are; ask
-> photo, on the strip) and it is the conservative reading: an alert
arrives unbidden, and an image that appears unbidden over whatever you
were doing is a different and larger thing than one you asked for. If it
turns out you want the photo with the alert too, the mechanism is already
there — the handler's side effect becomes a call the alert path makes as
well — but that is a decision, not an oversight.

## 4. Components

Five pieces. The boundary that matters: **`snapshot` and the tool know
nothing about the strip, and the strip knows nothing about cameras.**
A filesystem path is the only thing that crosses.

### 4.1 `CameraFleet.grab(camera, timeout=2.0) -> ndarray | None`

The watcher thread already has that camera's stream open and is sampling
one frame in ten. `grab` asks it for the **next** decoded frame.

- **It does not open a second connection.** Some cameras cap concurrent
  RTSP sessions, and you discover that limit as intermittent failure
  under load — the worst way to discover anything.
- Implementation: a per-camera slot plus a `threading.Event`. The watcher
  fills the slot only when something is waiting, so the cost when nobody
  asks is one `is_set()` per sampled frame.
- Returns `None` after `timeout`. Two seconds, from §6.2 of the plugin
  spec: a question that hangs is worse than one answered honestly,
  because he simply goes quiet.
- **It never falls back to the last analysed frame.** That frame can be
  40 seconds old, and presenting it as "ahora" is the same class of
  untruth this project spent 2026-08-24 removing from its own docs.

### 4.2 `snapshot.py`

Array in, JPEG on disk out, plus pruning. Testable with a synthetic
array and no camera.

- **Pillow does the encoding.** Measured: PIL 12.3.0 is already in the
  gateway venv. But it is there because Hermes brought it, not because we
  declare it — precisely the fresh-box trap fixed earlier today. So
  `pillow` joins the four requirements already in the plugin manifest and
  in `setup-runtime.sh`'s `PLUGIN_DEPS`.
- **Where:** `$HERMES_HOME/cache/images/vision/`, mode `0700`. Hermes
  already designates `cache/images` for generated media, and a dedicated
  subdirectory keeps pruning unambiguous.
- **Pruning:** by age and by count, on write. This directory holds
  pictures of the inside and outside of the house; an unbounded one is a
  slow privacy leak as much as a disk leak, and the manifest should say
  so among its silent failures.

### 4.3 `tool.py` — the `mirar` tool

Registers the tool per §6.2 of the plugin spec, with one change: the
return value is a sentence **and nothing else**. No `MEDIA:` line, for
the reason in §3.

- Omitting the camera means all of them, as §6.2 decided: "¿hay alguien?"
  should not force him to pick one, and picking wrong is worse than
  looking twice.
- `check_fn` keeps the tool out of the model's list when no camera is
  configured, so he is never offered something that cannot work.
- Sending the photo to the strip is a **side effect** of the handler, not
  part of its return value. The handler asks the kiosk adapter to show
  it; the answer he speaks is independent of whether that succeeded.

### 4.4 `samantha_kiosk` — the contract change

Approved by the user on 2026-08-24. The protocol gains one
server-to-client frame:

```json
{"type": "photo", "path": "/…/entrada-1756060000.jpg", "camera": "entrada"}
```

- `decode_client` is untouched: this is server-to-client only.
- The adapter exposes a way for another plugin to push one. The path is
  validated to live under the snapshot directory before it is sent — the
  strip must never be handed an arbitrary path to open.
- A strip that is not connected is not an error. The frame is dropped and
  the spoken answer is unaffected.

### 4.5 `photo.py` in the widget

Owns the texture, the thumbnail, the click and the timer. The window
grows and shrinks by calling the `ewmh.move_resize` that already places
the strip — reusing the placement code that works rather than opening a
second window that would need its own EWMH dance.

- **Thumbnail 320×180**, the strip growing from 900×96 to 900×210.
- **Click enlarges to 640×360** (900×480) and **resets the fade timer**.
- A second click dismisses.
- **Click, not voice, and the reason is physical:** the microphone is
  gated while he speaks (§2.8, or he hears himself). The photo appears
  *while* he is answering, which is exactly when a spoken "amplíala"
  cannot be heard.
- **"Déjala" and "otra vez" need no mechanism.** Clicking resets the
  timer, which is what "déjala" means. "Otra vez" is another `mirar`
  call, which returns a *fresh* photo — better than re-showing a stale
  one. Two intents, no new state.

## 5. Failure

| What | What he does |
|---|---|
| Camera does not answer in 2 s | Says so. Never substitutes an older frame. |
| Unknown camera name | Names the ones that exist. |
| No cameras configured | `check_fn` hides the tool entirely. |
| JPEG write fails | The sentence still goes out, without a photo. |
| Strip not running | The `photo` frame is dropped; the answer is unaffected. |
| Two cameras asked for at once | Two frames, sent in order; the strip lays thumbnails left to right and grows once. |

Nothing in this feature may let an exception reach the gateway. That
constraint is inherited and it is not weaker here: the gateway is the
brain, and it now owns the cameras.

## 6. Testing

Everything that decides anything is tested without hardware:

- `snapshot.py` with a synthetic array — encode, prune, permissions.
- The `photo` frame's encode/decode and the path validation, with strings.
- The fade timer and the click transitions with an injected clock.
- `grab`'s timeout and its "never substitutes an older frame" rule with a
  fake stream.
- **That a filesystem path never reaches the spoken text.** This is a
  test, not a care. The failure it guards against — CosyVoice reading a
  path aloud — already happened once in this project, with the reminders'
  scaffolding.

The only thing needing a real camera is that `grab` returns a real frame,
proved the way the plugin was proved on 2026-08-24: with a clip built
from BarnDoor's stored snapshots.

## 7. Out of scope

- **Live video.** §1.
- **The detections table and `revisar`.** They are §6.3 of the plugin
  spec and remain plan 2. This feature answers "what is there now", not
  "who came this morning".
- **A camera grid.** BarnDoor's UI is a panel of four; CLAUDE.md §1.5 is
  explicit that JARVIS is not one.
- **Faces, identity, recording.** Out by design, not omission.
- **Anything that makes the LLM see.** §1.

## 8. Decision-log entries owed

Two, for CLAUDE.md §12:

1. **The photo reaches the strip and nothing else**, and why `MEDIA:`
   was rejected despite fitting — with §3's argument that a privacy
   property held by convention is not held at all.
2. **The kiosk protocol gains a server-to-client `photo` frame** — the
   first change to that contract since it was written, and the reason
   the strip needed one when no other platform did.
