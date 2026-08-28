# The kiosk becomes JARVIS — design

> **Status:** design, agreed with the user 2026-08-28. It reverses the
> naming half of CLAUDE.md §12 (2026-08-23, "Samantha becomes JARVIS"),
> which decided the name would change **in prose only**. It does not
> reverse the rest of that entry: the persona, the voice and the repo
> name stand.
> The implementation plan follows from this document.

## What "kiosk" still means, and why it goes

The word is a fossil of v3. There is no kiosk: no Chromium, no
full-screen appliance, no openbox. There is a strip along the bottom of
somebody's desktop and a person who talks to it. The name survived
because it was cheap to leave alone — 2026-08-23 measured that renaming
"would touch every file, every unit and every env var to buy nothing".

That measurement was about the *code*. What the user asked for on
2026-08-28 is narrower and different: the **concept**. Three
identifiers carry it, and all three are things Hermes reasons about
rather than things Python imports:

| | now | after |
|---|---|---|
| Hermes platform | `samantha_kiosk` | `jarvis` |
| plugin id | `samantha-kiosk` | `jarvis` |
| chat / channel | `kiosk` / "Kiosk" | `jarvis` / "JARVIS" |
| session key | `agent:main:samantha_kiosk:dm:kiosk` | `agent:main:jarvis:dm:jarvis` |
| GTK window title | "Samantha" | "JARVIS" |

The package directory moves with them — `git mv` to
`Hermes/plugins/jarvis/` — because Hermes discovers plugins by the name
of the symlink in `.hermes/home/plugins/`, and a symlink called `jarvis`
pointing at a directory called `samantha_kiosk` is a lie told at the one
place an operator looks first. One copy of the adapter, history
preserved by `git mv`, no twin left behind to drift.

## The silent failure this must not cause

`samantha_vision/alert.py:35` and `samantha_code/voz.py:24` each hold
the session key **written out by hand**:

    KIOSK_SESSION_KEY = "agent:main:samantha_kiosk:dm:kiosk"

That constant is how a camera sighting and a coding assistant's question
become a turn. Change the platform without changing those two lines and
`ctx.inject_message()` returns **`True`** against a session that no
longer exists — CLAUDE.md §12 (2026-08-24) records this precisely: a
missing session row comes back `True`, because the lookup happens inside
the coroutine after the task is scheduled. Hermes logs "Plugin message
injection was not routed" and nothing else fails. The cameras would go
quiet and the strip would look perfectly healthy.

So the rename is not "find and replace `samantha_kiosk`". It is: change
the platform in **one** place, and change every place that repeats it by
hand, of which there are five.

## The package

`git mv Hermes/plugins/samantha_kiosk Hermes/plugins/jarvis`, then
inside it:

- **`plugin.yaml`** — `name: jarvis`, `label: JARVIS`. The manifest
  prose that explains how this plugin fails silently is rewritten in the
  new terms rather than left describing a kiosk.
- **`__init__.py`** — `register_platform(name="jarvis", label="JARVIS")`.
  The `_platform_hint()` body is persona and surface, and mentions no
  kiosk; it is untouched. `emoji`, `pii_safe`, `max_message_length` are
  untouched.
- **`adapter.py`** — `name = "jarvis"` (`:221`), `Platform("jarvis")`
  (`:229`), `chat_id="jarvis"` (`:730`), `get_chat_info` returning
  `{"name": "JARVIS", "type": "dm"}` (`:379`), the class `KioskAdapter`
  → `JarvisAdapter`, and the log/error prefixes `samantha-kiosk:` →
  `jarvis:`. The `/platform resume samantha_kiosk` hint in the
  port-in-use error names `jarvis` too, or it sends the operator to a
  platform that does not exist.
- **The four environment variables** become `JARVIS_PORT`,
  `JARVIS_TURN_TIMEOUT`, `JARVIS_ALLOWED_USERS`,
  `JARVIS_ALLOW_ALL_USERS`, **each falling back to its
  `SAMANTHA_KIOSK_*` name**. Verified 2026-08-28: none of them is set in
  any unit or drop-in on this box, so all four run on their
  defaults and nothing depends on the old names today. The fallback is
  one `os.environ.get(new) or os.environ.get(old)` per variable and
  costs nothing; without it a box that *had* set one would lose its
  allowlist silently, which is the same class of failure as the section
  above.

`SAMANTHA_WIDGET_*`, `samantha_widget`, the systemd units and the repo
name are **out of scope** and stay exactly as they are. That is the
user's decision of 2026-08-28 and it keeps this change to one gateway
restart instead of a reinstall.

## The three that point at it

- `samantha_vision/__init__.py:49` and `samantha_code/__init__.py:47` —
  `KIOSK_PLATFORM = "samantha_kiosk"` becomes
  `JARVIS_PLATFORM = "jarvis"`. Four call sites between them, all
  `Platform(...)` lookups into `runner.adapters`. A stale value here
  does not raise: the lookup returns `None` and the photo, the live view
  or the console line is simply dropped.
- `samantha_vision/alert.py:35` and `samantha_code/voz.py:24` — the
  hand-written session key, per the section above.
- `samantha_vision/tests/test_alert.py:62` pins the old key and moves
  with it. That test is the only automated thing standing between this
  change and the silent failure, so it is updated deliberately, not
  by sed.
