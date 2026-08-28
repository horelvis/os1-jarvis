# The kiosk becomes JARVIS — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps
> use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename the concept "kiosk" to JARVIS everywhere the running
system reasons about it — the Hermes platform, the plugin, the chat, the
session key and the window title — without touching the widget package,
the `SAMANTHA_*` variables, the systemd units or the repository name.

**Architecture:** One platform plugin moves (`git mv`) from
`Hermes/plugins/samantha_kiosk/` to `Hermes/plugins/jarvis/` and is
renamed inside. Four places outside it repeat the platform name or the
session key by hand and must move in the same change or the cameras go
quiet silently. The 32 existing sessions in `state.db` are migrated by a
one-shot script, last, with a backup.

**Tech Stack:** Python 3.12, pytest, ruff, Hermes Agent (pinned in
`.hermes/`), SQLite, GTK4 (one line), bash.

**Spec:** `docs/superpowers/specs/2026-08-28-jarvis-platform-design.md`
— read it first. It is organised around the silent failure this change
can cause; this plan implements it.

## Global Constraints

- **The platform name is exactly `jarvis`.** Lowercase, no prefix, no
  underscore. It appears in `register_platform(name=...)`,
  `Platform(...)`, the config keys and the session key.
- **The chat id is exactly `jarvis`** and the chat name is exactly
  `JARVIS`. Together they make the session key
  `agent:main:jarvis:dm:jarvis`.
- **The plugin label is exactly `JARVIS`** (was `Samantha (kiosk)`).
- **Tests run from the repo root with the widget's interpreter:**
  `PYTHONNOUSERSITE=1 widget/.venv/bin/python -m pytest <path> -q`.
  The `pytest` on `PATH` lacks `loguru` and fails at collection.
  Baseline measured 2026-08-28: **324 passed** across the three plugin
  test directories.
- **Out of scope, do not touch:** `widget/samantha_widget/` (except the
  one `set_title` line in Task 5), `SAMANTHA_WIDGET_*`, `systemd/`,
  `~/.samantha/`, the repository name, `protocol.py` (the wire contract
  is unchanged).
- **Do not touch `docs/superpowers/plans/` or any spec older than
  today.** They are the archive; they keep saying "kiosk" on purpose.
- Code and comments in English; user-facing strings in Spanish
  (CLAUDE.md §6, §2.9).
- Run `ruff check Hermes/ widget/` and `ruff format --check Hermes/
  widget/` before each commit.
- One commit per task, message in the house style (a plain statement of
  what changed, not a category prefix alone). **This departs from the
  spec's "one commit for the code, config and docs"**: seven reviewable
  commits beat one large one, and the way back is a revert of the range
  rather than of a single hash. The spec was amended to match.

---

### Task 1: The package becomes `jarvis`

The rename of the platform identity itself. Note that **no test fixes
the platform name today** — `grep -rn 'samantha_kiosk' tests/` finds
only import paths and one error code — so this task starts by writing
the test that should have existed, watching it fail, and then making it
pass.

**Files:**
- Move: `Hermes/plugins/samantha_kiosk/` → `Hermes/plugins/jarvis/` (with `git mv`)
- Modify: `Hermes/plugins/jarvis/plugin.yaml`
- Modify: `Hermes/plugins/jarvis/__init__.py`
- Modify: `Hermes/plugins/jarvis/adapter.py`
- Test: `Hermes/plugins/jarvis/tests/test_adapter.py`, `tests/test_hint.py`, `tests/test_protocol.py`

**Interfaces:**
- Consumes: nothing (first task).
- Produces: module `Hermes.plugins.jarvis` exporting `JarvisAdapter`
  (class attribute `name = "jarvis"`) and `register(ctx)`. The adapter's
  `get_chat_info()` returns `{"name": "JARVIS", "type": "dm"}` and
  `_handle_chat()` builds its source with `chat_id="jarvis"`,
  `chat_name="JARVIS"`. Task 3 depends on the platform string `"jarvis"`
  and on the resulting session key `agent:main:jarvis:dm:jarvis`.

- [ ] **Step 1: Move the package, keeping git history**

```bash
cd /home/nexus/git/os1-samantha
git mv Hermes/plugins/samantha_kiosk Hermes/plugins/jarvis
find Hermes/plugins/jarvis -name __pycache__ -type d -exec rm -rf {} +
```

- [ ] **Step 2: Repoint the imports so the suite runs again**

The tests import the package by path. Update those three import sites
(`test_adapter.py:9`, `:53`, `:809`, `:869`, `:903`; `test_protocol.py:6`;
`test_hint.py:13`, `:50`) and the class name in one pass:

```bash
cd /home/nexus/git/os1-samantha
sed -i 's/Hermes\.plugins\.samantha_kiosk/Hermes.plugins.jarvis/g; s/samantha_kiosk\b/jarvis/g; s/KioskAdapter/JarvisAdapter/g' \
  Hermes/plugins/jarvis/tests/*.py
```

- [ ] **Step 3: Write the failing test that fixes the identity**

Append to `Hermes/plugins/jarvis/tests/test_adapter.py`. This is the
test whose absence let the name drift for four months:

```python
def test_the_platform_is_called_jarvis():
    """The name the gateway registers, the session key, and the chat.

    None of the three was pinned before 2026-08-28, which is why the
    rename had to start here: `samantha_kiosk` could have been changed
    in one of them and left in the other two with every test green.
    """
    adapter = JarvisAdapter(config={})
    assert JarvisAdapter.name == "jarvis"
    assert adapter.platform.value == "jarvis"


def test_the_chat_is_called_jarvis():
    import asyncio

    adapter = JarvisAdapter(config={})
    info = asyncio.run(adapter.get_chat_info("ignored"))
    assert info == {"name": "JARVIS", "type": "dm"}
```

- [ ] **Step 4: Run them and watch them fail**

```bash
cd /home/nexus/git/os1-samantha
PYTHONNOUSERSITE=1 widget/.venv/bin/python -m pytest \
  Hermes/plugins/jarvis/tests/test_adapter.py -q -k jarvis
```

Expected: FAIL — `assert 'samantha_kiosk' == 'jarvis'`. If instead it
fails on `Platform` not resolving, read the module docstring of
`adapter.py`: `Platform` is stubbed outside a gateway, and the stub
carries `.value`.

