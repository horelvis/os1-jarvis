from Hermes.plugins.samantha_voice import provider as prov


class _FakeTTS:
    OUTPUT_SAMPLE_RATE = 24000

    def __init__(self, available=True, chunks=(b"\x00\x01" * 100,)):
        self._available = available
        self._chunks = chunks
        self.calls: list[str] = []

    def is_available(self):
        return self._available

    async def stream(self, text):
        self.calls.append(text)
        for c in self._chunks:
            yield c, "cosyvoice"


def test_declares_the_format_cosyvoice_actually_emits():
    p = prov.CosyVoiceStreamingProvider({}, {})
    assert p.sample_rate == 24000
    assert p.channels == 1
    assert p.sample_width == 2


def test_init_stores_config_and_section_per_contract_1():
    # Hermes constructs every StreamingTTSProvider with (tts_config,
    # section) and expects them retained — see
    # docs/superpowers/specs/hermes-contracts-v0.20.5.md, Contract 1.
    tts_config = {"provider": "cosyvoice"}
    section = {"enabled": True}
    p = prov.CosyVoiceStreamingProvider(tts_config, section)
    assert p.tts_config is tts_config
    assert p.section is section


def test_available_follows_the_tts_module(monkeypatch):
    monkeypatch.setattr(prov, "tts", _FakeTTS(available=False))
    assert prov.CosyVoiceStreamingProvider.available() is False
    monkeypatch.setattr(prov, "tts", _FakeTTS(available=True))
    assert prov.CosyVoiceStreamingProvider.available() is True


def test_stream_yields_pcm_bytes_not_tuples(monkeypatch):
    fake = _FakeTTS(chunks=(b"aa", b"bb"))
    monkeypatch.setattr(prov, "tts", fake)
    out = list(
        prov.CosyVoiceStreamingProvider({}, {}).stream("Hola, ¿qué tal estás hoy?")
    )
    assert out == [b"aa", b"bb"]


def test_short_text_is_not_sent_raw(monkeypatch):
    # A single tiny clause must still reach CosyVoice as one call, not
    # be split further. The guard's job is merging, never splitting.
    fake = _FakeTTS()
    monkeypatch.setattr(prov, "tts", fake)
    list(prov.CosyVoiceStreamingProvider({}, {}).stream("Sí."))
    assert fake.calls == ["Sí."]


def test_empty_text_makes_no_call(monkeypatch):
    fake = _FakeTTS()
    monkeypatch.setattr(prov, "tts", fake)
    assert list(prov.CosyVoiceStreamingProvider({}, {}).stream("   ")) == []
    assert fake.calls == []


def test_records_bytes_yielded_per_clause(monkeypatch):
    # Plan 3 needs this to trim an interrupted reply to what was heard.
    monkeypatch.setattr(prov, "tts", _FakeTTS(chunks=(b"a" * 10,)))
    p = prov.CosyVoiceStreamingProvider({}, {})
    list(p.stream("Una frase lo bastante larga como para pasar el guardia."))
    assert p.bytes_yielded_per_clause == [
        ("Una frase lo bastante larga como para pasar el guardia.", 10)
    ]


def test_records_zero_bytes_for_a_clause_that_raises(monkeypatch):
    # The accounting must include a clause that failed and yielded no
    # audio — Plan 3's trim rule needs every attempted clause present,
    # not just the successful ones.
    class _RaisingTTS(_FakeTTS):
        async def stream(self, text):
            self.calls.append(text)
            raise RuntimeError("CosyVoice returned 200 with no audio")
            yield b""  # pragma: no cover - unreachable, keeps this an async gen

    monkeypatch.setattr(prov, "tts", _RaisingTTS())
    p = prov.CosyVoiceStreamingProvider({}, {})
    clause = "Una frase lo bastante larga como para pasar el guardia."
    out = list(p.stream(clause))
    assert out == []
    assert p.bytes_yielded_per_clause == [(clause, 0)]
