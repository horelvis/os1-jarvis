# Identity per person — implementation plan (part 1: the phones)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every phone in the house is a person — their own session, their own memory, their own persona, and their own set of tools — with several people able to hold a conversation at once.

**Architecture:** Hermes profiles already are complete `HERMES_HOME` isolation, and `gateway.profile_routes` already routes an inbound message to one by `platform` + `chat_id`. What is missing is on our side: a roster of one secret per person instead of one shared secret, an endpoint that knows whose it is, a `chat_id` on the wire instead of the literal `"jarvis"`, and a widget and adapter that hold more than one turn at a time.

**Tech Stack:** Python 3.12, aiohttp (the phone socket), `websockets` (the gateway socket), pytest, ruff. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-05-identidad-por-persona-design.md`

## Scope: this is part 1 of two

The spec has two separable halves. **This plan is the first**: identity that comes from an enrolled device, which cannot be wrong, plus the profiles, routing and concurrency that hang off it. On its own it delivers the whole feature for the phones.

**The second half — identity by voice in the room — is deliberately NOT here.** It rests on a measurement that has not been taken (whether two sisters of 16 and 17 separate), and the spec already says that if they do not, the phones deliver the feature and the room falls back to one identity. Writing its plan before that measurement would be planning work that may not exist. Task 12 ends by naming what that measurement is.

## Global Constraints

- **Spanish for anything a person reads or hears; English for code, comments and commit messages** (CLAUDE.md §2.9, §6).
- **`ruff format` and `ruff check` must pass.** Type hints are mandatory on public functions.
- **Run everything with `PYTHONNOUSERSITE=1`** — a venv built with `--system-site-packages` also sees `~/.local/lib`, and a different `websockets` or `numpy` there gets loaded instead (CLAUDE.md §2.8).
- **Widget tests:** `cd widget && PYTHONNOUSERSITE=1 .venv/bin/python -m pytest -v`
- **Gateway-plugin tests run from the repo root**, because they import `Hermes.plugins.jarvis.*`: `PYTHONNOUSERSITE=1 widget/.venv/bin/python -m pytest Hermes/plugins/jarvis/tests -v`
- **No test in this repo touches the network, the GPU or a display.** Anything that needs the live gateway is a probe under `tools/`, run by hand, whose output is written into a document.
- **`casa` is the identity a turn gets when nobody knows whose it is.** A failure NEVER degrades to another person. Every default in this plan points at `casa`.
- **Backwards compatibility on both wires is mandatory and is not optional politeness:** the widget and the gateway are versioned separately and ship separately. A new field is always optional; a missing one always means today's behaviour.

---

### Task 1: The probe that can invalidate this plan

**Files:**
- Create: `Hermes/plugins/jarvis/tools/probe_profiles.py`
- Create: `docs/superpowers/specs/2026-09-05-probe-profiles.md`

**Interfaces:**
- Consumes: nothing.
- Produces: a written finding. Tasks 7, 11 and 12 assume its answer is yes.

This runs FIRST and everything else waits on it. The spec's whole tool boundary — that the daughters' profile does not load `terminal` or the cameras — rests on plugins and toolsets resolving per profile in this pinned Hermes. It is plausible and it is not measured. **If the answer is no, stop and report: the boundary has to be redone, most likely as a second gateway on another port, and tasks 7 and 11 change shape.**

- [ ] **Step 1: Write the probe**

```python
"""Does this Hermes resolve plugins and toolsets PER PROFILE?

Run by hand, against the live box, never from a test:

    PYTHONNOUSERSITE=1 widget/.venv/bin/python \
        Hermes/plugins/jarvis/tools/probe_profiles.py

It answers one question and prints what it saw. Nothing is written and
no gateway is started. Modelled on
`Hermes/plugins/jarvis_teacher/tools/probe_busqueda.py`, which found
that the search import was not the one the design guessed.

Note before running: `probe_busqueda.py` recorded that asking Hermes a
question from a BARE process triggers its full plugin discovery, which
on this box starts the camera threads against the real house cameras.
Expect that, do not be alarmed by it, and do not run this while
something else is using the cameras.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

HERMES = Path(__file__).resolve().parents[3] / ".hermes"
sys.path.insert(0, str(HERMES / "src"))


def main() -> int:
    print(f"HERMES_HOME = {os.getenv('HERMES_HOME', '(unset)')}")

    from hermes_cli import profiles

    print("\n-- profiles on this box --")
    for name in sorted(getattr(profiles, "list_profiles", lambda: [])() or []):
        print(f"  {name}")

    print("\n-- does a profile home carry its own plugin config? --")
    root = Path.home() / ".hermes"
    for home in [root, *sorted((root / "profiles").glob("*"))]:
        cfg = home / "config.yaml"
        print(f"  {home}: config.yaml={'yes' if cfg.is_file() else 'no'}")

    print("\n-- how the gateway resolves a profile for an inbound source --")
    from gateway import profile_routing

    print(f"  match_profile_route: {profile_routing.match_profile_route}")
    print(f"  specificity: guild=2 chat=4 thread=8 (from the module)")

    print("\nTHE QUESTION: with `gateway.multiplex_profiles: true` and two")
    print("profiles served, does each profile load only the plugins its own")
    print("config.yaml enables? Read gateway/run.py's _multiplex_profile_homes")
    print("and the plugin loader it hands each home to, and write down which.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run it against the live box**

Run: `PYTHONNOUSERSITE=1 widget/.venv/bin/python Hermes/plugins/jarvis/tools/probe_profiles.py`

Expected: it prints without raising. What it prints is data, not a pass or a fail.

- [ ] **Step 3: Read `gateway/run.py` and answer the question in writing**

Search `.hermes/src/gateway/run.py` for `_multiplex_profile_homes` and follow what each served home is handed to. Write `docs/superpowers/specs/2026-09-05-probe-profiles.md` with: the exact function that loads plugins for a profile, whether its input is the profile home or a global config, one quoted line of evidence for each, and a verdict of **yes** or **no**.

- [ ] **Step 4: Commit**

```bash
git add Hermes/plugins/jarvis/tools/probe_profiles.py docs/superpowers/specs/2026-09-05-probe-profiles.md
git commit -m "probe: do plugins and toolsets resolve per Hermes profile"
```

- [ ] **Step 5: Stop if the verdict is no**

Report to the user. Do not start task 2.

---

### Task 2: `personas.py` — who exists, and what happens when nobody knows

**Files:**
- Create: `widget/jarvis_widget/personas.py`
- Test: `widget/tests/test_personas.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `CASA: str`, `normalizar(raw: str | None) -> str`, `es_valida(raw: str) -> bool`. Tasks 3, 4, 5 and 6 use `normalizar` as the ONLY way a person id is made.

Pure, no imports beyond the standard library, testable with no display and no socket — the shape `wave_model.py` and `bars_model.py` already have.

- [ ] **Step 1: Write the failing test**

```python
"""The one place a person id is made, and the one place `casa` comes from."""

from jarvis_widget.personas import CASA, es_valida, normalizar


def test_casa_is_the_fallback_for_nothing_at_all():
    assert normalizar(None) == CASA
    assert normalizar("") == CASA
    assert normalizar("   ") == CASA


def test_a_name_is_folded_and_trimmed():
    assert normalizar("  Marta  ") == "marta"
    assert normalizar("PAPÁ") == "papá"


def test_anything_that_could_escape_a_path_or_a_key_becomes_casa():
    # A person id becomes a Hermes chat_id, a profile name and a file
    # name. Degrading to `casa` is the rule; never raise, never pass it
    # through, and never land on another person.
    for hostile in ("../papá", "a/b", "papá\n", "x" * 65, "a b"):
        assert normalizar(hostile) == CASA


def test_es_valida_agrees_with_normalizar():
    assert es_valida("marta")
    assert not es_valida("../papá")
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `cd widget && PYTHONNOUSERSITE=1 .venv/bin/python -m pytest tests/test_personas.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'jarvis_widget.personas'`

- [ ] **Step 3: Write the module**

```python
"""Who a turn belongs to, and what it is when nobody knows.