- [ ] **Step 5: Rename the identity inside the adapter**

In `Hermes/plugins/jarvis/adapter.py`:

- `:220` — `class KioskAdapter(BasePlatformAdapter):` → `class JarvisAdapter(BasePlatformAdapter):`
- `:221` — `name = "samantha_kiosk"` → `name = "jarvis"`
- `:229` — `platform = Platform("samantha_kiosk")` → `platform = Platform("jarvis")`
- `:379` — `return {"name": "Kiosk", "type": "dm"}` → `return {"name": "JARVIS", "type": "dm"}`
- `:730-731` — `chat_id="kiosk", chat_name="Kiosk",` → `chat_id="jarvis", chat_name="JARVIS",`
- `:331` — the fatal error code `"samantha_kiosk_port_in_use"` → `"jarvis_port_in_use"`. **Step 2's sed did NOT touch this string**: its pattern is `samantha_kiosk\b`, and there is no word boundary between `kiosk` and `_`. The three assertions at `test_adapter.py:215`, `:246`, `:250` still say the old code, so change them too:
  ```bash
  sed -i 's/samantha_kiosk_port_in_use/jarvis_port_in_use/g' \
    Hermes/plugins/jarvis/adapter.py Hermes/plugins/jarvis/tests/test_adapter.py
  ```
- `:332-335` — the operator hint text: `SAMANTHA_KIOSK_PORT` stays for now (Task 2 renames it) but `/platform resume samantha_kiosk` → `/platform resume jarvis`
- every log prefix `samantha-kiosk:` → `jarvis:` (`:338`, `:343`, `:412`, `:446`, `:725`, and any other — `grep -n 'samantha-kiosk:' adapter.py`)
- `:623` — `def _origin_is_the_kiosk` → `def _origin_is_the_strip`, and its call sites
- the module docstring's `Platform("samantha_kiosk")` reference (`:1`, `:21`)

- [ ] **Step 6: Rename the identity in `__init__.py` and the manifest**

`Hermes/plugins/jarvis/__init__.py`:

```python
"""jarvis — the strip on the desktop, as a Hermes platform."""
```

- the import and `__all__`: `KioskAdapter` → `JarvisAdapter` (`:10`, `:13`)
- `:166` — `adapter_factory=lambda cfg: JarvisAdapter(cfg)`
- `register_platform(name="jarvis", label="JARVIS", ...)`
- the docstring of `register()` says "Register the kiosk platform" →
  "Register the JARVIS platform", and its prose about a denied *kiosk*
  message becomes a denied *JARVIS* message

`Hermes/plugins/jarvis/plugin.yaml`:

```yaml
name: jarvis
label: JARVIS
kind: platform
version: 1.0.0
description: >
  Holds the single WebSocket the strip talks over. Text only in this
  version; audio arrives in plan 3b.
```

Rewrite the four numbered failure notes in that manifest's comment block
in the new terms (`a denied JARVIS turn`, `JARVIS_TURN_TIMEOUT`, etc.).
Leave note 4 ("THE VOICE IS NOT HERS YET") alone — it is historical and
already marked out of scope there.

- [ ] **Step 7: Run the whole package suite**

```bash
cd /home/nexus/git/os1-samantha
PYTHONNOUSERSITE=1 widget/.venv/bin/python -m pytest Hermes/plugins/jarvis/tests -q
```

Expected: PASS, and two tests more than before the move.

- [ ] **Step 8: Prove nothing else still imports the old path**

```bash
cd /home/nexus/git/os1-samantha
grep -rn 'samantha_kiosk\|KioskAdapter' Hermes/plugins/jarvis/ && echo "STILL THERE" || echo "clean"
```

Expected: `clean`.

- [ ] **Step 9: Lint and commit**

```bash
cd /home/nexus/git/os1-samantha
ruff check Hermes/ && ruff format --check Hermes/
git add -A Hermes/plugins/jarvis
git commit -m "refactor(jarvis): the kiosk platform is called jarvis, and a test says so

No test fixed the platform name, the chat name or the session key
before today, which is how `samantha_kiosk` could have been changed in
one place and left in another with everything green. The two new tests
in test_adapter.py are the ones that should have existed."
```

---

### Task 2: The four environment variables become `JARVIS_*`

**Files:**
- Modify: `Hermes/plugins/jarvis/adapter.py:169-177`
- Modify: `Hermes/plugins/jarvis/plugin.yaml` (the `optional_env` block)
- Test: `Hermes/plugins/jarvis/tests/test_adapter.py`

**Interfaces:**
- Consumes: `JarvisAdapter` from Task 1.
- Produces: module constants `_ENV_PORT = "JARVIS_PORT"`,
  `_ENV_TURN_TIMEOUT = "JARVIS_TURN_TIMEOUT"`,
  `ENV_ALLOWED_USERS = "JARVIS_ALLOWED_USERS"`,
  `ENV_ALLOW_ALL_USERS = "JARVIS_ALLOW_ALL_USERS"`, plus
  `_LEGACY_ENV: dict[str, str]` mapping each new name to its
  `SAMANTHA_KIOSK_*` predecessor, and `_env(name: str) -> str | None`
  which reads the new name and falls back to the old one.

- [ ] **Step 1: Write the failing tests**

Append to `Hermes/plugins/jarvis/tests/test_adapter.py`:

```python
def test_the_port_comes_from_the_new_variable(monkeypatch):
    monkeypatch.setenv("JARVIS_PORT", "7801")
    assert JarvisAdapter(config={})._configured_port == 7801


def test_the_old_variable_still_works(monkeypatch):
    """A box that set SAMANTHA_KIOSK_PORT before 2026-08-28 keeps it.

    Nothing on this machine sets any of the four (verified 2026-08-28:
    no unit, no drop-in), so this protects a box we cannot see rather
    than this one.
    """
    monkeypatch.delenv("JARVIS_PORT", raising=False)
    monkeypatch.setenv("SAMANTHA_KIOSK_PORT", "7802")
    assert JarvisAdapter(config={})._configured_port == 7802


def test_the_new_variable_wins_over_the_old(monkeypatch):
    monkeypatch.setenv("JARVIS_PORT", "7803")
    monkeypatch.setenv("SAMANTHA_KIOSK_PORT", "7804")
    assert JarvisAdapter(config={})._configured_port == 7803
```

