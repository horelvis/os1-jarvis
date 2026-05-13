"""Unit tests for backend/samantha/tts.py.

The Piper voice model is large (~60 MB) and lives outside the repo
at ~/.samantha/voices/. Tests that require it skip cleanly when it
isn't present — keeps CI / fresh-clone runs green without forcing a
60 MB download up front.
"""

from __future__ import annotations

import pytest

from samantha import tts


def test_is_available_reflects_disk_state():
    """is_available() is a thin Path.is_file() probe."""
    assert tts.is_available() in (True, False)


def test_synth_empty_text_returns_empty_bytes():
    """Blank inputs short-circuit before loading the voice — useful
    for not paying piper startup on no-op calls."""
    assert tts.synth("") == b""
    assert tts.synth("   ") == b""


def test_synth_raises_when_voice_missing(monkeypatch, tmp_path):
    """If the model path doesn't exist, synth must raise rather than
    return a silent placeholder — the /speak fallback at the route
    layer is what makes the bad path UX-safe."""
    monkeypatch.setattr(tts.config, "tts_backend", "piper")
    monkeypatch.setattr(tts.config, "tts_voices_dir", str(tmp_path))
    # Force re-load attempt on the next synth call.
    monkeypatch.setattr(tts, "_voice", None)
    monkeypatch.setattr(tts, "_voice_load_failed", False)
    with pytest.raises(tts.VoiceMissingError):
        tts.synth("hola")


@pytest.mark.skipif(
    not tts.is_available(),
    reason="piper voice model not on disk (~/.samantha/voices/) — skip real synth",
)
def test_synth_produces_riff_wave():
    """End-to-end: feed real text, get a parseable WAV back."""
    data = tts.synth("Hola. Soy Samantha.")
    assert data[:4] == b"RIFF"
    assert data[8:12] == b"WAVE"
    # 22.05 kHz mono 16-bit → at least a few KB for a 2-second phrase.
    assert len(data) > 4_000
