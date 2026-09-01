"""The page is not testable in a browser from here — that needs an
iPhone in a hand, exactly as §2.3 says of the strip's appearance. What IS
testable is that it does not lie about the contract and does not reach
the network."""

from pathlib import Path

PAGE = Path(__file__).parent.parent / "samantha_widget" / "static" / "movil.html"


def test_the_page_exists_and_is_self_contained() -> None:
    """§1.1: nothing leaves the house. A page that pulls a font or a
    framework from a CDN is the house talking to the internet every time
    somebody presses the button."""
    text = PAGE.read_text()

    assert "http://" not in text.replace("http://www.w3.org", "")
    assert "https://" not in text
    assert "cdn" not in text.lower()


def test_the_page_reads_the_rate_instead_of_assuming_it() -> None:
    """48 kHz is usual, not guaranteed — it is the device's choice."""
    text = PAGE.read_text()

    assert "sampleRate" in text
    assert "48000" not in text


def test_the_page_speaks_the_protocol_the_server_expects() -> None:
    text = PAGE.read_text()

    for token in ('"start"', '"end"', '"busy"'):
        assert token in text


def test_the_visible_text_is_spanish() -> None:
    """CLAUDE.md §2.9: user-facing strings in Spanish."""
    text = PAGE.read_text()

    assert "Mantén pulsado" in text