- [ ] **Step 2: Run them and watch them fail**

```bash
cd /home/nexus/git/os1-samantha
PYTHONNOUSERSITE=1 widget/.venv/bin/python -m pytest \
  Hermes/plugins/jarvis/tests/test_adapter.py -q -k variable
```

Expected: FAIL — the first with `7777 != 7801`.

- [ ] **Step 3: Implement the names and the fallback**

Replace `adapter.py:169-177` with:

```python
# Env var names, declared in plugin.yaml's optional_env. Config-dict keys
# stay the fallback so unit tests can construct an adapter without
# touching the process environment.
_ENV_PORT = "JARVIS_PORT"
_ENV_TURN_TIMEOUT = "JARVIS_TURN_TIMEOUT"

# Authorization, read by gateway/authz_mixin.py via the registry entry
# that __init__.py's register() declares. Kept here so the name lives
# next to the other two and register() cannot drift from the adapter.
ENV_ALLOWED_USERS = "JARVIS_ALLOWED_USERS"
ENV_ALLOW_ALL_USERS = "JARVIS_ALLOW_ALL_USERS"

# The names these four had while the platform was called samantha_kiosk.
# Nothing on the box that made this change set any of them — verified
# 2026-08-28 across every unit and drop-in — so this map protects a
# machine we cannot see. Losing an allowlist silently is the same class
# of failure as the session key in samantha_vision/alert.py: it does not
# raise, it just stops answering.
_LEGACY_ENV = {
    _ENV_PORT: "SAMANTHA_KIOSK_PORT",
    _ENV_TURN_TIMEOUT: "SAMANTHA_KIOSK_TURN_TIMEOUT",
    ENV_ALLOWED_USERS: "SAMANTHA_KIOSK_ALLOWED_USERS",
    ENV_ALLOW_ALL_USERS: "SAMANTHA_KIOSK_ALLOW_ALL_USERS",
}


def _env(name: str) -> Optional[str]:
    """The new variable, or the one it replaced. Never raises."""
    return os.getenv(name) or os.getenv(_LEGACY_ENV.get(name, ""), None)
```

Then replace every `os.getenv(_ENV_PORT)` / `os.getenv(_ENV_TURN_TIMEOUT)`
with `_env(...)` (`grep -n 'os.getenv(_ENV' adapter.py`), and in
`__init__.py`'s `register()` change
`os.environ.setdefault(ENV_ALLOWED_USERS, DEFAULT_USER_ID)` to set the
default only when neither name is present:

```python
    if not _env(ENV_ALLOWED_USERS):
        os.environ.setdefault(ENV_ALLOWED_USERS, DEFAULT_USER_ID)
```

importing `_env` alongside the other names at the top of `__init__.py`.

- [ ] **Step 4: Update the error text and the manifest**

In `adapter.py`, the port-in-use message now names `JARVIS_PORT`. In
`plugin.yaml`, rename the four `optional_env` entries and their Spanish
prompts, e.g.:

```yaml
  - name: JARVIS_PORT
    description: "Puerto donde se sirve el WebSocket de JARVIS (por defecto 7777)"
    prompt: "Puerto de JARVIS"
    password: false
```

- [ ] **Step 5: Run the suite**

```bash
cd /home/nexus/git/os1-samantha
PYTHONNOUSERSITE=1 widget/.venv/bin/python -m pytest Hermes/plugins/jarvis/tests -q
```

Expected: PASS.

- [ ] **Step 6: Lint and commit**

```bash
cd /home/nexus/git/os1-samantha
ruff check Hermes/ && ruff format --check Hermes/
git add -A Hermes/plugins/jarvis
git commit -m "refactor(jarvis): the four switches carry his name, and answer to the old one

Nothing on this box sets any of them, so the fallback protects a
machine we cannot see rather than this one. An allowlist that goes
missing does not raise — it stops answering."
```

---

### Task 3: The four that point at it

The task the whole spec is organised around. Two plugins hold the
platform name and the session key **written out by hand**, and getting
them wrong produces no error anywhere: `ctx.inject_message()` returns
`True` against a session that does not exist (CLAUDE.md §12,
2026-08-24), so the cameras go quiet while the strip looks healthy.

**Files:**
- Modify: `Hermes/plugins/samantha_vision/__init__.py:49` (+ call sites `:165`, `:185`, `:225`)
- Modify: `Hermes/plugins/samantha_vision/alert.py:35`
- Modify: `Hermes/plugins/samantha_code/__init__.py:47` (+ call site `:64`)
- Modify: `Hermes/plugins/samantha_code/voz.py:24`
- Test: `Hermes/plugins/samantha_vision/tests/test_alert.py:62`

**Interfaces:**
- Consumes: the platform string `"jarvis"` and the session key
  `agent:main:jarvis:dm:jarvis` produced by Task 1.
- Produces: `JARVIS_PLATFORM = "jarvis"` in both plugins (replacing
  `KIOSK_PLATFORM`) and `JARVIS_SESSION_KEY` (replacing
  `KIOSK_SESSION_KEY`) in `alert.py` and `voz.py`.

- [ ] **Step 1: Update the test that pins the key, and watch it fail**

In `Hermes/plugins/samantha_vision/tests/test_alert.py:62`:

```python
    assert session_key == "agent:main:jarvis:dm:jarvis"
```

Then:

```bash
cd /home/nexus/git/os1-samantha
PYTHONNOUSERSITE=1 widget/.venv/bin/python -m pytest \
  Hermes/plugins/samantha_vision/tests/test_alert.py -q
```

Expected: FAIL — `assert 'agent:main:samantha_kiosk:dm:kiosk' == 'agent:main:jarvis:dm:jarvis'`.

- [ ] **Step 2: Add the test `samantha_code` never had**

`voz.py` holds the same constant and nothing pins it. Append to
`Hermes/plugins/samantha_code/tests/test_voz.py` (create the file if it
does not exist, with the imports the sibling tests use):

