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

from Hermes.plugins.samantha_kiosk import (
    _FALLBACK_HINT,
    _PERSONA_FILE,
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
    from Hermes.plugins import samantha_kiosk

    monkeypatch.setattr(samantha_kiosk, "_PERSONA_FILE", _PERSONA_FILE / "nope")
    assert samantha_kiosk._platform_hint() == _FALLBACK_HINT


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
