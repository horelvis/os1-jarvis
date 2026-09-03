"""Getting a phone enrolled, without typing a token on a touchscreen.

One QR, pointing at a welcome page served over PLAIN HTTP — deliberately,
because of a chicken-and-egg: HTTPS cannot be used before the certificate
it depends on is trusted. The QR itself is harmless — it encodes only a
LAN URL. The page behind it is not: it embeds the shared secret,
in cleartext, in its second link's href. That is exactly why serving
the page at all is bounded to a short window rather than the life of
the process — see `remote.Enrolment` and `remote.ENROLMENT_SECONDS`.
"""

from __future__ import annotations

import os
import plistlib
import uuid
from pathlib import Path


def write_qr(url: str, path: Path) -> Path:
    """A PNG of `url`, via pypng (`qrcode[png]`'s `PyPNGImage`).

    Written 0600 for consistency with `certs.py` and `remote_auth.py` —
    not because this file holds anything sensitive (it does not: `url`
    is a LAN address, never the secret), but a QR that is world-readable
    while its neighbours are locked down invites the wrong guess about
    which of the two matters.
    """
    import qrcode
    from qrcode.image.pure import PyPNGImage

    path.parent.mkdir(parents=True, exist_ok=True)
    qrcode.make(url, image_factory=PyPNGImage, box_size=8, border=2).save(str(path))
    os.chmod(path, 0o600)
    return path


def mobileconfig(ca_pem: Path) -> bytes:
    """An iOS profile that installs the house CA as a trusted root.

    Installing it is only half: iOS then needs the switch under
    Settings → General → About → Certificate Trust Settings, which no
    profile can set for you. `widget/README.md` carries the steps.
    """
    return plistlib.dumps(
        {
            "PayloadType": "Configuration",
            "PayloadVersion": 1,
            "PayloadIdentifier": "casa.jarvis.ca",
            "PayloadUUID": str(uuid.uuid4()),
            "PayloadDisplayName": "JARVIS — certificado de casa",
            "PayloadDescription": (
                "Permite que este iPhone confíe en JARVIS dentro de casa."
            ),
            "PayloadContent": [
                {
                    "PayloadType": "com.apple.security.root",
                    "PayloadVersion": 1,
                    "PayloadIdentifier": "casa.jarvis.ca.root",
                    "PayloadUUID": str(uuid.uuid4()),
                    "PayloadDisplayName": "JARVIS Home CA",
                    "PayloadCertificateFileName": "ca.pem",
                    "PayloadContent": ca_pem.read_bytes(),
                }
            ],
        }
    )
