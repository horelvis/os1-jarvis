"""Who may open the phone socket.

Pure, so it can be tested without a socket or a certificate — and it is
worth testing alone, because it is the whole of the authentication that
replaces "only from this machine". What is behind it is an agent with
the `terminal` toolset.

The origin check is the same one `Hermes/plugins/jarvis/adapter.py`
makes, and for the same reason written there: WebSockets are not subject
to the same-origin policy, so without it any page in any browser on the
network could open the socket and talk to an agent with tools. An absent
Origin is allowed because non-browser clients do not send one and are
not the attacker this is about; browsers always do.
"""

from __future__ import annotations

import json
import os
import secrets
from hmac import compare_digest
from pathlib import Path
from urllib.parse import urlsplit

from .personas import CASA, normalizar

DEFAULT_SECRET_PATH = Path.home() / ".jarvis" / "remote.token"
DEFAULT_ROSTER_PATH = Path.home() / ".jarvis" / "personas.json"

# 32 URL-safe characters. It travels in a link that is added to a phone's
# home screen, so it has to survive being a URL and being looked at.
_SECRET_BYTES = 24


def load_or_create_secret(path: Path | None = None) -> str:
    """The shared secret, made once and reused.

    Written 0600 before anything is put in it: creating it world-readable
    and chmod'ing afterwards leaves a window in which the secret is on
    disk and readable.

    Superseded by `load_or_create_roster` for new boxes, but kept: this
    is what an un-migrated box still has, and what the roster's own
    creation path reads to adopt an already-enrolled house.
    """
    target = Path(
        path or os.getenv("JARVIS_WIDGET_REMOTE_TOKEN") or DEFAULT_SECRET_PATH
    )
    if target.is_file():
        return target.read_text().strip()
    target.parent.mkdir(parents=True, exist_ok=True)
    secret = secrets.token_urlsafe(_SECRET_BYTES)
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(secret)
    return secret


def new_secret() -> str:
    """A fresh secret, the same size as the one this module already makes.

    Exists so `remote.py` can mint one for a newly enrolled person
    without importing `_SECRET_BYTES` across module boundaries.
    """
    return secrets.token_urlsafe(_SECRET_BYTES)


def _adopted_or_fresh_secret() -> str:
    """What `casa`'s secret should be the very first time a roster is
    written.

    Three iPhones in this house are enrolled against the OLD
    single-secret file (`load_or_create_secret`'s `remote.token`)
    already. A roster that ignored it and minted a fresh `casa` secret
    would lock all three out on an upgrade that is supposed to be
    invisible to them, so the file is adopted whole when it exists —
    same environment override, same default path — and only a box with
    no history at all gets a freshly minted secret.
    """
    old_path = Path(os.getenv("JARVIS_WIDGET_REMOTE_TOKEN") or DEFAULT_SECRET_PATH)
    if old_path.is_file():
        return old_path.read_text().strip()
    return new_secret()


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
    roster = {CASA: _adopted_or_fresh_secret()}
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump(roster, handle)
    return roster


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


class Guard:
    """The two questions asked of every connection."""

    def __init__(self, secretos: dict[str, str], origin: str, *also: str) -> None:
        self.secretos = dict(secretos)
        self.origin = origin
        # More than one, because there is more than one way in. The page
        # is reached at `https://brain.local:8443` when mDNS works and
        # at the LAN address when it does not — the fallback the design
        # asks for, and the one that matters on a network whose router
        # does not answer `.local`. A browser sends the origin it was
        # loaded from, and `origin_ok` compares whole, so binding only
        # the name refused every connection made by the fallback.
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

    def origin_ok(self, origin: str) -> bool:
        if not origin:
            return True
        # Compared whole rather than by hostname suffix: a check that
        # accepted anything ending in the host name would accept
        # `brain.local.evil.com`.
        try:
            offered = urlsplit(origin)
        except ValueError:
            return False
        if not offered.scheme or not offered.hostname:
            return False
        return any(self._same(offered, mine) for mine in self.origins)

    @staticmethod
    def _same(offered, mine: str) -> bool:
        try:
            expected = urlsplit(mine)
        except ValueError:
            return False
        return (
            offered.scheme == expected.scheme
            and offered.hostname == expected.hostname
            and (offered.port or (443 if offered.scheme == "https" else 80))
            == (expected.port or (443 if expected.scheme == "https" else 80))
        )
