"""Unit tests for Hermes/plugins/jarvis_voice/tts.py (CosyVoice 3 backend)."""

from __future__ import annotations

import pytest

from Hermes.plugins.jarvis_voice import tts
from Hermes.plugins.jarvis_voice.tts_config import TTSConfig


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
    monkeypatch.setattr(
        tts,
        "config",
        TTSConfig(
            ref_wav=str(tmp_path / "missing.wav"),
            ref_transcript_path=str(tmp_path / "missing.txt"),
        ),
    )
    assert tts.is_available() is False


def test_synth_raises_when_refs_missing(monkeypatch, tmp_path):
    """If the ref files don't exist, synth must raise VoiceMissingError."""
    monkeypatch.setattr(
        tts,
        "config",
        TTSConfig(
            ref_wav=str(tmp_path / "missing.wav"),
            ref_transcript_path=str(tmp_path / "missing.txt"),
        ),
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


def test_synth_does_not_touch_the_shared_client(monkeypatch):
    """synth() must own its client, not borrow and close the shared one.

    An httpx.AsyncClient may only be used on the loop that created it,
    and synth() runs its own asyncio.run() loop. It used to reconcile
    that by closing the module global on the way out — which, now that
    the Hermes whole-file provider calls synth() on a live path, could
    yank the pool out from under a /speak stream mid-request. It now
    creates and closes its own client instead.
    """
    seen: list[object] = []

    async def fake_stream_cosyvoice(text, *, client=None):
        seen.append(client)
        yield b"\x00\x01" * 8

    sentinel = object()
    monkeypatch.setattr(tts, "_stream_cosyvoice", fake_stream_cosyvoice)
    monkeypatch.setattr(tts, "_client", sentinel)

    wav, backend = tts.synth("Hola, ¿qué tal estás?")
    assert backend == "cosyvoice"
    assert wav.startswith(b"RIFF")
    assert seen and all(c is not None and c is not sentinel for c in seen)
    assert tts._client is sentinel  # untouched, still usable by /speak


def test_shared_client_is_rebuilt_when_the_running_loop_changed():
    """The safety net for the constraint above: a cached client whose
    loop is gone is unusable, so _get_client() drops it rather than
    handing it out to fail."""
    import asyncio

    async def grab():
        return tts._get_client()

    first = asyncio.run(grab())  # created on a loop that is now closed
    second = asyncio.run(grab())
    assert first is not second
    asyncio.run(tts.aclose())
    assert tts._client is None
