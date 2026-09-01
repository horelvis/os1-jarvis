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

DEFAULT_SECRET_PATH = Path.home() / ".samantha" / "remote.token"

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
        path or os.getenv("SAMANTHA_WIDGET_REMOTE_TOKEN") or DEFAULT_SECRET_PATH
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

    def __init__(self, secret: str, origin: str) -> None:
        self.secret = secret
        self.origin = origin

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
            mine = urlsplit(self.origin)
        except ValueError:
            return False
        if not offered.scheme or not offered.hostname:
            return False
        return (
            offered.scheme == mine.scheme
            and offered.hostname == mine.hostname
            and (offered.port or (443 if offered.scheme == "https" else 80))
            == (mine.port or (443 if mine.scheme == "https" else 80))
        )
