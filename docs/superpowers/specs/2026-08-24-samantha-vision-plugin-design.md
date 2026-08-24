# The vision plugin — design

> Written 2026-08-24. Supersedes the vision path built into the widget on
> 2026-08-23, which works and is deliberately being moved rather than
> extended. What is new here is not that JARVIS sees — he already does —
> but that he can be **asked**, that he sees through **more than one**
> camera, and that the seeing lives where the thinking lives.

---

## 1. Goal and shape

Today the widget watches one camera and pushes a prompt at the gateway
when it notices somebody. Nobody can ask it anything: the camera speaks
and cannot be questioned. That gap was recorded on the day the feature
landed and is what this design closes.

The shape, in one sentence: **a Hermes plugin owns the cameras, alerts
through the path reminders already use, and registers a tool so the
model can look on demand.**

Three consequences follow, and each is a reason for the design rather
than a side effect:

- **The gateway already has a lifecycle.** systemd starts it, restarts
  it, and journals it. A camera thread inside it inherits all of that.
  A separate process would need its own unit, its own logging and its
  own supervision, for nothing.
- **The tool is native, not bolted on.** `register_tool` puts it in the
  same registry as the built-ins JARVIS already uses. There is no MCP
  server, no port, no transport, nothing to keep alive.
- **The widget gets smaller.** It goes back to being the strip: draw,
  listen, speak. Vision, PyAV and onnxruntime leave it.

### What it is not

It is **not** a vision *agent*. There is no second model, no reasoning
about scenes, no VLM. It is a sensor with a memory and two doors — one
that knocks, one that answers.

---

## 2. Why a plugin, and what was rejected

**A Hermes plugin**, `Hermes/plugins/samantha_vision/`, sibling to
`samantha_kiosk` and `samantha_voice`.

Verified against the pinned runtime on 2026-08-24, because the design
rests on it:

- `_VALID_PLUGIN_KINDS` (`hermes_cli/plugins.py:625`) is
  `{"standalone", "backend", "exclusive", "platform", "model-provider"}`.
  This plugin is **`standalone`**: it holds no exclusive slot and
  replaces no provider.
- `register_tool(name, toolset, schema, handler, check_fn=None,
  requires_env=None, is_async=False, description="", emoji="",
  override=False)` (`plugins.py:1705`) registers into the global tool
  registry. `override=True` would need
  `plugins.entries.<id>.allow_tool_override: true`; **we never override
  a built-in, so that gate stays shut** — and `samantha-config.yaml`
  already sets it `false` for the other two plugins.
- The proactive delivery path is not theoretical: on 2026-08-23 a
  cronjob reached the strip unprompted and spoke. `unwrap_delivery()`
  in `widget/samantha_widget/speech.py` already strips the scaffolding
  Hermes wraps such a message in.
- Only the `tts` toolset is disabled in `samantha-config.yaml`, so the
  agent has `core`, `code_execution`, `browser`, `cronjob` and the rest.
  A new tool joins that set; the model chooses it the same way.

### Rejected, with reasons

- **The widget serving MCP over HTTP.** Considered first and dropped
  when the plugin route was found. It made the strip a server, put the
  tool's availability behind the UI process, and added a transport to
  maintain. The plugin needs none of that.
- **A separate MCP process holding the cameras.** Own unit, own
  supervision, and it decodes RTSP a second time.
- **Leaving it in the widget and adding a query path.** Keeps vision
  inside the UI process, where a camera thread competes with the GTK
  main loop, Silero and Whisper. The strip should draw.
- **A vision agent with its own model** (VLM or LLM). Measured
  2026-08-24: 20591 MiB of 24564 are in use, leaving under 4 GB. A VLM
  fits only by squeezing what is already there — and CosyVoice and
  Whisper are both in the critical path of a conversation. Revisit only
  if "what does it see" turns out to need scene description rather than
  labels.
- **`code_execution` plus a shell script.** JARVIS could capture a frame
  with `ffmpeg` today. He could not interpret it — the local model is
  text-only — and getting there would make him narrate the steps, which
  CLAUDE.md §1 forbids. A dedicated tool returns one sentence.

