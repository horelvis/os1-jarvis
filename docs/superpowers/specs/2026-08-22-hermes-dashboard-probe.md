# Hermes dashboard & desktop probe — can they host Samantha?

Read-only source investigation of `~/hermes-src` @ `fcbd1076` (tag `v2026.8.19`).
Nothing was run, installed, or modified. Every claim below cites a file and line
read in this session. The 4090 is off; no runtime verification was possible, and
every "works" below means "the source says so", not "observed".

---

## Executive answer

**The dashboard can host our frontend, three different ways, and all three are
documented public contracts** — not private internals. The strongest is a
*dashboard plugin*: `plugins/<name>/dashboard/manifest.json` + a plain JS bundle
+ an optional `plugin_api.py` exposing a FastAPI `APIRouter`. That gives us a
route, a full-viewport overlay layer, our own WebSocket, and our own backend
endpoints, from inside the plugin we are already writing.

**But it will not give us the OS1 screen for free.** The dashboard shell paints
a persistent left sidebar with a "HERMES / AGENT" wordmark on every route, and
there is no chromeless route mode. Getting the terracotta screen means a theme
whose `customCSS` hides the shell, or an `overlay` slot component that covers
it. Both are supported; neither is what the extension point is *for*.

**And the dashboard has no voice at all.** Zero microphone code, zero TTS code
in `web/src`. Every voice feature in Hermes' browser surface lives in the
Electron desktop app instead. So "adopt the dashboard" does not mean "adopt a
working voice loop" — it means adopt a chat UI and build the voice loop anyway.

---

## Q1 — Can the dashboard serve OUR frontend instead of its own?

**Yes. Four mechanisms, in increasing order of how much of the shell survives.**

### 1a. `HERMES_WEB_DIST` — replace the entire SPA (blunt, total)

`hermes_cli/web_server.py:138`

```python
WEB_DIST = Path(os.environ["HERMES_WEB_DIST"]) if "HERMES_WEB_DIST" in os.environ else Path(__file__).parent / "web_dist"
```

Point that at `frontend/dist` and the FastAPI server serves *our* React app at
`/` with the full `/api/*` surface intact. This is not a hack we invented — it
is how Hermes ships itself:

- `Dockerfile:360` — `ENV HERMES_WEB_DIST=/opt/hermes/hermes_cli/web_dist`
- `nix/hermes-agent.nix:193` — `--set HERMES_WEB_DIST $out/share/hermes-agent/web_dist`
- `apps/desktop/electron/main.ts:10358` and `:10736` — the desktop app sets it
  when it spawns its backend
- `hermes_cli/main.py:11450-11499` — `hermes dashboard` validates a custom
  `HERMES_WEB_DIST` and prints `→ Using web dist from HERMES_WEB_DIST: …`,
  exiting 1 if the dist has no `index.html`
- `tests/hermes_cli/test_dashboard_web_dist_validation.py` — regression tests
  for exactly that validation

The mount path is `mount_spa()` at `web_server.py:17328-17505`. It serves
`WEB_DIST/index.html` with three globals injected into `<head>`
(`web_server.py:17385-17402`):

```
window.__HERMES_SESSION_TOKEN__      // loopback auth token
window.__HERMES_DASHBOARD_EMBEDDED_CHAT__
window.__HERMES_BASE_PATH__
window.__HERMES_AUTH_REQUIRED__      // gated mode instead of the token
```

Our app would need to read `__HERMES_SESSION_TOKEN__` and pass it to `/api/*`
and to WebSockets, which is the same thing the built-in SPA does.

Caveat: it mounts `/assets` as a `StaticFiles` directory (`:17473`) and
intercepts `/assets/{filename}.css` (`:17436`) — a Vite layout, which our
frontend already produces. It also serves any file under the dist directly
(`:17494-17499`) with a traversal guard, then falls back to `index.html` for
client-side routing.

Caveat 2: **this is all-or-nothing**. Setting it deletes the Hermes dashboard
for that process. No `/config`, no `/skills`, no `/sessions`, no theme picker.
If the point of migrating onto Hermes is to gain those surfaces, this throws
them away.

Caveat 3: `hermes serve` (the headless backend the desktop app spawns) exports
`HERMES_SERVE_HEADLESS=1`, and `mount_spa()` checks it first (`:17345`) —
headless serves **no** SPA regardless of `HERMES_WEB_DIST`. We would have to run
`hermes dashboard`, not `hermes serve`. This split is documented at
`AGENTS.md:533`.

### 1b. Dashboard plugin with `tab.override` — replace one route (the real door)

