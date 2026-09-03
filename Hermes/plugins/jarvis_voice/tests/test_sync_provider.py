import pytest

import Hermes.plugins.jarvis_voice as pkg
from Hermes.plugins.jarvis_voice import sync_provider as sync


class _FakeTTS:
    def __init__(self, available=True, wav=b"RIFF....WAVEfmt ", backend="cosyvoice"):
        self._available = available
        self._wav = wav
        self._backend = backend
        self.calls: list[str] = []

    def is_available(self):
        return self._available

    def synth(self, text):
        self.calls.append(text)
        return self._wav, self._backend


def test_name_matches_the_streaming_registration():
    # Both registries must answer to the same name, or one Hermes path
    # speaks in Samantha's voice and the other in Edge TTS's.
    from Hermes.plugins.jarvis_voice import provider as prov

    assert sync.CosyVoiceSyncProvider().name == "cosyvoice"
    assert prov.CosyVoiceStreamingProvider.__name__  # imported, registered on import


def test_is_available_follows_the_tts_module(monkeypatch):
    monkeypatch.setattr(sync, "tts", _FakeTTS(available=False))
    assert sync.CosyVoiceSyncProvider().is_available() is False
    monkeypatch.setattr(sync, "tts", _FakeTTS(available=True))
    assert sync.CosyVoiceSyncProvider().is_available() is True


def test_is_available_never_raises(monkeypatch):
    class _Exploding:
        def is_available(self):
            raise OSError("disk gone")

    monkeypatch.setattr(sync, "tts", _Exploding())
    assert sync.CosyVoiceSyncProvider().is_available() is False


def test_synthesize_writes_the_wav_bytes_and_returns_the_path(monkeypatch, tmp_path):
    fake = _FakeTTS(wav=b"RIFFDATA")
    monkeypatch.setattr(sync, "tts", fake)
    out = tmp_path / "reply.wav"
    written = sync.CosyVoiceSyncProvider().synthesize("Hola, ¿qué tal?", str(out))
    assert written == str(out)
    assert out.read_bytes() == b"RIFFDATA"
    assert fake.calls == ["Hola, ¿qué tal?"]


def test_requested_mp3_gets_a_wav_extension_not_a_mislabelled_file(
    monkeypatch, tmp_path
):
    # The dispatcher asks for mp3 by default; CosyVoice only emits WAV.
    # The ABC says to write the closest format and fix the extension.
    monkeypatch.setattr(sync, "tts", _FakeTTS(wav=b"RIFFDATA"))
    out = tmp_path / "reply.mp3"
    written = sync.CosyVoiceSyncProvider().synthesize("Hola.", str(out), format="mp3")
    assert written == str(tmp_path / "reply.wav")
    assert not out.exists()


def test_no_audio_raises_instead_of_writing_an_empty_file(monkeypatch, tmp_path):
    # Raising keeps us safe: the dispatcher turns it into an error
    # envelope and never falls through to Edge TTS.
    monkeypatch.setattr(sync, "tts", _FakeTTS(wav=b"", backend="empty"))
    out = tmp_path / "reply.wav"
    with pytest.raises(RuntimeError, match="no audio"):
        sync.CosyVoiceSyncProvider().synthesize("Hola.", str(out))
    assert not out.exists()


def test_register_puts_a_cosyvoice_provider_in_hermes_whole_file_registry():
    # The whole-file path looks providers up in agent.tts_registry, which
    # only ctx.register_tts_provider populates. Registering nothing there
    # is what routed Samantha's words through Microsoft's cloud.
    class _FakeCtx:
        def __init__(self):
            self.registered = []

        def register_tts_provider(self, provider):
            self.registered.append(provider)

    ctx = _FakeCtx()
    pkg.register(ctx)
    assert [p.name for p in ctx.registered] == ["cosyvoice"]
