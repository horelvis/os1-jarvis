# samantha-vision: the camera, live

> **Status:** design, nothing built. Written 2026-08-25 from a
> brainstorming session whose decisions are logged in §11.
>
> Its predecessors are running code: `2026-08-24-samantha-vision-plugin-design.md`
> (the watcher, the cameras, the alert) and
> `2026-08-24-samantha-vision-snapshot-design.md` (`mirar`, the photo,
> the band). Where this file refers to the tap, `grab()`, the band or the
> strip's channel, it is describing live code and says so.

## 1. Goal

You say "Jarvis, muéstrame la cámara de la entrada" and the entrance
appears **moving** above the strip, and stays there until you tell him
to put it away.

That is the whole feature. One camera, in motion, on demand, gone when
asked.

## 2. What it is not

- **Not a second surface.** It lives in the band that `mirar` already
  grows — 900×480, along the bottom edge. Not full screen, not a window
  with a title, nothing to alt-tab to.
- **Not recorded.** A live view leaves no file, no snapshot in the
  spool, no row anywhere. What you saw, you saw.
- **Not audio.** Only the video substream is demuxed. If a camera
  carries an audio track it is ignored in the gateway and never reaches
  the strip. Nothing to synchronise, and his voice never competes with
  the noise of the porch.
- **Not two cameras at once.** One live view at a time. The strip's
  channel holds one connection and the band is one band; two
  simultaneous views would multiply the state for something nobody
  asked for.
- **Not unprompted.** Same rule as the photo (CLAUDE.md §12,
  2026-08-25): an image that appears over whatever you were doing,
  unbidden, is a larger thing than one you asked for. A sighting never
  opens a live view.

## 3. The cost, measured — and why §4 no longer says no

CLAUDE.md §4 records that live video was considered and dropped: "a
second decoder, continuous bandwidth, and a window that stays". Two
thirds of that objection are already false, and the measurement is in
the code rather than in a benchmark:

`CameraStream.frames()` (`vision.py:226-240`) calls
`self._container.decode(video=0)`. **libav decodes every frame**; the
`SAMPLE_EVERY = 10` sampling only chooses which decoded frames are
converted to an ndarray and shown to YOLO (`cameras.py:182-185`). The
RTSP connection is open permanently, per camera, and every frame that
arrives is already decoded, right now, all day.

So a live view adds:

- **no second decoder** — the packets are the ones the watcher is
  already receiving;
- **no additional bandwidth from the camera** — one connection, as
  today;
- **no additional CPU in the gateway** — it already decodes; it will
  now also hand the raw packet to a callback, which costs a reference
  copy;
- **new: moving the bytes over loopback and decoding them in the
  widget**, plus painting.

The third of the objection that stands is "a window that stays", and §7
is about exactly that.

**One product consequence, stated because it will otherwise surprise
someone:** the plugin reads the camera's **substream** by convention
(`vision.py:176-181`). The live view is that image in motion — the same
quality as the snapshots `mirar` produces, not 1080p.

## 4. The wire: the strip's channel

The channel is the WebSocket on `:7777` that already carries his tokens,
the `done` and the `photo` frame — `Hermes/plugins/samantha_kiosk/`, a
module whose name is a fossil of the Chromium kiosk (CLAUDE.md §10). In
prose it is the strip's channel.

Today `photo` carries a **path** and the widget opens the file
(`protocol.py:photo`, `adapter.py:449-481`). Video cannot: there is no
file, and writing twenty files a second to name them would be absurd.

Three additions, **server to client only**. `decode_client` is untouched
for the second time.

### 4.1 `live` — open

```json
{"type": "live", "camera": "entrada", "epoch": 7, "codec": "h264",
 "extradata": "<base64>", "width": 704, "height": 480}
```

`extradata` is the codec's parameter sets (SPS/PPS), read from
`container.streams.video[0].codec_context.extradata`. It travels here
because a decoder cannot start without it; sending packets alone is how
a restream ends up as a black rectangle that looks like a bug in the
drawing code.

### 4.2 `live_end` — close

```json
{"type": "live_end", "epoch": 7, "reason": "asked"}
```

`reason` is one of `asked`, `timeout` and `lost`. The strip uses it to
decide whether to shrink in silence.