This is the documented extension point, and the doc is canonical:
`website/docs/user-guide/features/extending-the-dashboard.md` (927 lines),
linked from the plugin developer guide at
`website/docs/developer-guide/plugins/index.md:19`.

Discovery: `web_server.py:17901-18027` (`_discover_dashboard_plugins`) scans
`~/.hermes/plugins/<name>/dashboard/manifest.json`, the bundled `plugins/` tree,
and (opt-in) project plugins. Manifest fields (`:17984-18021`):

```json
{
  "name": "samantha",
  "label": "Samantha",
  "tab": { "path": "/samantha", "override": "/", "hidden": true },
  "slots": ["overlay", "backdrop"],
  "entry": "dist/index.js",
  "css": "dist/style.css",
  "api": "plugin_api.py"
}
```

- `tab.override` — "When set to a built-in route path, this plugin replaces that
  page instead of adding a new tab" (`web/src/plugins/types.ts:15-16`, honoured
  at `web/src/App.tsx:319-336` and `:481`). Documented behaviour: the original
  component is removed from the router, no nav tab is added, first plugin wins a
  contested path.
- `tab.hidden` — register the component and slots without a nav tab
  (`types.ts:18`, `web_server.py:17990`).
- Two in-tree plugins already ship this shape: `plugins/kanban/dashboard/` and
  `plugins/hermes-achievements/dashboard/` (manifest + `dist/` + `plugin_api.py`).

Loading: `web/src/plugins/usePlugins.ts` fetches `/api/dashboard/plugins`,
injects the CSS `<link>`, and appends the JS bundle as a `<script>` (with
optional SRI `integrity`). The bundle calls
`window.__HERMES_PLUGINS__.register(name, Component)`.

The host exposes a **versioned SDK** on `window.__HERMES_PLUGIN_SDK__`
(`web/src/plugins/registry.ts:110-190`): React itself, hooks, the API client,
`fetchJSON`, `authedFetch`, `buildWsUrl`, `buildWsAuthParam`, a component kit,
and `useI18n`. `SDK_CONTRACT_VERSION = "1.1.0"` (`registry.ts:105`). Plugins are
told to use `buildWsUrl` rather than hand-assembling WS URLs
(`web/src/plugins/sdk.d.ts:64-73`) — that is how a plugin opens its own socket
with the right auth param in both loopback and gated OAuth modes.

Critically, the bundle **need not use React at all**. `register()` takes a
`ComponentType`; a one-line wrapper that mounts our existing app into a `<div>`
via `useEffect` is sufficient. Our OS1 code does not have to be rewritten.

### 1c. Backend routes from the same plugin (`plugin_api.py`)

`web_server.py:18538-18653` (`_mount_plugin_api_routes`). The plugin's Python
file must expose `router` (a FastAPI `APIRouter`); it is mounted at
`app.include_router(router, prefix=f"/api/plugins/{plugin['name']}")` (`:18646`).

**An `APIRouter` accepts `@router.websocket(...)`.** So the plugin can own
`/api/plugins/samantha/ws` — plan 3's entire §5.1 protocol, binary frames and
all, inside the officially sanctioned mount point, with no fork and no
monkey-patch.