---

## 3. Lifecycle, and when the threads start

> Everything with a file:line in this section was measured on 2026-08-24
> against the pinned Hermes in `.hermes/src/`, by a throwaway plugin that
> made the gateway speak unprompted. It was written up beside the code as
> `PROBE.md` and folded in here on 2026-08-24, because this is where the
> next person looks.

### `register(ctx)` is the only entry point

**No lifecycle hook fires after registration.** The two candidates were
both refuted:

- `register_auxiliary_task` (`hermes_cli/plugins.py:2940`) is not a
  lifecycle hook at all — it declares an LLM-backed *side job* routed
  through `auxiliary_client.py`. Nothing about it runs code at startup.
- `register_hook` (`plugins.py:3114`) is the real hook API, and its
  allow-list `VALID_HOOKS` (`plugins.py:161`) has no "gateway is up" or
  "plugin loaded" event. The closest are `on_session_start` (per
  session, `run_agent.py:725`) and `pre_gateway_dispatch` (per inbound
  message — it does hand over the `GatewayRunner`, but only once
  somebody has already spoken).

There *is* a `gateway:startup` event (`gateway/run.py:13160`), and it is
not the plugin API: `self.hooks` there is `gateway/hooks.py::HookRegistry`,
a separate system that scans `.hermes/home/hooks/` for `HOOK.yaml` +
`handler.py` pairs. A plugin cannot subscribe to it. (`ctx.on_unload`
exists with no `on_load` counterpart, which is the same fact from the
other side: `register()` *is* the load.)

So a plugin that must act later **starts its own threads from
`register()`** — one per configured camera, each daemonised so a gateway
shutdown does not wait on a blocked network read.

Registration itself must stay pure, for a reason measured on 2026-08-23
in the kiosk adapter: work done during registration that touches the
outside world turns a missing dependency into a plugin that never loads,
and Hermes reports that as a retry-forever loop at DEBUG level. **A
camera that cannot be reached is a warning in the log and a thread that
keeps trying, never a plugin that fails to register.**

`shutdown()` sets a stop flag and joins each thread with a short
timeout. A thread wedged inside a decoder read is abandoned rather than
waited on, because a gateway that will not stop is worse than a leaked
thread on the way to process exit.

### Speaking first: `ctx.inject_message`

```python
ctx.inject_message(content: str, role: str = "user", *,
                   session_key: str | None = None) -> bool
```

`plugins.py:1973`, and documented (`website/docs/user-guide/features/
plugins.md`, "Injecting Messages"). The session key is deterministic:
`build_session_key` (`gateway/session.py:1090`) joins namespace /
platform / chat_type / chat_id, and the kiosk adapter always opens its
source with `chat_id="kiosk"`, `chat_type="dm"` — so it is the constant
`agent:main:samantha_kiosk:dm:kiosk`. A `/new` mints a fresh
`session_id` under the same key, so the constant stays correct.

**What arrives is a user message.** `_dispatch_plugin_message_injection`
(`gateway/run.py:18717`) builds a plain inbound `MessageEvent` with
`internal=True` and hands it to the platform adapter — the same path an
inbound `chat` frame from the widget takes. The model reads the injected
text as something the user said, and *his answer* is what reaches the
strip. `role` is nearly cosmetic: a non-`"user"` role only prefixes the
content with `[role]` and still arrives as user input.

**There is no way to push a finished assistant message through this
API, and that is the property we want.** It makes "he is told, never
made to recite" (CLAUDE.md §1) a fact about the mechanism rather than
about our discipline: the alert can only ever be an instruction, and
the instruction is never spoken back. Slash commands and approvals are
not reachable this way either — the docs are explicit that injected
text is always conversational input. A busy session is safe: it uses
the existing busy-session queue rather than starting a competing turn,
and `True` means the gateway accepted it for dispatch, not that the turn
finished.

**The permission is per plugin and default-off.**
`_gateway_injection_allowed()` (`plugins.py:2043`) reads
`plugins.entries.<plugin_id>.allow_gateway_injection`, where
`<plugin_id>` is the manifest `key` or `name` — for us
`samantha-vision`. Authorisation is rechecked at dispatch rather than
trusted from the session, and a live adapter must exist for the
session's platform.

