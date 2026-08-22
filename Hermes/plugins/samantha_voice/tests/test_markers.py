from Hermes.plugins.samantha_voice.markers import has_unclosed_tag


def test_plain_text_has_no_tag():
    assert has_unclosed_tag("Hola, ¿qué tal estás hoy?") is False


def test_open_without_close_is_unclosed():
    assert has_unclosed_tag("Eso me hace gracia, <laughter>de verdad") is True


def test_matched_pair_is_closed():
    assert (
        has_unclosed_tag("Eso me hace gracia, <laughter>de verdad</laughter>.") is False
    )


def test_bracket_marker_is_not_the_tag_pair():
    # [laughter] is a different marker (a sound cue) — it doesn't use the
    # <laughter>...</laughter> pair this check looks for.
    assert has_unclosed_tag("[laughter] No me lo puedo creer.") is False


def test_two_opens_one_close_is_still_unclosed():
    assert has_unclosed_tag("<laughter>a</laughter><laughter>b") is True