Gating (read this before planning deployment): user-source plugins are only
imported if the plugin name is in `plugins.enabled` in config.yaml and not in
`plugins.disabled` (`:18576-18590`, GHSA-mcfc-hp25-cjv7 / #46435). Project
plugins (`./.hermes/plugins/`) never get their Python imported (`:18598-18605`,
GHSA-5qr3-c538-wm9j). The `api` path is validated to be a relative file inside
the plugin's `dashboard/` dir (`:17994-18009` + re-checked at `:18607-18620`).

### 1d. Themes — YAML, no code

`~/.hermes/dashboard-themes/<name>.yaml`, listed via `/api/dashboard/themes`,
applied by `web/src/themes/context.tsx`. The model
(`web/src/themes/types.ts:1-186`) covers: a 3-layer palette that cascades into
every shadcn token via `color-mix()`; typography including an arbitrary
`fontUrl` injected as a `<link rel="stylesheet">` (so Cormorant Garamond +
Inter Tight from Google Fonts is one line); `layoutVariant`
(`standard | cockpit | tiled`); named asset URLs as CSS vars; per-component
chrome overrides that accept any CSS string; `colorOverrides`; and
**`customCSS` — raw CSS injected verbatim into a `<style>` tag**
(`context.tsx:258-276`, applied at `:389`).

There is even a first-paint shim: `_render_active_theme_bootstrap_css()`
(`web_server.py:17300-17318`) injects critical CSS for user themes so the
dashboard does not flash Hermes teal before the theme resolves.

**Recommended composition for us:** 1b + 1c + 1d — a plugin whose manifest sets
`tab.override: "/"` and `tab.hidden: true`, whose `plugin_api.py` owns our
WebSocket, paired with a `samantha.yaml` theme that carries the terracotta
palette, the two typefaces, and `customCSS` that hides the shell. That keeps the
rest of the Hermes dashboard reachable (config, skills, sessions) while `/` is
pure OS1.

---

## Q2 — What does the WebSocket carry?

There are **six** WebSocket endpoints, not one:

| Endpoint | Line | Carries |
|---|---|---|
| `/api/audio/speak-stream` | `web_server.py:5335` | JSON in, **binary int16 PCM out** |
| `/api/console` | `:16594` | text (Hermes console) |
| `/api/pty` | `:16944` | raw terminal bytes both ways (xterm.js) |
| `/api/ws` | `:17134` | **JSON-RPC** — the gateway surface |
| `/api/pub` | `:17165` | text — PTY-side event publisher |
| `/api/events` | `:17193` | text — event fan-out to the React sidebar |

### `/api/ws` — the token stream, and it is JSON only

`/api/ws` delegates to `tui_gateway.ws.handle_ws` (`web_server.py:17148-17151`),
which "reuses `tui_gateway.server.dispatch` verbatim so every RPC method … flows
through the same handlers whether the client is Ink over stdio or an iOS / web
client over WebSocket" (`tui_gateway/ws.py:1-21`). Wire protocol: newline-
delimited JSON-RPC both directions, `gateway.ready` emitted on accept.

It streams assistant tokens. Emitted event types (from `_emit(...)` across
`tui_gateway/*.py`):

```
message.start  message.delta  message.interim  message.complete
reasoning.delta  reasoning.available  thinking.delta
tool.start  tool.generating  tool.complete  tool.output_risk
status.update  session.info  session.usage  approval.request
voice.status  voice.transcript  voice.interrupted  wake.detected
moa.phase  moa.aggregating  moa.reference  error  reaction
notification.clear  terminal.close  browser.progress
pet.generate.progress  pet.hatch.progress
preview.restart.progress  preview.restart.complete
```

`message.delta` / `reasoning.delta` / `thinking.delta` are coalesced into ~30fps
batches (`tui_gateway/ws.py:41-60`) so a burst of tokens is one loop wakeup.

Inbound: ~150 JSON-RPC methods, including `prompt.submit`, `session.create`,
`session.interrupt`, `session.steer`, `session.history`, `slash.exec`,
`voice.record`, `voice.toggle`, `voice.tts`, `wake.start`, `wake.stop`,
`wake.pause`, `wake.resume`, `wake.status`, `wake.feed`.

**No binary frames.** `/api/ws` is JSON end to end.

### `/api/audio/speak-stream` — this one IS our §5.1 TTS half

`web_server.py:5335-5484`. Its own docstring states the protocol:

```
client → {"text": "..."} frames (incremental), {"done": true}, {"stop": true}
server → {"type":"start","sample_rate":N,"channels":1}, binary PCM frames, {"type":"end"}
server → {"type":"fallback"} when the provider has no chunked API
```

It resolves the streamer via `resolve_streaming_provider(cfg)` (`:5377`) —
**the exact registry our CosyVoice provider from plan 1 registers into** — cuts
sentences with `tools.tts_streaming.SentenceChunker` (`:5450`), and pushes each
sentence's PCM with `ws.send_bytes(chunk)` (`:5476`). It even flushes on idle
(0.5s poll, ~2s force flush, `:5410-5424`) so narration before a tool call is
spoken promptly, and treats disconnect or `{"stop":true}` as barge-in.

`docs/streaming-tts.md:1-8` confirms the three consumers of that provider
registry: CLI/TUI voice mode, "the dashboard speak-stream WebSocket", and "via
the gateway `StreamingTTSConsumer` — any platform adapter that opts into
streaming audio" (`gateway/streaming_tts_consumer.py:55`, calling the adapter's
`write_streaming_tts` at `:335`).

**Verdict on Q2:** the outbound half of our §5.1 protocol already exists, is
better tuned than our draft (idle flush, barge-in, fallback signalling), and is
wired to the provider we already built. We should delete our version of it and
speak this one. The inbound half does not exist here.

---

## Q3 — Does microphone audio come IN through the dashboard?

**The earlier research is confirmed, with one genuine and useful exception.**

