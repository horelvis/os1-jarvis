"""Hearing his name, with a scripted scorer instead of a real model.

openWakeWord's job is one score per frame. Deciding what counts as
having heard the phrase — how many frames in a row, and how long to stay
quiet afterwards — is ours, and it is what decides whether he wakes up
when the television says something that rhymes.
"""

from jarvis_widget.hotword import Hotword

# One prediction per frame, so the scripted scores line up one-to-one.
CHUNK = 512

FRAME = b"\x00\x00" * 512


class ScriptedScorer:
    def __init__(self, scores: list[float]) -> None:
        self.scores = list(scores)
        self.calls = 0

    def predict(self, frame):
        self.calls += 1
        score = self.scores.pop(0) if self.scores else 0.0
        return {"hey_jarvis": score}


def _clock(times: list[float]):
    seq = list(times)

    def now() -> float:
        return seq.pop(0) if len(seq) > 1 else seq[0]

    return now


def test_it_is_deaf_until_the_model_is_loaded():
    h = Hotword(chunk_samples=CHUNK)
    assert h.ready is False
    assert h.heard(FRAME) is False


def test_one_loud_frame_is_not_his_name():
    h = Hotword(chunk_samples=CHUNK)
    h.use(ScriptedScorer([0.9, 0.0, 0.0]))
    assert h.heard(FRAME) is False


def test_three_frames_in_a_row_are():
    h = Hotword(chunk_samples=CHUNK)
    h.use(ScriptedScorer([0.9, 0.9, 0.9]))
    assert [h.heard(FRAME) for _ in range(3)] == [False, False, True]


def test_a_gap_in_the_middle_starts_the_count_again():
    h = Hotword(chunk_samples=CHUNK)
    h.use(ScriptedScorer([0.9, 0.1, 0.9, 0.9]))
    assert [h.heard(FRAME) for _ in range(4)] == [False, False, False, False]


def test_it_stays_quiet_for_a_moment_after_firing():
    # The phrase is still in openWakeWord's buffer and keeps scoring.
    h = Hotword(
        chunk_samples=CHUNK,
        cooldown=2.0,
        now=_clock([0.0, 0.0, 0.0, 0.5, 1.0, 3.0, 3.0, 3.0]),
    )
    h.use(ScriptedScorer([0.9] * 8))
    assert [h.heard(FRAME) for _ in range(5)] == [False, False, True, False, False]
    # Past the cooldown it can fire again.
    assert [h.heard(FRAME) for _ in range(3)] == [False, False, True]


def test_a_scorer_that_throws_does_not_take_the_microphone_down():
    class Broken:
        def predict(self, frame):
            raise RuntimeError("no model")

    h = Hotword(chunk_samples=CHUNK)
    h.use(Broken())
    assert h.heard(FRAME) is False


def test_an_empty_score_is_not_a_hit():
    class Empty:
        def predict(self, frame):
            return {}

    h = Hotword(chunk_samples=CHUNK)
    h.use(Empty())
    assert h.heard(FRAME) is False


def test_the_threshold_is_the_sensitivity():
    h = Hotword(chunk_samples=CHUNK, sensitivity=0.6, confirmations=1)
    h.use(ScriptedScorer([0.59, 0.61]))
    assert [h.heard(FRAME) for _ in range(2)] == [False, True]
