# Probe: do plugins and toolsets resolve per Hermes profile?

**Question this answers** (task 1 of
`docs/superpowers/specs/2026-09-05-identidad-por-persona-design.md`):
with `gateway.multiplex_profiles: true` serving two profiles from one
gateway process, does each profile's inbound traffic see only the
plugins and tools **that profile's own `config.yaml` enables** — so
that, concretely, a daughter's profile never loads `terminal` or
`jarvis_vision` even though the parents' profile does, in the same
process? Tasks 7, 11 and 12 of that plan assume the answer is yes.

**Verdict: YES**, established by reading
`.hermes/src/gateway/run.py`, `.hermes/src/hermes_cli/plugins.py` and
`.hermes/src/tools/registry.py`. Not exercised live with two real
profiles — this box has only one profile (`default`), so the
multiplex path itself could not be driven end to end here (see
"What was NOT measured live" below). The verdict rests on static
reading of the pinned source, which is what step 3 of the task brief
asked for when a live two-profile rig does not exist.

## The probe

`Hermes/plugins/jarvis/tools/probe_profiles.py`, modelled on
`Hermes/plugins/jarvis_teacher/tools/probe_busqueda.py`. Run:

```
PYTHONNOUSERSITE=1 widget/.venv/bin/python \
    Hermes/plugins/jarvis/tools/probe_profiles.py
```