```python
def test_the_voice_path_targets_the_jarvis_session():
    """The other hand-written copy of the session key.

    samantha_vision/alert.py has had a test since it was written;
    voz.py has not, and it injects on exactly the same key.
    """
    from Hermes.plugins.samantha_code.voz import JARVIS_SESSION_KEY

    assert JARVIS_SESSION_KEY == "agent:main:jarvis:dm:jarvis"
```

Run it; expected FAIL with `ImportError: cannot import name 'JARVIS_SESSION_KEY'`.

- [ ] **Step 3: Rename the platform constant in both plugins**

`Hermes/plugins/samantha_vision/__init__.py:49`:

```python
# The platform the photo is allowed to reach, and the only one. Not a
# config key on purpose: `MEDIA:` was rejected precisely because it let
# any adapter render an image, and a configurable destination would put
# that decision back (spec §3).
JARVIS_PLATFORM = "jarvis"
```

and its three call sites (`:165`, `:185`, `:225`), which read
`Platform(KIOSK_PLATFORM)`.

`Hermes/plugins/samantha_code/__init__.py:47`, keeping its comment:

```python
JARVIS_PLATFORM = "jarvis"
```

and its call site `:64`.

- [ ] **Step 4: Rename the session key in both plugins**

`Hermes/plugins/samantha_vision/alert.py:35`, with the comment above it
updated — it currently cites "every `samantha_kiosk` row in
`state.db`", which stops being true the moment Task 6 runs:

```python
# Where the strip's conversation lives. Measured against
# `gateway/session.py::build_session_key` and every `jarvis` row in
# `state.db` after the 2026-08-28 migration: the adapter always opens
# its source with chat_id="jarvis", chat_type="dm", so the key is a
# constant. A `/new` mints a fresh session_id under the SAME key, so it
# stays correct.
JARVIS_SESSION_KEY = "agent:main:jarvis:dm:jarvis"
```

`Hermes/plugins/samantha_code/voz.py:24`:

```python
JARVIS_SESSION_KEY = "agent:main:jarvis:dm:jarvis"
```

Update every use of both names in those two files
(`grep -n 'KIOSK_SESSION_KEY\|KIOSK_PLATFORM' Hermes/plugins/samantha_vision Hermes/plugins/samantha_code -r`).

- [ ] **Step 5: Run both suites**

```bash
cd /home/nexus/git/os1-samantha
PYTHONNOUSERSITE=1 widget/.venv/bin/python -m pytest \
  Hermes/plugins/samantha_vision/tests Hermes/plugins/samantha_code/tests -q
```

Expected: PASS.

- [ ] **Step 6: Prove no hand-written copy survives**

```bash
cd /home/nexus/git/os1-samantha
grep -rn 'samantha_kiosk' Hermes/plugins/ && echo "STILL THERE" || echo "clean"
```

Expected: `clean`. Any hit here is a silent-failure path.

- [ ] **Step 7: Lint and commit**

```bash
cd /home/nexus/git/os1-samantha
ruff check Hermes/ && ruff format --check Hermes/
git add -A Hermes/plugins
git commit -m "fix(vision,code): the two hand-written session keys follow the platform

Both inject into the strip's session by a key written out as a string.
Injecting into a session that does not exist returns True, so getting
this wrong is a camera that goes quiet with nothing in any log. voz.py
had no test pinning its copy; it has one now."
```

---

### Task 4: A clean box comes up as JARVIS

**Files:**
- Modify: `Hermes/setup-runtime.sh:90`
- Modify: `Hermes/samantha-config.yaml:15`, `:19`, `:26`, `:248`

**Interfaces:**
- Consumes: the plugin directory name `jarvis` from Task 1.
- Produces: a `setup-runtime.sh` that symlinks `jarvis` (and
  `samantha_code`), and a tracked config whose `plugins.enabled`,
  `plugins.entries` and `platform_toolsets` name `jarvis`.

- [ ] **Step 1: Fix the symlink loop, and the plugin it forgets**

`Hermes/setup-runtime.sh:90` lists three plugins and `samantha_code` is
not among them — a pre-existing bug (that plugin was symlinked by hand
on 2026-08-26; a fresh box would come up without it). Fix both in one
line:

```bash
for plugin in samantha_voice jarvis samantha_vision samantha_code; do
```

- [ ] **Step 2: Rename the ids in the tracked config**

In `Hermes/samantha-config.yaml`:
- `:19` — `    - samantha-kiosk` → `    - jarvis`
- `:26` — `    samantha-kiosk:` → `    jarvis:`
- `:248` — `  samantha_kiosk:` (under `platform_toolsets`) → `  jarvis:`
- `:15` — the comment "without samantha-kiosk the strip has nothing to
  talk to" → "without jarvis the strip has nothing to talk to"
- `:105`, `:118` — prose mentioning "the text-only kiosk adapter" and
  "the kiosk's 90 s watchdog" → "the text-only JARVIS adapter", "JARVIS'
  90 s watchdog"

- [ ] **Step 3: Verify the config still parses**

```bash
cd /home/nexus/git/os1-samantha
PYTHONNOUSERSITE=1 widget/.venv/bin/python -c "
import yaml, sys
c = yaml.safe_load(open('Hermes/samantha-config.yaml'))
assert 'jarvis' in c['plugins']['enabled'], c['plugins']['enabled']
assert 'jarvis' in c['plugins']['entries'], list(c['plugins']['entries'])
assert 'jarvis' in c['platform_toolsets'], list(c['platform_toolsets'])
assert 'samantha-kiosk' not in str(c) and 'samantha_kiosk' not in str(c)
print('config ok:', sorted(c['plugins']['enabled']))
"
```

Expected: `config ok: ['jarvis', 'samantha-code', 'samantha-vision', 'samantha-voice']`.

- [ ] **Step 4: Commit**

```bash
cd /home/nexus/git/os1-samantha
git add Hermes/setup-runtime.sh Hermes/samantha-config.yaml
git commit -m "chore(hermes): a fresh box symlinks jarvis, and samantha_code at last

The loop had three plugins in it and there are four — samantha_code was
symlinked by hand in August and a clean install would have come up
without it."
```

---

### Task 5: The window is called JARVIS

**Files:**
- Modify: `widget/samantha_widget/window.py:96-101`, `:371`
- Modify: `docs/verification-checklist.md` (every `xwininfo`/`xprop -name Samantha`)

