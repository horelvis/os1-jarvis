"""The phone socket: who holds the turn, and what happens to the second
person who presses.

Three iPhones plus the desk can press at once. Queueing spoken orders
ages badly — he would answer something asked a minute ago — so a press
during a running turn is refused and the page says so.
"""

from samantha_widget.remote import RemoteDesk


class FakeEndpoint:
    def __init__(self, name: str) -> None:
        self.name = name
        self.written: list[bytes] = []
        self.refusals = 0

    def write(self, pcm: bytes) -> None:
        self.written.append(pcm)

    def refuse(self) -> None:
        self.refusals += 1


def test_the_first_to_press_holds_the_turn() -> None:
    desk = RemoteDesk(on_utterance=lambda pcm, endpoint: None)
    phone = FakeEndpoint("iphone-cocina")

    assert desk.claim(phone) is True
    assert desk.busy is True
    assert desk.current is phone


def test_the_second_to_press_is_refused_not_queued() -> None:
    desk = RemoteDesk(on_utterance=lambda pcm, endpoint: None)
    first, second = FakeEndpoint("a"), FakeEndpoint("b")
    desk.claim(first)

    assert desk.claim(second) is False
    assert desk.current is first
    assert second.written == []


def test_releasing_lets_the_next_one_in() -> None:
    desk = RemoteDesk(on_utterance=lambda pcm, endpoint: None)
    first, second = FakeEndpoint("a"), FakeEndpoint("b")
    desk.claim(first)
    desk.release()

    assert desk.busy is False
    assert desk.claim(second) is True


def test_the_utterance_is_delivered_with_the_endpoint_that_spoke() -> None:
    """The reply has to go back where the question came from, so the
    endpoint travels with the audio."""
    seen: list[tuple[bytes, object]] = []
    desk = RemoteDesk(on_utterance=lambda pcm, endpoint: seen.append((pcm, endpoint)))
    phone = FakeEndpoint("iphone-cocina")
    desk.claim(phone)

    desk.finish(b"\x01\x02" * 100, phone)

    assert seen == [(b"\x01\x02" * 100, phone)]


def test_a_release_by_a_phone_that_does_not_hold_the_turn_is_ignored() -> None:
    """Otherwise a second phone releasing frees the first one's turn."""
    desk = RemoteDesk(on_utterance=lambda pcm, endpoint: None)
    first, second = FakeEndpoint("a"), FakeEndpoint("b")
    desk.claim(first)

    desk.release(second)

    assert desk.current is first
