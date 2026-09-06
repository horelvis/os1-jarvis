"""Getting a phone enrolled, without typing a token on a touchscreen.

One QR, and since 2026-09-06 it carries an ENVELOPE rather than a link:
where the box is, the person's token, and the fingerprint of the key
their phone must pin (`sobre`). That is what lets a phone be added
without recompiling the app, which is what the address and the
certificate living inside it used to cost.

**The QR is now a secret.** It was not before — it encoded a LAN URL —
and every comment that said so has been corrected. It holds a token
that authenticates one person to this house, so it is written 0600, it
is shown only while the enrolment window is open, and a photograph of
the strip taken by somebody else in the room IS a credential leak. The
window (`remote.ENROLMENT_SECONDS`) is what bounds that, and it matters
more now than it did when it only bounded a page.

The plain-HTTP welcome page still exists for a phone with no app, but it
is no longer reachable by scanning: its address is typed. It is on its
way out (owner, 2026-09-06).
"""

from __future__ import annotations

import json
import os
import plistlib
import uuid
from pathlib import Path

# The envelope's format version. The app rejects a version it does not
# know, so this number is a promise: change it only when a field
# changes meaning, never when one is added.
VERSION_SOBRE = 1


def sobre(*, url: str, token: str, ca: str) -> str:
    """Everything a phone needs, as the JSON that goes inside the QR.

    Four mandatory fields and no defaults, deliberately: the app
    rejects an incomplete envelope outright rather than falling back to
    the system's own certificate validation, which is the property that
    makes pinning worth anything. So a missing field has to fail HERE,
    where there is a traceback and a journal, and not on a phone whose
    only symptom is a scan that does nothing.

    `wss` is checked for the same reason. A QR offering `ws://` is a
    box that has been misconfigured into plaintext, and the app drops it
    before connecting — so it must never be written.
    """
    if not url or not token or not ca:
        raise ValueError(
            "un sobre incompleto no se escribe: url, token y ca son obligatorios"
        )
    if not url.startswith("wss://"):
        raise ValueError(f"el sobre exige wss, no {url!r}")
    return json.dumps(
        {"v": VERSION_SOBRE, "url": url, "token": token, "ca": ca},
        # Compact and stable: a QR's size is its scannability, and a
        # sorted, space-free payload is also diffable in a log.
        separators=(",", ":"),
    )


def write_qr(payload: str, path: Path) -> Path:
    """A PNG of `payload`, via pypng (`qrcode[png]`'s `PyPNGImage`).

    Written 0600 because this file IS sensitive, which reverses what
    this docstring said until 2026-09-06: the payload used to be a LAN
    URL and is now an envelope carrying one person's token. Anyone who
    can read this PNG can be that person. The mode is the same; only the
    reason changed, and the reason is the part that decides whether
    somebody later "tidies" it.
    """
    import qrcode
    from qrcode.image.pure import PyPNGImage

    path.parent.mkdir(parents=True, exist_ok=True)
    qrcode.make(payload, image_factory=PyPNGImage, box_size=8, border=2).save(str(path))
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