It printed without raising, confirming only static, harmless facts
about this box (one profile, `default`, with its own `config.yaml`;
the shape of `profile_routing.match_profile_route`). It does not call
`discover_plugins()` and does not ask Hermes a question, so — unlike
`probe_busqueda.py` — it did **not** trigger `jarvis_vision`'s camera
threads. The brief's own example code had an off-by-one
(`parents[3]` resolves to the nonexistent `Hermes/.hermes` from this
file's depth and fails importing `hermes_cli`); the committed probe
uses `parents[4]`, which is the repo root. `list_profiles()` returns
`ProfileInfo` dataclass instances rather than bare names, so the
"profiles on this box" section prints a full repr — harmless with one
profile (`sorted()` never compares), but worth knowing before trusting
that block verbatim on a box with two or more profiles.

## The chain of evidence, source to source

### 1. A profile is a full HERMES_HOME, and the gateway enumerates which ones it serves

`_multiplex_profile_homes` (`gateway/run.py:2204`):

```python
def _multiplex_profile_homes(config: object) -> list[tuple[str, "Path"]]:
    """Return the authoritative profile set for one multiplex gateway config."""
    from hermes_cli.profiles import profiles_to_serve

    return list(
        profiles_to_serve(
            multiplex=True,
            profile_allowlist=getattr(config, "multiplex_profile_allowlist", None),
        )
    )
```

### 2. An inbound message is routed to one profile by platform + chat_id, per turn

`_resolve_profile_home_for_source` (`gateway/run.py:27985`) resolves,
in order: `source.profile` (stamped by the `/p/<profile>/` URL prefix
or `profile_routes` matching), then `_profile_name_for_source` (which
calls `gateway.profile_routing.match_profile_route` against
`platform` + `chat_id` + optional `guild_id`/`thread_id`), then the
active profile as a fallback. This is the mechanism already recorded
as established (`gateway/profile_routing.py`,
`GatewayRunner._profile_name_for_source`).

### 3. The whole agent turn is run inside a context-local Hermes-home override for that profile

`_run_agent` (`gateway/run.py:27895`):

```python
profile_home = self._resolve_profile_home_for_source(source)
with _profile_runtime_scope(profile_home):
    return await self._run_agent_inner(
        message, context_prompt, history, source, session_id, ...
    )
```

`_profile_runtime_scope` (`gateway/run.py:2217`) installs
`set_hermes_home_override(str(profile_home))` — a `ContextVar`
(`hermes_constants.py:17`) — for the duration of the turn, plus the
profile's own secret scope. The docstring states the intent plainly:

> "Scope config/skills/memory AND credentials to a profile for one
> turn."

The same wrapper is used for platform-event dispatch
(`_make_default_profile_platform_event_handler`, `run.py:15689`) and
for plugin discovery at adapter startup (`_start_one_profile_adapters`,
`run.py:15228`) — the same seam covers "the plugins this profile
loads" and "the turn this profile runs," not two different mechanisms
that could drift apart.

### 4. Plugin discovery is keyed per resolved Hermes home, not process-global

`hermes_cli/plugins.py:5634`, `get_plugin_manager()`:

> "Managers are cached per resolved home so repeated calls within the
> same profile reuse discovery state ... while a profile switch — via
> `HERMES_HOME` or the context-local `set_hermes_home_override()` —
> gets its own manager with its own plugin submodules, instead of
> silently inheriting another profile's context engine or stale
> relative-import state."

`_plugin_home_key()` (`plugins.py:5584`) resolves
`get_hermes_home()`, which itself resolves the context-local override
before the environment variable (`hermes_constants.py:114`,
`get_hermes_home`: "Resolution order: context-local override ... →
`HERMES_HOME` env var → the platform-native default"). So a profile
served under `_profile_runtime_scope` gets **its own** `PluginManager`
instance, and `_start_one_profile_adapters` calls `discover_plugins()`
precisely while that override is active
(`with _profile_runtime_scope(profile_home): ... discover_plugins()`,
`run.py:15234-15238`) — each profile's plugin set is discovered from
that profile's own `<home>/plugins` and its own `config.yaml`'s
`plugins.entries.*.enabled` gates, not the process's launch home.

### 5. Registered tools are namespaced by that same per-home scope key, and merged rather than shared

`PluginContext.register_tool` (`plugins.py:1742-1766`) registers into
the global tool registry with `scope=self._manager.scope_key` — the
resolved-home key of the manager that discovered the plugin. In
`tools/registry.py`, `ToolRegistry.__init__` (line 433) documents the
storage shape directly:

> "Plugin registrations are overlays keyed by resolved HERMES_HOME. A
> profile sees its own overlay first and then the global built-ins."

And the read path, `_merged_tools` (`registry.py:469`):

```python
def _merged_tools(self, scope: Optional[str] = None) -> Dict[str, ToolEntry]:
    """Return global tools overlaid with one profile's plugin tools."""
    active_scope = scope or self.current_scope_key()
    merged = dict(self._tools)
    merged.update(self._scoped_tools.get(active_scope, {}))
    return merged
```

`current_scope_key()` (`registry.py:465`) is `hermes_home_key()` with
no argument, so it too resolves through the same context-local
override installed by `_profile_runtime_scope`. `get_definitions()`
(`registry.py:1025`), which builds the OpenAI-format tool schema list
handed to the LLM for a turn, calls `self._snapshot_entries()` →
`self._merged_tools()` with no explicit scope — so during a turn
scoped to profile A, it returns the global built-ins plus **only**
profile A's `_scoped_tools` overlay. Profile B's plugin-registered
tools (its own `terminal`, its own `jarvis_vision` camera tool) live
under a different scope key and are invisible to A's turn, and vice
versa.

## What each half of the question rests on — quoted, per the brief's ask

- **"the exact function that loads plugins for a profile, and its
  input is the profile home, not a global config":**
  `hermes_cli.plugins.get_plugin_manager()` — "Managers are cached per
  resolved home ... a profile switch ... gets its own manager with its
  own plugin submodules" (`plugins.py:5634-5642`), fed by
  `_plugin_home_key()` → `get_hermes_home()`, whose "resolution order"
  is "context-local override ... → HERMES_HOME env var ... "
  (`hermes_constants.py:114-120`) — the override being exactly what
  `_profile_runtime_scope(profile_home)` sets per profile
  (`run.py:2217-2250`).
- **"one quoted line of evidence for each half":** input is the
  profile home — `manager = PluginManager(scope_key=hermes_home_key(current_home))`
  (`plugins.py:5661`), where `current_home = _plugin_home_key()`
  resolves the profile's overridden home, never a global config
  object. Output is scoped, not global — `"Plugin registrations are
  overlays keyed by resolved HERMES_HOME. A profile sees its own
  overlay first and then the global built-ins."`
  (`tools/registry.py:439-441`).

## What was NOT measured live

This box has exactly one Hermes profile (`default`); there is no
second profile to multiplex against it, so:

- No live run actually served two profiles at once and confirmed a
  camera tool or `terminal` was absent from one profile's tool
  definitions while present in the other's.
- `gateway.multiplex_profiles` has never been turned on and exercised
  on this box.

A live experiment, if the design wants one before trusting this
further: create a second profile with `hermes profile create test`,
enable a plugin in only one profile's `config.yaml` (e.g. a
toolset-free stub plugin, not the real cameras, to avoid the
`jarvis_vision` side effect noted in `probe_busqueda.py`), turn on
`gateway.multiplex_profiles` with both profiles served, send one
message routed to each profile (via `profile_routes` or two
credentials), and inspect `registry.get_definitions()` — or simpler,
the tool list actually sent to the LLM in the request log — for each
turn. That is a task 7/11-sized rig, not this probe; this probe
answered what it could from source, which was enough to reach a
verdict without building that rig.

## Conclusion for the plan

The plan's tool boundary — a profile's `config.yaml` decides what that
profile's turns can call, enforced by the pinned Hermes' own
per-home plugin manager and per-home tool-registry overlay — is
real in this source, not aspirational. Tasks 7, 11 and 12 may proceed
on that basis. The one caveat worth carrying forward: it is verified
by reading, not by a live two-profile run: build the live rig above
before treating "daughter's profile has no terminal" as tested rather
than designed.
