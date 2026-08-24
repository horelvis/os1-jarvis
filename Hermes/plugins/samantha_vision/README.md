# samantha-vision

The house cameras, and what is worth saying about them.

This plugin lives inside the Hermes gateway, not inside the widget. It
watches every configured camera on a thread of its own, runs YOLOv9 over
one frame in ten, and — when the quiet rules say a sighting is worth
mentioning — hands the gateway a **prompt**, not a sentence. What reaches
the user is his answer to it, in his own words. He is told; he is never
made to recite (CLAUDE.md §1).

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
- **`onnxruntime` and `av`** in the gateway's runtime. `check_requirements()`
  refuses to load the plugin without them.
- **`allow_gateway_injection: true`** on this plugin's config entry.
  Starting a turn nobody asked for is default-off; without it
  `ctx.inject_message()` returns `False` and the cameras watch in silence.

## Configuring the cameras — and where the password goes

The camera URLs carry the RTSP password, so they live **only** in the
git-ignored `.hermes/home/config.yaml`. `Hermes/samantha-config.yaml` is
tracked in git and carries the shape as a comment, nothing more.

Write this under `plugins.entries.samantha-vision` in
`.hermes/home/config.yaml`:

```yaml
      settings:
        cameras:
          - name: fuera
            url: rtsp://admin:<RTSP_PASSWORD>@192.168.100.142:554/h264Preview_01_sub
          - name: entrada
            url: rtsp://admin:<RTSP_PASSWORD>@192.168.100.143:554/h264Preview_01_sub
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

The house's two Reolink cameras, as of 2026-08-24:

| name here | address | BarnDoor calls it | state |
|---|---|---|---|
| `fuera` | `192.168.100.142` | `exterior` | offline — port 554 unreachable |
| `entrada` | `192.168.100.143` | `garage` | live |

The user is `admin`; the password is `RTSP_PASSWORD` in
`~/git/barndoor/.env`, which is git-ignored there. It is the same
credential BarnDoor's Frigate uses (`frigate-config/config.yml`).

**Always the sub-stream** (`h264Preview_01_sub`). The main stream is 4K,
costs real time to decode, and YOLO scales everything to 320 px anyway.

**On a new box there are no cameras.** `.hermes/home/config.yaml` is not
in git and never will be, so nothing above is restored by cloning the
repo. The symptom of forgetting is not an error: the plugin registers,
logs `no cameras configured`, and he simply never mentions anybody.

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

## The quiet rules, and their numbers

They are not guesses. They come from BarnDoor's `agent/rules.py`,
arrived at against these same two cameras, and they are the only reason
one model call per event is affordable.

| Rule | Value | Why |
|---|---|---|
| Confidence floor | `0.7` | Below it, YOLOv9-t at 320 px announces shadows. |
| Anti-spam | `180 s` per label **per camera** | Without it, one person in the doorway is announced every three seconds. |
| Quiet hours | `23:00`–`07:00` | Silence — but a person overrides it. A parked car does not. |
| Watched classes | 8 | persona, bicicleta, coche, moto, autobús, camión, gato, perro. |
| Sampling | one frame in ten | The GPU belongs to Whisper and CosyVoice, which are in the critical path of a conversation. A camera is not. |

The anti-spam key carries the **camera as well as the label**, which is
the point of naming them: somebody walking from `fuera` to `entrada` is
two events and should be.

## What it does when a camera is off

A camera that is off, unplugged or rebooting is a Tuesday. Each camera
owns its own failure: one warning line the first time, `DEBUG` after
that, and a retry that backs off from 30 s to a 5-minute ceiling. The
other cameras carry on and the gateway never notices. When it comes
back, one line says so.

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
- `<name>: alguien` — a sighting got through the quiet rules; his reply
  follows on the strip.
- `nobody to tell, sighting dropped` — nothing to inject into. Either the
  gateway is still starting, or **the strip has never spoken on this
  box**: there is no session row until the user talks, and no amount of
  waiting makes one. Say something to him first.

## Tests

```bash
cd /home/nexus/git/os1-samantha
PYTHONNOUSERSITE=1 ./widget/.venv/bin/python -m pytest \
  Hermes/plugins/samantha_vision/tests/ -q
```

Nothing here needs a camera, a GPU or a network: the two things that
touch the outside world — building the detector and opening a stream —
arrive as callables the tests substitute.