**Interfaces:**
- Consumes: nothing.
- Produces: a GTK window whose title is `JARVIS`. Nothing reads the
  title programmatically; it is what `xwininfo -name` and `xprop -name`
  match on.

- [ ] **Step 1: Change the title and the comment that explains it**

`widget/samantha_widget/window.py:99-101`:

```python
        # Out of the alt-tab list and off the taskbar: this is furniture,
        # not an application the user switches to. The title is also what
        # `xprop -name JARVIS` looks for when verifying the states.
        self.set_title("JARVIS")
```

and the docstring at `:371` that says `xwininfo -name Samantha`.

- [ ] **Step 2: Update every verification command that names the window**

```bash
cd /home/nexus/git/os1-samantha
grep -rn 'name "\?Samantha"\?\|-name Samantha' docs/ widget/ --include='*.md' --include='*.py'
```

Change each to `JARVIS`. A stale one answers "No window with name …
exists!" with the strip on screen and running — measured 2026-08-25,
and it cost an afternoon.

- [ ] **Step 3: Run the widget suite**

```bash
cd /home/nexus/git/os1-samantha/widget
PYTHONNOUSERSITE=1 ./.venv/bin/python -m pytest tests -q
```

Expected: PASS (the title is not asserted anywhere; this proves nothing
broke).

- [ ] **Step 4: Lint and commit**

```bash
cd /home/nexus/git/os1-samantha
ruff check widget/ && ruff format --check widget/
git add widget/samantha_widget/window.py docs/
git commit -m "feat(widget): the window on the desktop is called JARVIS

Nothing reads the title; it is what xwininfo and xprop match on, so
every verification command that named Samantha moves with it."
```

---

### Task 6: The state migration

**Files:**
- Create: `Hermes/migrate-kiosk-to-jarvis.py`
- Test: `Hermes/tests/test_migrate_kiosk_to_jarvis.py`

**Interfaces:**
- Consumes: the session key `agent:main:jarvis:dm:jarvis` from Task 1.
- Produces: `migrate(db_path: Path) -> dict[str, int]`, returning the
  number of rows changed per table, keys `sessions`,
  `delivery_obligations`, `gateway_routing`. Importable, so the test can
  drive it against a throwaway database; runnable as
  `python Hermes/migrate-kiosk-to-jarvis.py <path>`.

- [ ] **Step 1: Write the failing test against a toy database**

Create `Hermes/tests/test_migrate_kiosk_to_jarvis.py`:

```python
"""The migration, against a database built to look like the real one.

The real state.db has 32 session rows, 459 obligations and 1 routing
row on the old key (measured 2026-08-28). The shape is what matters
here: messages hang off session_id, NOT off the session key, which is
why 1,750 message rows and ten FTS tables are untouched by this.
"""

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import importlib.util

# The script has a hyphen in its name, so it cannot be imported by name.
# `SourceFileLoader.load_module()` would also work on 3.12 and is
# removed in 3.13; this is the API that survives.
_path = Path(__file__).resolve().parents[1] / "migrate-kiosk-to-jarvis.py"
_spec = importlib.util.spec_from_file_location("migrate_kiosk_to_jarvis", _path)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
migrate = _mod.migrate

OLD = "agent:main:samantha_kiosk:dm:kiosk"
NEW = "agent:main:jarvis:dm:jarvis"


def _db(tmp_path):
    path = tmp_path / "state.db"
    c = sqlite3.connect(path)
    c.executescript(
        """
        CREATE TABLE sessions (id INTEGER PRIMARY KEY, session_key TEXT,
            chat_id TEXT, display_name TEXT, origin_json TEXT);
        CREATE TABLE delivery_obligations (obligation_id TEXT PRIMARY KEY,
            session_key TEXT, platform TEXT, chat_id TEXT);
        CREATE TABLE gateway_routing (scope TEXT NOT NULL DEFAULT '',
            session_key TEXT NOT NULL, entry_json TEXT NOT NULL,
            updated_at REAL NOT NULL, PRIMARY KEY (scope, session_key));
        CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT,
            content TEXT);
        """
    )
    origin = json.dumps(
        {"platform": "samantha_kiosk", "chat_id": "kiosk",
         "chat_name": "Kiosk", "chat_type": "dm", "user_id": "primary"}
    )
    c.execute("INSERT INTO sessions VALUES (1, ?, 'kiosk', 'Kiosk', ?)", (OLD, origin))
    c.execute("INSERT INTO sessions VALUES (2, NULL, NULL, NULL, NULL)")
    c.execute("INSERT INTO delivery_obligations VALUES ('o1', ?, 'samantha_kiosk', 'kiosk')", (OLD,))
    c.execute(
        "INSERT INTO gateway_routing VALUES ('/root', ?, ?, 1.0)",  # scope, key, entry_json, updated_at
        (OLD, json.dumps({"session_key": OLD, "platform": "samantha_kiosk",
                          "display_name": "Kiosk",
                          "origin": {"platform": "samantha_kiosk",
                                     "chat_id": "kiosk", "chat_name": "Kiosk"}})),
    )
    c.execute("INSERT INTO messages VALUES (1, 'sess-1', 'hola')")
    c.commit()
    c.close()
    return path


def test_every_row_moves_to_the_new_key(tmp_path):
    path = _db(tmp_path)
    counts = migrate(path)
    assert counts == {"sessions": 1, "delivery_obligations": 1, "gateway_routing": 1}
    c = sqlite3.connect(path)
    assert c.execute("SELECT session_key FROM sessions WHERE id=1").fetchone()[0] == NEW
    assert c.execute("SELECT session_key, platform FROM delivery_obligations").fetchone() == (NEW, "jarvis")
    assert c.execute("SELECT session_key FROM gateway_routing").fetchone()[0] == NEW


def test_the_origin_json_is_rewritten_not_just_the_key(tmp_path):
    path = _db(tmp_path)
    migrate(path)
    c = sqlite3.connect(path)
    origin = json.loads(c.execute("SELECT origin_json FROM sessions WHERE id=1").fetchone()[0])
    assert origin["platform"] == "jarvis"
    assert origin["chat_id"] == "jarvis"
    assert origin["chat_name"] == "JARVIS"
    assert c.execute("SELECT chat_id, display_name FROM sessions WHERE id=1").fetchone() == ("jarvis", "JARVIS")


def test_the_routing_blob_is_rewritten_too(tmp_path):
    path = _db(tmp_path)
    migrate(path)
    c = sqlite3.connect(path)
    blob = json.loads(c.execute("SELECT entry_json FROM gateway_routing").fetchone()[0])
    assert blob["platform"] == "jarvis"
    assert blob["session_key"] == NEW
    assert blob["display_name"] == "JARVIS"
    assert blob["origin"]["chat_name"] == "JARVIS"


def test_messages_and_sessions_without_a_key_are_untouched(tmp_path):
    path = _db(tmp_path)
    migrate(path)
    c = sqlite3.connect(path)
    assert c.execute("SELECT content FROM messages").fetchone()[0] == "hola"
    assert c.execute("SELECT session_key FROM sessions WHERE id=2").fetchone()[0] is None


def test_running_it_twice_changes_nothing_the_second_time(tmp_path):
    path = _db(tmp_path)
    migrate(path)
    assert migrate(path) == {"sessions": 0, "delivery_obligations": 0, "gateway_routing": 0}
```

