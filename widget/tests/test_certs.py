"""The certificate, and the address it is issued for.

Safari will not open a microphone outside a secure context. On a private
IP that means a certificate this house trusts, which means a local CA and
a two-minute ritual per iPhone. There is nothing to test about Safari
here; what IS testable is that the files come out with the right names in
them and the right permissions on them.
"""

import ssl
import subprocess

import pytest

from samantha_widget.certs import ensure_certificate, lan_address


def test_lan_address_is_a_real_private_address() -> None:
    """Never 0.0.0.0, never loopback.

    What actually keeps a Docker bridge out of the answer is the
    routing-table method `lan_address()` uses — asking which source
    address the kernel would pick to reach the outside, which never
    lands on one of those bridges even though this box has twelve of
    them. A string-prefix check on the result would be over-fit to this
    machine's bridge subnets and would fail on a perfectly ordinary LAN
    elsewhere (172.16.0.0/12 is a legitimate private range too), so it
    is not asserted here.
    """
    import ipaddress

    address = ipaddress.ip_address(lan_address())

    assert address.is_private
    assert not address.is_loopback


@pytest.mark.skipif(
    subprocess.run(["which", "openssl"], capture_output=True).returncode != 0,
    reason="openssl is not installed",
)
def test_a_certificate_is_made_once_and_reused(tmp_path) -> None:
    first = ensure_certificate(tmp_path, "brain.local", "192.168.100.58")
    second = ensure_certificate(tmp_path, "brain.local", "192.168.100.58")

    assert first == second
    for path in first:
        assert path.is_file()


@pytest.mark.skipif(
    subprocess.run(["which", "openssl"], capture_output=True).returncode != 0,
    reason="openssl is not installed",
)
def test_the_leaf_carries_both_the_name_and_the_ip(tmp_path) -> None:
    """mDNS is the nice path and it fails on networks with client
    isolation, so the IP has to work as a fallback."""
    _ca, cert, _key = ensure_certificate(tmp_path, "brain.local", "192.168.100.58")

    text = subprocess.run(
        ["openssl", "x509", "-in", str(cert), "-noout", "-text"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout

    assert "DNS:brain.local" in text
    assert "IP Address:192.168.100.58" in text


@pytest.mark.skipif(
    subprocess.run(["which", "openssl"], capture_output=True).returncode != 0,
    reason="openssl is not installed",
)
def test_the_private_key_is_not_readable_by_others(tmp_path) -> None:
    import stat

    _ca, _cert, key = ensure_certificate(tmp_path, "brain.local", "192.168.100.58")

    assert stat.S_IMODE(key.stat().st_mode) == 0o600


@pytest.mark.skipif(
    subprocess.run(["which", "openssl"], capture_output=True).returncode != 0,
    reason="openssl is not installed",
)
def test_the_pair_loads_into_an_ssl_context(tmp_path) -> None:
    """The only test that proves the files are usable rather than merely
    present — a mismatched key and cert pass every check above."""
    _ca, cert, key = ensure_certificate(tmp_path, "brain.local", "192.168.100.58")

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(cert), str(key))