**It returns `False` silently, in two cases that want opposite
handling:**

- **The gateway is still starting.** `_install_plugin_message_injector()`
  (`gateway/run.py:18634`) publishes the live runner into
  `PluginManager._gateway_message_injector`, and it is called at
  `gateway/run.py:13155`, immediately after `self._running = True` —
  i.e. **after every platform adapter has connected**. Before that,
  injection returns `False` and logs "no live gateway is available". On
  this box that window was under a second, but a slow or retrying
  adapter pushes it arbitrarily later, so **a fixed delay is the wrong
  answer**: treat `False` as "not yet" and retry, bounded.
- **The strip has never spoken on this box.** There is no session row,
  `lookup_by_session_key` returns `None`, and no amount of waiting makes
  one. Vision cannot introduce itself to a gateway nobody has talked to
  yet, so the retry must end in dropping the sighting.

### The other path, and why we do not want it

Cron does **not** use injection. `cron/scheduler.py::_deliver_result`
(line 2652) runs the agent first and then pushes the finished text at
the platform through `tools.send_message_tool::_send_to_platform`,
optionally wrapped in a "Cronjob Response: …" header. That is the
finished-assistant lane: it would put vision's own words on the strip
verbatim and bypass his voice entirely. It exists; do not use it for
detections.

---

## 4. Runtime topology

```
┌──────────────────────────────────────────────────────────────┐
│  Hermes gateway (systemd, :7777)                             │
│                                                              │
│   samantha_vision (this design)                              │
│     one thread per camera → YOLO → Watcher rules             │
│     ├─ knocks:  worth saying → a turn, delivered to the strip│
│     ├─ answers: register_tool("mirar" / "revisar")           │
│     └─ remembers: detections.db (what, where, when)          │
│                                                              │
│   samantha_kiosk (surface)   samantha_voice (TTS)            │
└───────────────┬──────────────────────────────────────────────┘
        ws://127.0.0.1:7777/ws
                │
┌───────────────▼──────────────┐
│  widget — the strip          │
│  draws, listens, speaks      │
│  (no cameras any more)       │
└──────────────────────────────┘
```

---

## 5. The cameras stop being a variable

Today: `SAMANTHA_WIDGET_CAMERA`, one RTSP URL or file, one thread
(`widget/samantha_widget/__main__.py:414`).

Tomorrow: a list in the plugin's config, each with a **name the model
and the user both use**:

```yaml
plugins:
  entries:
    samantha-vision:
      allow_tool_override: false
      cameras:
        - name: fuera
          url: rtsp://user:pass@192.168.100.142:554/h264Preview_01_sub
        - name: entrada
          url: rtsp://user:pass@192.168.100.143:554/h264Preview_01_sub
      # Anything PyAV can open works, which is how this is tested while
      # the cameras are off: a recording is as good as a live stream for
      # everything except proving the network.
```

Rules that carry over unchanged, because they were arrived at against
these same cameras and not guessed:

| Rule | Value | Why |
|---|---|---|
| Confidence floor | `0.7` | Below it, YOLOv9-t at 320 px announces shadows. |
| Anti-spam | `180 s` per label **per camera** | Without it, one person in the doorway is announced every three seconds. |
| Quiet hours | `23:00`–`07:00` | A person overrides the silence; a parked car does not. |
| Watched classes | 8 | persona, bicicleta, coche, moto, autobús, camión, gato, perro. |

**The anti-spam key gains the camera.** Today it is the label; with two
cameras, somebody walking from `fuera` to `entrada` is two events and
should be — that is the whole point of naming them.

**A camera that is off, unplugged or rebooting is a Tuesday, not an
error.** It says so once and retries. One dead camera must never stop
the others: each thread owns its own failure.

---

## 6. Two doors on one engine

> **Only the first door is built.** §6.1 shipped on 2026-08-24 and is
> running. §6.2 (`mirar`, `revisar`) and §6.3 (the detections table) are
> **plan 2**: nothing in `Hermes/plugins/samantha_vision/` registers a
> tool or writes a row today. Read them as design, not as description —
> unlike §3, which is measurement.

