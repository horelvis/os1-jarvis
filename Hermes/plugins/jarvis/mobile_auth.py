"""Authentication for the opt-in Hermes mobile listener.

This intentionally owns the existing ``~/.jarvis`` roster format without
importing the widget package. M4 moves media, not this admission boundary.
"""

from __future__ import annotations

import json
import os
import secrets
from hmac import compare_digest
from pathlib import Path
from urllib.parse import urlsplit

CASA = "casa"
_SECRET_BYTES = 24


def _path(value: Path | str | None, env: str, default: str) -> Path:
    return Path(value or os.getenv(env) or Path.home() / ".jarvis" / default)


def load_roster(
    roster_path: Path | str | None = None, token_path: Path | str | None = None
) -> dict[str, str]:
    """Load the roster, adopting the legacy token when creating it."""
    roster_file = _path(roster_path, "JARVIS_MOBILE_ROSTER", "personas.json")
    token_file = _path(token_path, "JARVIS_MOBILE_TOKEN", "remote.token")
    if roster_file.is_file():
        try:
            raw = json.loads(roster_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            raw = {}
        if isinstance(raw, dict):
            roster = {
                persona: secret
                for persona, secret in raw.items()
                if isinstance(persona, str)
                and isinstance(secret, str)
                and persona.isascii()
                and secret.isascii()
            }
            if roster:
                return roster
    secret = (
        token_file.read_text(encoding="utf-8").strip()
        if token_file.is_file()
        else secrets.token_urlsafe(_SECRET_BYTES)
    )
    roster = {CASA: secret}
    try:
        roster_file.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(roster_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as handle:
            json.dump(roster, handle)
    except OSError:
        pass
    return roster


def bearer_token(value: str | None) -> str | None:
    if not value:
        return None
    scheme, separator, token = value.partition(" ")
    if not separator or scheme.casefold() != "bearer":
        return None
    return token.strip() or None


class MobileGuard:
    """Timing-safe bearer lookup and exact-origin validation."""

    def __init__(self, roster: dict[str, str], origins: tuple[str, ...]) -> None:
        self._roster = dict(roster)
        self._origins = origins

    def persona_for(self, offered: str | None) -> str | None:
        if not offered or not offered.isascii():
            return None
        found = None
        for persona, secret in sorted(self._roster.items()):
            if secret.isascii() and compare_digest(offered, secret):
                found = persona
        return found

    def origin_ok(self, origin: str) -> bool:
        if not origin:
            return True
        try:
            offered = urlsplit(origin)
        except ValueError:
            return False
        return any(self._same_origin(offered, expected) for expected in self._origins)

    @staticmethod
    def _same_origin(offered: object, expected: str) -> bool:
        try:
            mine = urlsplit(expected)
            return (
                offered.scheme == mine.scheme
                and offered.hostname == mine.hostname
                and (offered.port or (443 if offered.scheme == "https" else 80))
                == (mine.port or (443 if mine.scheme == "https" else 80))
            )
        except (AttributeError, ValueError):
            return False
