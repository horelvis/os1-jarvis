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

import contextlib
import os
import socket
import subprocess
from pathlib import Path

_YEARS = 3650


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


def ensure_certificate(
    directory: Path, hostname: str, ip: str
) -> tuple[Path, Path, Path]:
    """(ca_pem, cert_pem, key_pem), made once and reused."""
    directory.mkdir(parents=True, exist_ok=True)
    ca_key = directory / "ca.key"
    ca_pem = directory / "ca.pem"
    key_pem = directory / "jarvis.key"
    cert_pem = directory / "jarvis.pem"
    if ca_pem.is_file() and cert_pem.is_file() and key_pem.is_file():
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
            str(_YEARS),
            "-sha256",
            "-extfile",
            str(config),
            "-extensions",
            "ext",
        ]
    )
    csr.unlink(missing_ok=True)
    return ca_pem, cert_pem, key_pem