### 6.1 The knock — the alert

Unchanged in spirit from what works today, and the rule that governs it
is CLAUDE.md §1: **he is told, not made to recite.** A detection does
not become speech. It becomes a turn, carrying a prompt that asks for
one short line in his own words and forbids mentioning cameras or
detections. What reaches you is his:

```
cámara fuera: alguien
← Oye. Hay alguien fuera de casa.
```

The camera's name enters the prompt so he can place it — "en la
entrada" — without ever saying the word "cámara".

Delivery uses the path the reminders proved on 2026-08-23. That path
wraps the body in scaffolding (a job id, a rule of dashes, an English
footer); `unwrap_delivery()` already strips it, and the alert must go
through the same treatment or he reads furniture out loud.

### 6.2 The answer — the tool

```python
ctx.register_tool(
    name="mirar",
    toolset="vision",
    description="Mira una cámara de la casa ahora mismo y di qué hay.",
    emoji="👁",
    schema={
        "type": "object",
        "properties": {
            "camara": {
                "type": "string",
                "description": (
                    "Nombre de la cámara. Omitir para mirar todas."
                ),
            }
        },
        "required": [],
    },
    handler=_handle_mirar,
    check_fn=_cameras_configured,
)
```

- **Omitting the camera looks at all of them.** "¿Hay alguien?" should
  not force him to pick one, and picking wrong is worse than looking
  twice.
- **The frame is captured when asked**, not read from what the watcher
  last analysed. The watcher samples one frame in ten; a question is
  about now.

  Concretely: the handler takes the **next** frame off the stream the
  watcher thread already has open, and does not open a second
  connection to the camera. Two decoders on one sub-stream is waste, and
  some cameras cap concurrent RTSP sessions — a limit you discover as an
  intermittent failure under load, which is the worst way to discover
  it. The handler therefore blocks until the next frame arrives, with a
  timeout: **2 seconds, after which it answers that the camera is not
  responding.** A question that hangs is worse than one answered
  honestly, because he simply goes quiet.
- **The return value is a sentence, not a structure.** `describe()`
  already produces one — "alguien y un perro" — and the model turns it
  into speech. A JSON blob invites him to read fields aloud.
- **Nothing found is not an error.** "En la entrada no hay nadie" is an
  answer.
- `check_fn` keeps the tool out of the model's list when no camera is
  configured, so he is never offered something that cannot work.

### 6.3 The memory

A SQLite table in the plugin's own directory — the same technology
Hermes already uses for `state.db`, so nothing new is introduced.

```sql
CREATE TABLE detections (
    id       INTEGER PRIMARY KEY,
    seen_at  TEXT NOT NULL,   -- ISO 8601, local time
    camera   TEXT NOT NULL,
    label    TEXT NOT NULL,
    score    REAL NOT NULL
);
CREATE INDEX detections_by_time ON detections (seen_at);
```

Every detection that passes the confidence floor is written — including
the ones the anti-spam rule keeps quiet, because "no lo dijo" is not
"no lo vio". That distinction is the reason the table exists.

A second tool reads it:

```python
ctx.register_tool(
    name="revisar",
    toolset="vision",
    description="Di qué han visto las cámaras en un rato reciente.",
    emoji="👁",
    schema={
        "type": "object",
        "properties": {
            "desde_horas": {
                "type": "number",
                "description": "Cuántas horas atrás mirar. Por defecto 12.",
            },
            "camara": {"type": "string"},
        },
        "required": [],
    },
    handler=_handle_revisar,
    check_fn=_cameras_configured,
)
```

It answers "¿ha venido alguien esta mañana?" — the question that makes
having cameras worth anything, and the one no amount of looking at the
present can answer.

**Retention:** rows older than 30 days are deleted on startup. Nobody
asked for a year of history, and an unbounded table on an appliance is
a slow leak.

---

## 7. What leaves the widget

