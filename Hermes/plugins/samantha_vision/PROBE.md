# How a plugin says something nobody asked for

Task 1 of the vision plan, run 2026-08-24 against the pinned Hermes in
`.hermes/src/`. Everything here was measured on this box, not read off a
changelog. The next four tasks are written against this file.

**The one-line answer:** `ctx.inject_message(text, role="user",
session_key="agent:main:samantha_kiosk:dm:kiosk")`. It becomes a normal
user turn on the kiosk platform, the model answers it in his own words,
and the strip speaks the answer. It is **not** a finished assistant
message — the plan's assumption holds and Task 5 does not have to change.

---

## 1. The hook that runs after registration: there isn't one

`register(ctx)` is the whole of a plugin's lifecycle on the way in. The
two candidates named in the plan were both refuted:

- **`register_auxiliary_task` (`plugins.py:2940`) is not a lifecycle
  hook at all.** It declares an LLM-backed *side job* — vision analysis,
  compression, smart-approval — that routes through
  `auxiliary_client.py` and gets its own `auxiliary.<key>` config block.
  Nothing about it runs code at startup.
- **`register_hook` (`plugins.py:3114`) is the real hook API**, and its
  allow-list `VALID_HOOKS` (`plugins.py:161`) has no "gateway is up" /
  "plugin loaded" event. The closest are `on_session_start` (fires per
  session, from `run_agent.py:725`) and `pre_gateway_dispatch` (fires per
  inbound message — it does hand over `gateway: GatewayRunner`, but only
  once somebody has already spoken).

There is a `gateway:startup` event, emitted at `gateway/run.py:13160`,
and it is **not** the plugin API: `self.hooks` there is
`gateway/hooks.py::HookRegistry`, a separate directory-scanning system
that loads `HOOK.yaml` + `handler.py` pairs out of `.hermes/home/hooks/`.
A plugin cannot subscribe to it. (`ctx.on_unload` exists with no
`on_load` counterpart, which is the same fact from the other side:
`register()` *is* the load.)

**So a plugin that must act later starts its own thread from
`register()`.** That is what the probe does, and what the camera loop in
Task 2 will have to do.

## 2. The delivery object, and how a plugin reaches it

### The object

`PluginManager._gateway_message_injector` — a `(owner, callable)` pair,
not a platform registry and not a bus. The **live gateway publishes
itself into it**:

- `GatewayRunner._install_plugin_message_injector()`
  (`gateway/run.py:18634`) calls
  `get_plugin_manager().set_gateway_message_injector(self,
  self._schedule_plugin_message_injection)`.
- It is installed at `gateway/run.py:13155`, immediately after
  `self._running = True` — i.e. **after every platform adapter has
  connected**. Before that moment injection returns `False` with
  `"inject_message: no live gateway is available"`.
- `_clear_plugin_message_injector()` (line 14659) takes it back down on
  shutdown, and only if the runner is still the registered owner.

### How a plugin reaches it

