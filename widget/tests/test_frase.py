import unicodedata

from jarvis_widget.frase import consumir, cargar_o_crear, generar, parecida
from jarvis_widget.palabras import PALABRAS


def test_a_phrase_is_ordinary_words_a_person_can_say():
    frase = generar(4)
    palabras = frase.split()
    assert len(palabras) == 4
    # Words, not a code: Whisper transcribes language, and "X7K-9QM"
    # comes back as "equis siete ka". Being unheard is the one failure
    # a spoken interface cannot afford (CLAUDE.md §12, 2026-08-26).
    assert all(p.isalpha() and p.islower() for p in palabras)


def test_two_phrases_are_not_the_same():
    assert generar() != generar()


def test_it_is_matched_the_way_the_wake_word_is_matched():
    # Whisper produced five spellings of one name in a single morning,
    # so this is a similarity, not a comparison.
    assert parecida("gato ventana lento roble", "gato ventana lento roble")
    assert parecida("Gato, ventana, lento, roble.", "gato ventana lento roble")
    assert parecida("gato bentana lento roble", "gato ventana lento roble")
    assert not parecida("hola qué tal", "gato ventana lento roble")


def test_it_is_made_once_and_reused_until_consumed(tmp_path):
    ruta = tmp_path / "frase.txt"
    primera = cargar_o_crear(ruta)
    assert cargar_o_crear(ruta) == primera
    consumir(ruta)
    assert cargar_o_crear(ruta) != primera


def test_the_file_is_not_world_readable(tmp_path):
    ruta = tmp_path / "frase.txt"
    cargar_o_crear(ruta)
    assert oct(ruta.stat().st_mode)[-3:] == "600"


# The wordlist: pinned by property, not by contents. What matters is not
# which 512+ words are there but that the four rules in palabras.py's own
# docstring hold for all of them.


def _fold_como_parecida(palabra: str) -> str:
    """The same fold `parecida` applies before comparing two phrases —
    reimplemented here rather than imported, so this test exercises the
    actual behaviour rather than trusting the module under test to
    describe itself correctly."""
    decomposed = unicodedata.normalize("NFD", palabra)
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn")


def test_there_are_at_least_512_words():
    # Four words at ≥36 bits needs log2(n) * 4 >= 36, i.e. n >= 512.
    assert len(PALABRAS) >= 512


def test_the_words_are_unique():
    assert len(PALABRAS) == len(set(PALABRAS))


def test_every_word_is_lowercase_ascii_letters_or_ene():
    # Explicit about the alphabet: plain lowercase a-z, plus "ñ" as its
    # own letter. Never an accented vowel or a dieresis — palabras.py's
    # third rule is that no word needs one, so none should carry one.
    for palabra in PALABRAS:
        assert palabra == palabra.lower()
        assert all((c.isascii() and c.isalpha()) or c == "ñ" for c in palabra)


def test_no_word_is_an_accented_form_of_another_once_folded():
    # Two words that collided under `parecida`'s own fold would be
    # genuinely indistinguishable once heard through Whisper and
    # compared — the "papa"/"papá" trap palabras.py's third rule exists
    # to avoid. This is what actually enforces that rule; without this
    # test it is only a comment.
    folded = [_fold_como_parecida(palabra) for palabra in PALABRAS]
    assert len(folded) == len(set(folded))
