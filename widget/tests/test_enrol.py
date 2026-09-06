"""Getting a phone enrolled without typing a token on a touchscreen."""

import io
import plistlib
import stat

from jarvis_widget.enrol import mobileconfig, write_qr
from jarvis_widget.personas import CASA
from jarvis_widget.remote import Enrolment


def test_a_closed_enrolment_is_for_nobody():
    e = Enrolment()
    assert e.persona() is None
    assert not e.is_open(now=1000.0)


def test_opening_names_the_person_it_is_for():
    e = Enrolment()
    e.abrir("marta", now=1000.0)
    assert e.persona(now=1000.0) == "marta"
    assert e.is_open(now=1000.0)


def test_the_window_closes_and_takes_the_person_with_it():
    e = Enrolment()
    e.abrir("marta", now=1000.0)
    assert not e.is_open(now=1000.0 + 10_000)
    assert e.persona(now=1000.0 + 10_000) is None


def test_a_name_that_does_not_survive_normalizar_enrols_casa():
    e = Enrolment()
    e.abrir("../papá", now=1000.0)
    assert e.persona(now=1000.0) == CASA


def test_the_qr_is_a_png_that_is_not_empty(tmp_path) -> None:
    path = write_qr("https://brain.local:8443/#tok", tmp_path / "qr.png")

    assert path.is_file()
    assert path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_the_qr_file_is_written_0600(tmp_path) -> None:
    """Consistency with certs.py and remote_auth.py, not because this
    file is itself sensitive — see enrol.py's own docstring."""
    path = write_qr("https://brain.local:8443/#tok", tmp_path / "qr.png")

    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_the_png_is_pypngs_not_pillows(tmp_path) -> None:
    """The dependency was approved on the strength of writing PNG
    through pypng rather than Pillow — not on Pillow being absent from
    the process, which turned out to be false on a box with the apt
    package python3-pil (a fact about that box's environment, not about
    this code; a prior version of this test asserted the wrong thing).

    So this asserts on the OUTPUT instead: it reproduces pypng's own
    encoding of the same input, independently of `write_qr`, and
    compares byte for byte. `qrcode.image.pil.PilImage` (Pillow's
    factory) produces a same-sized-in-modules but differently-compressed
    PNG for identical input — 456 bytes measured 2026-09-01 against
    pypng's 329 — so this would catch write_qr silently switching
    factories, without depending on Pillow being importable or not."""
    import qrcode
    from qrcode.image.pure import PyPNGImage

    url = "https://brain.local:8443/#tok"
    expected = io.BytesIO()
    qrcode.make(url, image_factory=PyPNGImage, box_size=8, border=2).save(expected)

    path = write_qr(url, tmp_path / "qr.png")

    assert path.read_bytes() == expected.getvalue()


def test_the_profile_is_a_plist_carrying_the_certificate(tmp_path) -> None:
    ca = tmp_path / "ca.pem"
    ca.write_bytes(b"-----BEGIN CERTIFICATE-----\nAAAA\n-----END CERTIFICATE-----\n")

    profile = plistlib.loads(mobileconfig(ca))

    assert profile["PayloadType"] == "Configuration"
    payload = profile["PayloadContent"][0]
    assert payload["PayloadType"] == "com.apple.security.root"
    assert payload["PayloadContent"] == ca.read_bytes()


def test_the_profile_identifies_itself_recognisably(tmp_path) -> None:
    """It appears in Settings under whatever name this gives it, and the
    user has to find it there to trust it."""
    ca = tmp_path / "ca.pem"
    ca.write_bytes(b"-----BEGIN CERTIFICATE-----\nAAAA\n-----END CERTIFICATE-----\n")

    profile = plistlib.loads(mobileconfig(ca))

    assert "JARVIS" in profile["PayloadDisplayName"]


def test_the_envelope_carries_the_four_fields_and_the_version() -> None:
    import json

    from jarvis_widget.enrol import sobre

    texto = sobre(
        url="wss://brain.local:8443/ws",
        token="un-secreto",
        ca="sha256/AAAA",
    )
    datos = json.loads(texto)

    assert datos == {
        "v": 1,
        "url": "wss://brain.local:8443/ws",
        "token": "un-secreto",
        "ca": "sha256/AAAA",
    }


def test_the_envelope_refuses_to_be_written_incomplete() -> None:
    """The app rejects a partial envelope rather than falling back to
    system validation (contract). The box must therefore never produce
    one: an empty token or a missing fingerprint is a bug HERE, and a
    QR that a person scans and that silently does nothing is the worst
    possible way to find out."""
    import pytest

    from jarvis_widget.enrol import sobre

    for kwargs in (
        {"url": "", "token": "t", "ca": "sha256/A"},
        {"url": "wss://x/ws", "token": "", "ca": "sha256/A"},
        {"url": "wss://x/ws", "token": "t", "ca": ""},
    ):
        with pytest.raises(ValueError):
            sobre(**kwargs)


def test_the_envelope_refuses_a_url_that_is_not_wss() -> None:
    """`wss` is mandatory in the contract, and the app drops a `ws://`
    QR before connecting. A box that writes one has misconfigured
    itself — say so here rather than shipping a QR nothing will accept."""
    import pytest

    from jarvis_widget.enrol import sobre

    with pytest.raises(ValueError):
        sobre(url="ws://brain.local:8443/ws", token="t", ca="sha256/A")
