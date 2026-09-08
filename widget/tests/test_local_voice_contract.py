"""Offline P0 vectors and reference traces, not tests of a live voice endpoint."""

import hashlib
import json
import struct
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "local_voice_v1"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def decode_pcm(direction: str, data: bytes) -> tuple[int | None, list[int]]:
    """Reference byte layout used by both platform fixture consumers."""
    if direction == "client":
        assert 2 <= len(data) <= 3200 and len(data) % 2 == 0, "input_size"
        turn, pcm = None, data
    else:
        assert 6 <= len(data) <= 48004 and len(data) % 2 == 0, "output_size"
        turn = struct.unpack(">I", data[:4])[0]
        assert turn > 0, "turn_zero"
        pcm = data[4:]
    return turn, list(struct.unpack(f"<{len(pcm) // 2}h", pcm))


class TraceReader:
    """Minimal executable ordering oracle; contains no networking or model work."""

    def __init__(self) -> None:
        self.generation = 0
        self.reset()

    def reset(self) -> None:
        self.connected = True
        self.hello = False
        self.ready = False
        self.microphone = False
        self.current = 0
        self.playing = None
        self.text = ""
        self.turns = {}

    def snapshot(self) -> dict:
        return {
            "generation": self.generation,
            "ready": self.ready,
            "microphone": self.microphone,
            "current": self.current,
            "playing": self.playing,
            "text": self.text,
            "terminals": sum(t["terminal"] for t in self.turns.values()),
            "live": sum(not t["terminal"] for t in self.turns.values()),
        }

    def active(self, turn: int) -> dict:
        assert turn in self.turns, "invalid_turn"
        state = self.turns[turn]
        assert not state["terminal"], "terminal_turn"
        return state

    def step(self, step: dict) -> None:
        action = step.get("action")
        if action == "checkpoint":
            actual = self.snapshot()
            for key, value in step["expect"].items():
                assert actual[key] == value, (key, actual[key], value)
            return
        if action in {"disconnect", "close"}:
            self.connected = self.ready = self.microphone = False
            self.playing = None
            self.text = ""
            for state in self.turns.values():
                state["terminal"] = True
            return
        if action == "connect":
            assert not self.connected
            self.generation += 1
            self.reset()
            return
        if action == "late_callback":
            assert step["generation"] < self.generation
            return
        assert action is None, "unknown_harness_action"
        assert self.connected, "disconnected"
        direction = step["direction"]
        if "binary_hex" in step:
            turn, _ = decode_pcm(direction, bytes.fromhex(step["binary_hex"]))
            if direction == "client":
                assert self.ready and self.microphone, "audio_disabled"
            else:
                state = self.active(turn)
                assert state["text"], "text_required"
                if turn == self.current:
                    self.playing = turn
            return
        message = step["json"]
        kind = message["type"]
        if direction == "client":
            if kind == "hello":
                assert not self.hello, "duplicate_hello"
                self.hello = True
                return
            assert self.ready, "not_ready"
            if kind == "microphone":
                self.microphone = message["enabled"]
            elif kind == "cancel":
                assert message["turn"] in self.turns, "invalid_turn"
                if self.playing == message["turn"]:
                    self.playing = None
            else:
                raise AssertionError("client_event")
            return
        if kind == "ready":
            assert self.hello and not self.ready, "unexpected_ready"
            self.ready = True
            return
        if kind == "error":
            if "turn" in message:
                self.active(message["turn"])["error"] = True
            return
        assert self.ready, "not_ready"
        turn = message["turn"]
        if kind == "turn_started":
            assert self.microphone, "audio_disabled"
            assert turn == self.current + 1 and turn <= 4294967295, "turn_sequence"
            self.current = turn
            self.playing = None
            self.text = ""
            self.turns[turn] = {
                "terminal": False,
                "stopped": False,
                "transcript": False,
                "text": False,
                "error": False,
            }
            return
        state = self.active(turn)
        if kind == "speech_stopped":
            assert not state["stopped"], "duplicate_speech_stopped"
            state["stopped"] = True
        elif kind == "transcript":
            assert state["stopped"], "speech_stop_required"
            assert not state["transcript"], "duplicate_transcript"
            state["transcript"] = True
        elif kind == "text":
            assert state["transcript"], "transcript_required"
            state["text"] = True
            if turn == self.current:
                self.text += message["delta"]
        elif kind == "turn_done":
            if message["status"] == "completed":
                assert state["stopped"], "speech_stop_required"
            elif message["status"] == "failed":
                assert state["error"], "error_required"
            if message["status"] != "completed" and self.playing == turn:
                self.playing = None
            state["terminal"] = True
        else:
            raise AssertionError("server_event")


@pytest.mark.parametrize(
    "vector", load("binary.json")["vectors"], ids=lambda v: v["id"]
)
def test_binary_vectors(vector: dict) -> None:
    data = bytes.fromhex(vector["hex"])
    if not vector["valid"]:
        with pytest.raises(AssertionError):
            decode_pcm(vector["direction"], data)
        return
    turn, samples = decode_pcm(vector["direction"], data)
    assert samples == vector["samples"]
    assert turn == vector.get("turn")


@pytest.mark.parametrize("boundary", load("binary.json")["boundaries"])
def test_binary_boundaries(boundary: dict) -> None:
    data = bytes(boundary["bytes"])
    if boundary["direction"] == "server":
        data = struct.pack(">I", 1) + data[4:]
    if boundary["valid"]:
        decode_pcm(boundary["direction"], data)
    else:
        with pytest.raises(AssertionError):
            decode_pcm(boundary["direction"], data)


@pytest.mark.parametrize("trace", load("traces.json")["traces"], ids=lambda t: t["id"])
def test_reference_traces(trace: dict) -> None:
    reader = TraceReader()
    if trace["valid"]:
        for step in trace["steps"]:
            reader.step(step)
    else:
        with pytest.raises(AssertionError, match=trace["error"]):
            for step in trace["steps"]:
                reader.step(step)


def test_fixture_integrity() -> None:
    manifest = load("manifest.json")
    assert manifest["protocol"] == "jarvis.local-voice.v1"
    for name, expected in manifest["sha256"].items():
        assert hashlib.sha256((FIXTURES / name).read_bytes()).hexdigest() == expected
