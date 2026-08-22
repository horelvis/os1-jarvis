from Hermes.plugins.samantha_voice import announce


def test_missing_clip_returns_nothing_and_never_raises(tmp_path, monkeypatch):
    # This runs on a path where something has already failed. Raising
    # here would replace a useful failure with a useless one.
    monkeypatch.setattr(
        announce, "ANNOUNCEMENT_CLIP_PATH", str(tmp_path / "sin-voz.pcm")
    )
    assert announce.announcement_pcm() == b""


def test_an_unreadable_clip_is_treated_as_absent(tmp_path, monkeypatch):
    # A directory where the file should be — the shape a half-finished
    # recording step leaves behind.
    (tmp_path / "sin-voz.pcm").mkdir()
    monkeypatch.setattr(
        announce, "ANNOUNCEMENT_CLIP_PATH", str(tmp_path / "sin-voz.pcm")
    )
    assert announce.announcement_pcm() == b""


def test_a_recorded_clip_is_returned_verbatim(tmp_path, monkeypatch):
    # Headerless PCM in, the same bytes out: the caller yields them
    # straight into the audio stream, so anything added here would be
    # audible.
    clip = tmp_path / "sin-voz.pcm"
    pcm = b"\x01\x02" * 1000
    clip.write_bytes(pcm)
    monkeypatch.setattr(announce, "ANNOUNCEMENT_CLIP_PATH", str(clip))
    assert announce.announcement_pcm() == pcm


def test_the_configured_path_is_tilde_expanded(tmp_path, monkeypatch):
    # The shipped constant is written with a leading `~`; without
    # expansion it would resolve to a literal "~" directory, the read
    # would always miss, and the announcement would never play.
    assert announce.ANNOUNCEMENT_CLIP_PATH.startswith("~/")
    (tmp_path / "sin-voz.pcm").write_bytes(b"\x03\x04")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(announce, "ANNOUNCEMENT_CLIP_PATH", "~/sin-voz.pcm")
    assert announce.announcement_pcm() == b"\x03\x04"


def test_the_announcement_sounds_like_her():
    # personality.py: tuteo, coloquial, one or two short sentences, no
    # emojis, no "ERROR", no apology for being what she is. It also has
    # to tell the only person who can fix it what is wrong.
    text = announce.ANNOUNCEMENT_TEXT
    assert text == text.strip()
    assert 1 <= text.count(".") <= 3
    assert not any(token in text.upper() for token in ("ERROR", "FALLO", "TTS"))
    assert text.isprintable()