### Confirmed: no streaming inbound STT

The only inbound-audio endpoint is `POST /api/audio/transcribe`
(`web_server.py:5024-5112`). It takes a **base64 `data:` URL in a JSON body**,
caps at `_MAX_TRANSCRIPTION_UPLOAD_BYTES`, writes a temp file, and calls
`tools.voice_mode.transcribe_recording`. One utterance, one request. It is
explicitly built for the MediaRecorder-blob pattern — the temp file prefix is
literally `hermes-desktop-voice-` (`:5064`). Nice detail: an empty transcript
returns `{"ok": true, "transcript": ""}` rather than a 400, so a VAD loop
re-listens quietly (`:5104-5108`).

`voice.record` over `/api/ws` (`tui_gateway/server.py:15151-15298`) does **not**
help a browser: it drives `hermes_cli.voice.start_continuous`, i.e. the
**server's** microphone via sounddevice. On a kiosk where browser and backend
are the same box that is arguably fine; on our split (mini-PC screen, 4090
backend) it is the wrong machine.

### The exception: `wake.feed` is a real client→server streaming audio path

`tui_gateway/server.py:14998-15035`:

> Push client-captured PCM into the armed wake detector. `pcm`: base64-encoded
> int16 mono little-endian samples. `sample_rate`: must be 16000. Used when
> `wake.start` returned `capture: "client"` so remote backends without a
> microphone can still run openWakeWord on Mac/desktop audio.

Soft cap 64000 bytes = 2s of 16 kHz int16 (`:15022`). `wake.start`
(`:14722-14790`) sets `prefer_client = surface in ("gui","desktop") or
params["client_capture"]`, and `resolve_capture_mode`
(`tools/wake_word.py:251-282`) returns `"client"` when the backend has no usable
input device. The response carries `sample_rate` and `frame_length` for the
client to chunk against (`server.py:14992-14994`).

So there **is** a documented, plugin-reachable path for streaming mic audio from
a browser to the backend — but it terminates in the wake detector, not in STT.

**Net:** the mic contract is `wake.feed` (streaming, 16 kHz PCM, wake word only)
plus `POST /api/audio/transcribe` (utterance-at-a-time, for the actual words).
There is no streaming ASR seam anywhere in this surface. If plan 3 wants
continuous server-side VAD/ASR, we are still building it — but we would build it
behind our own `@router.websocket` under `/api/plugins/samantha/`, which is the
sanctioned place to put it.

---

## Q4 — The desktop app

**Found:** `apps/desktop/` (not a top-level directory of its own — it lives
under `apps/`, alongside `apps/shared/` and `apps/bootstrap-installer/`).

**What it is:** **Electron**, `productName: "Hermes"`, version 0.17.0, main
`dist/electron-main.mjs`, built with `vite` + `electron-builder`
(`apps/desktop/package.json`). The renderer is its own React app in
`apps/desktop/src/`, using `@assistant-ui/react` and nanostores.

**It is NOT a webview onto the dashboard.** `AGENTS.md:533` is explicit:

> desktop has no build/runtime dependency on the dashboard frontend; it spawns
> a headless `hermes serve` backend server (the same gateway `dashboard` serves,
> minus the browser UI entirely: `serve` sets `headless_backend=True` … so
> `mount_spa()` disables the SPA even if a stray `web_dist/` exists — only the
> JSON-RPC/WS/API surface is reachable).

I confirmed independently: `grep` for `__HERMES_PLUGINS__` / `dashboard-plugins`
across `apps/desktop/src` and `apps/desktop/electron` returns **nothing**. The
two frontends share only `apps/shared` (`@hermes/shared` — the JSON-RPC WS
client), which `web/package.json` also depends on.

### It does have an extension point — a substantial one

`website/docs/developer-guide/desktop-plugin-sdk.md` (927+ lines). A desktop
plugin is **a single ESM file** default-exporting a `HermesPlugin`, dropped at
`$HERMES_HOME/desktop-plugins/<id>/plugin.js` — no build step, hot-reloads on
save. There is also a **unified package** mode:
`$HERMES_HOME/plugins/<id>/desktop/plugin.js`, "for plugins that also ship
agent-side code" — i.e. exactly our shape.

Contribution areas (doc lines 200-215): `PANES_AREA`, `ROUTES_AREA` (a full page
in the workspace pane), `SIDEBAR_NAV_AREA`, `STATUSBAR_AREAS`, `TITLEBAR_AREAS`,
`PALETTE_AREA`, `KEYBINDS_AREA`, `THEMES_AREA`, `COMPOSER_AREAS`. The host API
(doc 464-520) includes `host.request<T>(method, params?)` — described as
"active-gateway JSON-RPC — **the real power**".

