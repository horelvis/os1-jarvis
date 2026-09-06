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

from jarvis_widget.certs import ensure_certificate, lan_address


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


@pytest.mark.skipif(
    subprocess.run(["which", "openssl"], capture_output=True).returncode != 0,
    reason="openssl is not installed",
)
def test_the_fingerprint_is_of_the_public_key_not_the_certificate(tmp_path) -> None:
    """The whole point of pinning SPKI rather than the certificate:
    reissuing the leaf from the SAME key must not invalidate a phone.
    A test that only checked "returns a string" would not notice the
    day somebody switches this to `openssl x509 -fingerprint`."""
    from jarvis_widget.certs import spki_fingerprint

    ca_pem, _cert, _key = ensure_certificate(tmp_path, "brain.local", "192.168.1.40")
    huella = spki_fingerprint(ca_pem)

    assert huella.startswith("sha256/")
    # Base64 of 32 bytes: 44 characters, the last one '='.
    assert len(huella) == len("sha256/") + 44
    assert huella.endswith("=")

    # The independent computation: the exact pipeline the contract
    # gives operators, run here rather than trusted.
    esperado = subprocess.run(
        "openssl x509 -in %s -pubkey -noout "
        "| openssl pkey -pubin -outform der "
        "| openssl dgst -sha256 -binary "
        "| openssl base64" % ca_pem,
        shell=True,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert huella == f"sha256/{esperado}"


@pytest.mark.skipif(
    subprocess.run(["which", "openssl"], capture_output=True).returncode != 0,
    reason="openssl is not installed",
)
def test_the_fingerprint_is_stable_across_calls(tmp_path) -> None:
    from jarvis_widget.certs import spki_fingerprint

    ca_pem, _cert, _key = ensure_certificate(tmp_path, "brain.local", "192.168.1.40")

    assert spki_fingerprint(ca_pem) == spki_fingerprint(ca_pem)


def test_the_served_chain_carries_the_ca_not_only_the_leaf(tmp_path) -> None:
    """The bug an iPhone found on 2026-09-06, and the reason it was
    invisible here.

    A phone enrolling with JARVIS is handed the SHA-256 of the house
    CA's PUBLIC KEY in its QR (`enrol.sobre`'s `ca`), and pins it. To
    check that pin it has to SEE the CA certificate — the leaf alone
    carries a different key, by design. The box was serving exactly one
    certificate, so the app had nothing to compare against and reported
    that the certificate did not match.

    It passed every test here because every test supplied the CA from a
    local file (`-CAfile`, `cafile=`), which is precisely what a phone
    does not have.
    """
    from jarvis_widget.certs import cadena_servida, ensure_certificate

    ca_pem, cert_pem, _key = ensure_certificate(tmp_path, "brain.local", "192.168.1.40")
    cadena = cadena_servida(tmp_path, cert_pem, ca_pem)

    texto = cadena.read_text()
    assert texto.count("BEGIN CERTIFICATE") == 2, "leaf and CA, in that order"
    # The leaf must come first: TLS requires the server's own
    # certificate to be the first in the chain.
    assert texto.index(cert_pem.read_text().strip()[:60]) < texto.index(
        ca_pem.read_text().strip()[:60]
    )


def test_the_chain_is_rebuilt_when_the_certificate_changes(tmp_path) -> None:
    """A stale chain would serve a leaf that no longer matches the key,
    which fails in a way that looks like the bug it replaced."""
    from jarvis_widget.certs import cadena_servida, ensure_certificate

    ca_pem, cert_pem, _key = ensure_certificate(tmp_path, "brain.local", "192.168.1.40")
    cadena = cadena_servida(tmp_path, cert_pem, ca_pem)
    cadena.write_text("basura de antes")

    de_nuevo = cadena_servida(tmp_path, cert_pem, ca_pem)

    assert de_nuevo.read_text().count("BEGIN CERTIFICATE") == 2


def test_the_chain_is_not_world_readable(tmp_path) -> None:
    from jarvis_widget.certs import cadena_servida, ensure_certificate

    ca_pem, cert_pem, _key = ensure_certificate(tmp_path, "brain.local", "192.168.1.40")

    assert cadena_servida(tmp_path, cert_pem, ca_pem).stat().st_mode & 0o077 == 0


def _dias_de_validez(pem) -> int:
    import datetime

    salida = subprocess.run(
        ["openssl", "x509", "-in", str(pem), "-noout", "-dates"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    fechas = dict(linea.split("=", 1) for linea in salida.strip().splitlines())
    leer = lambda s: datetime.datetime.strptime(s.strip(), "%b %d %H:%M:%S %Y %Z")  # noqa: E731
    return (leer(fechas["notAfter"]) - leer(fechas["notBefore"])).days


def test_the_leaf_lives_no_longer_than_apple_allows(tmp_path) -> None:
    """398 days, and it is not a preference.

    iOS and macOS refuse any TLS server certificate whose validity
    exceeds 398 days. This box issued its leaf for ten years, so every
    iPhone rejected it before looking at anything else — which is what
    an app reported on 2026-09-06 as "the certificate does not match",
    after the missing chain had already been fixed.
    """
    from jarvis_widget.certs import DIAS_HOJA, ensure_certificate

    _ca, cert_pem, _key = ensure_certificate(tmp_path, "brain.local", "192.168.1.40")

    assert DIAS_HOJA <= 398
    assert _dias_de_validez(cert_pem) <= 398


def test_the_ca_keeps_its_long_life(tmp_path) -> None:
    """Apple's limit is for SERVER certificates. The root is pinned by
    the public key in the QR, not served as a leaf, and reissuing it
    would strand every enrolled phone — the exact cost
    `spki_fingerprint` exists to avoid."""
    from jarvis_widget.certs import ensure_certificate

    ca_pem, _cert, _key = ensure_certificate(tmp_path, "brain.local", "192.168.1.40")

    assert _dias_de_validez(ca_pem) > 398


def test_a_leaf_about_to_expire_is_reissued_and_the_ca_is_not(tmp_path) -> None:
    """The half that matters more than the number. A 398-day leaf with
    no renewal is a box that stops answering phones in thirteen months,
    silently, with nothing in any log at the moment it breaks.

    The CA must survive the reissue: the phones pinned ITS key, and
    replacing it means re-enrolling every one of them.
    """
    from jarvis_widget.certs import ensure_certificate, spki_fingerprint

    # A leaf with one day of life, which is inside the renewal window.
    ca_pem, cert_pem, _key = ensure_certificate(
        tmp_path, "brain.local", "192.168.1.40", dias_hoja=1
    )
    huella_antes = spki_fingerprint(ca_pem)
    primera = cert_pem.read_text()

    ensure_certificate(tmp_path, "brain.local", "192.168.1.40")
    segunda = cert_pem.read_text()

    assert segunda != primera, "an expiring leaf must be replaced"
    assert spki_fingerprint(ca_pem) == huella_antes, "the CA's key must not move"


def test_a_healthy_leaf_is_left_alone(tmp_path) -> None:
    """Reissuing on every boot would churn the serial and the file for
    nothing, and would hide a renewal that had genuinely stopped."""
    from jarvis_widget.certs import ensure_certificate

    _ca, cert_pem, _key = ensure_certificate(tmp_path, "brain.local", "192.168.1.40")
    primera = cert_pem.read_text()

    ensure_certificate(tmp_path, "brain.local", "192.168.1.40")

    assert cert_pem.read_text() == primera


def test_deleting_the_leaf_does_not_move_the_ca(tmp_path) -> None:
    """The gesture an operator reaches for when a certificate looks
    wrong — delete it and restart — must not invalidate every enrolled
    phone. It did, on the live box, on 2026-09-06: the reuse guard
    required all three files, so a missing leaf fell through to the full
    path and regenerated the root with it.
    """
    from jarvis_widget.certs import ensure_certificate, spki_fingerprint

    ca_pem, cert_pem, _key = ensure_certificate(tmp_path, "brain.local", "192.168.1.40")
    huella = spki_fingerprint(ca_pem)
    cert_pem.unlink()

    ensure_certificate(tmp_path, "brain.local", "192.168.1.40")

    assert cert_pem.is_file(), "the leaf must be reissued"
    assert spki_fingerprint(ca_pem) == huella, "the CA must not move"
