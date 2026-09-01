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


def test_lan_address_matches_what_the_routing_table_would_use() -> None:
    """The prefix checks this replaces were over-fitted to this box's
    Docker bridges; `172.16.0.0/12` is a legitimate home network. What
    is worth pinning is the METHOD — the address the kernel would send
    from — because that is what keeps the result off a bridge on any
    machine, not a string prefix."""
    import shutil

    if shutil.which("ip") is None:
        pytest.skip("iproute2 is not installed")
    out = subprocess.run(
        ["ip", "-4", "route", "get", "192.0.2.1"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    expected = out[out.index("src") + 1]

    assert lan_address() == expected


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


@pytest.mark.skipif(
    subprocess.run(["which", "openssl"], capture_output=True).returncode != 0,
    reason="openssl is not installed",
)
def test_the_root_may_only_vouch_for_this_box(tmp_path) -> None:
    """It is installed on three iPhones as a SYSTEM root, and `ca.key`
    sits 0600 on the same box as an agent holding the `terminal`
    toolset. Unconstrained, whoever takes that key can impersonate any
    site in the world to those phones — a bank included. The constraint
    shrinks the blast radius from "the whole internet" to "this box".

    Asserted twice over: the extension is present AND openssl refuses a
    leaf signed by this CA for a name outside it. The first alone would
    pass on a constraint nobody enforces."""
    ca, leaf, _key = ensure_certificate(tmp_path, "brain.local", "192.168.100.58")

    text = subprocess.run(
        ["openssl", "x509", "-in", str(ca), "-noout", "-text"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "Name Constraints" in text
    assert "DNS:brain.local" in text
    assert "IP:192.168.100.58/255.255.255.255" in text

    # The house's own leaf still validates against it.
    assert (
        subprocess.run(
            ["openssl", "verify", "-CAfile", str(ca), str(leaf)],
            capture_output=True,
        ).returncode
        == 0
    )

    # And one for somebody's bank, signed by the same key, does not.
    config = tmp_path / "elsewhere.cnf"
    config.write_text(
        "[req]\ndistinguished_name=dn\nprompt=no\n"
        "[dn]\nCN=bank.example.com\n"
        "[ext]\nbasicConstraints=CA:FALSE\nsubjectAltName=DNS:bank.example.com\n"
    )
    key = tmp_path / "elsewhere.key"
    csr = tmp_path / "elsewhere.csr"
    forged = tmp_path / "elsewhere.pem"
    subprocess.run(
        ["openssl", "genrsa", "-out", str(key), "2048"], check=True, capture_output=True
    )
    subprocess.run(
        [
            "openssl",
            "req",
            "-new",
            "-key",
            str(key),
            "-out",
            str(csr),
            "-config",
            str(config),
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "openssl",
            "x509",
            "-req",
            "-in",
            str(csr),
            "-CA",
            str(ca),
            "-CAkey",
            str(tmp_path / "ca.key"),
            "-CAcreateserial",
            "-out",
            str(forged),
            "-days",
            "10",
            "-sha256",
            "-extfile",
            str(config),
            "-extensions",
            "ext",
        ],
        check=True,
        capture_output=True,
    )

    refused = subprocess.run(
        ["openssl", "verify", "-CAfile", str(ca), str(forged)],
        capture_output=True,
        text=True,
    )
    assert refused.returncode != 0
    assert "permitted subtree violation" in (refused.stdout + refused.stderr)