Correction to the doc's framing: the three SDKs "do not share code, APIs, or
delivery. Only the backend `plugin_api.py` namespace (`/api/plugins/<id>`) is
shared" (doc lines 25-33). So one `plugin_api.py` serves both surfaces — which
means a WebSocket we add there is reachable from dashboard *and* desktop.

### The wake word — our earlier ruling was wrong

We ruled the wake word out because it is documented as CLI/TUI/desktop-only.
That is a statement about which **surfaces ship a UI for it**, not about
reachability.

`wake.start` / `wake.stop` / `wake.pause` / `wake.resume` / `wake.status` /
`wake.feed` are ordinary JSON-RPC methods on the gateway
(`tui_gateway/server.py:14722, 14871, 14898, 14916, 14928, 14998`), and
`wake.detected` is an ordinary emitted event. Anything that can speak
`/api/ws` can call them:

- A **desktop plugin** calls `host.request('wake.start', {surface:'gui', client_capture:true, persist:true})`.
- A **dashboard plugin** opens `/api/ws` with `buildWsUrl` and sends the same
  JSON-RPC frame.
- The `surface` gate is config, not code: `wake_surface_enabled`
  (`tools/wake_word.py:316-327`) returns true when `wake_word.surface` is
  `auto` or matches the caller's string — and the caller supplies its own
  string. `"gui"` is already an accepted value.

