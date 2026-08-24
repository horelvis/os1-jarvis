# samantha-vision

The house cameras, and what is worth saying about them.

This plugin lives inside the Hermes gateway, not inside the widget. It
watches every configured camera on a thread of its own, runs YOLOv9 over
one frame in ten, and — when the quiet rules say a sighting is worth
mentioning — hands the gateway a **prompt**, not a sentence. What reaches
the user is his answer to it, in his own words. He is told; he is never
made to recite (CLAUDE.md §1).

Since 2026-08-25 it also registers a **tool**, `mirar`, so he can be
asked. The camera no longer only knocks. See "Being asked" below; the
photo that goes with the answer reaches the strip and nothing else, for
the reason in CLAUDE.md §12.

It moved here from `widget/samantha_widget/vision.py` on 2026-08-24. The
widget no longer opens a camera and no longer has camera switches; if
you are looking for `SAMANTHA_WIDGET_CAMERA`, this is where it went.

## What it needs

- **The model.** `~/.samantha/models/yolov9-t-320.onnx`, 8 MB, copied
  from BarnDoor's `frigate-config/models/` (its
  `scripts/build-yolov9-onnx.sh` is what produced it). It is not in this
  repo. Without it no thread starts and the plugin is inert — and "he
  stopped noticing people" has no other symptom. Override the path with
  `SAMANTHA_YOLO_MODEL`.
- **`onnxruntime`, `av`, `numpy` and `pillow`** in the gateway's runtime.
  `Hermes/setup-runtime.sh` installs them; `uv sync` does not, because
  Hermes moved that extra to lazy-install. Nothing refuses to load the
  plugin without them — corrected 2026-08-24, this used to claim a
  `check_requirements()` that Hermes never called and that has been
  deleted. What actually happens is one line and no threads:
  `no detector, no cameras watched — No module named 'onnxruntime'`.
  Pillow is the newest of the four and the mildest: it encodes the JPEG,
  and its import is deferred to the moment of writing one, so a box
  without it loses the picture and keeps the watching, the alerts and the
  spoken answer.
- **`allow_gateway_injection: true`** on this plugin's config entry.
  Starting a turn nobody asked for is default-off; without it
  `ctx.inject_message()` returns `False` and the cameras watch in silence.

## Configuring the cameras — and where the password goes

**The password is never written into a URL.** It lives in `.env` at the
repo root — git-ignored, one `KEY=value` line — and the URL names it:

```
RTSP_PASSWORD=…
```

`Hermes/run-gateway.sh` sources that file if it is there, which is the
single chokepoint: both units that start a Hermes process
(`samantha-hermes.service`, `samantha-hermes-serve.service`) and every
manual invocation go through it, so nothing else has to be taught.
`.env.example` is tracked and carries the key names with no values, so a
fresh box knows what is missing. The plugin expands `${RTSP_PASSWORD}` when it builds a `Camera`,
and a URL naming a variable that is **not** set drops that camera with a
warning that says which variable — it never connects with the literal
text as a password and never logs the URL.

The camera addresses themselves are still local to this box, so they live
**only** in the git-ignored `.hermes/home/config.yaml`.
`Hermes/samantha-config.yaml` is tracked in git and carries the shape as
a comment, nothing more.

Write this under `plugins.entries.samantha-vision` in
`.hermes/home/config.yaml`:

```yaml
      settings:
        cameras:
          - name: fuera
            url: rtsp://admin:${RTSP_PASSWORD}@192.168.x.142:554/h264Preview_01_sub
          - name: entrada
            url: rtsp://admin:${RTSP_PASSWORD}@192.168.x.143:554/h264Preview_01_sub
```

**The `settings:` level is load-bearing.** `ctx.get_config("cameras")`
resolves `plugins.entries.<plugin_id>.settings.cameras` and nothing else
(`hermes_cli/plugins.py::get_config`, with a legacy fallback to
`config.`). Put the list straight under the entry — as the sibling of
`allow_gateway_injection`, which *is* read from there because Hermes
itself reads it — and the plugin loads, starts no threads, and logs `no
cameras configured (config key 'cameras' empty)`. Measured 2026-08-24;
it is the one mistake this config invites.

