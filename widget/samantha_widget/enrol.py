"""Getting a phone enrolled, without typing a token on a touchscreen.

One QR, pointing at a welcome page served over PLAIN HTTP — deliberately,
because of a chicken-and-egg: HTTPS cannot be used before the certificate
it depends on is trusted. That page carries nothing sensitive; the link
with the secret in it is behind the second button, over HTTPS.
"""

from __future__ import annotations

import plistlib
import uuid
from pathlib import Path


def write_qr(url: str, path: Path) -> Path:
    """A PNG of `url`. Pillow is never imported — see pyproject.

    That claim does not hold for free. `qrcode`'s own
    `image/styles/moduledrawers/__init__.py` — pulled in by ANY submodule
    of `qrcode.image.*`, `PyPNGImage` included — does `try: from .pil
    import ... except ImportError: pass`. The `[png]` extra only means
    Pillow is not a *declared* dependency; if it happens to already be
    importable — as it is on this box, via the apt package `python3-pil`,
    for reasons that have nothing to do with us — that bare `try`
    succeeds and Pillow loads anyway. Measured 2026-09-01: a plain
    `import qrcode` here pulls in `PIL.Image` and friends whether we
    asked for them or not.
    `sys.modules["PIL"] = None` is the standard way to make an import
    fail without touching what is actually installed (Python treats a
    `None` entry as "already looked for, not there"); it is only in
    place for the one import this function needs, and it is undone
    before returning either way.
    """
    import sys

    blocked = "PIL" not in sys.modules
    if blocked:
        sys.modules["PIL"] = None  # type: ignore[assignment]
    try:
        import qrcode
        from qrcode.image.pure import PyPNGImage
    finally:
        if blocked:
            del sys.modules["PIL"]

    path.parent.mkdir(parents=True, exist_ok=True)
    qrcode.make(url, image_factory=PyPNGImage, box_size=8, border=2).save(str(path))
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