Pure: no sockets, no files, no GTK. A person id is three things at
once — the `chat_id` on the gateway wire, the name of a Hermes profile,
and a file name under `~/.jarvis/` — so it is made in exactly one place
and it is made narrow.

`CASA` is the identity of a turn nobody can attribute: a guest, a
device that was never enrolled, a name that does not survive this
module. It owns no tools and it never writes into a person's memory.
**A failure degrades here and never to another person**, which is what
makes the probabilistic half of this feature (a voice in a room) safe
to build on later.
"""

from __future__ import annotations

# Not a person. The shared identity a turn falls back to.
CASA = "casa"

# One path segment, one chat_id, one profile name — so: lowercase
# letters, digits, and the two separators Hermes' own profile grammar
# allows. Accented letters are kept because the people in this house
# have them in their names.
_LARGO_MAXIMO = 64


def es_valida(raw: str) -> bool:
    """Whether `raw` is already a person id, exactly as it stands."""
    if not raw or len(raw) > _LARGO_MAXIMO:
        return False
    return all(c.isalnum() or c in "-_" for c in raw) and raw == raw.casefold()


def normalizar(raw: str | None) -> str:
    """A person id, or `CASA`. Never raises, never returns empty.

    Anything that could escape a path, a config key or a session key
    becomes `CASA` rather than being rejected: the callers are a socket
    handler and an audio thread, and neither has anywhere to put an
    exception.
    """
    if raw is None:
        return CASA
    limpio = raw.strip().casefold()
    return limpio if es_valida(limpio) else CASA
```

- [ ] **Step 4: Run the tests**

Run: `cd widget && PYTHONNOUSERSITE=1 .venv/bin/python -m pytest tests/test_personas.py -v`
Expected: PASS, 4 tests.

- [ ] **Step 5: Format, lint and commit**

```bash
cd widget && .venv/bin/ruff format jarvis_widget/personas.py tests/test_personas.py && .venv/bin/ruff check .
cd .. && git add widget/jarvis_widget/personas.py widget/tests/test_personas.py
git commit -m "feat(widget): a person id, and casa when nobody knows"
```

---

### Task 3: One secret per person, and a Guard that answers *who*

**Files:**
- Modify: `widget/jarvis_widget/remote_auth.py`
- Test: `widget/tests/test_remote_auth.py` (existing file, add to it)

**Interfaces:**
- Consumes: `personas.normalizar`.
- Produces: `load_or_create_roster(path: Path | None = None) -> dict[str, str]`, `save_roster(roster, path=None) -> None`, `new_secret() -> str`, `Guard(secretos: dict[str, str], origin: str, *also: str)`, `Guard.persona_for(offered: str | None) -> str | None`. `Guard.token_ok` stays and keeps its meaning. Task 4 writes into the roster; task 5 reads `persona_for`.

Today there is ONE secret for the whole house and the endpoint is named after its IP. This is the task that makes a phone a person.

- [ ] **Step 1: Write the failing tests**

```python
import json

from jarvis_widget.personas import CASA
from jarvis_widget.remote_auth import Guard, load_or_create_roster


def test_the_roster_is_made_once_and_reused(tmp_path):
    ruta = tmp_path / "personas.json"
    primero = load_or_create_roster(ruta)
    assert primero == {CASA: primero[CASA]}
    assert load_or_create_roster(ruta) == primero


def test_the_roster_file_is_not_world_readable(tmp_path):
    ruta = tmp_path / "personas.json"
    load_or_create_roster(ruta)
    assert oct(ruta.stat().st_mode)[-3:] == "600"


def test_a_secret_names_its_person(tmp_path):
    ruta = tmp_path / "personas.json"
    ruta.write_text(json.dumps({"papá": "aaa", "marta": "bbb"}))
    ruta.chmod(0o600)
    guard = Guard(load_or_create_roster(ruta), "https://brain.local:8443")
    assert guard.persona_for("bbb") == "marta"
    assert guard.persona_for("aaa") == "papá"


def test_an_unknown_secret_is_nobody_and_not_casa(tmp_path):
    # `casa` is where an UNATTRIBUTED turn goes. An unknown secret is a
    # failed authentication, which is a different thing: the socket is
    # refused, not downgraded.
    guard = Guard({"papá": "aaa"}, "https://brain.local:8443")
    assert guard.persona_for("zzz") is None
    assert guard.persona_for(None) is None
    assert guard.persona_for("") is None


def test_token_ok_still_means_what_it_meant():
    guard = Guard({"papá": "aaa"}, "https://brain.local:8443")
    assert guard.token_ok("aaa")
    assert not guard.token_ok("zzz")
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `cd widget && PYTHONNOUSERSITE=1 .venv/bin/python -m pytest tests/test_remote_auth.py -v`
Expected: FAIL with `ImportError: cannot import name 'load_or_create_roster'`

- [ ] **Step 3: Implement**

Add to `widget/jarvis_widget/remote_auth.py`, keeping `load_or_create_secret` where it is — the old single-secret path is what an un-migrated box still has:

```python
import json

from .personas import CASA, normalizar

DEFAULT_ROSTER_PATH = Path.home() / ".jarvis" / "personas.json"


def load_or_create_roster(path: Path | None = None) -> dict[str, str]:
    """`{person: secret}`, made once and reused.

    A new box starts with one entry, `casa`, and grows one per person
    as phones are enrolled (task 4). Written 0600 before anything is
    put in it, for the reason `load_or_create_secret` gives: creating it
    world-readable and chmod'ing afterwards leaves a window in which
    every secret in the house is on disk and readable.
    """
    target = Path(
        path or os.getenv("JARVIS_WIDGET_REMOTE_ROSTER") or DEFAULT_ROSTER_PATH
    )
    if target.is_file():
        crudo = json.loads(target.read_text() or "{}")
        # Names are re-normalised on the way in: this file is edited by
        # hand, and a person id that does not survive `normalizar` would
        # otherwise reach a session key and a profile name.
        return {normalizar(k): v for k, v in crudo.items() if isinstance(v, str)}
    target.parent.mkdir(parents=True, exist_ok=True)
    roster = {CASA: secrets.token_urlsafe(_SECRET_BYTES)}
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump(roster, handle)
    return roster


def new_secret() -> str:
    """A fresh secret, the same size as the one this module already makes.

    Exists so `remote.py` can mint one for a newly enrolled person
    without importing `_SECRET_BYTES` across module boundaries.
    """
    return secrets.token_urlsafe(_SECRET_BYTES)


def save_roster(roster: dict[str, str], path: Path | None = None) -> None:
    """Replace the roster on disk, 0600, atomically."""
    target = Path(
        path or os.getenv("JARVIS_WIDGET_REMOTE_ROSTER") or DEFAULT_ROSTER_PATH
    )
    temporal = target.with_suffix(".tmp")
    fd = os.open(temporal, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump(roster, handle)
    temporal.replace(target)
```

and replace `Guard.__init__` / add `persona_for`:

```python
    def __init__(self, secretos: dict[str, str], origin: str, *also: str) -> None:
        self.secretos = dict(secretos)
        self.origin = origin
        self.origins = [origin, *also]

    def persona_for(self, offered: str | None) -> str | None:
        """Whose secret this is, or None if it is nobody's.

        Every entry is compared even after a match. Breaking early would
        make the time taken depend on the position of the matching name
        in the roster, which is a timing oracle for WHO is on this
        network — a smaller leak than the secret itself, and free to
        avoid.
        """
        if not offered:
            return None
        encontrada: str | None = None
        for persona, secreto in sorted(self.secretos.items()):
            if compare_digest(offered, secreto):
                encontrada = persona
        return encontrada

    def token_ok(self, offered: str | None) -> bool:
        """Constant-time: a timing oracle on a LAN is not theoretical."""
        return self.persona_for(offered) is not None
```

- [ ] **Step 4: Run the tests**

Run: `cd widget && PYTHONNOUSERSITE=1 .venv/bin/python -m pytest tests/test_remote_auth.py -v`
Expected: PASS, including the tests that were already in the file — check that none of them constructed `Guard` with a bare string, and fix any that did.

- [ ] **Step 5: Commit**

```bash
cd widget && .venv/bin/ruff format . && .venv/bin/ruff check .
cd .. && git add widget/jarvis_widget/remote_auth.py widget/tests/test_remote_auth.py
git commit -m "feat(widget): one secret per person, and a guard that answers who"
```

---

### Task 4: Enrolling a phone names the person at the keyboard

**Files:**
- Create: `widget/tools/enrolar.py`
- Modify: `widget/jarvis_widget/remote.py` (the `Enrolment` class and the welcome page)
- Test: `widget/tests/test_enrol.py` (existing file, add to it)

**Interfaces:**
- Consumes: `personas.normalizar`, `remote_auth.load_or_create_roster`, `remote_auth.save_roster`.
- Produces: `remote.Enrolment.abrir(persona: str, now: float | None = None) -> None` and `remote.Enrolment.persona(now: float | None = None) -> str | None`, alongside the existing `open_enrolment` / `is_open`. Task 5 does not use these; the welcome page does.

**Why the person is chosen at the keyboard and not on the page.** `enrol.py` says it itself: the welcome page embeds the secret in cleartext and that is why the window is short. With one secret that was one risk. With a roster, letting the page ask "who are you?" means whoever is on the wifi during those five minutes can answer "papá" and walk away with the token that holds `terminal`. So the window is opened FOR a named person, by someone at this machine, and the page has nothing to choose.

- [ ] **Step 1: Write the failing test**

```python
import time

from jarvis_widget.personas import CASA
from jarvis_widget.remote import Enrolment


def test_a_closed_enrolment_is_for_nobody():
    e = Enrolment()
    assert e.persona() is None
    assert not e.is_open(now=1000.0)


def test_opening_names_the_person_it_is_for():
    e = Enrolment()
    e.abrir("marta", now=1000.0)
    assert e.persona(now=1000.0) == "marta"
    assert e.is_open(now=1000.0)


def test_the_window_closes_and_takes_the_person_with_it():
    e = Enrolment()
    e.abrir("marta", now=1000.0)
    assert not e.is_open(now=1000.0 + 10_000)
    assert e.persona(now=1000.0 + 10_000) is None


def test_a_name_that_does_not_survive_normalizar_enrols_casa():
    e = Enrolment()
    e.abrir("../papá", now=1000.0)
    assert e.persona == CASA
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `cd widget && PYTHONNOUSERSITE=1 .venv/bin/python -m pytest tests/test_enrol.py -v`
Expected: FAIL — `Enrolment` has no `abrir` and no `persona`.

- [ ] **Step 3: Implement the window**

In `widget/jarvis_widget/remote.py`, give `Enrolment` a person. Keep whatever method opens it today and add:

```python
    def abrir(self, persona: str, now: float | None = None) -> None:
        """Open the window FOR one named person.

        Wraps the existing `open_enrolment`, which is what raises the
        plain-HTTP socket. The name is normalised here rather than
        trusted: it arrives from a file written by `tools/enrolar.py`,
        and a name that does not survive would otherwise become a
        profile name and a session key.
        """
        self._persona = normalizar(persona)
        self.open_enrolment(now)

    def persona(self, now: float | None = None) -> str | None:
        """Who the open window is for, or None when it is shut.

        A method rather than a property because it takes the injectable
        clock every other method here takes, and because a stale name
        must never be readable: an expired window is nobody's.
        """
        return self._persona if self.is_open(now) else None
```

Set `self._persona: str | None = None` in `__init__` alongside `_opened_at`, and clear it in whatever closes the window, so a stale name can never be served. Note the existing methods are `open_enrolment(now=None)` and `is_open(now=None)` — not `open()`.

- [ ] **Step 4: Serve that person's secret, and make one if they are new**

In the welcome-page handler in `remote.py`, replace `guard.secret` with the secret of `enrolment.persona`, minting one when the person is not yet on the roster:

```python
        persona = enrolment.persona()
        if persona is None:
            # The window is shut. This is the normal state and it is not
            # an error: the page simply is not there.
            raise web.HTTPNotFound()
        secreto = guard.secretos.get(persona)
        if secreto is None:
            secreto = new_secret()
            guard.secretos[persona] = secreto
            save_roster(guard.secretos)
        target = f"https://{HOSTNAME}:{PORT}/#{secreto}"
```

- [ ] **Step 5: Write the tool that opens it**

```python
"""Open the enrolment window for ONE named person.

    PYTHONNOUSERSITE=1 widget/.venv/bin/python widget/tools/enrolar.py marta