then `systemctl --user restart samantha-hermes.service`.

The house's two cameras, as of 2026-08-24. Addresses are placeholders:
this file is pushed to GitHub, and the real ones live next to the URLs
they describe, in `.hermes/home/config.yaml`.

| name here | address | BarnDoor calls it | state |
|---|---|---|---|
| `fuera` | `192.168.x.142` | `exterior` | offline — port 554 unreachable |
| `entrada` | `192.168.x.143` | `garage` | live |

The credential lives in the git-ignored `.env` on this box; it is shared
with BarnDoor.

**Always the sub-stream** (`h264Preview_01_sub`). The main stream is 4K,
costs real time to decode, and YOLO scales everything to 320 px anyway.

**On a new box, two things are yours to write by hand: the cameras and
the `.env`.** Everything else is scripted — `Hermes/setup-runtime.sh`
symlinks this directory into `$HERMES_HOME/plugins/`, installs `av`,
`onnxruntime`, `numpy` and `pillow` (which `uv sync` does not), and
enables the plugin; `Hermes/apply-config.sh` merges the tracked
`Hermes/samantha-config.yaml`, which lists `samantha-vision` and grants
it `allow_gateway_injection`. What no script can restore is the camera
block above — `.hermes/home/config.yaml` is not in git and never will be
— and the credential it names.

The symptom of forgetting is not an error. The plugin registers, logs
`no cameras configured (config key 'cameras' empty)`, and he simply
never mentions anybody.

### A recording is a camera

`url` is handed to PyAV, so **anything PyAV can open works** — including
a path to a file (an absolute one — nothing expands `~`):

```yaml
        cameras:
          - name: entrada
            url: /home/nexus/git/barndoor/frigate-storage/recordings/2026-05-05/18/exterior/14.26.mp4
```

That is how this whole path is tested, and how it was built while both
cameras were off: a recording proves the detector, the quiet rules, the
prompt and his answer. The only thing it cannot prove is the network.

### The names are interface, not configuration

`name` is what he says out loud and what the user asks for, so it must be
a word somebody would use for that place. It is handed to him as a
labelled value — `Dónde: entrada.` — and never inside a prepositional
phrase: bare nouns carry no article, `en la fuera de casa` is broken
Spanish, and a model handed broken Spanish repairs it by inventing a
place that fits. That was measured, twice, on the live gateway. See the
comment above `_TEMPLATE` in `alert.py` before touching the wording.

A nameless or url-less entry is dropped with one warning line; a typo in
one camera never costs the house the others.

## Being asked: the `mirar` tool

The cameras used to only knock. Since 2026-08-25 there is a tool:

| | |
|---|---|
| Name | `mirar` |
| Toolset | `camaras` — **ours**, and not `vision` |
| Argument | `camara`, optional. Omitted means all of them. |
| Returns | one sentence per camera, and nothing else |
| Waits | 2 s per camera for the next decoded frame |

**It never opens a second connection.** `CameraFleet.grab()` asks the
watcher thread that already has that stream open for its **next** frame,
through a per-camera slot and an `Event`. Some cameras cap concurrent
RTSP sessions and you find that limit as intermittent failure under load.
It never falls back to the last analysed frame either: that frame can be
forty seconds old, and offering it as "ahora" is a lie. After two seconds
he says `En {camara} no alcanzo a ver ahora mismo.` and means it.

**The toolset is `camaras` and the name matters.** The design said
`vision`; `vision` is a **built-in Hermes toolset** carrying
`vision_analyze`, an image-analysis tool this box cannot serve — the
model behind the strip is Qwen3.8-27B and it does not look at images.
Listing `vision` in `platform_toolsets` to reach `mirar` also offered him
that one. `check_fn` exists to keep him from being offered what cannot
work; a toolset of our own keeps that promise one level up.

**`check_fn` hides the tool when no camera is configured**, so a box with
an empty `cameras:` list is not offered something that can only fail.

