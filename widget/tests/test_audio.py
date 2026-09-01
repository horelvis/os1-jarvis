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