Reference implementation to copy: `apps/desktop/src/lib/wake-client-capture.ts`
("captures the default mic, downsamples to 16 kHz mono int16 frames, and pushes
them via `wake.feed`", coalescing queued frames into one call, `:123-155`) and
`apps/desktop/src/store/wake-word.ts:277-390`.

Detection is on-device for all three engines (openwakeword default with a
bundled "hey hermes" model, sherpa, porcupine — `tools/wake_word.py:1-30`), so
no audio leaves the box for the hotword.

**This is the single most valuable finding in this probe.** "Hey Samantha" as a
wake phrase is reachable from a plugin. Whether it belongs in plan 3 or a later
plan is a scoping call, but it should stop being listed as impossible.

### One caution about the desktop app as a host

It is an auto-updating consumer Electron app: `hermes update`, background update
checks, one-click update (`apps/desktop/README.md:41-49`), electron-builder
DMG/NSIS/AppImage targets. For a kiosk appliance that boots into one screen and
never shows a menu, that is a whole update surface and a whole window-chrome
surface we do not want to own. Chromium `--kiosk` against a local URL remains
the better shell for us.

---

## Q5 — What would it cost us aesthetically?

**Honest answer: adopting the dashboard *shell* is disqualifying. Adopting the
dashboard *plugin system* is not.** They are separable, and the distinction is
the whole decision.

### What the shell forces on you

`web/src/App.tsx:511-830` is the shell, and every route renders inside it:

- A `<aside id="app-sidebar">` (`:580-786`) that is `lg:sticky` and always
  visible at kiosk width. It contains the wordmark `Typography` rendering
  literally `Hermes` / `<br/>` / `Agent`, uppercase, `tracking-[0.0525rem]`
  (`:612-620`); the nav tabs; an `AuthWidget`; a `SidebarFooter` with status; a
  `ThemeSwitcher`; a `LanguageSwitcher`.
- A mobile `<header>` with a hamburger and the brand (`:526-582`) — this one is
  `lg:hidden`, so on a 1920px kiosk it is already invisible. Small mercy.
- `<Routes>` is nested five divs deep inside all of that (`:777-787`). There is
  no chromeless route: `/login` and pairing are the only things outside, and
  they are auth flows, not a mode we can request.

`web/README.md` also carries a "Typography & contrast rules" section that reads
like a house style guide — a `text-xs` size floor, an opacity floor of 0.7, and
"the dashboard preserves the Nous brand uppercase aesthetic" via a `text-display`
utility. Our design is one weight of Cormorant Garamond at rest on a flat
terracotta field. These are not compatible design languages; they are opposite
ones.

### What actually gets us out

Two escape hatches, both documented, both sufficient:

1. **`overlay` slot.** `<PluginSlot name="overlay" />` sits at `App.tsx:826` as a
   bare direct child of the root flex container — *outside* the sidebar, outside
   `<main>`, last in paint order. The doc describes it as a "Fixed-position layer
   above everything else" (extending-the-dashboard.md:590). A slot component
   rendering `position:fixed; inset:0; z-index:…; background:#d1684e` covers the
   entire shell, sidebar included. Combined with `tab.hidden: true`
   (doc:708 — "Used by plugins that only exist to inject into slots"), our
   plugin adds no tab and simply *is* the screen.

   Note the contrast with `backdrop` (`:522-525`), which is wrapped in
   `pointer-events-none fixed inset-0 z-0` — decorative only. `overlay` is not
   wrapped; the component controls its own positioning and can take input.

2. **Theme `customCSS`.** Raw CSS, injected verbatim
   (`themes/context.tsx:258-276`). `#app-sidebar` is a **stable id**, not a
   generated class (`App.tsx:581`), so `#app-sidebar { display: none }` is a
   one-liner that survives Tailwind churn. Plus `fontUrl` for the two typefaces
   and the palette for terracotta. The shipped `strike-freedom-cockpit` demo
   (doc:845) does exactly this class of thing — full palette, custom fonts,
   `layoutVariant: cockpit`, notched card corners, a scanline overlay — so a
   total reskin is a use case the maintainers anticipated and support.

### The honest judgment

Could our interface live inside it without becoming a Hermes app with a skin?
**Yes — but only because we would be using the plugin system to *evict* the
Hermes UI, not to sit inside it.** We would ship a plugin that overrides `/`,
hides itself from the nav, paints the whole viewport, and a theme that turns the
remaining chrome off. What we gain is not their look; it is their *plumbing* —
plugin discovery, the auth-aware WS URL builder, the `/api/plugins/<name>` mount,
and (with `HERMES_WEB_DIST` unset) the rest of the dashboard still reachable at
`/config` when we need it.

The cost is honest and worth stating: we would depend on a shell whose CSS we
are actively suppressing. If they rename `#app-sidebar` or restructure the root,
our terracotta screen grows a Hermes sidebar until we notice. The `overlay`
approach is much more robust than the `customCSS` approach for exactly this
reason — it covers the shell rather than deleting parts of it, so a shell
refactor changes what is *underneath* our opaque layer, not what is visible.

**Recommendation on aesthetics: use `overlay` + `tab.hidden`, and treat
`customCSS` as optional polish, not as the mechanism.**

---

## Q6 — How stable is what we would be leaning on?

Mixed, and it matters *which* thing you lean on. Ranked from safest:

### Tier 1 — documented public contract, safe

- **The plugin `manifest.json` + `/api/plugins/<name>` backend mount.** Canonical
  927-line doc (`extending-the-dashboard.md`), linked from the developer guide
  index (`plugins/index.md:19`). Two in-tree consumers (kanban,
  hermes-achievements). The doc's own framing: "All three are drop-in at runtime:
  no repo clone, no `npm run build`, no patching the dashboard source."
- **The general Python plugin `ctx`** — `register_tts_provider`,
  `register_transcription_provider`, `register_dashboard_auth_provider`,
  `register_memory_provider`, and 11 others (`hermes_cli/plugins.py:2372, 2653,
  2713, …`). Governed by an explicit written compatibility policy
  (`AGENTS.md:797-823`): keep surfaces additive, do not remove or rename
  `PluginContext` methods, new params optional and keyword-only, deprecations
  need a once-per-process warning plus two minor releases. Plus the standing
  rule (`AGENTS.md:854-859`, attributed to Teknium, May 2026): "plugins MUST NOT
  modify core files … If a plugin needs a capability the framework doesn't
  expose, expand the generic plugin surface — never hardcode plugin-specific
  logic into core."
- **`HERMES_WEB_DIST`** — used by the Dockerfile, the Nix derivation, and the
  desktop app; validated by `hermes dashboard` with a dedicated regression test
  file. This will not disappear quietly.
- **The `tui_gateway` JSON-RPC surface** (`/api/ws`) — the shared contract behind
  Ink-over-stdio, the dashboard chat tab, the desktop app, and iOS
  (`tui_gateway/ws.py:1-21`). Four independent consumers is strong evidence of
  stability, and `wake.*` / `voice.*` are part of it.

### Tier 2 — sanctioned but young, watch it

- **The frontend SDK on `window.__HERMES_PLUGIN_SDK__`.** It is versioned
  (`SDK_CONTRACT_VERSION = "1.1.0"`, `registry.ts:105`) and deliberately
  hand-authored as "the *versioned API boundary* — changing it is a deliberate
  act, visible in review, not an accidental consequence of refactoring an
  internal helper" (`sdk.d.ts:18-21`). It has unit tests (`registry.test.ts`,
  `usePlugins.test.ts`).

  **But its own header says `STATUS: spike`** (`sdk.d.ts:2`), and it carries four
  open questions including "Should the host assert at runtime that a plugin's
  declared `manifest.sdk_version` is compatible before executing it?" and whether
  to ship it as a published types package at all (`sdk.d.ts:27-35`). It is a
  boundary the maintainers intend to honour, not one they have finished
  designing.

  Mitigation: we barely need it. If our bundle mounts our own app into a div, we
  touch `register`, `registerSlot`, and `buildWsUrl` — three symbols, all of them
  the parts the doc most insists plugins use.