**The answer is words. The picture is a side effect.** The return value
carries no `MEDIA:` tag and no filesystem path — a tool result travels
wherever the turn travels, and CosyVoice reads the answer out loud. The
photo goes to the strip alone, through the kiosk adapter, and whether
that succeeded never changes what he says. CLAUDE.md §12, 2026-08-25, has
the argument.

### Where the pictures live

`$HERMES_HOME/cache/images/vision/`, mode `0700`, one JPEG per grab:

    entrada-1756060000.jpg     # <camera>-<unix seconds>, quality 85, 0600

Hermes already designates `cache/images` for generated media; the
subdirectory is ours so pruning is unambiguous. A camera name that is not
a plain word is flattened rather than rejected — a strange name should
cost a strange filename, never a write outside this directory.

**Pruning runs on every write**, not on a timer somebody can forget to
start:

| | |
|---|---|
| Keep | the newest **20** |
| Maximum age | **3600 s** (one hour) |

This directory holds pictures of the inside and the outside of the house.
An unbounded one is a privacy leak as much as a disk leak, which is the
reason for both numbers.

### What he does with it, measured on the live gateway

Three things, all reported rather than fixed, because each is a decision
somebody has to make rather than a bug:

- **He calls `mirar` with no argument, 5 times out of 5**, even when the
  user named a camera. So "enséñame la entrada" is answered with a survey
  of every camera. Spelling out "omitir SOLO si no se ha nombrado
  ninguna" in the schema changed nothing across three further asks and
  was reverted: a prompt edit that does not work is noise in the file.
- **He invents visual detail he cannot see.** "Puerta cerrada, el porche
  vacío", against a tool that had said only "En la entrada no hay nadie."
  He is text-only and never sees the JPEG; anything beyond the eight
  watched labels is fabricated. Not fixable at the tool layer — the
  sentence is already minimal.
- **He mangles a bare camera name**: `fuera` came back as "Fuora",
  because "En fuera no alcanzo a ver" is not natural Spanish and he
  repairs it. Fixing it properly means camera names gaining a spoken form
  in the config, which is a schema change and a decision about how the
  places in this house are named.

## The quiet rules, and their numbers

They are not guesses. They come from BarnDoor's `agent/rules.py`,
arrived at against these same two cameras, and they are the only reason
one model call per event is affordable.

| Rule | Value | Why |
|---|---|---|
| Confidence floor | `0.7` | Below it, YOLOv9-t at 320 px announces shadows. |
| Anti-spam | `180 s` per label **per camera** | Without it, one person in the doorway is announced every three seconds. |
| Night window | `23:00`–`07:00` | A **person** seen in it beats the 180 s window and the escalation both: the second time somebody is in the garden at 3am is more worth saying than the first. |
| Night floor | `30 s` per label per camera | What the night window is gated by *instead*. Without it, "beats the anti-spam" meant every sampled frame: 19,200 utterances over an eight-hour night, measured. |
| Watched classes | 8 | persona, bicicleta, coche, moto, autobús, camión, gato, perro. |
| Sampling | one frame in ten | The GPU belongs to Whisper and CosyVoice, which are in the critical path of a conversation. A camera is not. |

The anti-spam key carries the **camera as well as the label**, which is
the point of naming them: somebody walking from `fuera` to `entrada` is
two events and should be.

**Nothing is silenced at night, but a person is paced.** The night
window is the *only* place `is_quiet_hours` is used (`vision.py:384`),
and all it does is set `urgent` for a person. Until 2026-08-24 `urgent`
skipped the anti-spam outright; it now **replaces** it with the 30 s
night floor (`vision.py:387`; `NIGHT_FLOOR_SECONDS` at `vision.py:272`)
and **resets the escalation level** (`vision.py:392`). If you came here
after "why did he not mention the person again for thirty seconds at
3 a.m.", that is the floor, and it is the whole of what gates him at
night.

There is still no *suppression* path anywhere in the plugin: a car seen
at 03:00 is announced exactly as it would be at noon — a car is never
`urgent`, so it obeys the ordinary window. If you came here after "why
did he mention a car at 3 a.m.", that is the rule working, not
breaking.

## What it does when a camera is off

