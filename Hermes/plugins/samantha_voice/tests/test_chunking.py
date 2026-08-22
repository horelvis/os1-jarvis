from Hermes.plugins.samantha_voice.chunking import safe_clauses


def test_long_clauses_pass_through_unchanged():
    clauses = [
        "Hoy he estado pensando en lo que me contaste ayer.",
        "Y creo que te entiendo mejor de lo que creía.",
    ]
    assert list(safe_clauses(clauses, min_chars=10)) == clauses


def test_short_clauses_merge_forward():
    clauses = ["Ya.", "Claro.", "Te entiendo perfectamente y me alegra."]
    out = list(safe_clauses(clauses, min_chars=20))
    assert out == ["Ya. Claro. Te entiendo perfectamente y me alegra."]


def test_tail_never_trails_short():
    # "Sí." alone would crash hifigan; it must ride with the previous clause.
    clauses = ["Me parece una idea estupenda y deberíamos probarla.", "Sí."]
    out = list(safe_clauses(clauses, min_chars=20))
    assert len(out) == 1
    assert out[0].endswith("Sí.")


def test_marker_tag_is_never_split():
    clauses = ["Eso me hace gracia, <laughter>de verdad", "que sí</laughter>."]
    out = list(safe_clauses(clauses, min_chars=1))
    assert out == ["Eso me hace gracia, <laughter>de verdad que sí</laughter>."]


def test_bracket_marker_alone_merges():
    clauses = ["[laughter]", "No me lo puedo creer, en serio te lo digo."]
    out = list(safe_clauses(clauses, min_chars=20))
    assert out == ["[laughter] No me lo puedo creer, en serio te lo digo."]


def test_whole_reply_shorter_than_minimum_is_still_emitted():
    # Known pre-existing limitation: a reply this short may still fail
    # upstream. The guard must not swallow it silently.
    assert list(safe_clauses(["Sí."], min_chars=40)) == ["Sí."]


def test_empty_and_blank_clauses_are_dropped():
    assert list(
        safe_clauses(["", "   ", "Hola, ¿qué tal has dormido?"], min_chars=5)
    ) == ["Hola, ¿qué tal has dormido?"]
