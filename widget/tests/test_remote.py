"""The phone socket: who holds the turn, and what happens to the second
person who presses.

Three iPhones plus the desk can press at once. Queueing spoken orders
ages badly — he would answer something asked a minute ago — so a press
during a running turn is refused and the page says so.
"""

from samantha_widget.remote import ANSWERING_SECONDS, HELD_TURN_SECONDS, RemoteDesk


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


def test_a_turn_held_under_the_ceiling_cannot_be_stolen() -> None:
    desk = RemoteDesk(on_utterance=lambda pcm, endpoint: None)
    first, second = FakeEndpoint("a"), FakeEndpoint("b")
    desk.claim(first, now=0.0)

    assert desk.claim(second, now=HELD_TURN_SECONDS - 1) is False
    assert desk.current is first
    assert second.refusals == 1


def test_a_turn_held_past_the_ceiling_is_stolen_not_refused() -> None:
    """A phone that pressed and vanished — a dead app, a dropped
    connection with no `end` frame — must not lock out the house
    forever. No sleeping: the clock is passed in."""
    desk = RemoteDesk(on_utterance=lambda pcm, endpoint: None)
    first, second = FakeEndpoint("a"), FakeEndpoint("b")
    desk.claim(first, now=0.0)

    assert desk.claim(second, now=HELD_TURN_SECONDS + 1) is True
    assert desk.current is second
    assert second.refusals == 0


def test_finishing_ends_the_deadline_so_a_long_reply_is_not_stolen() -> None:
    """The deadline is for the RECORDING phase only — a phone that
    pressed and never released. Once `end` arrived and `finish()` ran,
    the reply may legitimately take minutes (he holds a terminal), so a
    claim well past HELD_TURN_SECONDS after the press must still be
    refused, not allowed to steal the turn mid-answer."""
    desk = RemoteDesk(on_utterance=lambda pcm, endpoint: None)
    first, second = FakeEndpoint("a"), FakeEndpoint("b")
    desk.claim(first, now=0.0)
    desk.finish(b"\x01\x02" * 100, first, now=0.0)

    assert desk.claim(second, now=HELD_TURN_SECONDS + 1) is False
    assert desk.current is first
    assert second.refusals == 1


def test_a_reply_that_never_settles_can_still_be_stolen_eventually() -> None:
    """`finish()` re-stamps the deadline rather than clearing it: a turn
    that ends in silence (the gateway's own `📬 No home channel` first
    turn is exactly that shape — CLAUDE.md §5) must not hold a phone
    forever with no way back except its own socket dropping."""
    desk = RemoteDesk(on_utterance=lambda pcm, endpoint: None)
    first, second = FakeEndpoint("a"), FakeEndpoint("b")
    desk.claim(first, now=0.0)
    desk.finish(b"\x01\x02" * 100, first, now=0.0)

    assert desk.claim(second, now=ANSWERING_SECONDS + 1) is True
    assert desk.current is second
    assert second.refusals == 0