- `setup-runtime.sh:90` — the symlink loop
  (`for plugin in samantha_voice samantha_kiosk samantha_vision`) learns
  `jarvis`. A fresh box that misses this gets a gateway with no platform
  and a strip with nothing to talk to.

## Config, and the state that already exists

**Config**, in both the tracked `Hermes/samantha-config.yaml` and the
git-ignored live `.hermes/home/config.yaml`: `plugins.enabled`,
`plugins.entries`, `platform_toolsets.samantha_kiosk` →
`platform_toolsets.jarvis`, `platforms.samantha_kiosk` →
`platforms.jarvis`, and the `home_channel` block (`platform: jarvis`,
`chat_id: jarvis`, `name: JARVIS`). Remember the trap of §12
(2026-08-26): `apply-config.sh` deep-merges the tracked file over the
live one and **replaces lists wholesale**, so the two must be changed
together or the next apply re-asserts the old name.

**State.** Measured 2026-08-28 on the live `state.db`: 32 rows in
`sessions` carry the key, `delivery_obligations` has 459 rows (439
`delivered`, 20 `abandoned` — no queue is pending), `gateway_routing`
has 1. The 1,750 rows of `messages` hang off `session_id`, **not** off
the key, so neither they nor the ten FTS tables and their six triggers
are touched. The migration is therefore small enough to be honest about:

1. `cp state.db state.db.bak-20260828` — with the gateway stopped.
2. `UPDATE sessions SET session_key`, and rewrite `origin_json`
   (`platform`, `chat_id`, `chat_name`) and `display_name`.
3. `UPDATE delivery_obligations SET session_key, platform`.
4. `UPDATE gateway_routing` — the key column and the `platform`,
   `display_name`, `origin` fields inside its JSON blob.

It ships as a one-shot script under `Hermes/`, not as inline SQL in a
plan step, so that it can be read before it is run and re-run after a
restore.

## The widget

`window.py:101` sets the title to "Samantha"; it becomes "JARVIS". The
widget knows the port and the protocol, never the platform name, so
there is nothing else — but `xwininfo -name Samantha` appears in
CLAUDE.md §5, in `window.py:371` and in the verification docs, and every
one of those must move in the same commit. A stale `xwininfo -name`
answers "No window with name … exists!" with the strip on screen and
running, which cost an afternoon on 2026-08-25.

## Documentation, and the history that stays wrong on purpose

CLAUDE.md (§0's diagram, §3's tree, §5's commands, §9's table, §10's
glossary) and a new dated entry in §12 recording this decision and its
cost. AGENTS.md, README.md, PROGRESS.md.

**The plans and specs under `docs/superpowers/` are not touched.** They
are the record of what happened, and a plan from 2026-08-22 that says
"kiosk" is not wrong — it is what was built that day. Rewriting them
would make the archive agree with the present at the price of no longer
being an archive. The glossary keeps its `Chromium kiosk` entry and
gains a line saying the platform was called `samantha_kiosk` until
2026-08-28, so a reader meeting the word in an old document knows what
it was.

## Testing

- `pytest` for the moved plugin, plus `samantha_vision` and
  `samantha_code`, which hold the constants above.
- `ruff check` and `ruff format --check`.
- `git grep -n 'samantha_kiosk\|samantha-kiosk'` must return only
  `docs/superpowers/` (the archive), the glossary line, and the §12
  entry. Anything else is a rename that was missed.
- **Live, and this is the part no test covers:** start the gateway,
  confirm the platform registers as `jarvis`, `xwininfo -name JARVIS`,
  one spoken turn through the strip, and **one camera alert arriving**.
  The alert is not optional: it is the only path that exercises the
  hand-written session key, which is the failure this whole document is
  organised around.

## Order, and how to get back

One commit per task — the package, the variables, the constants that
point at it, the clean-box scripts, the window, the migration script,
the docs — and the state migration itself last, after all of them, with
its backup. Seven reviewable commits rather than one large one; the way
back is a revert of the range plus the backup. If the platform fails to register, the way
back is `git revert` plus restoring `state.db.bak-20260828` — which is
why the migration is last and why the backup is taken with the gateway
stopped rather than under it.

The persona is unaffected, but the system prompt is frozen when the
session is born (§7), and the session key changes underneath it here.
`/new` then `/approve` through the strip after the migration, or he
answers the first turn as whatever he was.

## Cost, stated plainly

- **`git grep samantha_kiosk` stops being the way to find this code.**
  The archive keeps the old word and the running system uses the new
  one, so anyone reading a 2026-08 plan alongside the tree has to hold
  both names. The glossary line is the whole mitigation.
- **The code and the concept now disagree about "samantha".** The
  platform is `jarvis` and it lives in a repo called `os1-samantha`,
  next to `samantha_widget`, started by `samantha-widget.service`. That
  mismatch existed before in prose and is now sharper: two of the four
  plugins keep the old prefix, one does not.
- **A box that already ran this project needs the migration**, or it
  starts with an empty session and no home channel — and the missing
  home channel eats the first turn silently (§5).

## What this is not

Not a rename of `samantha_widget`, the `SAMANTHA_WIDGET_*` variables,
the systemd units, `~/.samantha/`, or the repository. Not a change to
the wire protocol between the strip and the gateway: `protocol.py` is
untouched, and a widget built before this change talks to a gateway
built after it. Not a change to the persona, the voice, the cameras or
what he can do.