- [ ] **Step 2: Run it and watch it fail**

```bash
cd /home/nexus/git/os1-samantha
PYTHONNOUSERSITE=1 widget/.venv/bin/python -m pytest Hermes/tests/test_migrate_kiosk_to_jarvis.py -q
```

Expected: FAIL — the loader cannot find `migrate-kiosk-to-jarvis.py`.

- [ ] **Step 3: Write the migration**

Create `Hermes/migrate-kiosk-to-jarvis.py`:

```python
#!/usr/bin/env python3
"""Move the strip's conversation from the kiosk key to the JARVIS one.

Run ONCE, with the gateway stopped, after the rename lands:

    systemctl --user stop samantha-hermes.service
    cp .hermes/home/state.db .hermes/home/state.db.bak-20260828
    python Hermes/migrate-kiosk-to-jarvis.py .hermes/home/state.db

What it does NOT touch, and why that is the whole reason it is small:
`messages` hangs off `session_id`, not off the session key, so the
1,750 rows of conversation and the ten FTS tables with their six
triggers are not part of this. Only the key, the two JSON blobs that
repeat it, and the obligations move.

Idempotent: a second run reports zero rows and changes nothing.
"""

import json
import sqlite3
import sys
from pathlib import Path

OLD_KEY = "agent:main:samantha_kiosk:dm:kiosk"
NEW_KEY = "agent:main:jarvis:dm:jarvis"
OLD_PLATFORM, NEW_PLATFORM = "samantha_kiosk", "jarvis"
OLD_CHAT, NEW_CHAT = "kiosk", "jarvis"
OLD_NAME, NEW_NAME = "Kiosk", "JARVIS"


def _rewrite(blob: str | None) -> str | None:
    """Rewrite one JSON blob's platform/chat/name fields, at any depth."""
    if not blob:
        return blob

    def walk(node):
        if isinstance(node, dict):
            return {k: walk(v) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(v) for v in node]
        if node == OLD_KEY:
            return NEW_KEY
        if node == OLD_PLATFORM:
            return NEW_PLATFORM
        if node == OLD_CHAT:
            return NEW_CHAT
        if node == OLD_NAME:
            return NEW_NAME
        return node

    try:
        return json.dumps(walk(json.loads(blob)))
    except (TypeError, ValueError):
        # A blob we cannot parse is left exactly as it was. Losing the
        # key is recoverable from the backup; corrupting a row is not.
        return blob


def migrate(db_path: Path | str) -> dict[str, int]:
    """Move every row on the old key. Returns rows changed per table."""
    con = sqlite3.connect(str(db_path))
    counts = {"sessions": 0, "delivery_obligations": 0, "gateway_routing": 0}
    try:
        with con:
            rows = con.execute(
                "SELECT id, origin_json FROM sessions WHERE session_key = ?",
                (OLD_KEY,),
            ).fetchall()
            for sid, origin in rows:
                con.execute(
                    "UPDATE sessions SET session_key = ?, chat_id = ?, "
                    "display_name = ?, origin_json = ? WHERE id = ?",
                    (NEW_KEY, NEW_CHAT, NEW_NAME, _rewrite(origin), sid),
                )
            counts["sessions"] = len(rows)

            cur = con.execute(
                "UPDATE delivery_obligations SET session_key = ?, platform = ?, "
                "chat_id = ? WHERE session_key = ?",
                (NEW_KEY, NEW_PLATFORM, NEW_CHAT, OLD_KEY),
            )
            counts["delivery_obligations"] = cur.rowcount

            # (scope, session_key) is this table's PRIMARY KEY, so the
            # UPDATE is addressed by both — there is no surrogate id to
            # hold on to. Columns verified against the live schema
            # 2026-08-28: scope, session_key, entry_json, updated_at.
            rows = con.execute(
                "SELECT scope, entry_json FROM gateway_routing WHERE session_key = ?",
                (OLD_KEY,),
            ).fetchall()
            for scope, entry in rows:
                con.execute(
                    "UPDATE gateway_routing SET session_key = ?, entry_json = ? "
                    "WHERE scope = ? AND session_key = ?",
                    (NEW_KEY, _rewrite(entry), scope, OLD_KEY),
                )
            counts["gateway_routing"] = len(rows)
    finally:
        con.close()
    return counts


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        raise SystemExit(2)
    target = Path(sys.argv[1])
    if not target.exists():
        raise SystemExit(f"no such database: {target}")
    for table, n in migrate(target).items():
        print(f"  {table}: {n} rows")
```

- [ ] **Step 4: Run the tests**

```bash
cd /home/nexus/git/os1-samantha
PYTHONNOUSERSITE=1 widget/.venv/bin/python -m pytest Hermes/tests/test_migrate_kiosk_to_jarvis.py -q
```

Expected: PASS, 5 tests.

- [ ] **Step 5: Rehearse it on a copy of the real database**

Do not run it on `state.db` yet — that is Task 8. Prove it on a copy:

```bash
cd /home/nexus/git/os1-samantha
cp .hermes/home/state.db /tmp/rehearsal.db
PYTHONNOUSERSITE=1 widget/.venv/bin/python Hermes/migrate-kiosk-to-jarvis.py /tmp/rehearsal.db
PYTHONNOUSERSITE=1 widget/.venv/bin/python -c "
import sqlite3
c = sqlite3.connect('/tmp/rehearsal.db')
print('old key left:', c.execute(\"select count(*) from sessions where session_key like '%kiosk%'\").fetchone()[0])
print('new key rows:', c.execute(\"select count(*) from sessions where session_key = 'agent:main:jarvis:dm:jarvis'\").fetchone()[0])
print('messages:', c.execute('select count(*) from messages').fetchone()[0])
print('fts still queryable:', c.execute(\"select count(*) from messages_fts where messages_fts match 'hola'\").fetchone()[0] >= 0)
"
rm /tmp/rehearsal.db
```

Expected: `old key left: 0`, `new key rows: 32`, `messages: 1750`,
`fts still queryable: True`.

- [ ] **Step 6: Commit**

```bash
cd /home/nexus/git/os1-samantha
ruff check Hermes/ && ruff format --check Hermes/
git add Hermes/migrate-kiosk-to-jarvis.py Hermes/tests/test_migrate_kiosk_to_jarvis.py
git commit -m "feat(hermes): a one-shot that moves the conversation to the jarvis key

Small because messages hang off session_id, not off the key: 32 session
rows, 459 obligations and one routing blob move; 1,750 messages and ten
FTS tables do not. Idempotent, and rehearsed on a copy before it is
allowed near the real database."
```

---

### Task 7: The living documentation

**Files:**
- Modify: `CLAUDE.md` (§0 diagram, §3 tree, §5 commands, §9 table, §10 glossary, new §12 entry)
- Modify: `AGENTS.md`, `README.md`
- Modify: `PROGRESS.md` (new entry at the top)

**Interfaces:**
- Consumes: everything above.
- Produces: documentation in which `samantha_kiosk` appears only as
  history.

- [ ] **Step 1: Update CLAUDE.md's structural sections**

- §0's process diagram: `+ samantha_kiosk (surface)` → `+ jarvis (surface)`
- §3's tree: `│       ├── samantha_kiosk/  ← the surface he speaks through`
  becomes `│       ├── jarvis/          ← the surface he speaks through`
- §5: the `xwininfo -name` line and the note under it (Task 5 changed
  the title; §5 explains what to match on)
- §9's table: `The surface Hermes speaks through` → `Hermes/plugins/jarvis/`,
  and `The photo frame, and the path it refuses` →
  `Hermes/plugins/jarvis/{protocol,adapter}.py`
- §10's glossary: keep the `Chromium kiosk` row (it is history) and add:

```markdown
| **`samantha_kiosk`** | What the platform, the plugin and the chat were called until 2026-08-28. Every plan and spec under `docs/superpowers/` still says it, because they are the record of the day they were written. In the running system it is `jarvis` (§12). |
```

- [ ] **Step 2: Add the §12 entry**

At the top of §12's list, in the house style — decision, what forced it,
and the cost stated rather than discovered:

```markdown
### 2026-08-28 — The kiosk stops being a kiosk

**Decision (the user's):** the concept "kiosk" becomes JARVIS. The
Hermes platform `samantha_kiosk` → `jarvis`, the plugin id, the chat
(`kiosk`/"Kiosk" → `jarvis`/"JARVIS"), the session key, and the GTK
window title. The package moves with them, `Hermes/plugins/jarvis/`.

**This reverses the naming half of 2026-08-23** ("the name is only
changed in prose"), and only that half: the persona, the voice and the
repo name stand. That entry measured the cost of renaming the CODE and
was right; what was renamed here is the CONCEPT, which lives in four
identifiers Hermes reasons about rather than in every file.

**The trap, and it is the reason the plan was written around it:**
`samantha_vision/alert.py` and `samantha_code/voz.py` each held the
session key written out by hand. `ctx.inject_message()` returns `True`
against a session that does not exist (§12, 2026-08-24), so a missed
rename there is cameras that go quiet with a strip that looks perfectly
healthy and nothing in any log. Both are pinned by tests now; `voz.py`
had none.

**What was not renamed, deliberately:** `samantha_widget`, the
`SAMANTHA_WIDGET_*` variables, the systemd units, `~/.samantha/` and
the repository. The code and the concept now disagree about "samantha"
more sharply than before — two of the four plugins keep the old prefix
— and `git grep samantha_kiosk` no longer finds this code. The glossary
line is the whole mitigation.

**Cost that lands on any other box:** the state migration
(`Hermes/migrate-kiosk-to-jarvis.py`) must be run there too, or JARVIS
starts with no session and no home channel — and a missing home channel
eats the first turn in silence (§5).
```

- [ ] **Step 3: Update AGENTS.md and README.md**

```bash
cd /home/nexus/git/os1-samantha
grep -n 'kiosk\|Kiosk' AGENTS.md README.md
```

Rewrite each hit that describes the running system. Leave any sentence
that is explicitly about v3's Chromium kiosk.

- [ ] **Step 4: Add the PROGRESS.md entry**

`PROGRESS.md` is in Spanish, newest first, `## <fecha> — <título> ✅`.
Write this step LAST, after Task 8 has produced the three numbers it
asks for. The entry, with the bracketed values replaced by what Task 8
actually measured — do not invent them:

