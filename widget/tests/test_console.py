"""The lines shown on the strip, as pure state. No GTK in here."""

from samantha_widget.console import (
    HEIGHT,
    LINE_HEIGHT,
    MAX_LINE_CHARS,
    PADDING,
    Console,
)


def test_it_starts_hidden():
    c = Console()
    assert not c.visible and c.height == 0


def test_writing_makes_it_appear_and_asks_for_the_resize():
    c = Console()
    assert c.write("buscando el fallo") is True
    assert c.visible and c.height == LINE_HEIGHT + PADDING


def test_it_grows_with_the_content_up_to_the_ceiling():
    # Three lines take the room of three lines, not of the ceiling.
    c = Console()
    c.write("una\ndos\ntres")
    assert c.height == LINE_HEIGHT * 3 + PADDING
    c.write("\n".join(str(i) for i in range(50)))
    assert c.height == HEIGHT


def test_more_lines_do_ask_for_a_resize_while_it_is_growing():
    c = Console()
    c.write("una")
    assert c.write("dos") is True


def test_a_blob_with_newlines_is_split():
    c = Console()
    c.write("una\ndos\ntres")
    assert c.lines == ["una", "dos", "tres"]


def test_blank_lines_are_dropped():
    # Most of a tool's output and none of its meaning: the lines kept
    # should be lines of content.
    c = Console()
    c.write("una\n\n   \ndos")
    assert c.lines == ["una", "dos"]


def test_only_the_last_few_are_kept():
    c = Console(max_lines=3)
    c.write("\n".join(str(i) for i in range(10)))
    assert c.lines == ["7", "8", "9"]


def test_a_very_long_line_is_cut():
    c = Console()
    c.write("x" * 5000)
    assert len(c.lines[0]) == MAX_LINE_CHARS


def test_clearing_puts_it_away():
    c = Console()
    c.write("algo")
    assert c.clear() is True
    assert not c.visible and c.height == 0


def test_clearing_an_empty_one_asks_for_nothing():
    c = Console()
    assert c.clear() is False


def test_the_block_is_oldest_first():
    c = Console()
    c.write("una\ndos")
    assert c.text() == "una\ndos"
