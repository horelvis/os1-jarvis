"""A certificate this house trusts, made with the openssl that is already
installed.

`cryptography` would do this in Python and is deliberately not used: the
system `openssl` (3.0.13 here) is on any Ubuntu, the files it makes are
inspectable with the tools anyone already knows, and this project counts
its dependencies.

Issued for ten years. It is installed by hand on each iPhone, through
Settings → General → About → Certificate Trust Settings, and nobody
wants to do that twice.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import os
import socket
import subprocess
from pathlib import Path

_YEARS = 3650

# Apple refuses any TLS server certificate whose validity exceeds 398
# days — iOS and macOS both. This box issued its leaf for ten years, so
# every iPhone rejected it before looking at anything else, and reported
# it the only way a phone can: "the certificate does not match". Found
# by a real device on 2026-09-06, after the missing chain
# (`cadena_servida`) had already been fixed and turned out not to be the
# whole story.
#
# The CA is NOT subject to this: the limit is for server certificates,
# and the root is pinned by its public key in the enrolment QR rather
# than served as one. `_YEARS` above stays where it is.
DIAS_HOJA = 398

# Reissue the leaf this many days before it expires. Without renewal a
# 398-day certificate is a box that stops answering phones in thirteen
# months — silently, with nothing in any log at the moment it breaks.
# Thirty days is enough slack that a box switched off for a holiday
# still comes back inside the window.
DIAS_MARGEN_RENOVACION = 30


@contextlib.contextmanager
def _private_files():
    """openssl creates its own output files, so the only way a key is
    never briefly world-readable is to narrow the umask around the call.
    A chmod afterwards closes a window that has already been open for
    the length of a 2048-bit keygen."""
    previous = os.umask(0o077)
    try:
        yield
    finally:
        os.umask(previous)


def lan_address() -> str:
    """This box's address on the house network.

    Found by asking the routing table which source address would be used
    to reach the outside — which never picks a Docker bridge, and there
    are twelve of those here. No packet is sent; UDP connect only sets
    the socket's peer.
    """
    override = os.getenv("JARVIS_WIDGET_REMOTE_HOST")
    if override:
        return override
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.0.2.1", 9))  # TEST-NET-1: routable, never routed
        return probe.getsockname()[0]
    finally:
        probe.close()


def _run(args: list[str]) -> None:
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"openssl failed: {' '.join(args)}\n{result.stderr}")


def _capture(args: list[str], stdin: bytes | None = None) -> bytes:
    """`_run`'s sibling for the two steps whose OUTPUT is the point.

    `_run` exists for commands that either work or must raise; these two
    are pipes. Same `check=True` posture: a failure here must not become
    an empty fingerprint, which would produce an envelope the app
    accepts and then cannot verify against anything.
    """
    return subprocess.run(args, input=stdin, capture_output=True, check=True).stdout


def _dias_restantes(cert_pem: Path) -> int:
    """Days until the leaf expires; 0 when that cannot be established.

    Zero on anything unreadable, so an unparseable certificate is
    renewed rather than trusted — the cheap direction to be wrong in.
    """
    import datetime

    try:
        salida = _capture(
            ["openssl", "x509", "-in", str(cert_pem), "-noout", "-enddate"]
        ).decode()
        cuando = datetime.datetime.strptime(
            salida.strip().split("=", 1)[1].strip(), "%b %d %H:%M:%S %Y %Z"
        ).replace(tzinfo=datetime.timezone.utc)
    except (OSError, ValueError, IndexError, subprocess.CalledProcessError):
        return 0
    return (cuando - datetime.datetime.now(datetime.timezone.utc)).days


def ensure_certificate(
    directory: Path, hostname: str, ip: str, dias_hoja: int = DIAS_HOJA
) -> tuple[Path, Path, Path]:
    """(ca_pem, cert_pem, key_pem), made once, reused, and RENEWED.

    The leaf is reissued when it is within `DIAS_MARGEN_RENOVACION` of
    expiry. **The CA is never touched by that** — every enrolled phone
    pinned its public key from the QR (`spki_fingerprint`), so replacing
    it would mean re-enrolling all of them, while replacing the leaf
    costs nobody anything. That asymmetry is the reason the pin is on
    the key and not on the certificate.
    """
    directory.mkdir(parents=True, exist_ok=True)
    ca_key = directory / "ca.key"
    ca_pem = directory / "ca.pem"
    key_pem = directory / "jarvis.key"
    cert_pem = directory / "jarvis.pem"
    # **The CA is made once and never again.** Not "once unless a file is
    # missing": the guard used to require all THREE files, so deleting
    # the leaf to force a renewal regenerated the root as well — found
    # by doing exactly that on the live box, 2026-09-06. Every phone
    # pinned that root's public key from its enrolment QR, so moving it
    # silently invalidates all of them, and the operator gesture most
    # likely to trigger it is the one somebody reaches for when a
    # certificate looks wrong.
    if ca_pem.is_file() and ca_key.is_file():
        if (
            cert_pem.is_file()
            and key_pem.is_file()
            and _dias_restantes(cert_pem) > DIAS_MARGEN_RENOVACION
        ):
            return ca_pem, cert_pem, key_pem
        # Missing, expiring, expired or unreadable: a new leaf from the
        # SAME CA, which no phone has to be told about.
        _emitir_hoja(
            directory, ca_key, ca_pem, key_pem, cert_pem, hostname, ip, dias_hoja
        )
        return ca_pem, cert_pem, key_pem

    with _private_files():
        _run(["openssl", "genrsa", "-out", str(ca_key), "2048"])
    os.chmod(ca_key, 0o600)
    # nameConstraints, and it is not decoration. This CA is installed on
    # three iPhones as a SYSTEM ROOT, which means it can vouch for any
    # name in the world to those phones — and `ca.key` sits 0600 on the
    # same box as an agent holding the `terminal` toolset. Unconstrained,
    # whoever obtains that key owns the banking session of every phone in
    # the house. Constrained, the blast radius shrinks from "the whole
    # internet" to "this box": the only certificates those phones will
    # accept from it are for `brain.local` and this LAN address.
    #
    # Critical, deliberately: a client that cannot understand the
    # constraint must reject the chain rather than ignore the limit. iOS
    # understands it.
    ca_config = directory / "ca.cnf"
    ca_config.write_text(
        "[req]\ndistinguished_name=dn\nprompt=no\nx509_extensions=ca_ext\n"
        "[dn]\nCN=JARVIS Home CA\n"
        "[ca_ext]\nsubjectKeyIdentifier=hash\n"
        "basicConstraints=critical,CA:TRUE\n"
        "keyUsage=critical,keyCertSign,cRLSign\n"
        "nameConstraints=critical,"
        f"permitted;DNS:{hostname},permitted;IP:{ip}/255.255.255.255\n"
    )
    _run(
        [
            "openssl",
            "req",
            "-x509",
            "-new",
            "-nodes",
            "-key",
            str(ca_key),
            "-sha256",
            "-days",
            str(_YEARS),
            "-out",
            str(ca_pem),
            "-config",
            str(ca_config),
            "-extensions",
            "ca_ext",
        ]
    )

    _emitir_hoja(directory, ca_key, ca_pem, key_pem, cert_pem, hostname, ip, dias_hoja)
    return ca_pem, cert_pem, key_pem


def cadena_servida(directory: Path, cert_pem: Path, ca_pem: Path) -> Path:
    """The leaf FOLLOWED BY the CA, as one file, for `load_cert_chain`.

    Found by a real iPhone on 2026-09-06, and it had been invisible here
    for a reason worth writing down. The box served exactly ONE
    certificate — the leaf — and every test that ever checked the TLS
    path supplied the CA separately from a local file (`-CAfile`,
    `cafile=`). That is what makes `Verify return code: 0` come back,
    and it is precisely what a phone does not have.

    A phone enrolling here is handed the SHA-256 of the CA's PUBLIC KEY
    in its QR (`enrol.sobre`) and pins it. To check that pin it has to
    SEE the CA certificate: the leaf carries a different key, on
    purpose, so that reissuing the leaf does not strand every enrolled
    phone. With only the leaf on the wire there is nothing to compare
    the pin against, and the app can only report that the certificate
    does not match — which is exactly what it reported.

    Rebuilt on every call rather than cached: it costs two small file
    reads at startup, and a stale chain would serve a leaf that no
    longer matches its key — a failure that looks like the bug this
    fixes.
    """
    cadena = directory / "cadena.pem"
    # The leaf FIRST: TLS requires the server's own certificate to open
    # the chain, with issuers after it.
    texto = cert_pem.read_text() + ca_pem.read_text()
    fd = os.open(cadena, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(texto)
    return cadena


def spki_fingerprint(ca_pem: Path) -> str:
    """The CA's public key, SHA-256, in the HPKP form the phone pins.

    **The key, not the certificate**, and that is the whole design: a
    leaf reissued from the same key keeps every enrolled phone working,
    where pinning the certificate would strand all of them on the day it
    is renewed. The cost, and it belongs written down next to the code
    rather than only in the contract: ROTATING THE CA KEY means
    re-enrolling every phone in the house.

    Shells out to `openssl` rather than reaching for `cryptography`,
    because this module already does exactly that for every other
    certificate operation and adding a second way to do the same job is
    how two of them drift apart. Four processes, once per QR — the cost
    is invisible next to `openssl req`, which this module already runs.
    """
    pubkey = _capture(["openssl", "x509", "-in", str(ca_pem), "-pubkey", "-noout"])
    der = _capture(["openssl", "pkey", "-pubin", "-outform", "der"], stdin=pubkey)
    digest = hashlib.sha256(der).digest()
    return "sha256/" + base64.b64encode(digest).decode("ascii")


def _emitir_hoja(
    directory: Path,
    ca_key: Path,
    ca_pem: Path,
    key_pem: Path,
    cert_pem: Path,
    hostname: str,
    ip: str,
    dias_hoja: int,
) -> None:
    """Issue the leaf from the EXISTING CA, replacing whatever was there.

    Split out of `ensure_certificate` on 2026-09-06 so a leaf can be
    renewed without touching the root. That separation is the whole
    point of pinning the CA's public key rather than the certificate:
    the phones hold `spki_fingerprint(ca_pem)` from their enrolment QR,
    and this function never touches `ca.key` or `ca.pem`, so every
    enrolled phone keeps working across a renewal with nothing to do.
    """
    config = directory / "leaf.cnf"
    config.write_text(
        "[req]\ndistinguished_name=dn\nreq_extensions=ext\nprompt=no\n"
        f"[dn]\nCN={hostname}\n"
        "[ext]\nbasicConstraints=CA:FALSE\n"
        "keyUsage=digitalSignature,keyEncipherment\n"
        "extendedKeyUsage=serverAuth\n"
        f"subjectAltName=DNS:{hostname},IP:{ip}\n"
    )
    csr = directory / "jarvis.csr"
    with _private_files():
        _run(["openssl", "genrsa", "-out", str(key_pem), "2048"])
    os.chmod(key_pem, 0o600)
    _run(
        [
            "openssl",
            "req",
            "-new",
            "-key",
            str(key_pem),
            "-out",
            str(csr),
            "-config",
            str(config),
        ]
    )
    _run(
        [
            "openssl",
            "x509",
            "-req",
            "-in",
            str(csr),
            "-CA",
            str(ca_pem),
            "-CAkey",
            str(ca_key),
            "-CAcreateserial",
            "-out",
            str(cert_pem),
            "-days",
            str(dias_hoja),
            "-sha256",
            "-extfile",
            str(config),
            "-extensions",
            "ext",
        ]
    )
    csr.unlink(missing_ok=True)