`ctx.inject_message()` (`plugins.py:1973`), the documented public API
(`.hermes/src/website/docs/user-guide/features/plugins.md`, "Injecting
Messages"). Signature:

```python
ctx.inject_message(content: str, role: str = "user", *,
                   session_key: str | None = None) -> bool
```

Four gates, every one of which fails **silently to a log line**:

1. **`session_key` is required in gateway mode** and must name a session
   that already exists. `_dispatch_plugin_message_injection` does
   `await self.async_session_store.lookup_by_session_key(session_key)`
   and returns `False` if the entry or its `origin` is missing.
2. **The permission is default-off, per plugin.**
   `_gateway_injection_allowed()` (`plugins.py:2043`) reads
   `plugins.entries.<plugin_id>.allow_gateway_injection`, and
   `<plugin_id>` is `manifest.key or manifest.name` — for us the
   manifest `name:`, e.g. `samantha-vision`.
3. **Authorisation is rechecked at dispatch**, not trusted from the
   session: `self._is_user_authorized(source,
   allow_adapter_delegation=False)`. For the kiosk this passes because
   `samantha_kiosk`'s own `register()` sets
   `SAMANTHA_KIOSK_ALLOWED_USERS=primary`.
4. **A live adapter must exist** for the session's platform
   (`_adapter_for_source`).

### The session key is deterministic

`build_session_key` (`gateway/session.py:1090`) joins namespace /
platform / chat_type / chat_id. The kiosk adapter always opens its source
with `chat_id="kiosk"`, `chat_type="dm"`, so the key is always:

```
agent:main:samantha_kiosk:dm:kiosk
```

Confirmed against `.hermes/home/state.db`: every `samantha_kiosk` row
since 2026-08-23 carries exactly that `session_key`, and the rows survive
gateway restarts (`origin_json` is stored with them). A `/new` mints a
fresh `session_id` under the same key, so the constant stays correct.

**The one case where it is not correct: a box where the strip has never
spoken.** No session row, `lookup_by_session_key` returns `None`,
injection returns `False` and logs "not routed". Vision cannot introduce
itself to a gateway nobody has talked to yet.

## 3. Question 3 — user message or finished assistant message?

**A user message.** The plan's assumption is correct; Task 5 stands.

`_dispatch_plugin_message_injection` (`gateway/run.py:18716`) builds a
plain inbound event and hands it to the platform adapter:

```python
event = MessageEvent(
    text=content,
    message_type=MessageType.TEXT,
    source=source,
    internal=True,
    allow_gateway_control=False,
    metadata={
        "hermes_plugin_id": plugin_id,
        "hermes_plugin_injection": True,
        "gateway_session_key": session_key,
        "gateway_session_id": entry.session_id,
        "gateway_session_strict": True,
    },
)
await adapter.handle_message(event)
```

That is the same path an inbound `chat` frame from the widget takes. The
model reads the injected text as something the user said and answers it,
and the answer is what reaches the strip.

Four consequences worth carrying into Task 5:

- **`role` is nearly cosmetic.** A non-`"user"` role only prefixes the
  content — `msg = content if role == "user" else f"[{role}] {content}"`
  — and still arrives as user input. There is **no** way to push a
  finished assistant message through this API, which is exactly the
  property we want.
- **The injected text is never spoken back.** Whatever prompt vision
  sends is instruction, not script; only his reply is heard. So the
  prompt must be worded as an instruction (as `widget/samantha_widget/
  vision.py` already does today), and it can be as long as it needs.
- **Slash commands and approvals are not reachable this way** — the docs
  are explicit: "Injected text is always conversational input."
- **A busy session is safe.** The docs: "Active sessions use the existing
  busy-session queue rather than starting a competing turn." `True` means
  the gateway accepted it for async dispatch, not that the turn or the
  delivery finished.

### The other path, and why we do not want it

Cron does **not** use injection. `cron/scheduler.py::_deliver_result`
(line 2652) runs the agent first and then pushes the finished text at the
platform through `tools.send_message_tool::_send_to_platform`, optionally
wrapped in a "Cronjob Response: …" header. That is the finished-assistant
lane: it would put vision's own words on the strip verbatim and bypass
his voice entirely. It exists; do not use it for detections.

## 4. The code that worked, verbatim

`plugin.yaml` (throwaway — Task 2 replaces it):

```yaml
manifest_version: 2
api_version: 1
name: samantha-vision
label: Samantha (vision probe)
kind: standalone
version: 0.0.1
description: >
  THROWAWAY. Task 1 of the vision plan: prove that a plugin can start a
  turn nobody asked for. Five seconds after registration it injects one
  user message into the kiosk session and logs whether the gateway took
  it. Deleted in task 2, when the real plugin takes this directory.
author: Horelvis Castillo
```

`__init__.py`:

```python
from .probe_deliver import schedule_probe

__all__ = ["register"]


def register(ctx):
    schedule_probe(ctx)
```

`probe_deliver.py`:

```python
import logging
import threading

logger = logging.getLogger(__name__)

KIOSK_SESSION_KEY = "agent:main:samantha_kiosk:dm:kiosk"
PROBE_TEXT = "probe: di algo corto"
DELAY_SECONDS = 5.0


def schedule_probe(ctx) -> None:
    timer = threading.Timer(DELAY_SECONDS, _fire, args=(ctx,))
    timer.daemon = True
    timer.start()


def _fire(ctx) -> None:
    accepted = ctx.inject_message(
        PROBE_TEXT,
        role="user",
        session_key=KIOSK_SESSION_KEY,
    )
    logger.warning("samantha-vision probe: inject_message -> %s", accepted)
```

Config, merged in with `Hermes/apply-config.sh` (**reverted after the
probe** — the tracked `Hermes/samantha-config.yaml` does not enable this
plugin, and a later task re-adds the real entry):

```yaml
plugins:
  enabled:
    - samantha-kiosk
    - samantha-voice
    - samantha-vision
  entries:
    samantha-vision:
      allow_tool_override: false
      allow_gateway_injection: true
```

And the plugin has to be visible to discovery, the same way the other two
are — `.hermes/home/plugins/` holds symlinks into this repo:

```bash
ln -sfn "$PWD/Hermes/plugins/samantha_vision" .hermes/home/plugins/samantha_vision
```

## 5. What it did

```
$ systemctl --user restart samantha-hermes.service
# widget already running by hand with SAMANTHA_WIDGET_NO_MIC=1

gateway  14:12:35.855  samantha-kiosk: serving /ws on :7777
gateway  14:12:40.703  WARNING samantha-vision probe: inject_message -> True
widget   ← A órdenes.
widget     dice: A órdenes.
```

He spoke, unprompted, in his own words, in Spanish — and **not** the
literal probe text. The widget log has no `→` line: nothing was sent from
the strip. CosyVoice loaded its reference clip on the same turn, so the
words were also synthesised in his voice.

## 6. Timing, which is tighter than it looks

Registration ran at ~14:12:35.70, the kiosk adapter finished connecting
at 14:12:35.855, and the injector is installed only after **all**
adapters connect. Five seconds cleared it here by roughly 4.8 s, but that
margin is a property of this box's startup, not a guarantee: a slow
adapter (a network platform, a retrying one) pushes
`_install_plugin_message_injector()` arbitrarily later, and an injection
attempted before it returns `False` and is simply lost.

**Task 2 should not use a fixed delay.** `ctx.inject_message()` returns a
boolean; treat `False` as "not yet" and retry, rather than firing once
into a gateway that is not listening. The same applies to the
never-spoken-to-the-strip case in §2 — that one never becomes `True`
until the user speaks, so a retry must be bounded or the detection
dropped.