A camera that is off, unplugged or rebooting is a Tuesday. Each camera
owns its own failure: one warning line the first time, `DEBUG` after
that, and a retry that backs off from 30 s to a 5-minute ceiling. The
other cameras carry on and the gateway never notices. When it comes
back, one line says so.

"The first time" is **per failure mode**, not per camera: unreachable and
"no frames" keep separate flags, so a camera flipping between them
announces each rather than leaving a stale WARNING describing the state
it is no longer in. A camera that stays in one state still costs exactly
one line.

**A camera that answers but sends no video** gets the same treatment,
and did not until 2026-08-24. Nothing raises in that case — a wrong
sub-stream path, a camera in a boot loop, a recording that has already
ended — so without counting frames it was indistinguishable from a
camera with an empty driveway in front of it, backing off to five
minutes in complete silence.

**A camera that dies mid-stream** is the reason `open()` passes both
`timeout` and `stimeout`. ffmpeg renamed that option; libavformat 62
(FFmpeg 8, which is what PyAV 18.1.0 links here) knows only `timeout`,
and an unknown option is dropped without a warning — leaving
`timeout=0`, which is infinite. Probed 2026-08-24 against `127.0.0.1:1`.
Both names are passed on purpose; the tidy version is the one that hangs.


## Reading the journal

```bash
journalctl --user -u samantha-hermes.service -f | grep samantha-vision
```

- `registered` — the plugin loaded.
- `no cameras configured (config key 'cameras' empty)` — the config never
  arrived. Correct on a box with no cameras; indistinguishable from a
  typo in the key, which is why the line names the key it read.
- `watching N camera(s): …` — the threads are up.
- `<name> unreachable — …` — that camera only, once.
- `<name> connected but produced no frames` — it answered and sent no
  video. Once per camera, `DEBUG` after that.
- `<name> dropped, ${VAR} is not set` — the URL names a variable the
  environment does not have. Check `.env` against `.env.example`.
- `<name>: alguien` — a sighting got through the quiet rules; his reply
  follows on the strip.
- `mirar <name>` or `mirar (todas)` — he was asked to look, and this is
  the argument he actually passed. Not decoration: what he says next is
  his paraphrase, and this line is the only way to tell "he asked about
  one camera and was answered about two" from "he was answered about one
  and embellished".
- `<name> snapshot not written — …` — the JPEG failed (no Pillow, a full
  disk). He still answered in words.
- `<name> photo not shown` — the picture did not reach the strip. At
  `DEBUG` when the answer was simply that nothing was listening; a
  WARNING when something went wrong. `no gateway, photo dropped` and
  `no strip platform, photo dropped` are the two ordinary cases, and
  `samantha-kiosk: refusing photo outside the spool: …` is the adapter
  declining a path that does not live in the snapshot directory.
- `no live gateway, sighting dropped after 4 attempts` — every attempt
  came back `False`. Two causes, and neither of them is a missing
  session: **the gateway is not listening** (still starting, or going
  down), which is the common one and which retrying fixes; or
  **`allow_gateway_injection` was never granted** (`plugins.py:2012`),
  which fails identically on every attempt and forever. Hermes' own
  `inject_message: gateway injection denied for plugin samantha-vision`
  turns up on the same grep and tells the two apart. Corrected
  2026-08-24, when this line read that the strip might never have spoken
  on this box — which cannot produce it at all, and sent readers hunting
  for it.
- `Plugin message injection was not routed: plugin=samantha-vision …` —
  **Hermes' own line, not ours**, and this is the one that means there is
  no session to inject into: no row exists until the user has talked to
  the strip. `inject_message` returns `True` in that case, because the
  lookup happens inside the coroutine after the task has been scheduled
  (`gateway/run.py:18715` returns `True`; `:18729` is where the missing
  row is found; `:18708` logs it), so nothing on our side can see it. Say
  something to him first.

## Tests

```bash
cd /home/nexus/git/os1-samantha
PYTHONNOUSERSITE=1 ./widget/.venv/bin/python -m pytest \
  Hermes/plugins/samantha_vision/tests/ -q
```

Nothing here needs a camera, a GPU or a network: the two things that
touch the outside world — building the detector and opening a stream —
arrive as callables the tests substitute.