- **Slot names.** `KNOWN_SLOT_NAMES` is a `const` array of 30 names
  (`slots.ts:63-92`), documented in the user guide. `registerSlot` accepts any
  string; the shell only renders slots it knows. `overlay` is in both the code
  list and the doc table. Low risk, but a slot could be removed in a shell
  redesign without breaking a type check.

### Tier 3 — private, do not lean on

- **`hermes_cli/web_server.py` internals.** 19,222 lines, one module, no
  `__all__`, everything prefixed `_`. `_serve_index`, `_discover_dashboard_plugins`,
  `_mount_plugin_api_routes`, `_ws_auth_ok`, `_SESSION_TOKEN` — read these to
  understand behaviour, never import them.
- **`web/src/App.tsx` shell structure.** The `#app-sidebar` id is stable *today*;
  nothing promises it. This is precisely why `overlay` beats `customCSS`.
- **The desktop renderer** (`apps/desktop/src/**`). Use it as a reference
  implementation for `wake-client-capture.ts` and `voice-playback.ts`; do not
  import from it. The desktop SDK doc itself warns the loader gives "error
  isolation only … do not treat this pipeline as a trust boundary"
  (desktop-plugin-sdk.md:854-868).

One structural comfort: the maintainers' stated policy is that third-party
integrations belong in **standalone plugin repos**, not in-tree
(`AGENTS.md:862-880`, "No new third-party-product plugins in-tree", June 2026).
That is exactly what Samantha is. The plugin surface is the surface they are
actively committing to keep working for people outside the repo, because they
have told everyone else to live there too.

---

---

## Q7 (not asked, but it changes the answer) — which Hermes process are we even running?

Hermes has **three** independent server surfaces, and they do not host each
other. This turned out to matter more than anything else in the probe.

| Command | Serves the SPA? | Serves `/api/*` + `/api/ws`? | Hosts platform adapters? | Port |
|---|---|---|---|---|
| `hermes dashboard` | **yes** (`mount_spa`) | yes | no | 9119 (`hermes_cli/main.py:8117`) |
| `hermes serve` | **no** — exports `HERMES_SERVE_HEADLESS=1`, `mount_spa()` short-circuits at `web_server.py:17345` | yes | no | — |
| `hermes gateway` | **no** — `gateway/run.py` contains zero references to `web_server` or `mount_spa` | via the `api_server` **platform adapter** | **yes** | 8642 in our unit |

**Our systemd unit runs the third one.** `systemd/samantha-hermes.service:31`:

```
ExecStart=/usr/bin/env hermes gateway
```

…with `API_SERVER_ENABLED=true` and `API_SERVER_PORT=8642`. `api_server` is a
platform adapter (`gateway/platforms/api_server.py:1360`,
`APIServerAdapter(BasePlatformAdapter)`), listed among the port-binding adapters
at `gateway/run.py:383`.

So the dashboard is not "already running and we just add a plugin to it" — it is
a **second process we do not currently start**. Hosting our UI there means
running `hermes dashboard` alongside `hermes gateway` (they share `~/.hermes`,
config, sessions, and skills, but not a port or a process), or migrating our
integration off the gateway entirely. Either is defensible; neither is free, and
it interacts directly with open task #1 ("arrancar los servicios del 4090
juntos").

### And the platform-adapter path has a hole plan 3 was assuming was filled

The streaming-TTS seam on platform adapters is real but **unimplemented by every
shipped adapter**. `gateway/platforms/base.py:4621-4656` declares
`supports_streaming_tts` / `begin_streaming_tts` / `write_streaming_tts` /
`finish_streaming_tts` / `abort_streaming_tts`, and the comment above them is
explicit:

> Default: False (whole-file auto-TTS path remains). Override to opt in.