There is deliberately no reason for "the gateway stopped": a process on
its way down cannot promise to send anything, so the strip must treat a
**socket that closes with a view open** as a close in its own right.
Designing a frame for it would invite trusting a message that may never
arrive.

### 4.3 Binary frames — the video

One WebSocket **binary** message per access unit. Four bytes of header,
big-endian, carrying the `epoch`; the rest is the H.264 packet exactly
as it arrived from the camera.

**The epoch exists because closing and the packets in flight race.** You
say "ya está", the gateway closes, and three frames of the previous view
are still on the socket. Without a number to stamp them, the strip
paints them onto a band that has already shrunk. Four bytes settle it
with no shared state.

**Nothing is sent before a keyframe.** H.264 can only be entered there.

**The trust boundary moves, and shrinks.** `push_photo` validates the
path against the snapshot directory because the socket is an
unauthenticated local listener and the strip opens whatever it is handed
(`adapter.py:461-481`). Bytes need no path validation — there is no path
— so the guard becomes a **size cap per binary frame**, in the same
spirit as `_MAX_MESSAGE_CHARS` (`protocol.py:19-25`).

### 4.4 The change this forces in the strip

`gateway.py:105` is `def _dispatch(self, raw: str)` and calls
`json.loads`. With the `websockets` library, `async for raw in ws`
yields `str` for text frames and `bytes` for binary ones — and
`json.loads` accepts bytes, so today a binary frame would fail as "not
an object" and be dropped by the branch that deliberately ignores
unknown types (`gateway.py:51-58`). **Branch on the type before
parsing.** That silent-drop rule stays: it is what lets the gateway and
the widget be versioned separately.

## 5. The plugin

### 5.1 The tap

`CameraStream.frames()` becomes a demux loop instead of a decode loop:

```python
for packet in self._container.demux(video=0):
    if tap is not None:
        tap(bytes(packet), packet.is_keyframe)
    for frame in packet.decode():
        ...                       # exactly what it does today
```

`tap` arrives as an injected callable, the same shape as
`make_detector`, `open_stream` and `on_detections` — so the whole loop
runs in a test with no camera, no GPU and no gateway in the room
(`cameras.py:196-200`). When nobody is watching it costs one `is None`
comparison per packet.

`_offer()` and `grab()` are untouched: `mirar` keeps working exactly as
it does.

### 5.2 The session

One small object: which camera, which epoch, when it started, where to
push. Born with the order, dead with the opposite order, the ceiling,
the camera falling over or the strip disconnecting. Its epoch increments
on every open and never repeats within a gateway lifetime.

### 5.3 The two spoken orders

Two tools in the existing `camaras` toolset, in Spanish, beside `mirar`:

| tool | what it does |
|---|---|
| `ver_en_vivo` | opens the live view on one camera |
| `dejar_de_ver` | closes it |

**The measured trap.** The snapshot spec records that he calls `mirar`
with **no camera 5 times out of 5**, even when one was named. With
`mirar` that is cheap — it surveys all of them. With video there is no
"all": there is one view. So `ver_en_vivo` with no camera does not
guess. One camera alive → use it. Several → **ask which**, in one line.
That is the honest answer and it avoids opening the entrance when you
said the garage.

**The descriptions must draw the line between `mirar` and
`ver_en_vivo`,** because the words are close enough for a model to
confuse: `mirar` is a photo of right now; `ver_en_vivo` is the camera
in motion until told to stop.

### 5.4 The ceiling

**Two minutes**, then `live_end` with `reason: "timeout"`.

It exists because closing depends on him hearing you, and this box still
has no microphone plugged in (CLAUDE.md §4). Without a ceiling, one
misheard sentence leaves a decoder feeding a window all night.

## 6. The widget

### 6.1 Decoding off the main loop

Packets arrive on the asyncio thread. Decoding there — or worse, on the
GTK main loop — would stutter the wave, which is drawn on the frame
clock. So: a bounded queue, **one decoder thread** using PyAV (already
in the venv, 18.1.0, it arrived with faster-whisper), and a
**single-slot mailbox** holding the newest decoded frame.

