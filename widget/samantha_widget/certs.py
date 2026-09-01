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

import os
import socket
import subprocess
from pathlib import Path

_YEARS = 3650


def lan_address() -> str:
    """This box's address on the house network.

    Found by asking the routing table which source address would be used
    to reach the outside — which never picks a Docker bridge, and there
    are twelve of those here. No packet is sent; UDP connect only sets
    the socket's peer.
    """
    override = os.getenv("SAMANTHA_WIDGET_REMOTE_HOST")
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

    _run(["openssl", "genrsa", "-out", str(ca_key), "2048"])
    os.chmod(ca_key, 0o600)
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
            "-subj",
            "/CN=JARVIS Home CA",
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
