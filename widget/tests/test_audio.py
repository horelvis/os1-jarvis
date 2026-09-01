"""The microphone thread, and the one thing that must never end it.

`audio.py` is PortAudio and a thread, so almost none of it is testable
without a device. The exception is the loop itself, which is where the
invariant of 2026-09-01 lives: **failure is silence, never deafness**.
A device that has gone away ends this thread on purpose; a bug in the
frame callback must not, because the result is indistinguishable from a
healthy widget that has simply stopped hearing anybody.
"""

from samantha_widget.audio import Microphone
from samantha_widget.vad import FRAME_SAMPLES


class FakeStream:
    """`sd.RawInputStream`, for exactly as many frames as asked for."""

    def __init__(self, frames: int) -> None:
        self.left = frames

    def read(self, samples: int) -> tuple[bytes, bool]:
        if self.left <= 0:
            # What an unplugged device looks like: the pump ends here,
            # deliberately, and that is the branch under test's floor.
            raise RuntimeError("device gone")
        self.left -= 1
        return b"\x00\x00" * samples, False


def test_a_raising_callback_does_not_end_the_microphone_thread(capsys) -> None:
    """The failure this closes: anything the frame callback raised came
    out of `_pump` — the callback is called OUTSIDE the read's `try` —
    the thread returned, and the microphone was never read again. One
    traceback in the journal, a strip that looks perfectly healthy, and
    a JARVIS who cannot hear. Vosk was one raise away from it at four
    call sites; this is the backstop under the guard at those sites.
    """
    seen = []

    def on_frame(frame: bytes) -> None:
        seen.append(frame)
        raise ValueError("json.loads: nothing to decode")

    mic = Microphone(on_frame)
    mic._stream = FakeStream(20)
    mic._running = True
    mic._pump()

    # All twenty frames were delivered: the first failure did not stop
    # the loop, and the nineteen after it did not either.
    assert len(seen) == 20
    # And it said so once, not twenty times.
    assert capsys.readouterr().err.count("la captura falló") == 1


def test_a_dead_device_still_ends_it() -> None:
    """The other half, unchanged since 2026-08: a stream that raises on
    `read` is not survivable and the thread returns."""
    frames = []
    mic = Microphone(frames.append)
    mic._stream = FakeStream(3)
    mic._running = True
    mic._pump()

    assert [len(f) for f in frames] == [FRAME_SAMPLES * 2] * 3


def test_audible_covers_the_gap_between_clauses() -> None:
    """`busy` is False for a third of a second between clauses, while his
    voice is still leaving the speaker.

    Measured 2026-09-01 against the real Player: a three-clause reply
    spent 0.70 s of its 2.70 s with `busy` False, in two gaps of ~0.36 s
    — the time CosyVoice takes to synthesise the next clause. The
    barge-in gate is `if player.busy and not detector.speaking`, so in
    those gaps there is NO gate: his own voice reaches the detector,
    opens a turn, and from then on `detector.speaking` keeps the gate
    bypassed for the whole rest of the reply. That is the feedback loop
    the user hit — he transcribed himself and answered, GPU pinned at
    94%.

    `busy` cannot be widened: `say()` waits on it clause by clause, and a
    tail there would slow his speech. Hence a second property.
    """
    from samantha_widget.audio import TAIL_SECONDS, Player

    player = Player()
    now = 1000.0

    # Nothing played yet: not audible.
    assert player.audible(now) is False

    # A block just went to the speaker. Queue empty, not writing — this
    # is exactly the between-clauses state, and it must still count.
    player._last_block_at = now
    assert player.audible(now + 0.05) is True
    assert player.audible(now + TAIL_SECONDS - 0.01) is True

    # Long enough after the last sound, the room is his no more.
    assert player.audible(now + TAIL_SECONDS + 0.01) is False


def test_audible_is_true_whenever_busy_is() -> None:
    """It widens the window; it never narrows it."""
    from samantha_widget.audio import Player

    player = Player()
    player.write(b"\x00\x00" * 10)

    assert player.busy is True
    assert player.audible(1000.0) is True
