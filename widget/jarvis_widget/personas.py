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

import re

# Not a person. The shared identity a turn falls back to.
CASA = "casa"

# Mirrors Hermes' own profile grammar
# (`.hermes/src/hermes_cli/profiles.py`, `_PROFILE_ID_RE`), because a
# person id becomes a profile name. ASCII only, deliberately: `'á'`
# passes `str.isalnum()`, and an id Hermes cannot use as a profile
# would make `profile_routes` fail to match in silence.
_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def es_valida(raw: str) -> bool:
    """Whether `raw` is already a person id, exactly as it stands."""
    return bool(_ID.match(raw))


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