```markdown
## 2026-08-28 — El kiosko deja de serlo: la plataforma es JARVIS ✅

Cierra `docs/superpowers/specs/2026-08-28-jarvis-platform-design.md`.
La palabra «kiosko» era un fósil de la v3 — no hay Chromium, ni
aparato, ni openbox: hay una tira y alguien que le habla. La decisión
del 2026-08-23 dejó el nombre cambiado sólo en la prosa porque renombrar
el CÓDIGO no compraba nada; lo que se ha renombrado aquí es el
CONCEPTO, que vive en cuatro identificadores que Hermes maneja: la
plataforma (`samantha_kiosk` → `jarvis`), el id del plugin, el chat
(`kiosk`/«Kiosk» → `jarvis`/«JARVIS») y la clave de sesión. El paquete
se movió con ellos.

**Lo que podía romperse en silencio, y por eso el plan giraba
alrededor de ello:** `samantha_vision/alert.py` y `samantha_code/voz.py`
llevaban la clave de sesión escrita a mano. `inject_message()` devuelve
`True` contra una sesión que no existe, así que un renombrado a medias
son cámaras mudas con la tira aparentemente sana y ni una línea en
ningún log. Las dos están fijadas por tests ahora; `voz.py` no tenía
ninguno.

**Ningún test fijaba el nombre de la plataforma** antes de hoy — se
podía cambiar en un sitio y dejarlo en otro con todo en verde. Los dos
primeros tests de la tarea 1 son los que debían haber existido.

**Medido:** [N] tests en verde (línea base 324); la migración movió
[N] sesiones, [N] obligaciones y [N] fila de routing, con los 1.750
mensajes y las diez tablas FTS intactas; y una alerta de cámara llegó
después del corte, que es el camino que el fallo silencioso habría
roto.

**No se ha renombrado, a propósito:** `samantha_widget`, las variables
`SAMANTHA_WIDGET_*`, las units de systemd, `~/.samantha/` ni el
repositorio. Los planes y specs de `docs/superpowers/` siguen diciendo
«kiosk»: son el registro del día en que se escribieron.
```

- [ ] **Step 5: Prove the archive is the only place the old name lives**

```bash
cd /home/nexus/git/os1-samantha
git grep -n 'samantha_kiosk\|samantha-kiosk' -- . ':!docs/superpowers/'
```

Expected: only the glossary row and the §12 entry in `CLAUDE.md`.

- [ ] **Step 6: Commit**

```bash
cd /home/nexus/git/os1-samantha
git add CLAUDE.md AGENTS.md README.md PROGRESS.md
git commit -m "docs: the running system says jarvis, the archive keeps saying kiosk

The plans and specs are the record of the day they were written and are
left alone; the glossary explains the word to whoever meets it there."
```

---

### Task 8: Live cutover

Not a test — the part no test covers. Everything up to here can be green
with the strip mute.

**Files:**
- Modify: `.hermes/home/config.yaml` (git-ignored, live)
- Modify: `.hermes/home/plugins/` (the symlink)
- Modify: `.hermes/home/state.db` (the migration)

**Interfaces:**
- Consumes: all previous tasks.
- Produces: a running gateway serving the platform `jarvis`.

- [ ] **Step 1: Stop everything that holds the database or the port**

```bash
systemctl --user stop samantha-widget.service samantha-hermes.service
systemctl --user is-active samantha-widget.service samantha-hermes.service
```

Expected: `inactive` twice.

- [ ] **Step 2: Back up, then migrate**

```bash
cd /home/nexus/git/os1-samantha
cp .hermes/home/state.db .hermes/home/state.db.bak-20260828
PYTHONNOUSERSITE=1 widget/.venv/bin/python Hermes/migrate-kiosk-to-jarvis.py .hermes/home/state.db
```

Expected: `sessions: 32`, `delivery_obligations: 459`, `gateway_routing: 1`.

- [ ] **Step 3: Move the symlink**

```bash
rm ~/git/os1-samantha/.hermes/home/plugins/samantha_kiosk
ln -sfn ~/git/os1-samantha/Hermes/plugins/jarvis ~/git/os1-samantha/.hermes/home/plugins/jarvis
ls -l ~/git/os1-samantha/.hermes/home/plugins/
```

Expected: four symlinks, one of them `jarvis -> …/Hermes/plugins/jarvis`.

- [ ] **Step 4: Rename the ids in the live config**

Edit `.hermes/home/config.yaml` by hand — `plugins.enabled`,
`plugins.entries`, `platform_toolsets.samantha_kiosk` →
`platform_toolsets.jarvis`, `platforms.samantha_kiosk` →
`platforms.jarvis`, and inside it the whole `home_channel` block:

```yaml
platforms:
  jarvis:
    enabled: true
    home_channel:
      platform: jarvis
      chat_id: jarvis
      name: JARVIS
      user_id: primary
```

Do **not** run `apply-config.sh` to do this: it deep-merges the tracked
file over the live one and replaces lists wholesale (§12, 2026-08-26),
which would re-assert other tracked values as a side effect.

- [ ] **Step 5: Start the gateway and read the log**

```bash
systemctl --user start samantha-hermes.service
sleep 5
journalctl --user -u samantha-hermes.service --since '1 min ago' --no-pager | grep -iE 'jarvis|kiosk|plugin|platform' | tail -20
```

Expected: `jarvis: serving /ws on :7777`, and **no** line mentioning
`samantha_kiosk`. If the platform does not register, the symlink or an
id in the live config is wrong — check `.hermes/home/logs/agent.log`,
which is the real log (§12, 2026-08-26), not only the journal.

- [ ] **Step 6: Start the strip and verify it is JARVIS**

```bash
systemctl --user start samantha-widget.service
sleep 8
DISPLAY=:1 xwininfo -name JARVIS | head -5
```

Expected: window geometry, not "No window with name … exists!".

- [ ] **Step 7: One spoken turn**

```bash
cd /home/nexus/git/os1-samantha/widget
PYTHONNOUSERSITE=1 ./.venv/bin/python tools/probe_gateway.py "Jarvis, ¿me oyes?"
```

Expected: a reply in his voice and register. If it returns nothing, the
home channel is wrong — `/sethome` through the strip (§5).

- [ ] **Step 8: The alert path — the one that fails silently**

This is the step the whole change is organised around. With the gateway
up, confirm a camera sighting still becomes a turn:

```bash
journalctl --user -u samantha-hermes.service -f | grep -iE 'inject|not routed|samantha-vision'
```

Wait for a real sighting, or stand in front of a camera. Expected: an
injection that IS routed, and a spoken mention. **A line saying "Plugin
message injection was not routed" means a session key was missed** —
go back to Task 3.

- [ ] **Step 9: New session, so the persona and the label take**

Through the strip: `/new`, then `/approve` (§7 — the system prompt is
frozen when the session is born).

- [ ] **Step 10: Record what it measured and commit the progress entry**

Fill in Task 7's Step 4 with the real numbers from Steps 2, 5 and 8,
then:

```bash
cd /home/nexus/git/os1-samantha
git add PROGRESS.md
git commit -m "docs(progress): the kiosk became JARVIS, and the alert path proved it"
```