On each tick the GTK side takes whatever is in the mailbox, wraps it in
`Gdk.MemoryTexture` — which does not copy — and paints it with
`append_texture`, the same call the photo band already makes
(`photo_area.py:161-176`). The texture is created on the main thread;
the decoder thread only ever produces plain buffers.

### 6.2 Drop late, never early

If the decoder falls behind, the tempting fix is to drop packets. It is
wrong: an H.264 frame depends on the ones before it, so dropping
packets yields broken pictures, not old ones. Dropping happens **after**
decoding — which is what the single-slot mailbox does, keeping the
newest and discarding the rest.

If the *packet* queue grows past roughly four seconds, nothing
accumulates: the view closes and says so. Video that falls further and
further behind is worse than video that stops.

### 6.3 The band

The pure model that already exists (`photo.py`) knows how tall the strip
must be and until when; live is one more state beside it, with its own
GTK-free module so it can be tested without a screen.

Unlike a photo it **does not start as a thumbnail**: a 114-pixel
thumbnail of video is useless, so it opens directly at the large size —
the 900×480 window, at 510,600, that the snapshot work already measured.

### 6.4 The input region — §12's deferred fix, now taken

CLAUDE.md §12 (2026-08-25) deferred this deliberately: the band is as
wide as the strip and mostly transparent, so while something is up it
**swallows pointer events** over that much desktop. For a photo that is
fifteen seconds and the risk of the fix exceeded the harm. For video it
is two minutes, and it no longer is.

The fix is `XShapeCombineRectangles` through the ctypes handle, setting
the window's input region to the video rectangle only:
`Gdk.Surface.set_input_region` wants a `cairo.Region`, and Cairo is the
trap this machine is built around (CLAUDE.md §2.3).

**It is a new X mechanism in the file whose EWMH work cost this project
days**, so it is its own task, with its own verification by screen
capture, and it must not be entangled with the decoding work.

With the region in place the video rectangle **does** receive clicks, so
a click on it closes the view. That adds no new order, and it gives a
way out by hand on the day he does not hear you — which, on a box with
no microphone, is not hypothetical.

### 6.5 What does not change

The strip keeps listening while the video is up; that is the condition
for being able to say "ya está". The microphone gate while he speaks is
unrelated and untouched.

## 7. Closing, and things falling over

**One way out.** Closing is a function that takes a reason, and
everything arrives there: the spoken order, the click, the ceiling, and
the three failures below. Two ways to close become two states that
contradict each other.

**Closing twice is not an error.** You say "ya está" in the same second
the ceiling fires; the second call finds no session and stays quiet. The
epoch does the same job on the strip's side.

**A camera that falls over does not come back on its own.** The watcher
already retries with its 30 s → 5 min backoff, and a reopened stream may
carry different codec parameters. The view could re-attach itself —
and deliberately does not: a video window reappearing on your desktop
unasked is precisely what §12 avoided when it decided the unprompted
alert carries no photo. Close with `lost`, and he says it in one line.

**The strip disconnecting** kills the session with the socket; when it
comes back there is no view. And the other way round: asking for a live
view **while the strip is not connected does not open an invisible
session** — he says he cannot. This is the one place where live differs
from the photo, where an absent strip costs only the picture and the
spoken sentence stays true. Here the sentence would be a lie.

**The gateway stopping** releases the tap with the daemon threads, and
the strip sees only a socket that closed — which §4.2 makes a close in
its own right, precisely because no frame can be promised there. **A
decoder failure in the strip** — a broken packet, something that is not
H.264 — closes and says so, rather than leaving a black band up, which
is the failure that looks like success.

## 8. What he says

Never the codec, never the socket, never the word "sesión". One short
line, in his voice (CLAUDE.md §1: he uses tools, he never performs using
them):

| when | roughly |
|---|---|
| opening | "Ahí la tiene, señor." |
| ceiling fired | "La quito, señor." |
| camera lost | "La entrada ha dejado de dar imagen, señor." |
| strip not connected | he says he cannot show it now |

Exact wording is `docs/personality.md`'s business, not this file's. The
constraint that **is** this file's: the camera name is handed to him as
a labelled value, never inside a preposition — CLAUDE.md §12
(2026-08-24) records a camera named `fuera` becoming "alguien en la
entrada" twice on the live gateway, because a model handed broken
Spanish repairs it by inventing a place that fits.