`grep -rl "def write_streaming_tts" gateway plugins` returns **only
`gateway/platforms/base.py`** — the abstract definition. Not Discord, not Google
Chat, not `api_server`, not anything. `StreamingTTSConsumer`
(`gateway/streaming_tts_consumer.py:55`, calling the seam at `:335`) exists and
is referenced by `docs/streaming-tts.md:5-8`, but no in-tree adapter opts in.

Consequences:

1. **Our current `api_server` path gets no streaming TTS today** — it falls back
   to whole-file synthesis, which is exactly the latency we are trying to remove.
2. **A plan-3 platform adapter would be the first implementation of that seam
   anywhere in the tree.** No reference implementation to copy, no other consumer
   keeping it honest as the core moves, and the abort/idempotency contract at
   `base.py:4650-4656` to get right ourselves.

Compare with `/api/audio/speak-stream` (`web_server.py:5335-5484`), which is
implemented, shipped, exercised by the desktop app
(`apps/desktop/src/lib/voice-playback.ts:94-120`), and already handles sentence
chunking, idle flush, fallback signalling, and barge-in. Preferring the written
code over the abstract seam is the whole argument in one comparison.


## Recommendation

**Build plan 3 as a Hermes *plugin* rather than a `kind: platform` adapter — but
keep our own frontend and our own WebSocket.** Concretely: extend the plugin we
already have (the one carrying the CosyVoice TTS provider) with a
`dashboard/manifest.json` declaring `tab.override: "/"`, `tab.hidden: true`, and
`slots: ["overlay"]`; a thin `dist/index.js` that mounts our existing OS1 app
into a fixed full-viewport overlay; and a `dashboard/plugin_api.py` exposing an
`APIRouter` with our `@router.websocket` for the parts Hermes has no contract
for. Delete our §5.1 TTS-out protocol and speak `/api/audio/speak-stream`
instead — it already streams int16 PCM from `resolve_streaming_provider`, which
is where our CosyVoice provider already lives, and it handles idle-flush and
barge-in better than our draft. Keep `POST /api/audio/transcribe` for
utterance-at-a-time STT rather than reinventing it, and keep Chromium `--kiosk`
as the shell — the Electron desktop app buys us a plugin SDK we do not need and
an auto-update surface we actively do not want. This keeps every seam on a
documented contract, deletes most of plan 3's protocol work, leaves the Hermes
config/skills/sessions pages reachable at their own routes, and — the finding
that changes scope — puts `wake.start(surface:"gui", client_capture:true)` +
`wake.feed` within reach of our own frontend, so "Hey Samantha" is a
plugin-level feature after all, not a fork-level one. The price, stated plainly:
this needs `hermes dashboard` running as a second process next to
`hermes gateway` (Q7), because the gateway serves no SPA. I think that price is
worth paying — the alternative is being the first and only implementation of an
unimplemented adapter seam — but it is a real operational change and it belongs
in the plan as a decision, not a footnote.

**What would change my mind:**

1. **If the `overlay` slot does not actually cover the shell when rendered.** I
   read `App.tsx:826` and the slot docs; I could not run it. If in practice the
   root container's `overflow-hidden` or a stacking context traps it, the whole
   aesthetic argument collapses back to `customCSS`-hides-the-sidebar, which is
   fragile enough that plain `HERMES_WEB_DIST` (1a) becomes the better answer —
   we lose the Hermes pages but keep a clean screen. **Verify this first**, on
   the 4090, before writing a line of plan 3.
2. **If we want continuous server-side VAD/barge-in on inbound audio.** Nothing
   in Hermes offers a streaming ASR seam, so we build it either way — but if
   that is the bulk of plan 3, the plugin-vs-adapter question stops mattering
   much and we should pick on operational grounds (does the kiosk talk to
   `hermes dashboard` or to a platform adapter?) rather than on code reuse.
3. **If `plugins.enabled` gating turns out to be painful in our deployment.** A
   user-source plugin's Python is only imported when the name is in
   `plugins.enabled` (`web_server.py:18583-18590`). If our install flow cannot
   reliably write that config, the backend router silently never mounts and the
   failure mode is a blank screen. Shipping under the bundled path or pinning
   the config in our setup script both solve it, but it needs to be a deliberate
   step in the plan, not an assumption.
4. **If running a second Hermes process is unacceptable.** See Q7: our unit runs
   `hermes gateway`, which serves no SPA at all. The dashboard-hosting story
   requires `hermes dashboard` as a separate process on 9119. If the answer is
   "one process on the 4090, full stop", then the plugin's `dashboard/` half is
   dead on arrival and we are back to a platform adapter — in which case we
   should budget for implementing `write_streaming_tts` ourselves, because no
   shipped adapter has.
