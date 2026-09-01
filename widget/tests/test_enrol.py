"""Getting a phone enrolled without typing a token on a touchscreen."""

import plistlib

from samantha_widget.enrol import mobileconfig, write_qr


def test_the_qr_is_a_png_that_is_not_empty(tmp_path) -> None:
    path = write_qr("https://brain.local:8443/#tok", tmp_path / "qr.png")

    assert path.is_file()
    assert path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_making_the_qr_does_not_drag_in_pillow(tmp_path) -> None:
    """The dependency was approved on the strength of being small."""
    import sys

    write_qr("https://brain.local:8443/#tok", tmp_path / "qr.png")

    assert "PIL" not in {name.split(".")[0] for name in sys.modules}


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
