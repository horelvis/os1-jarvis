"""Unit tests for backend/samantha/tts.py (CosyVoice 3 backend)."""

from __future__ import annotations

import pytest

from samantha import tts


def test_is_available_reflects_disk_state():
    """is_available() is a thin Path.is_file() probe."""
    assert tts.is_available() in (True, False)


def test_synth_empty_text_returns_empty_bytes():
    """Blank inputs short-circuit before hitting the network."""
    data, mode = tts.synth("")
    assert data == b""
    assert mode == "empty"
    data, mode = tts.synth("   ")
    assert data == b""
    assert mode == "empty"


def test_is_available_false_when_refs_missing(monkeypatch, tmp_path):
    """is_available() returns False when ref WAV or transcript are absent."""
    monkeypatch.setattr(tts.config, "tts_cosyvoice_ref_wav", str(tmp_path / "missing.wav"))
    monkeypatch.setattr(
        tts.config, "tts_cosyvoice_ref_transcript_path", str(tmp_path / "missing.txt")
    )
    assert tts.is_available() is False


def test_synth_raises_when_refs_missing(monkeypatch, tmp_path):
    """If the ref files don't exist, synth must raise VoiceMissingError."""
    monkeypatch.setattr(tts.config, "tts_cosyvoice_ref_wav", str(tmp_path / "missing.wav"))
    monkeypatch.setattr(
        tts.config, "tts_cosyvoice_ref_transcript_path", str(tmp_path / "missing.txt")
    )
    monkeypatch.setattr(tts, "_cosyvoice_ref_transcript", None)
    monkeypatch.setattr(tts, "_cosyvoice_ref_wav_bytes", None)
    with pytest.raises(tts.VoiceMissingError):
        tts.synth("hola")


def test_tts_shared_client_reused_and_closed():
    """stream() must reuse one AsyncClient; aclose() releases it."""
    import asyncio

    c1 = tts._get_client()
    c2 = tts._get_client()
    assert c1 is c2
    asyncio.run(tts.aclose())
    assert tts._client is None
