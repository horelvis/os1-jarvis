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

from loguru import logger

from .personas import CASA, es_valida

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


def _es_canonica(clave: object) -> bool:
    """Whether `clave` is already a person id, exactly as it stands —
    not merely one that WOULD become one through `normalizar`.

    Used only for a key already read off disk or handed to `save_roster`:
    a key that only survives by folding (an accented `papá`, an
    upper-case `MARTA`) is a typo, not a person, and folding it in
    `load_or_create_roster` used to let a typo overwrite `casa` or
    promote itself into an existing person's slot. `normalizar` itself
    stays exactly what it was for task 4's enrolment path, where turning
    a raw string INTO a valid id is exactly the point.
    """
    return (
        isinstance(clave, str)
        and es_valida(clave)
        and clave == clave.strip().casefold()
    )


def _sanitized_roster(crudo: dict) -> dict[str, str]:
    """Only entries whose key is already canonical, string-valued, and
    the first of its kind. Anything else is dropped rather than folded
    — see `_es_canonica` — and every drop is logged once, naming the
    key and never the secret."""
    limpio: dict[str, str] = {}
    for clave, valor in crudo.items():
        if not isinstance(valor, str):
            logger.warning(
                f"personas: entrada descartada, valor no es texto — {clave!r}"
            )
            continue
        if not _es_canonica(clave):
            logger.warning(f"personas: entrada descartada, id inválido — {clave!r}")
            continue
        if clave in limpio:
            logger.warning(f"personas: entrada duplicada descartada — {clave!r}")
            continue
        limpio[clave] = valor
    return limpio


def _read_roster_file(target: Path) -> dict[str, str] | None:
    """The roster as parsed and sanitised, or `None` if the file itself
    cannot be trusted at all.

    Never raises: this runs inside `_boot`, with nobody to catch a
    traceback, and a hand-edited file — or the path itself — is exactly
    the kind of thing that goes wrong in the ways a person makes
    mistakes: invalid JSON, valid JSON whose top level is not an object,
    bytes that are not valid UTF-8 at all, or the path being unreadable
    outright (permissions, or a directory left where a file is
    expected). Logged once, naming the path and never the contents, and
    the file — or whatever is at that path — is left untouched: an
    operator may want to look at it.

    The KIND of node is checked with `stat`, before anything is opened,
    rather than leaving it to the `try` below: a directory or a Unix
    socket raise promptly and would be caught there, but a FIFO with no
    writer on the other end does not raise at all — `read_text()` simply
    blocks forever. No `except` catches a hang, so the only way to rule
    it out is to never attempt the read.
    """
    if not target.is_file():
        logger.warning(
            f"personas: {target} no es un archivo normal; se ignora sin tocarlo"
        )
        return None
    try:
        crudo = json.loads(target.read_text() or "{}")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        logger.warning(f"personas: {target} no se puede leer; se ignora sin tocarlo")
        return None
    if not isinstance(crudo, dict):
        logger.warning(f"personas: {target} no es un objeto; se ignora sin tocarlo")
        return None
    return _sanitized_roster(crudo)


def _write_roster_file(
    target: Path, roster: dict[str, str], *, exclusive: bool
) -> None:
    """Write `roster` as JSON to `target`, flushed and fsynced before the
    handle closes: a power cut between the write and the flush is what
    used to leave the empty file that then read back as a roster with
    no `casa` in it at all."""
    flags = os.O_WRONLY | os.O_CREAT | (os.O_EXCL if exclusive else os.O_TRUNC)
    fd = os.open(target, flags, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump(roster, handle)
        handle.flush()
        os.fsync(handle.fileno())


def load_or_create_roster(path: Path | None = None) -> dict[str, str]:
    """`{person: secret}`, made once and reused.

    A new box starts with one entry, `casa`, and grows one per person
    as phones are enrolled (task 4). Written 0600 before anything is
    put in it, for the reason `load_or_create_secret` gives: creating it
    world-readable and chmod'ing afterwards leaves a window in which
    every secret in the house is on disk and readable.

    Always contains `casa`. A roster that came back without it — an
    empty file, one edited by hand to drop it — would otherwise lock
    every phone in the house out and 500 the enrolment page, both in
    silence; one is minted, persisted, and logged instead.
    """
    target = Path(
        path or os.getenv("JARVIS_WIDGET_REMOTE_ROSTER") or DEFAULT_ROSTER_PATH
    )
    # `exists()`, not `is_file()`: a directory (or a FIFO, a socket, a
    # device node) left at this path must go through the read attempt
    # below rather than falling to the create branch, which would crash
    # trying to `O_CREAT | O_EXCL` a path that is already there. Whether
    # the node is actually a regular file is `_read_roster_file`'s own
    # first check, made by `stat` and never by opening it.
    if target.exists():
        roster = _read_roster_file(target)
        if roster is None:
            # The file itself could not be trusted at all. It is left
            # exactly as it was; what comes back behaves like a fresh
            # box, in memory only — nothing is persisted over it.
            return {CASA: _adopted_or_fresh_secret()}
        if CASA not in roster:
            logger.warning(
                f"personas: {target} no tenía 'casa'; se ha creado uno nuevo"
            )
            roster[CASA] = new_secret()
            save_roster(roster, target)
        return roster
    roster = {CASA: _adopted_or_fresh_secret()}
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        _write_roster_file(target, roster, exclusive=True)
    except OSError as exc:
        # `exists()` is False for a dangling symlink, so it reaches
        # here — and `O_CREAT | O_EXCL` then fails because the link
        # itself is already a directory entry, even though it points
        # nowhere. A box that cannot persist its roster should still
        # answer its phones for this boot; the roster this returns is
        # simply never written to disk.
        logger.warning(f"personas: no se pudo crear {target} — {exc}")
    return roster


def save_roster(roster: dict[str, str], path: Path | None = None) -> None:
    """Replace the roster on disk, 0600, atomically.

    Refuses to write a key that is not already a valid person id,
    raising `ValueError`: reaching this function with one is a
    programming error, not runtime input — task 4 is what writes into
    this roster from an enrolment flow, and the roster's own grammar is
    not something to relax at the point that persists it.
    """
    for persona in roster:
        if not _es_canonica(persona):
            raise ValueError(f"id de persona inválido para escribir: {persona!r}")
    target = Path(
        path or os.getenv("JARVIS_WIDGET_REMOTE_ROSTER") or DEFAULT_ROSTER_PATH
    )
    temporal = target.with_suffix(".tmp")
    _write_roster_file(temporal, roster, exclusive=False)
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

        `compare_digest` raises `TypeError` on a non-ASCII `str`, on
        either side, and `offered` reaches here straight off an
        unauthenticated query string. A stranger on the wifi gets a 500
        rather than a refusal for that alone, and a single non-ASCII
        secret already on the roster would do the same to everyone
        else's login, not just its own — so both are simply "not a
        match" rather than an exception.
        """
        if not offered or not offered.isascii():
            return None
        encontrada: str | None = None
        for persona, secreto in sorted(self.secretos.items()):
            if secreto.isascii() and compare_digest(offered, secreto):
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