## 9. Testing

### 9.1 What a test can prove

- **The tap:** a fake stream yielding invented packets. The tap receives
  the bytes and the keyframe flag; **nothing leaves before the first
  keyframe**; with nobody watching it costs one comparison.
- **The session:** open/close idempotent, epoch advances, ceiling fires,
  a lost camera closes with its reason.
- **The orders:** no camera named and one alive → uses it; several →
  asks; a name that does not exist → behaves as `_resolve` already does
  (`tool.py:85-101`).
- **The wire:** `live` / `live_end` round-trip, the four-byte epoch
  header, the size cap, and — the important one — that the strip
  **branches on type before parsing** and still drops unknown types in
  silence.
- **The strip's pure half:** how tall the window must be and when, that
  the mailbox always keeps the newest frame, and that a packet queue
  past its bound closes rather than accumulates.

### 9.2 What only eyes can prove

Nothing about his appearance is provable from a test (CLAUDE.md §2.3).

- **That it moves:** two `ffmpeg -f x11grab` captures a second apart
  **must differ**. That is the honest proof of "live" as opposed to "a
  still someone left there".
- **That it is the strip:** `xwininfo -name "Samantha"` — that name, not
  `samantha-widget`; the window is titled `Samantha` (`window.py:36`)
  and PROGRESS.md 2026-08-25 records the afternoon the wrong name cost.
- **Geometry:** 900×96 → 900×480 → exact return to 900×96 at 510,984,
  with `_NET_WM_STATE_ABOVE/STICKY/SKIP_*` intact throughout.
- **The input region:** a click outside the video rectangle reaches the
  desktop; inside, it closes. By hand only.
- **Latency, free:** the camera burns its clock into the image
  (`25/08/2026 01:12:12` on the snapshot measured on 2026-08-25).
  Photograph the screen and compare that burned-in time against the
  system clock: end-to-end latency with nothing instrumented.
- **CPU:** the widget's, with and without the view; and the gateway's,
  which §3 claims **does not change**. An unmeasured claim is worth
  nothing.

### 9.3 The new switch

`SAMANTHA_WIDGET_LIVE=<file>` feeds the band a local video file as if
the gateway had pushed it — the counterpart of `SAMANTHA_WIDGET_PHOTO`
(`widget/README.md:66`). It is what lets the visible half be built and
photographed with no gateway and no camera.

### 9.4 The gap that stays open

The spoken close cannot be verified here: no microphone. It is exercised
through `SAMANTHA_WIDGET_FAKE_MIC`, the documented path, and **the
ceiling and the click exist precisely because of that gap**.

## 10. Costs accepted

- **The strip's channel now carries binary frames.** It has carried
  nothing but JSON since it was written on 2026-08-22.
- **A decoder thread inside the widget process**, beside GTK, Silero and
  Whisper. It exists only while a view is open. This is a smaller
  version of the counter-example CLAUDE.md §2.3 used to argue vision out
  of the widget — worth naming rather than hiding.
- **A new X mechanism** (`XShapeCombineRectangles`) in `ewmh.py`.
- **Two more tools** for a model that already confuses one of them with
  no camera argument.
- **Two minutes is a guess.** It is not one of BarnDoor's four
  calibrated constants and must not be filed beside them (CLAUDE.md §12,
  2026-08-24).

## 11. Decisions taken while designing this

Each of these was put to the user with its cost, and each answer is
theirs:

1. **Fluid video (15+ fps), not ~2 fps.** The cheaper option — reusing
   the frame the watcher already samples — was recommended and declined.
   §3 then found the expensive half of the cost was already being paid.
2. **Closed by voice, plus a hard ceiling.** Not by click alone, not by
   a fixed timer.
3. **In the band, 900×480.** Not larger, not full screen — §1.5,
   "present, not launched", survives intact.
4. **The input region fix now**, rather than accepting two minutes of
   swallowed clicks or shortening the ceiling to 30 s.
5. **No audio.**
6. **"Kiosk" is a fossil of a name, not a concept to design around.** The
   module keeps its name; the prose says "the strip's channel".