| Leaves | Why |
|---|---|
| `widget/samantha_widget/vision.py` | Moves to the plugin, whole. |
| `_watch_camera` + the camera thread (`__main__.py:414`) | The plugin owns the loop now. |
| `SAMANTHA_WIDGET_CAMERA`, `SAMANTHA_WIDGET_CAMERA_RETRY`, `SAMANTHA_YOLO_MODEL` | Replaced by plugin config. |
| The PyAV and onnxruntime **reason** | onnxruntime stays for Silero; PyAV came with faster-whisper. Neither is removed from `pyproject.toml`, but neither is there for vision any more. |
| `widget/tests/test_vision.py` | Moves with the module. |

The strip keeps drawing, listening and speaking. That is §2.3's claim
about what it is, restored.

---

## 8. Scope

**In:** the plugin, N named cameras, one thread each, the carried-over
quiet rules keyed per camera, the alert, `mirar`, `revisar`, the
detections table, and removing vision from the widget.

**Out, deliberately:**

- **Scene description.** Eight labels is the ceiling until a VLM earns
  its VRAM. "Un hombre con una caja" is out of reach and saying so
  plainly is better than half-promising it.
- **Faces, identity, recognising anybody.** Not "later" — not designed.
- **Recording, clips, playback.** BarnDoor already stores 1896
  recordings; duplicating that is how two projects become one tangle.
- **Controlling cameras** (pan, tilt, night mode).
- **A second model of any kind.**
- **Anything the user does not ask for out loud.** The alert stays as
  rare as the rules make it.

---

## 9. Risks and open questions

| Risk | Handling |
|---|---|
| **Camera threads inside the gateway destabilise it.** The gateway is the brain: if it dies, everything dies. Today a camera crash only took down the widget's thread. | Each camera thread catches everything, logs once, and retries on a backoff. A thread that cannot recover exits and says so; it must never propagate. Verified by pointing one camera at a URL that refuses connections. |
| **N cameras is N decoders.** Sub-streams at 320 px are cheap, but "multiple" has no upper bound in the user's intent. | Sample one frame in ten, as today, and document the cost per camera measured on the box before adding a third. |
| **The alert's scaffolding reaches his voice.** Measured on the reminders: job ids, dashes, an English footer. | Reuse `unwrap_delivery()`; test with a verbatim delivery message, as plan 2 did. |
| **Two sources of vision during the move.** If the widget still watches while the plugin starts watching, everything is announced twice. | The widget's camera path is removed in the same change that turns the plugin on. Not before, not after. |
| **The model invents camera names.** Asked about "el jardín" when no such camera exists. | The handler returns the list of real names in its error string, so the correction reaches him as an answer rather than a failure. |
| **A tool that answers "nada" all day teaches him not to use it.** | Not handled by design; noted. If it happens, the fix is prompt-side, not code-side. |
| **RTSP credentials in config.yaml.** The URLs carry user and password. | `samantha-config.yaml` is already git-ignored and already holds secrets; this changes nothing about that, and the spec says so rather than pretending otherwise. |

---

## 10. Testing

- **Unit, no camera, no GPU:** the rules — anti-spam keyed per camera,
  quiet hours across the 23:00 boundary, the confidence floor,
  `describe()` phrasing for one person, several, and mixed labels.
- **Unit, no camera:** the tool handlers against a fake detector — an
  unknown camera name, no cameras configured, nothing detected, one
  camera down out of two.
- **The memory:** insertion, the time window query, the 30-day sweep.
  A frozen clock, never `datetime.now()` in an assertion.
- **Integration, no camera:** point a camera at a recording. That is how
  the current vision path was built and it works for everything except
  proving the network.
- **Manual, on the box:** ask him what he sees, with a camera on, and
  listen to what he says. No test can tell you whether it sounded like
  him.

---

## 11. Decision-log entries owed

CLAUDE.md §12 gets these when this lands:

- **Vision moves from the widget into a Hermes plugin.** Reverses the
  2026-08-23 placement decision, which put it in the widget because
  onnxruntime and PyAV were already there. The reason it moves is that
  a camera you can question needs to live beside the thing that answers.
- **Cameras become plural and named.** The names are interface, not
  configuration: they are what he says and what you ask for.
- **He remembers what he saw.** A detections table, 30 days. The first
  thing in this project that remembers something the user never said.
