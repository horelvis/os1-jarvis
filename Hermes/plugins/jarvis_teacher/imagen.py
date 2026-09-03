"""Image references, resolved to local files before anything is drawn.

Its own spool, deliberately not the cameras'. `push_ficha` validates
against this directory and `push_photo` against theirs, so a picture of
the inside of the house and a diagram of the solar system can never be
confused for one another by a path check.
"""

from __future__ import annotations

import hashlib
import io
import os
import re
from collections.abc import Callable
from pathlib import Path

from loguru import logger

from .markdown import imagenes, sustituir_imagen

# Bigger than this and it is not a lesson illustration.
MAX_BYTES = 4 * 1024 * 1024


def spool_dir() -> Path:
    """The one directory lesson images live in. Created on use, 0700."""
    raiz = Path(
        os.environ.get("JARVIS_TEACHER_HOME", Path.home() / ".samantha" / "teacher")
    )
    destino = raiz / "img"
    destino.mkdir(parents=True, exist_ok=True)
    destino.chmod(0o700)
    return destino


def _es_imagen(datos: bytes) -> bool:
    """Decode it rather than believe a Content-Type header."""
    try:
        from PIL import Image

        Image.open(io.BytesIO(datos)).verify()
        return True
    except Exception:  # noqa: BLE001
        return False


def resolver(md: str, *, traer: Callable[[str], bytes], now: float) -> str:
    """Point every reference at a local file, dropping what will not resolve.

    A reference that cannot be fetched, is too large, or does not decode
    as an image is removed from the document and the card is drawn
    anyway — Ruling 7 from the cameras' `tool.py`: the picture is a
    luxury, the question is not.
    """
    salida = md
    for referencia in imagenes(md):
        if referencia.startswith(str(spool_dir())):
            continue
        try:
            datos = traer(referencia)
        except Exception as exc:  # noqa: BLE001 — catch ordinary errors, not cancellations
            logger.warning(f"jarvis-teacher: no se pudo traer una imagen: {exc}")
            salida = _quitar(salida, referencia)
            continue
        if not datos or len(datos) > MAX_BYTES or not _es_imagen(datos):
            salida = _quitar(salida, referencia)
            continue
        nombre = hashlib.sha256(datos).hexdigest()[:16] + ".img"
        destino = spool_dir() / nombre
        try:
            destino.write_bytes(datos)
            destino.chmod(0o600)
        except OSError as exc:
            logger.warning(f"jarvis-teacher: no se pudo guardar una imagen: {exc}")
            salida = _quitar(salida, referencia)
            continue
        salida = sustituir_imagen(salida, referencia, str(destino))
    return salida


def _quitar(md: str, referencia: str) -> str:
    """Drop one image reference, leaving the rest of the document alone.

    An inline reference is cut out mid-sentence. A reference alone on
    its line takes the whole line with it, so no blank line is left.
    References in code fences are not handed here (imagenes() filters them).
    """
    # Pattern to match the image syntax with this specific reference.
    patron = rf"!\[[^\]]*\]\({re.escape(referencia)}\)"

    lineas = md.splitlines(keepends=True)
    result = []
    i = 0
    while i < len(lineas):
        linea = lineas[i]
        if referencia not in linea:
            result.append(linea)
            i += 1
            continue

        # Check if this line is JUST the image reference (own-line).
        desnuda = linea.strip()
        if re.match(rf"^!\[[^\]]*\]\({re.escape(referencia)}\)$", desnuda):
            # Own-line reference; skip the entire line.
            # Also skip the following blank line if there is one.
            i += 1
            if i < len(lineas) and lineas[i].strip() == "":
                i += 1
            continue

        # Inline reference; remove just the image syntax.
        modified = re.sub(patron, "", linea)
        # Clean up double spaces left behind.
        modified = re.sub(r" {2,}", " ", modified)
        result.append(modified)
        i += 1

    return "".join(result)
