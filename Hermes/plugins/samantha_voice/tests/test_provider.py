import httpx

from Hermes.plugins.samantha_voice import provider as prov
from Hermes.plugins.samantha_voice.markers import has_unclosed_tag


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
    text = "Hola, ¿qué tal estás hoy? Cuéntame cómo te ha ido todo."
    assert len(text) >= prov.MIN_CLAUSE_CHARS  # one call must be enough to speak
    out = list(prov.CosyVoiceStreamingProvider({}, {}).stream(text))
    assert out == [b"aa", b"bb"]


def test_two_short_clauses_merge_into_one_synthesis_call(monkeypatch):
    # Hermes calls stream() once per already-atomic clause and never
    # with a batch, so merging short clauses up to MIN_CLAUSE_CHARS has
    # to happen across calls, via self._pending — not within a single
    # call. Neither clause alone is long enough to be safe to synthesise;
    # merged, they are.
    fake = _FakeTTS(chunks=(b"xy",))
    monkeypatch.setattr(prov, "tts", fake)
    p = prov.CosyVoiceStreamingProvider({}, {})

    first = "Sí,"
    second = "eso es justo lo que pensaba decirte."
    assert len(first) < prov.MIN_CLAUSE_CHARS
    assert len(second) < prov.MIN_CLAUSE_CHARS
    assert len(first) + 1 + len(second) >= prov.MIN_CLAUSE_CHARS

    assert list(p.stream(first)) == []
    assert fake.calls == []  # still buffering, nothing sent yet

    out = list(p.stream(second))
    merged = f"{first} {second}"
    assert out == [b"xy"]
    assert fake.calls == [merged]
    assert p.bytes_yielded_per_clause == [(merged, 2)]


def test_short_clause_followed_by_long_one_merges_and_synthesizes(monkeypatch):
    fake = _FakeTTS(chunks=(b"z",))
    monkeypatch.setattr(prov, "tts", fake)
    p = prov.CosyVoiceStreamingProvider({}, {})

    first = "Vale."
    second = "Cuéntame qué tal ha ido tu día, con todo detalle."
    assert len(first) < prov.MIN_CLAUSE_CHARS
    assert len(second) >= prov.MIN_CLAUSE_CHARS  # already safe alone

    assert list(p.stream(first)) == []
    out = list(p.stream(second))
    merged = f"{first} {second}"
    assert out == [b"z"]
    assert fake.calls == [merged]


def test_open_tag_holds_even_when_long_enough_alone(monkeypatch):
    # A clause can already clear MIN_CLAUSE_CHARS and still need holding:
    # sending it as-is would hand CosyVoice an opening <laughter> with no
    # matching close, which fails the same way a too-short clause does.
    fake = _FakeTTS()
    monkeypatch.setattr(prov, "tts", fake)
    p = prov.CosyVoiceStreamingProvider({}, {})

    first = "Eso me hace mucha gracia, la verdad, <laughter>de verdad que sí"
    assert len(first) >= prov.MIN_CLAUSE_CHARS
    assert list(p.stream(first)) == []
    assert fake.calls == []
    assert p._pending == first


def test_clause_that_closes_a_tag_merges_into_one_synthesis_call(monkeypatch):
    fake = _FakeTTS(chunks=(b"q",))
    monkeypatch.setattr(prov, "tts", fake)
    p = prov.CosyVoiceStreamingProvider({}, {})

    first = "Eso me hace mucha gracia, la verdad, <laughter>de verdad que sí"
    second = "me lo pareció</laughter>."

    assert list(p.stream(first)) == []
    out = list(p.stream(second))
    merged = f"{first} {second}"
    assert out == [b"q"]
    assert fake.calls == [merged]
    assert p.bytes_yielded_per_clause == [(merged, 1)]


def test_unclosed_tag_releases_once_pending_hits_the_cap(monkeypatch):
    # If the model never closes a <laughter> tag, has_unclosed_tag stays
    # true forever — without a cap, every further clause would merge
    # into _pending and the rest of the turn would go unspoken. Once
    # _pending reaches MAX_PENDING_CHARS it must release regardless of
    # tag balance, so the clauses that follow still get synthesised.
    fake = _FakeTTS(chunks=(b"r",))
    monkeypatch.setattr(prov, "tts", fake)
    p = prov.CosyVoiceStreamingProvider({}, {})

    opener = "<laughter>" + " ".join(["muy"] * 20)  # unclosed, already long
    assert has_unclosed_tag(opener)
    assert len(opener) < prov.MAX_PENDING_CHARS
    assert list(p.stream(opener)) == []
    assert fake.calls == []  # still held: unclosed tag, under the cap

    filler = " ".join(["gracioso"] * 35)  # no closing tag; pushes past the cap
    merged = f"{opener} {filler}"
    assert has_unclosed_tag(merged)
    assert len(merged) >= prov.MAX_PENDING_CHARS
    out = list(p.stream(filler))
    # Without the fix, this clause would stay pending forever and the
    # rest of the reply would never reach CosyVoice.
    assert out == [b"r"]
    assert fake.calls == [merged]
    assert p.bytes_yielded_per_clause == [(merged, 1)]
    assert p._pending == ""

    # The turn keeps speaking after the release.
    next_clause = "Y ahora seguimos hablando con toda normalidad, ¿verdad?"
    assert len(next_clause) >= prov.MIN_CLAUSE_CHARS
    out2 = list(p.stream(next_clause))
    assert out2 == [b"r"]
    assert fake.calls == [merged, next_clause]


def test_short_clause_left_pending_at_end_is_absent_from_accounting(monkeypatch):
    # No end-of-reply signal reaches this provider (see stream()'s
    # docstring), so a final short clause is never spoken and must not
    # be recorded as if it had been attempted.
    fake = _FakeTTS()
    monkeypatch.setattr(prov, "tts", fake)
    p = prov.CosyVoiceStreamingProvider({}, {})

    tail = "Sí."
    assert len(tail) < prov.MIN_CLAUSE_CHARS
    assert list(p.stream(tail)) == []
    assert fake.calls == []
    assert p.bytes_yielded_per_clause == []
    assert p._pending == tail


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


def test_transport_error_is_treated_like_a_failed_clause(monkeypatch):
    # httpx transport failures (timeout, connection refused, protocol
    # error) are httpx.HTTPError, not RuntimeError — catching only
    # RuntimeError would let one of these abort the whole reply instead
    # of just the clause that hit it.
    class _TimingOutTTS(_FakeTTS):
        async def stream(self, text):
            self.calls.append(text)
            raise httpx.ReadTimeout("cosyvoice took too long")
            yield b""  # pragma: no cover - unreachable, keeps this an async gen

    monkeypatch.setattr(prov, "tts", _TimingOutTTS())
    p = prov.CosyVoiceStreamingProvider({}, {})
    clause = "Una frase lo bastante larga como para pasar el guardia."
    out = list(p.stream(clause))
    assert out == []
    assert p.bytes_yielded_per_clause == [(clause, 0)]
