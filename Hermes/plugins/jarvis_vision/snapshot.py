"""A decoded frame becomes a file on disk, and old ones go away.

This directory holds pictures of the inside and the outside of the house.
An unbounded one is a privacy leak as much as a disk leak, which is why
pruning happens on every write rather than on a timer somebody can forget
to start.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import numpy as np
from loguru import logger

# Hermes already designates `cache/images` for generated media; a
# subdirectory of our own keeps pruning unambiguous and keeps this out of
# the way of anything else that writes there.
_ROOT = (
    Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
    / "cache"
    / "images"
    / "vision"
)

# Camera names come from a config file written by hand. Anything that is
# not a plain name is flattened rather than rejected: a bad name should
# cost a strange filename, never a write outside this directory.
_UNSAFE = re.compile(r"[^A-Za-z0-9_-]+")


def snapshot_dir() -> Path:
    """The one directory snapshots live in. Created on first use, 0700."""
    _ROOT.mkdir(parents=True, exist_ok=True)
    _ROOT.chmod(0o700)
    return _ROOT


def write_jpeg(frame: np.ndarray, camera: str, *, now: float) -> Path:
    """Write one RGB frame as a JPEG and return its path.

    Pillow, not PyAV: PyAV's image2 muxer ignores an in-memory target and
    writes a file named `<none>` into the working directory. Measured
    2026-08-24.

    The import is deferred to here, and that is not style. Since Task 5
    this module is on the plugin's LOAD path — `tool.py` imports it, and
    `__init__.py` imports that — so a module-level `from PIL import
    Image` would make a box without Pillow fail to load the plugin at
    all, costing the house the alerts and the watching as well as the
    snapshots. Deferred, a missing Pillow costs exactly the picture, and
    the caller (`tool.py`) already answers in words without one.
    """
    from PIL import Image

    directory = snapshot_dir()
    safe = _UNSAFE.sub("-", camera).strip("-") or "camara"
    path = directory / f"{safe}-{int(now)}.jpg"
    Image.fromarray(frame).save(path, "JPEG", quality=85)
    path.chmod(0o600)
    # Stamp the file's mtime to the logical `now` rather than leave it at
    # the wall-clock time of the write: prune() ages files off that mtime,
    # and the two must agree for a frame taken at a caller-supplied moment
    # (tests inject one far from the real clock; a real capture and the
    # write happen close enough together not to matter).
    os.utime(path, (now, now))
    prune(now=now)
    return path


def prune(*, keep: int = 20, max_age_s: float = 3600.0, now: float) -> int:
    """Delete old snapshots. Returns how many went. Never raises.

    Sorted by (mtime, name) descending, not mtime alone: several writes in
    the same second (or the same instant, on a fast filesystem) tie on
    mtime, and the filename — which carries the same timestamp — is the
    stable tiebreak that makes "keeps the newest" actually true.

    Listing (`glob`) failing is fatal to the whole pass — there is nothing
    to prune against. One file's `stat()` failing during that listing is
    NOT: a race with another writer, a permissions glitch, a dangling
    symlink must cost that one file, not silently disable pruning for
    every other file on every subsequent write.
    """
    try:
        candidates = list(snapshot_dir().glob("*.jpg"))
    except OSError as exc:
        logger.warning(f"jarvis-vision: cannot list snapshots: {exc}")
        return 0

    entries: list[tuple[float, str, Path]] = []
    for path in candidates:
        try:
            entries.append((path.stat().st_mtime, path.name, path))
        except OSError as exc:
            logger.warning(f"jarvis-vision: cannot stat {path.name}: {exc}")
    entries.sort(reverse=True)

    deleted = 0
    for index, (mtime, _name, path) in enumerate(entries):
        try:
            too_many = index >= keep
            too_old = (now - mtime) > max_age_s
            if too_many or too_old:
                path.unlink()
                deleted += 1
        except OSError as exc:
            logger.warning(f"jarvis-vision: cannot prune {path.name}: {exc}")
    return deleted
