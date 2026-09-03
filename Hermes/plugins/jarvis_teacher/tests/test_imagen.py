"""Images ride inside the Markdown, and the strip never fetches one.

The plugin resolves every reference to a local file first. That is not
tidiness: a widget that downloaded a url would be opening a connection
from the process that draws, with whatever it was handed.
"""

import pytest

from Hermes.plugins.jarvis_teacher import imagen


@pytest.fixture(autouse=True)
def spool(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_TEACHER_HOME", str(tmp_path))
    return tmp_path


def _png() -> bytes:
    # The smallest thing Pillow will open: a 1x1 PNG.
    import base64

    return base64.b64decode(
        b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )


def test_a_reference_becomes_a_local_path(spool) -> None:
    fuera = imagen.resolver("![](https://x/y.png)", traer=lambda _u: _png(), now=1.0)
    assert "https://" not in fuera
    assert str(imagen.spool_dir()) in fuera


def test_something_that_is_not_an_image_is_dropped(spool) -> None:
    fuera = imagen.resolver(
        "## T\n\n![](https://x/y.png)\n\n- a\n",
        traer=lambda _u: b"<html>no</html>",
        now=1.0,
    )
    assert "![](" not in fuera
    assert "- a" in fuera


def test_a_download_that_fails_costs_the_picture_not_the_card(spool) -> None:
    def traer(_url: str) -> bytes:
        raise OSError("sin red")

    fuera = imagen.resolver(
        "## T\n\n![](https://x/y.png)\n\n- a\n", traer=traer, now=1.0
    )
    assert "- a" in fuera


def test_a_document_with_no_images_comes_back_unchanged(spool) -> None:
    md = "## T\n\n- a\n- b\n"
    assert imagen.resolver(md, traer=lambda _u: b"", now=1.0) == md


def test_an_inline_reference_that_fails_leaves_sentence_readable(spool) -> None:
    """An inline image that fails is removed, leaving tidy text."""
    md = "Mira ![](https://x/y.png) aqui y sigue el texto importante despues.\n"

    def traer(_url: str) -> bytes:
        raise OSError("sin red")

    fuera = imagen.resolver(md, traer=traer, now=1.0)
    assert "https://" not in fuera
    assert "Mira aqui y sigue el texto importante despues." in fuera
    # No double spaces where the reference was
    assert "  " not in fuera


def test_an_own_line_reference_that_fails_leaves_no_blank_line(spool) -> None:
    """A reference alone on its line is removed with the whole line."""
    md = "## Titulo\n\n![](https://x/y.png)\n\nTexto despues.\n"

    def traer(_url: str) -> bytes:
        raise OSError("sin red")

    fuera = imagen.resolver(md, traer=traer, now=1.0)
    assert "https://" not in fuera
    assert "Titulo" in fuera
    assert "Texto despues." in fuera
    # No blank line where the image was
    assert "\n\n\n" not in fuera


def test_a_document_with_good_and_bad_references_keeps_the_good_one(
    spool,
) -> None:
    """Mixed references: good one rewritten to spool, bad one dropped."""

    def traer(url: str) -> bytes:
        if "good" in url:
            return _png()
        raise OSError("no good")

    md = "![](https://x/good.png) y ![](https://x/bad.png) aqui.\n"
    fuera = imagen.resolver(md, traer=traer, now=1.0)
    assert "https://" not in fuera
    assert str(imagen.spool_dir()) in fuera
    assert "y aqui." in fuera or "y  aqui." in fuera  # May have extra space


def test_a_reference_inside_a_fence_is_never_touched(spool) -> None:
    """Code block references are literal text and must survive exactly."""
    md = "```python\n![](https://x/y.png)\n```\n"

    fuera = imagen.resolver(md, traer=lambda _u: _png(), now=1.0)
    # The reference inside the fence is untouched
    assert md == fuera
