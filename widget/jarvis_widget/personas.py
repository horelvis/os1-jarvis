"""Who a turn belongs to, and what it is when nobody knows.

Pure: no sockets, no files, no GTK. A person id is three things at
once — the `chat_id` on the gateway wire, the name of a Hermes profile,
and a file name under `~/.jarvis/` — so it is made in exactly one place
and it is made narrow.

`CASA` is the identity of a turn nobody can attribute: a guest, a
device that was never enrolled, a name that does not survive this
module. **A failure degrades here and never to another person**, which
is what makes the probabilistic half of this feature (a voice in a
room) safe to build on later.

**What `CASA` does NOT yet mean, corrected 2026-09-06 (final review,
CLAUDE.md):** this used to claim it "owns no tools and it never writes
into a person's memory". Neither half is true today. Every `chat_id` —
`CASA` included — resolves to the same default Hermes profile, the one
holding `terminal`, because nothing in this branch configures
`profile_routes` or `multiplex_profiles`; `grep` finds neither outside
plan and spec documents. Per-profile isolation is the MECHANISM this
branch provides, not a POLICY anybody has configured. A reader must not
take this docstring's word that `CASA` — or any other persona — is
sandboxed from tools or from another person's memory.
"""

from __future__ import annotations

import re

# Not a person. The shared identity a turn falls back to.
CASA = "casa"

# Mirrors Hermes' own profile grammar
# (`.hermes/src/hermes_cli/profiles.py`, `_PROFILE_ID_RE`), because a
# person id becomes a profile name. ASCII only, deliberately: `'á'`
# passes `str.isalnum()`, and an id Hermes cannot use as a profile
# would make a future per-`chat_id` profile route fail to match in
# silence — kept strict ahead of that ever being configured (see the
# module docstring: nothing routes by profile today).
_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def es_valida(raw: str) -> bool:
    """Whether `raw` is already a person id, exactly as it stands."""
    # Guard: the type hint is a promise to readers; this is a promise to
    # the process. A socket handler decoding JSON or an audio thread can
    # send a number or None without warning. Any non-string is simply not
    # a valid id, never an exception.
    if not isinstance(raw, str):
        return False
    return bool(_ID.match(raw))


def normalizar(raw: str | None) -> str:
    """A person id, or `CASA`. Never raises, never returns empty.

    Anything that could escape a path, a config key or a session key
    becomes `CASA` rather than being rejected: the callers are a socket
    handler and an audio thread, and neither has anywhere to put an
    exception.
    """
    # Guard: the type hint is a promise to readers; this is a promise to
    # the process. A JSON decoder off the wire can send a number, a list
    # or bytes. None is documented and handled. Any non-string is simply
    # not a person id, never an exception.
    if not isinstance(raw, str):
        return CASA
    limpio = raw.strip().casefold()
    return limpio if es_valida(limpio) else CASA
