import os
from pathlib import Path

import numpy as np
from PIL import Image

from Hermes.plugins.samantha_vision import snapshot


def _frame() -> np.ndarray:
    # HxWx3 RGB, the shape CameraStream.frames() yields.
    return (np.random.default_rng(0).random((360, 640, 3)) * 255).astype("uint8")


def test_it_writes_a_real_jpeg(tmp_path, monkeypatch):
    monkeypatch.setattr(snapshot, "_ROOT", tmp_path)
    path = snapshot.write_jpeg(_frame(), "entrada", now=1000.0)
    assert path.exists()
    with Image.open(path) as im:
        assert im.format == "JPEG"
        assert im.size == (640, 360)


def test_the_name_carries_the_camera_and_the_moment(tmp_path, monkeypatch):
    monkeypatch.setattr(snapshot, "_ROOT", tmp_path)
    path = snapshot.write_jpeg(_frame(), "entrada", now=1000.0)
    assert "entrada" in path.name
    assert "1000" in path.name


def test_a_camera_name_cannot_escape_the_directory(tmp_path, monkeypatch):
    # The name comes from config, and config is written by hand.
    monkeypatch.setattr(snapshot, "_ROOT", tmp_path)
    path = snapshot.write_jpeg(_frame(), "../../etc/passwd", now=1000.0)
    assert path.parent == tmp_path


def test_the_directory_is_private(tmp_path, monkeypatch):
    # It holds pictures of the inside of the house.
    monkeypatch.setattr(snapshot, "_ROOT", tmp_path / "vision")
    snapshot.write_jpeg(_frame(), "entrada", now=1000.0)
    assert (snapshot._ROOT.stat().st_mode & 0o777) == 0o700


def test_prune_keeps_the_newest_and_drops_the_rest(tmp_path, monkeypatch):
    monkeypatch.setattr(snapshot, "_ROOT", tmp_path)
    for i in range(5):
        snapshot.write_jpeg(_frame(), "entrada", now=1000.0 + i)
    deleted = snapshot.prune(keep=2, max_age_s=1e9, now=2000.0)
    assert deleted == 3
    assert len(list(tmp_path.glob("*.jpg"))) == 2


def test_prune_drops_anything_older_than_the_window(tmp_path, monkeypatch):
    monkeypatch.setattr(snapshot, "_ROOT", tmp_path)
    snapshot.write_jpeg(_frame(), "entrada", now=1000.0)
    deleted = snapshot.prune(keep=50, max_age_s=10.0, now=5000.0)
    assert deleted == 1
    assert list(tmp_path.glob("*.jpg")) == []


def test_prune_skips_a_file_whose_stat_fails_but_prunes_the_rest(tmp_path, monkeypatch):
    # Reproduces a reviewer-found regression: one file's stat() raising
    # during the initial listing must not abort the whole pass and leave
    # every other file un-pruned.
    monkeypatch.setattr(snapshot, "_ROOT", tmp_path)
    good = snapshot.write_jpeg(_frame(), "entrada", now=1000.0)
    bad = snapshot.write_jpeg(_frame(), "salida", now=1001.0)

    real_stat = Path.stat

    def flaky_stat(self, *args, **kwargs):
        if self == bad:
            raise FileNotFoundError("vanished")
        return real_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", flaky_stat)

    deleted = snapshot.prune(keep=0, max_age_s=1e9, now=2000.0)

    assert deleted == 1
    # os.path.exists, not Path.exists: the monkeypatch above is still in
    # effect and Path.exists() calls Path.stat() internally.
    assert not os.path.exists(good)
    assert os.path.exists(bad)
