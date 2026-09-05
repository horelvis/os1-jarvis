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
This probe never calls `discover_plugins()` or asks Hermes a question,
so that side effect does NOT fire here — it stays a fact worth knowing
for anyone who later extends this probe to actually invoke discovery.

This box has one profile only (`default`), so the multiplex path
itself (two profiles served at once) could not be exercised live —
see the note at the bottom of the module and the written finding.

What this printed against the live box, 2026-09-05, `HERMES_HOME`
unset (`parents[4]` below — not `[3]` — is what actually reaches the
repo root from this file's depth; `[3]` silently resolves to a
nonexistent `Hermes/.hermes` and fails on the `hermes_cli` import):

    HERMES_HOME = (unset)

    -- profiles on this box --
      ProfileInfo(name='default', path=PosixPath('/home/nexus/.hermes'), ...)

    -- does a profile home carry its own plugin config? --
      /home/nexus/.hermes: config.yaml=yes

    -- how the gateway resolves a profile for an inbound source --
      match_profile_route: <function match_profile_route at 0x...>
      specificity: guild=2 chat=4 thread=8 (from the module)

    THE QUESTION: with `gateway.multiplex_profiles: true` and two
    profiles served, does each profile load only the plugins its own
    config.yaml enables? Read gateway/run.py's _multiplex_profile_homes
    and the plugin loader it hands each home to, and write down which.

`list_profiles()` returns `ProfileInfo` dataclass instances, not bare
names — `sorted()` over them prints a full repr rather than one name
per line. Left as printed rather than reformatted: with a single
profile `sorted()` never compares two entries, so it does not raise
here, but it would (`ProfileInfo` has no `__lt__`) the day a second
profile exists on this box. Worth knowing before trusting this output
verbatim on a box with more than one profile.

See `docs/superpowers/specs/2026-09-05-probe-profiles.md` for the
answer, reached by reading `.hermes/src/gateway/run.py`,
`.hermes/src/hermes_cli/plugins.py` and `.hermes/src/tools/registry.py`
rather than by running a second profile on this box.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

HERMES = Path(__file__).resolve().parents[4] / ".hermes"
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
    print("  specificity: guild=2 chat=4 thread=8 (from the module)")

    print("\nTHE QUESTION: with `gateway.multiplex_profiles: true` and two")
    print("profiles served, does each profile load only the plugins its own")
    print("config.yaml enables? Read gateway/run.py's _multiplex_profile_homes")
    print("and the plugin loader it hands each home to, and write down which.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
