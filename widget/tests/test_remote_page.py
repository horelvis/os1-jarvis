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


def test_the_microphone_is_released_when_the_press_ends() -> None:
    """iOS lights its recording indicator for as long as a track is
    live. Held across presses it stays lit for the whole session, which
    reads — correctly, from outside — as "it is listening to me all the
    time"."""
    text = PAGE.read_text()

    assert "getTracks().forEach" in text
    assert "track.stop()" in text


def test_a_refused_press_cleans_up_too() -> None:
    """`end()` returned before `node.disconnect()` when he was busy, so
    every refused press leaked a live ScriptProcessor."""
    text = PAGE.read_text()
    end = text[text.index("function end()") :]

    assert end.index("stopMic()") < end.index("wasRecording) return")


def test_hitting_the_ceiling_is_said_out_loud() -> None:
    """Silent truncation turns a long question into half a question."""
    text = PAGE.read_text()

    assert '"truncated"' in text
    assert "Demasiado largo" in text