Writes who it is for and signals the running widget, which puts the QR
on the strip. Deliberately a deliberate act at this keyboard: the page
behind that QR hands out a secret in cleartext to whoever asks, and with
a roster that secret belongs to a named person — the father's holds
`terminal`.

An already-enrolled phone never needs this again.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jarvis_widget.personas import CASA, normalizar  # noqa: E402

PENDIENTE = Path.home() / ".jarvis" / "enrolamiento.json"


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("uso: enrolar.py <persona>", file=sys.stderr)
        return 2
    persona = normalizar(argv[1])
    if persona == CASA and argv[1].strip().casefold() != CASA:
        print(f"«{argv[1]}» no es un nombre válido", file=sys.stderr)
        return 2

    PENDIENTE.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(PENDIENTE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump({"persona": persona, "escrito": time.time()}, handle)

    subprocess.run(
        ["systemctl", "--user", "kill", "-s", "USR1", "jarvis-widget.service"],
        check=False,
    )
    print(f"ventana abierta para {persona}; el QR está en la tira")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
```

- [ ] **Step 6: Read the pending person when USR1 arrives**

In `widget/jarvis_widget/__main__.py`, where SIGUSR1 is handled today, read `~/.jarvis/enrolamiento.json`, call `enrolment.abrir(persona)` with what it holds, and **delete the file**, so a name cannot be replayed by a second signal. A missing or unreadable file means `enrolment.abrir(CASA)` — never the owner.

- [ ] **Step 7: Run the tests and commit**

Run: `cd widget && PYTHONNOUSERSITE=1 .venv/bin/python -m pytest -v`
Expected: PASS.

```bash
cd widget && .venv/bin/ruff format . && .venv/bin/ruff check .
cd .. && git add widget/tools/enrolar.py widget/jarvis_widget/remote.py widget/jarvis_widget/__main__.py widget/tests/test_enrol.py
git commit -m "feat(widget): enrolling a phone names the person it is for"
```

---

### Task 5: The endpoint and the turn carry the person

**Files:**
- Modify: `widget/jarvis_widget/remote.py` (`Endpoint`, `WebEndpoint`, the socket handler)
- Modify: `widget/jarvis_widget/__main__.py` (`TurnOrigin`, `dispatch`)
- Test: `widget/tests/test_remote.py`, `widget/tests/test_main.py`

**Interfaces:**
- Consumes: `Guard.persona_for` (task 3), `personas.CASA`.
- Produces: `Endpoint.persona: str` on the protocol and on `WebEndpoint`; `TurnOrigin.take()` and `.settle()` keep returning the endpoint, so `settle_turn` is unchanged. Task 6 reads `endpoint.persona`.

- [ ] **Step 1: Write the failing tests**

```python
from jarvis_widget.personas import CASA


class FakeEndpoint:
    def __init__(self, persona=CASA):
        self.persona = persona
        self.name = "prueba"
        self.written = []
        self.refused = 0

    def write(self, pcm):
        self.written.append(pcm)

    def refuse(self):
        self.refused += 1


def test_an_endpoint_knows_whose_it_is():
    assert FakeEndpoint("marta").persona == "marta"


def test_a_turn_from_a_phone_carries_its_person():
    from jarvis_widget.__main__ import TurnOrigin

    origen = TurnOrigin()
    telefono = FakeEndpoint("marta")
    origen.arriving(telefono)
    assert origen.take() is telefono
    assert origen.current.persona == "marta"


def test_a_desk_turn_has_no_endpoint_and_therefore_no_person():
    from jarvis_widget.__main__ import TurnOrigin

    origen = TurnOrigin()
    assert origen.take() is None
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `cd widget && PYTHONNOUSERSITE=1 .venv/bin/python -m pytest tests/test_remote.py -v`
Expected: FAIL — no `persona` attribute anywhere.

- [ ] **Step 3: Implement**

In `remote.py`, add `persona: str` to the `Endpoint` Protocol next to `name`, and to `WebEndpoint.__init__`:

```python
    def __init__(self, ws, name: str, persona: str, loop) -> None:
        self._ws = ws
        self._loop = loop
        self.name = name
        # Who this phone belongs to. Set from the roster at connection
        # time and never from anything the phone says: a client that
        # could assert its own person could ask for the father's
        # profile, which is the one holding `terminal`.
        self.persona = persona
```

and in the socket handler, replace the boolean check with the lookup:

```python
        persona = guard.persona_for(request.query.get("t"))
        if persona is None:
            return web.Response(status=403, text="no")
        ...
        endpoint = WebEndpoint(ws, request.remote or "phone", persona, loop)
```

- [ ] **Step 4: Run the tests**

Run: `cd widget && PYTHONNOUSERSITE=1 .venv/bin/python -m pytest tests/test_remote.py tests/test_main.py -v`
Expected: PASS. Existing tests constructing `WebEndpoint` with three arguments need the fourth.

- [ ] **Step 5: Commit**

```bash
cd widget && .venv/bin/ruff format . && .venv/bin/ruff check .
cd .. && git add widget/jarvis_widget/remote.py widget/jarvis_widget/__main__.py widget/tests/
git commit -m "feat(widget): a phone knows whose it is, and so does its turn"
```

---

### Task 6: The chat frame carries a `chat_id`

**Files:**
- Modify: `widget/jarvis_widget/gateway.py` (`encode_chat`, `GatewayClient.send_chat`)
- Modify: `Hermes/plugins/jarvis/protocol.py` (`decode_client`)
- Modify: `Hermes/plugins/jarvis/adapter.py` (`_handle_chat`, the read loop)
- Modify: `widget/jarvis_widget/__main__.py` (`dispatch` passes the person)
- Test: `widget/tests/test_gateway.py`, `Hermes/plugins/jarvis/tests/test_protocol.py`, `Hermes/plugins/jarvis/tests/test_adapter.py`

**Interfaces:**
- Consumes: `endpoint.persona` (task 5).
- Produces: `encode_chat(text, user_id=DEFAULT_USER_ID, *, wake=False, chat_id=None)`; `GatewayClient.send_chat(text, *, wake=False, chat_id=None)`; `adapter.CHAT_ID_DEFAULT = "jarvis"`. Task 9 tags the frames coming back.

This is the one-line literal the whole feature was waiting behind: `adapter.py:822`'s `chat_id="jarvis"`.

- [ ] **Step 1: Write the failing tests**

```python
# widget/tests/test_gateway.py
import json

from jarvis_widget.gateway import encode_chat


def test_a_chat_frame_without_a_person_is_exactly_what_it_was():
    # The widget and the gateway ship separately. An older gateway must
    # see the frame it has always seen.
    assert json.loads(encode_chat("hola")) == {
        "type": "chat",
        "message": "hola",
        "user_id": "primary",
    }


def test_a_chat_frame_carries_the_person_when_there_is_one():
    frame = json.loads(encode_chat("hola", chat_id="marta"))
    assert frame["chat_id"] == "marta"
```

```python
# Hermes/plugins/jarvis/tests/test_protocol.py
import json

import pytest

from Hermes.plugins.jarvis.protocol import ProtocolError, decode_client


def test_chat_id_is_optional():
    msg = decode_client(json.dumps({"type": "chat", "message": "hola", "user_id": "primary"}))
    assert msg.get("chat_id") is None


def test_chat_id_is_validated_when_present():
    msg = decode_client(
        json.dumps({"type": "chat", "message": "hola", "user_id": "primary", "chat_id": "marta"})
    )
    assert msg["chat_id"] == "marta"


def test_a_chat_id_that_could_escape_a_session_key_is_refused():
    for hostile in ("a/b", "", "x" * 200, 7):
        with pytest.raises(ProtocolError):
            decode_client(
                json.dumps(
                    {"type": "chat", "message": "h", "user_id": "primary", "chat_id": hostile}
                )
            )
```

- [ ] **Step 2: Run them to make sure they fail**

Run:
```
cd widget && PYTHONNOUSERSITE=1 .venv/bin/python -m pytest tests/test_gateway.py -v
cd .. && PYTHONNOUSERSITE=1 widget/.venv/bin/python -m pytest Hermes/plugins/jarvis/tests/test_protocol.py -v
```
Expected: FAIL on the `chat_id` tests only.

- [ ] **Step 3: Implement the widget half**

```python
def encode_chat(
    text: str,
    user_id: str = DEFAULT_USER_ID,
    *,
    wake: bool = False,
    chat_id: str | None = None,
) -> str:
    frame: dict[str, Any] = {"type": "chat", "message": text, "user_id": user_id}
    if wake:
        frame["wake"] = True
    if chat_id:
        # Whose conversation this is. Absent means the house's one
        # session, which is what every build before today sent and what
        # an older gateway understands.
        frame["chat_id"] = chat_id
    return json.dumps(frame)
```

Give `send_chat` the same keyword and pass it through. In `__main__.dispatch`, the call becomes:

```python
                persona = phone.persona if phone is not None else None
                await client.send_chat(spoken, wake=wake.named, chat_id=persona)
```

A desk turn passes `None` and behaves exactly as it does today. **The room does not become multi-person in this plan** — that is part 2.

- [ ] **Step 4: Implement the gateway half**

In `protocol.decode_client`, inside the `chat` branch:

```python
        # Optional, and it must stay optional: the strip is versioned
        # separately, and a build older than today sends no chat_id.
        # Absent means the house's single session.
        chat = msg.get("chat_id")
        if chat is not None:
            if not isinstance(chat, str) or not chat.strip():
                raise ProtocolError("chat_id must be a non-blank string when present")
            if len(chat) > 64 or not all(c.isalnum() or c in "-_" for c in chat):
                # It becomes a session key and a profile name.
                raise ProtocolError(f"chat_id is not a usable id: {chat!r}")
```

In `adapter.py`, add the constant next to `DEFAULT_USER_ID`:

```python
# The chat this platform's turns belong to when the strip does not say.
# It was a literal inside `_handle_chat` until 2026-09-05, and that
# literal was the whole reason one house shared one memory.
CHAT_ID_DEFAULT = "jarvis"
```

then:

```python
    async def _handle_chat(
        self, message: str, user_id: str, chat_id: str | None = None
    ) -> None:
        chat = chat_id or CHAT_ID_DEFAULT
        source = self.build_source(
            chat_id=chat,
            chat_name=chat.upper() if chat == CHAT_ID_DEFAULT else chat.title(),
            chat_type="dm",
            user_id=user_id,
            user_name=user_id,
        )
```

and in the read loop: `await self._handle_chat(decoded["message"], decoded["user_id"], decoded.get("chat_id"))`.

- [ ] **Step 5: Run both suites**

Run:
```
cd widget && PYTHONNOUSERSITE=1 .venv/bin/python -m pytest -v
cd .. && PYTHONNOUSERSITE=1 widget/.venv/bin/python -m pytest Hermes/plugins/jarvis/tests -v
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add widget/jarvis_widget/gateway.py widget/jarvis_widget/__main__.py Hermes/plugins/jarvis/protocol.py Hermes/plugins/jarvis/adapter.py widget/tests/test_gateway.py Hermes/plugins/jarvis/tests/
git commit -m "feat(jarvis): the chat frame says whose conversation it is"
```

---

### Task 7: The allowlist gains the family

**Files:**
- Modify: `Hermes/jarvis-config.yaml`
- Modify: `systemd/jarvis-hermes.service` (or the `.env` that `Hermes/run-gateway.sh` sources)
- Modify: `widget/README.md`

**Interfaces:**
- Consumes: task 6's `chat_id`; task 1's verdict.
- Produces: nothing in code. This is configuration, and getting it wrong is silent.

**The failure mode this task exists to prevent:** an unauthorized user is dropped with a log line and NOTHING on the screen (`adapter.py` says so). `JARVIS_ALLOWED_USERS` gates on the **`user_id`**, which the widget still sends as `primary` for everybody — so today's value keeps working. Do not change `user_id` per person: it is the authorization axis and the `chat_id` is the identity axis, and conflating them means an unenrolled phone is refused by authorization rather than degraded to `casa`.

- [ ] **Step 1: Confirm what the allowlist reads**

Run: `grep -n "allowed_users_env\|allow_all_env" -A 3 Hermes/plugins/jarvis/__init__.py`
Expected: it names `ENV_ALLOWED_USERS` / `ENV_ALLOW_ALL_USERS`, i.e. `JARVIS_ALLOWED_USERS`.

- [ ] **Step 2: Leave it alone, and write down why**

Add to `widget/README.md`, under the phone section:

```markdown
**`JARVIS_ALLOWED_USERS` is not the family list.** It gates the
`user_id`, which is `primary` for every turn from this house, and it is
authorization: a name missing from it is dropped in silence. Who a turn
BELONGS to is the `chat_id`, which selects a Hermes profile. Adding
people to the allowlist is not how a person gets their own memory —
`gateway.profile_routes` is (task 11).
```

- [ ] **Step 3: Commit**

```bash
git add widget/README.md
git commit -m "docs(widget): the allowlist is authorization, not the family list"
```

---

### Task 8: More than one turn at a time, in the widget

**Files:**
- Modify: `widget/jarvis_widget/remote.py` (`RemoteDesk`)
- Test: `widget/tests/test_remote.py`

**Interfaces:**
- Consumes: `Endpoint.persona` (task 5).
- Produces: `RemoteDesk.claim` refuses only a SECOND claim by the same person; `RemoteDesk.current` becomes `RemoteDesk.holders: dict[str, Endpoint]`; `RemoteDesk.busy_for(persona) -> bool`. `release(endpoint)` and `finish(pcm, endpoint)` keep their signatures, so `settle_turn` is unchanged.

Today one turn is held for the whole house and the second presser hears "está ocupado". The user's decision is genuinely parallel conversations. The engines stay serialised (task 10); what changes here is the claim.

- [ ] **Step 1: Write the failing tests**

```python
def test_two_people_hold_turns_at_the_same_time():
    mesa = RemoteDesk(on_utterance=lambda pcm, ep: None)
    marta, lucia = FakeEndpoint("marta"), FakeEndpoint("lucía")
    assert mesa.claim(marta, now=0.0)
    assert mesa.claim(lucia, now=0.0)
    assert marta.refused == 0 and lucia.refused == 0


def test_the_same_person_pressing_twice_is_still_refused():
    # Two phones logged in as the same person, or one phone pressed
    # twice: a queued spoken order answered a minute later reads as him
    # being confused, which is the reason this refusal exists.
    mesa = RemoteDesk(on_utterance=lambda pcm, ep: None)
    uno, otro = FakeEndpoint("marta"), FakeEndpoint("marta")
    assert mesa.claim(uno, now=0.0)
    assert not mesa.claim(otro, now=0.0)
    assert otro.refused == 1


def test_an_expired_claim_is_stolen_only_from_its_own_person():
    mesa = RemoteDesk(on_utterance=lambda pcm, ep: None)
    uno, otro = FakeEndpoint("marta"), FakeEndpoint("marta")
    mesa.claim(uno, now=0.0)
    assert mesa.claim(otro, now=10_000.0)


def test_releasing_one_person_leaves_the_other_holding():
    liberadas = []
    mesa = RemoteDesk(
        on_utterance=lambda pcm, ep: None,
        on_release=lambda ep=None: liberadas.append(ep),
    )
    marta, lucia = FakeEndpoint("marta"), FakeEndpoint("lucía")
    mesa.claim(marta, now=0.0)
    mesa.claim(lucia, now=0.0)
    mesa.release(marta)
    assert mesa.busy_for("lucía")
    assert not mesa.busy_for("marta")
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `cd widget && PYTHONNOUSERSITE=1 .venv/bin/python -m pytest tests/test_remote.py -v`
Expected: FAIL — `test_two_people_hold_turns_at_the_same_time` refuses the second.

- [ ] **Step 3: Implement**

Replace `RemoteDesk`'s single `current` / `_claimed_at` / `_allowance` with one record per person:

```python
@dataclass
class _Claim:
    endpoint: Endpoint
    desde: float
    margen: float


class RemoteDesk:
    """Who is holding a turn — one at a time PER PERSON.

    Until 2026-09-05 this was one turn for the whole house, and a second
    press anywhere heard "está ocupado". The refusal survives where it
    was earned and only there: two presses by the SAME person, where a
    queued spoken order answered a minute later reads as him being
    confused. Two different people are two conversations, and they run
    at once — the shared engines are serialised in the speaker's queue,
    not here.
    """

    def __init__(self, on_utterance, on_release=None) -> None:
        self._on_utterance = on_utterance
        self._on_release = on_release
        self._claims: dict[str, _Claim] = {}

    @property
    def busy(self) -> bool:
        """Whether ANYBODY holds a turn. Kept for callers that only ask
        whether the house is quiet; identity questions use `busy_for`."""
        return bool(self._claims)

    def busy_for(self, persona: str) -> bool:
        return persona in self._claims

    def claim(self, endpoint: Endpoint, now: float | None = None) -> bool:
        if now is None:
            now = time.monotonic()
        held = self._claims.get(endpoint.persona)
        if held is not None and held.endpoint is not endpoint:
            if now - held.desde < held.margen:
                endpoint.refuse()
                return False
            self._give_back(held.endpoint)
        self._claims[endpoint.persona] = _Claim(endpoint, now, HELD_TURN_SECONDS)
        return True

    def release(self, endpoint: Endpoint | None = None) -> None:
        if endpoint is None:
            return
        held = self._claims.get(endpoint.persona)
        if held is None or held.endpoint is not endpoint:
            return
        self._give_back(endpoint)

    def _give_back(self, endpoint: Endpoint) -> None:
        self._claims.pop(endpoint.persona, None)
        if self._on_release is not None:
            self._on_release(endpoint)

    def finish(self, pcm: bytes, endpoint: Endpoint, now: float | None = None) -> None:
        if now is None:
            now = time.monotonic()
        held = self._claims.get(endpoint.persona)
        if held is not None and held.endpoint is endpoint:
            held.desde = now
            held.margen = ANSWERING_SECONDS
        self._on_utterance(pcm, endpoint)
```

`on_release` now takes the endpoint that let go. `__main__`'s callback is `on_release=lambda: speaker.route_home()` today and becomes `on_release=lambda endpoint: speaker.route_home()` — the argument is accepted and ignored **for this task only**, because the speaker still has one sink. Task 10 removes `route_home` entirely, and with it the line in `settle_turn`; do not try to make the sink per person here.

- [ ] **Step 4: Run the tests**

Run: `cd widget && PYTHONNOUSERSITE=1 .venv/bin/python -m pytest tests/test_remote.py tests/test_main.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd widget && .venv/bin/ruff format . && .venv/bin/ruff check .
cd .. && git add widget/jarvis_widget/remote.py widget/jarvis_widget/__main__.py widget/tests/
git commit -m "feat(widget): two people can hold a turn at once"
```

---

### Task 9: More than one turn at a time, on the gateway side

**Files:**
- Modify: `Hermes/plugins/jarvis/adapter.py` (`_turn`, `_open_turn`, `_settle`, `_watch_turn`, `send`)
- Modify: `Hermes/plugins/jarvis/protocol.py` (`token`, `done`, `error` gain an optional `chat_id`)
- Modify: `widget/jarvis_widget/gateway.py` (`decode_server` surfaces it; the callbacks pass it on)
- Test: `Hermes/plugins/jarvis/tests/test_adapter.py`, `widget/tests/test_gateway.py`

**Interfaces:**
- Consumes: task 6's `chat_id`.
- Produces: `protocol.token(text, chat_id=None)`, `protocol.done(ms, chat_id=None)`, `protocol.error(msg, chat_id=None)`; `GatewayClient` callbacks gain a trailing `chat_id: str | None` argument. Task 10 routes on it.

One socket now carries several people's replies. Without a tag on the way back, the widget cannot tell whose clause it is holding — and the 2026-09-01 defect (a reply reaching the wrong place) is exactly the shape of bug this prevents.

- [ ] **Step 1: Write the failing tests**

```python
# Hermes/plugins/jarvis/tests/test_protocol.py
import json

from Hermes.plugins.jarvis.protocol import done, error, token


def test_a_reply_frame_says_whose_it_is_when_asked():
    assert json.loads(token("hola", chat_id="marta"))["chat_id"] == "marta"
    assert json.loads(done(12, chat_id="marta"))["chat_id"] == "marta"
    assert json.loads(error("vaya", chat_id="marta"))["chat_id"] == "marta"


def test_a_reply_frame_without_a_person_is_byte_for_byte_what_it_was():
    assert json.loads(token("hola")) == {"type": "token", "token": "hola"}
    assert json.loads(done(12)) == {"type": "done", "thinking_ms": 12}
```

```python
# Hermes/plugins/jarvis/tests/test_adapter.py
def test_two_chats_hold_two_turns():
    a = JarvisAdapter(config={})
    uno = a._open_turn("marta")
    dos = a._open_turn("lucía")
    assert not uno.settled and not dos.settled
    a._settle(uno)
    assert not dos.settled
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `PYTHONNOUSERSITE=1 widget/.venv/bin/python -m pytest Hermes/plugins/jarvis/tests -v`
Expected: FAIL — `_open_turn` takes no argument and the frames carry no `chat_id`.

- [ ] **Step 3: Implement the frames**

```python
def token(text: str, chat_id: str | None = None) -> str:
    frame: Dict[str, Any] = {"type": "token", "token": text}
    if chat_id:
        # Whose reply this is. Omitted for the house's single session,
        # so a strip built before today reads exactly what it always did.
        frame["chat_id"] = chat_id
    return json.dumps(frame)
```

The same shape for `done` and `error`.

- [ ] **Step 4: Implement the turn map**

Add `chat` to the `_Turn` dataclass, and replace the single slot:

```python
        # At most one open turn PER CHAT. It was one for the whole
        # platform until 2026-09-05, which is what made the house a
        # single conversation. The rule that a second `chat` frame
        # supersedes rather than queues keeps its meaning — it now
        # applies within one person's conversation, where it was earned.
        self._turns: Dict[str, _Turn] = {}

    def _open_turn(self, chat: str) -> _Turn:
        previo = self._turns.get(chat)
        if previo is not None and not previo.settled:
            self._abandon_turn(previo)
        turn = _Turn(chat=chat)
        self._turns[chat] = turn
        turn.watchdog = asyncio.ensure_future(self._watch_turn(turn))
        return turn

    def _settle(self, turn: _Turn, *, keep_slot: bool = False) -> None:
        if turn.settled:
            return
        turn.settled = True
        if turn.watchdog is not None:
            turn.watchdog.cancel()
        if not keep_slot and self._turns.get(turn.chat) is turn:
            del self._turns[turn.chat]
```

`_abandon_turn` takes the turn to abandon rather than reading the slot. `_watch_turn` and `send()` pass `chat_id=turn.chat` into every frame they build — a frame with no chat is the house's single session, which is what an older strip expects.

- [ ] **Step 5: Implement the widget half**

`decode_server` needs no change — it already passes unknown fields through. In `GatewayClient`, thread `msg.get("chat_id")` into the `on_token`, `on_done` and `on_error` callbacks as a trailing argument defaulting to `None`, and update `__main__`'s three handlers to accept it. A `None` means the desk, exactly as it does everywhere else in this plan.

- [ ] **Step 6: Run both suites**

Run:
```
cd widget && PYTHONNOUSERSITE=1 .venv/bin/python -m pytest -v
cd .. && PYTHONNOUSERSITE=1 widget/.venv/bin/python -m pytest Hermes/plugins/jarvis/tests -v
```
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add Hermes/plugins/jarvis/ widget/jarvis_widget/gateway.py widget/jarvis_widget/__main__.py widget/tests/
git commit -m "feat(jarvis): one socket, several conversations, each frame tagged"
```

---

### Task 10: One synthesis queue, and a destination per clause

**Files:**
- Modify: `widget/jarvis_widget/__main__.py` (the speaker / `say`)
- Test: `widget/tests/test_main.py`

**Interfaces:**
- Consumes: task 9's per-frame `chat_id`.
- Produces: `speaker.say(clause, destino)` where `destino` is an `Endpoint` or `None` for the room. Nothing later depends on it.

**This is the task that repeats a bug already paid for once.** On 2026-09-01 the reply's destination was read when a clause was SYNTHESISED rather than when it was queued, the gateway's `done` arrived while CosyVoice was still working, and a question asked on a phone was answered out loud in the house. Every test was green because they all asserted the sink's value and none asserted where the bytes landed. With several people talking at once that bug is not a race but a certainty.

And §2.8 already records the other half: **synthesising clauses concurrently interleaves their chunks and garbles the speech.** So synthesis is one clause at a time, globally, and the destination rides with each clause.

- [ ] **Step 1: Write the failing test**

```python
def test_two_conversations_do_not_cross(monkeypatch):
    entregado = []

    class FakeSpeaker:
        def say(self, clause, destino):
            entregado.append((clause, getattr(destino, "persona", None)))

    marta, lucia = FakeEndpoint("marta"), FakeEndpoint("lucía")
    hablante = FakeSpeaker()
    hablante.say("una", marta)
    hablante.say("dos", lucia)
    hablante.say("tres", marta)
    assert entregado == [("una", "marta"), ("dos", "lucía"), ("tres", "marta")]


def test_the_destination_is_bound_when_the_clause_is_queued():
    # The failure this pins: reading the destination at synthesis time
    # let the turn end first, and the clause went to the room.
    cola = []

    def encolar(clause, destino):
        cola.append((clause, destino))

    telefono = FakeEndpoint("marta")
    encolar("hola", telefono)
    # the turn ends here, and the phone lets go
    telefono_actual = None
    assert cola == [("hola", telefono)]
    assert telefono_actual is None
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `cd widget && PYTHONNOUSERSITE=1 .venv/bin/python -m pytest tests/test_main.py -v`
Expected: FAIL — `say` takes one argument.

- [ ] **Step 3: Implement**

```python
class Speaker:
    """His voice: one clause at a time, each bound to where it goes.

    ONE worker, globally, because §2.8 measured that synthesising
    clauses concurrently interleaves their chunks and garbles the
    speech. Several people may be mid-turn; only one clause is ever
    being made.

    The destination rides IN the queue rather than being read when the
    clause is synthesised. That is not a style choice: on 2026-09-01 it
    was read at synthesis time, the gateway's `done` arrived while
    CosyVoice was still working, the turn had already ended — and a
    question asked on a phone was answered out loud in the house. Every
    test was green, because they all asserted the sink's value and none
    asserted where the bytes landed. There is no sink now, so that bug
    is unrepresentable rather than fixed.
    """

    def __init__(self, sintetizar, salida) -> None:
        self._sintetizar = sintetizar
        self._salida = salida
        self._cola: queue.Queue[tuple[str, object | None] | None] = queue.Queue()
        self._hilo = threading.Thread(target=self._trabajar, daemon=True)
        self._hilo.start()

    def say(self, clause: str, destino: object | None) -> None:
        """Queue one clause for one destination. `None` is the room."""
        self._cola.put((clause, destino))

    def _trabajar(self) -> None:
        while True:
            item = self._cola.get()
            if item is None:
                return
            clause, destino = item
            try:
                pcm = self._sintetizar(clause)
            except Exception as exc:  # noqa: BLE001 — one clause, not the voice
                print(f"voz: {clause[:30]!r} falló ({exc!r})", file=sys.stderr, flush=True)
                continue
            if destino is None:
                self._salida.write(pcm)
            else:
                destino.write(pcm)
```

`route_home()` and the single sink go away, and with them the `speaker.route_home()` line in `settle_turn`, which becomes just `desk.release(endpoint)`.

In `on_token` / `on_done`, resolve the destination ONCE per turn from the frame's `chat_id` and pass it to every `say` of that turn:

```python
        def destino_de(chat_id: str | None):
            """The endpoint a reply belongs to, or None for the room."""
            if not chat_id:
                return None
            claim = remote_desk._claims.get(chat_id)
            return claim.endpoint if claim is not None else None
```

If the person's claim is gone — their phone dropped mid-answer — this returns `None` and the rest of the answer is spoken in the room. **That is the residue recorded on 2026-09-01 and it is not fixed here**; it is written down in `PROGRESS.md` at task 12 so it is not lost.

- [ ] **Step 4: Run the tests**

Run: `cd widget && PYTHONNOUSERSITE=1 .venv/bin/python -m pytest -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd widget && .venv/bin/ruff format . && .venv/bin/ruff check .
cd .. && git add widget/jarvis_widget/__main__.py widget/tests/test_main.py
git commit -m "feat(widget): one voice queue, and each clause knows where it goes"
```

---

### Task 11: The profiles on disk, and the routing table

**Files:**
- Modify: `Hermes/jarvis-config.yaml`
- Create: `Hermes/crear-profiles.sh`
- Modify: `widget/README.md`

**Interfaces:**
- Consumes: task 1's verdict, task 6's `chat_id`.
- Produces: a working per-person memory. This is the task where the feature becomes true.

- [ ] **Step 1: Create one profile per person**

```bash
#!/usr/bin/env bash
# One Hermes profile per person in this house.
#
# Each is a complete HERMES_HOME — memory, sessions, SOUL.md, cron,
# skills and config.yaml — so what a person's JARVIS remembers, how he
# speaks to them and WHICH TOOLS HE HAS are all per profile.
#
# `casa` exists for turns nobody can attribute. It has no tools.
set -euo pipefail

for persona in casa marta lucia; do
  hermes profile create "$persona" || true
done
echo "hecho. Ahora edita cada ~/.hermes/profiles/<persona>/config.yaml"
```

- [ ] **Step 2: Give the daughters' profiles a smaller world**

In each daughter's `~/.hermes/profiles/<name>/config.yaml`, set the platform toolsets to exclude `terminal` and disable the `jarvis_vision` plugin entry, and point `model.default` at the harnessed build. In `casa`'s, disable every tool. **Verify against task 1's finding** — if it said plugins are global, stop here and report.

- [ ] **Step 3: Write the routing table**

In `Hermes/jarvis-config.yaml`:

```yaml
gateway:
  multiplex_profiles: true
  profile_routes:
    - name: marta
      platform: jarvis
      chat_id: "marta"
      profile: marta
    - name: lucia
      platform: jarvis
      chat_id: "lucia"
      profile: lucia
    - name: casa
      platform: jarvis
      chat_id: "casa"
      profile: casa
```

**The trap, and it has bitten this project before:** `apply-config.sh` deep-merges dicts but **replaces lists wholesale** (§12, 2026-08-24). `profile_routes` is a list. A local edit to `.hermes/home/config.yaml` alone is erased on the next apply, and the erasure is silent — every person falls back to the default profile and shares one memory again. Change it HERE, in the tracked file.

- [ ] **Step 4: Apply, restart, and set a home channel per person**

```bash
Hermes/apply-config.sh
systemctl --user restart jarvis-hermes.service
```

**Then, from each phone, send `/sethome` as its first message.** This is not optional and it is the thing that will look like a bug: a session with no home channel answers its FIRST turn with `📬 No home channel is set`, which the strip correctly discards as a system message — so the question that opened the conversation simply vanishes (CLAUDE.md §5). Every new person hits this exactly once.

- [ ] **Step 5: Verify with two phones**

Say something on one phone, something different on another, then ask each what you just told it. Each must answer from its own conversation. Then ask the daughter's phone to run a command; he must not have the tool.

- [ ] **Step 6: Write it down and commit**

Add the ritual — `crear-profiles.sh`, the `apply-config.sh` list trap, and the `/sethome` step — to `widget/README.md`.

```bash
git add Hermes/jarvis-config.yaml Hermes/crear-profiles.sh widget/README.md
git commit -m "feat(hermes): one profile per person, routed by chat_id"
```

---

### Task 12: `familia` — what he may tell you about them

**Files:**
- Create: `Hermes/plugins/jarvis_familia/{__init__.py,plugin.yaml,familia.py,README.md}`
- Test: `Hermes/plugins/jarvis_familia/tests/test_familia.py`

**Interfaces:**
- Consumes: the profile layout from task 11.
- Produces: a `familia` tool registered ONLY in the father's profile.

**Scope, stated so it is not quietly widened:** this reads what he has written down about each person (`~/.hermes/profiles/<persona>/memories/USER.md`). **Course progress is not here** — that needs the teacher's student dimension, which the spec puts in piece 4. Read-only, one direction, and it never writes.

**Register the tool with the OpenAI *function* object, not the parameters.** `register_tool(schema=…)` takes `{"description": …, "parameters": {…}}`, because Hermes builds `{**entry.schema, "name": entry.name}` and wraps THAT as the function. Every plugin in this repo passed the parameters object directly until 2026-09-03, and the result was every tool reaching the model with no parameters and no description — so `{}` was the only call it could make, and that was blamed on the model for months (§12, 2026-08-26).

- [ ] **Step 1: Write the failing test**

```python
from Hermes.plugins.jarvis_familia.familia import leer_memoria, resumen


def test_a_person_with_nothing_written_says_so(tmp_path):
    assert leer_memoria(tmp_path, "marta") == ""


def test_a_person_with_something_written_comes_back(tmp_path):
    perfil = tmp_path / "profiles" / "marta" / "memories"
    perfil.mkdir(parents=True)
    (perfil / "USER.md").write_text("Le cuesta el análisis.")
    assert "análisis" in leer_memoria(tmp_path, "marta")


def test_a_name_that_could_escape_the_profiles_directory_reads_nothing(tmp_path):
    assert leer_memoria(tmp_path, "../../etc") == ""


def test_the_summary_names_everyone_it_was_asked_about(tmp_path):
    texto = resumen(tmp_path, ["marta", "lucia"])
    assert "marta" in texto and "lucia" in texto
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `PYTHONNOUSERSITE=1 widget/.venv/bin/python -m pytest Hermes/plugins/jarvis_familia/tests -v`
Expected: FAIL, no module.

- [ ] **Step 3: Implement**

```python
"""What he may tell the owner of this box about the people in it.

Read-only and one direction. Profiles are airtight by construction, so
crossing that boundary is a deliberate act with exactly one beneficiary:
this tool is registered in the father's profile and nowhere else.
"""

from __future__ import annotations

from pathlib import Path


def leer_memoria(raiz: Path, persona: str) -> str:
    """What he has written down about `persona`, or "".

    The name is checked rather than trusted: it becomes a path.
    """
    if not persona or not all(c.isalnum() or c in "-_" for c in persona):
        return ""
    archivo = raiz / "profiles" / persona / "memories" / "USER.md"
    try:
        if not archivo.is_file():
            return ""
        return archivo.read_text(errors="replace")[:4000]
    except OSError:
        return ""


def resumen(raiz: Path, personas: list[str]) -> str:
    """One block per person, in Spanish, for the model to speak from."""
    trozos = []
    for persona in personas:
        texto = leer_memoria(raiz, persona).strip()
        trozos.append(f"— {persona}: {texto or 'todavía no sé nada de ella.'}")
    return "\n".join(trozos)
```

- [ ] **Step 4: Register it, with the right schema shape**

```python
    ctx.register_tool(
        name="familia",
        handler=_familia,
        schema={
            "description": (
                "Lo que sabes de las personas de la casa. Sólo lectura."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "persona": {
                        "type": "string",
                        "description": "De quién. Vacío para todas.",
                    }
                },
                "required": [],
            },
        },
    )
```

- [ ] **Step 5: Run the tests and commit**

Run: `PYTHONNOUSERSITE=1 widget/.venv/bin/python -m pytest Hermes/plugins/jarvis_familia/tests -v`
Expected: PASS.

```bash
git add Hermes/plugins/jarvis_familia/
git commit -m "feat(familia): he can say how they are getting on, one direction only"
```

- [ ] **Step 6: Update PROGRESS.md and name what comes next**

Append to `PROGRESS.md`, newest first: what this built, what task 1 found, and the two things this plan deliberately did not do — **identity by voice in the room**, which waits on measuring whether two sisters of 16 and 17 separate, and **the teacher's student dimension**, which is piece 4.

```bash
git add PROGRESS.md
git commit -m "docs: identity per person, part 1 done"
```
