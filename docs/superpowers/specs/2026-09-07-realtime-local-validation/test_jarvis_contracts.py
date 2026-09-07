"""Synthetic reproductions against real Jarvis routing helpers.

These tests import the production classes/functions but use fake endpoints and
bytes. They do not start GTK, sockets, Hermes, Whisper or CosyVoice.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "widget"))

from jarvis_widget.__main__ import destino_de, settle_turn
from jarvis_widget.remote import RemoteDesk


class FakeEndpoint:
    def __init__(self, persona: str, name: str = "phone") -> None:
        self.persona = persona
        self.name = name
        self.refusals = 0
        self.done_count = 0

    def refuse(self) -> None:
        self.refusals += 1

    def done(self) -> None:
        self.done_count += 1


class JarvisContractReproductions(unittest.TestCase):
    def test_destino_de_falls_to_room_when_remote_claim_is_released(self) -> None:
        desk = RemoteDesk(on_utterance=lambda _pcm, _endpoint: None)
        phone = FakeEndpoint("persona-a")
        self.assertTrue(desk.claim(phone, now=0.0))
        self.assertIs(destino_de(desk, "persona-a"), phone)

        desk.release(phone)

        self.assertIsNone(destino_de(desk, "persona-a"))

    def test_same_endpoint_can_start_second_turn_while_first_is_answering(self) -> None:
        heard: list[tuple[bytes, object]] = []
        desk = RemoteDesk(
            on_utterance=lambda pcm, endpoint: heard.append((pcm, endpoint))
        )
        phone = FakeEndpoint("persona-a")
        self.assertTrue(desk.claim(phone, now=0.0))
        desk.finish(b"old", phone, now=1.0)

        second_claim = desk.claim(phone, now=2.0)
        desk.finish(b"new", phone, now=3.0)

        self.assertTrue(second_claim)
        self.assertEqual([pcm for pcm, _endpoint in heard], [b"old", b"new"])
        self.assertTrue(all(endpoint is phone for _pcm, endpoint in heard))

    def test_settle_turn_releases_claim_without_terminal_done(self) -> None:
        desk = RemoteDesk(on_utterance=lambda _pcm, _endpoint: None)
        phone = FakeEndpoint("persona-a")
        self.assertTrue(desk.claim(phone, now=0.0))

        settle_turn(phone, desk)

        self.assertFalse(desk.busy_for("persona-a"))
        self.assertEqual(phone.done_count, 0)


if __name__ == "__main__":
    unittest.main()
