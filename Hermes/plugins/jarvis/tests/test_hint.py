"""The platform hint has to describe the surface that actually exists.

This file exists because of one measured failure. On 2026-08-24, with
the `mirar` tool already pushing photos down the socket, the strip could
not draw them yet — and the hint said so. Asked to show the entrance he
answered "sigo sin poder enseñarle nada en una pantalla, señor — aquí
solo hay voz", and in another turn offered Hermes Desktop instead. He
was right, and the fix was not to argue with the model: it was to make
the strip able to draw and to change the hint in the same commit. These
tests are what keeps the two from drifting apart again.
"""

from Hermes.plugins.jarvis import (
    _FALLBACK_HINT,
    _PERSONA_FILE,
    _TEACHING,
    _platform_hint,
)


def test_the_hint_says_a_camera_photo_can_be_shown():
    hint = _platform_hint()
    lowered = hint.lower()
    assert "foto" in lowered
    assert "cámara" in lowered
    assert "tira" in lowered


def test_the_hint_does_not_promise_a_general_display():
    # Narrow on purpose. A still from a camera, and nothing else — the
    # band draws a texture and has no way to render text or a file.
    hint = _platform_hint()
    assert "texto" in hint and "ficheros" in hint
    assert "markdown" in hint  # the no-screen-to-read rule survives


def test_the_hint_still_says_he_cannot_see_the_photo_himself():
    # He knows what the detector told him. He is not looking at the
    # picture, and a turn that pretends otherwise invents detail.
    assert "no la ves" in _platform_hint()


def test_the_hint_carries_the_persona():
    persona = _PERSONA_FILE.read_text(encoding="utf-8").strip()
    assert persona and persona in _platform_hint()


def test_a_missing_persona_file_still_yields_a_hint(monkeypatch):
    # The fallback path does not carry the screen sentence, and that is
    # the safe direction: it under-claims rather than over-claims.
    from Hermes.plugins import jarvis

    monkeypatch.setattr(jarvis, "_PERSONA_FILE", _PERSONA_FILE / "nope")
    assert jarvis._platform_hint() == _FALLBACK_HINT


def test_the_hint_says_he_can_show_something_that_moves():
    hint = _platform_hint().lower()
    assert "movimiento" in hint or "directo" in hint


def test_the_hint_says_how_to_delegate_coding():
    # Model-facing text, so naming the tool and the agent is correct
    # here even though the persona never says either out loud. Assert
    # on what is load-bearing — the agent named and the rule against
    # answering in its place — not the paragraph verbatim, so a
    # rewording does not break this for no reason.
    hint = _platform_hint().lower()
    assert "a2a_call" in hint
    assert "'codigo'" in hint
    assert "no respondas tú en su lugar" in hint


def test_the_hint_says_he_can_teach_and_what_the_screen_does() -> None:
    """The hint has to move in the same change as the drawing.

    In August it said there was no screen while the photo was already
    being pushed, and he declined correctly for the wrong reason
    (§12, 2026-08-25). Remember §7: an existing session only sees this
    after `/new` and `/approve`.

    Asserted against `_TEACHING` itself, not the whole hint. `_SCREEN`
    already ends "...tú no la ves: solo sabes lo que la cámara te ha
    contado" — about the cameras, nothing to do with teaching — and a
    hint-wide check for "no ves"/"no la ves" would pass on that alone,
    even with the teaching paragraph's own version of the same rule
    deleted. Checking `_TEACHING` in isolation is what keeps this test
    honest about which paragraph it is covering."""
    teaching = _TEACHING.lower()
    assert "clase" in teaching
    assert "temario" in teaching
    # He does not see the card. Saying he does is how he starts
    # describing what is on it.
    assert "no ves" in teaching
    # And the paragraph actually has to reach the model, not just exist.
    assert _TEACHING in _platform_hint()
