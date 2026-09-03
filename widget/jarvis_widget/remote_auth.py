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

import os
import secrets
from hmac import compare_digest
from pathlib import Path
from urllib.parse import urlsplit

DEFAULT_SECRET_PATH = Path.home() / ".jarvis" / "remote.token"

# 32 URL-safe characters. It travels in a link that is added to a phone's
# home screen, so it has to survive being a URL and being looked at.
_SECRET_BYTES = 24


def load_or_create_secret(path: Path | None = None) -> str:
    """The shared secret, made once and reused.

    Written 0600 before anything is put in it: creating it world-readable
    and chmod'ing afterwards leaves a window in which the secret is on
    disk and readable.
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


class Guard:
    """The two questions asked of every connection."""

    def __init__(self, secret: str, origin: str, *also: str) -> None:
        self.secret = secret
        self.origin = origin
        # More than one, because there is more than one way in. The page
        # is reached at `https://brain.local:8443` when mDNS works and
        # at the LAN address when it does not — the fallback the design
        # asks for, and the one that matters on a network whose router
        # does not answer `.local`. A browser sends the origin it was
        # loaded from, and `origin_ok` compares whole, so binding only
        # the name refused every connection made by the fallback.
        self.origins = [origin, *also]

    def token_ok(self, offered: str | None) -> bool:
        """Constant-time: a timing oracle on a LAN is not theoretical."""
        if not offered:
            return False
        return compare_digest(offered, self.secret)

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
