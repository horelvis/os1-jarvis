"""Turn boundaries, with a scripted VAD instead of a real one.

Silero's job is one number per frame. Deciding what a *turn* is — how
much speech starts one, how much silence ends one, what is too short to
bother transcribing — is ours, and it is the part that decides whether
she interrupts people or ignores them. So it is tested here, exactly,
with no model and no microphone in the room.
"""

from samantha_widget.vad import FRAME_SAMPLES, UtteranceDetector

FRAME = b"\x00\x00" * FRAME_SAMPLES
FRAME_SECONDS = FRAME_SAMPLES / 16000


class ScriptedProbe:
    def __init__(self, script: list[float]) -> None:
        self.script = list(script)

    def speech_probability(self, frame: bytes) -> float:
        del frame
        return self.script.pop(0) if self.script else 0.0


def _frames(*runs: tuple[float, float]) -> list[float]:
    out: list[float] = []
    for probability, seconds in runs:
        out += [probability] * max(1, round(seconds / FRAME_SECONDS))
    return out


def _run(script: list[float]) -> list[bytes]:
    detector = UtteranceDetector(ScriptedProbe(script))
    return [u for _ in script if (u := detector.push(FRAME)) is not None]


def test_silence_alone_produces_nothing() -> None:
    assert _run(_frames((0.0, 5.0))) == []


def test_a_normal_utterance_is_emitted_once() -> None:
    utterances = _run(_frames((0.0, 0.5), (0.9, 2.0), (0.0, 2.0)))

    assert len(utterances) == 1


def test_the_utterance_holds_roughly_the_speech() -> None:
    utterances = _run(_frames((0.0, 0.5), (0.9, 2.0), (0.0, 2.0)))
    seconds = len(utterances[0]) / 2 / 16000

    # 2 s of speech, the 0.7 s of silence that ends the turn, and since
    # 2026-08-26 the 0.5 s of run-up kept in front of it — see
    # `_PREROLL_SECONDS`, which exists so a wake word survives.
    assert 2.0 <= seconds <= 3.5


def test_a_single_loud_frame_does_not_start_a_turn() -> None:
    assert _run(_frames((0.0, 0.5), (0.95, 0.032), (0.0, 3.0))) == []


def test_a_gap_shorter_than_the_silence_window_does_not_split_a_turn() -> None:
    utterances = _run(_frames((0.9, 1.0), (0.0, 0.3), (0.9, 1.0), (0.0, 2.0)))

    assert len(utterances) == 1


def test_a_gap_longer_than_the_silence_window_splits_it() -> None:
    utterances = _run(_frames((0.9, 1.0), (0.0, 1.5), (0.9, 1.0), (0.0, 1.5)))

    assert len(utterances) == 2


def test_a_too_short_utterance_is_discarded() -> None:
    assert _run(_frames((0.9, 0.2), (0.0, 2.0))) == []


def test_a_stuck_vad_cannot_grow_the_buffer_forever() -> None:
    utterances = _run(_frames((0.99, 45.0)))

    assert len(utterances) >= 1
    assert len(utterances[0]) / 2 / 16000 <= 31.0


def test_speaking_flag_tracks_the_turn() -> None:
    detector = UtteranceDetector(ScriptedProbe(_frames((0.9, 1.0), (0.0, 2.0))))

    detector.push(FRAME)
    assert detector.speaking is False
    for _ in range(4):
        detector.push(FRAME)
    assert detector.speaking is True


def test_the_minimum_measures_speech_not_the_buffer() -> None:
    """0.3 s of speech makes a ~1 s buffer once the trailing silence is in
    it. Measuring the buffer would let every cough through."""
    assert _run(_frames((0.9, 0.3), (0.0, 2.0))) == []


def test_scattered_pre_roll_frames_do_not_count_towards_the_minimum() -> None:
    """A ticking clock before someone speaks must not top up the tally."""
    script: list[float] = []
    for _ in range(40):  # ~2.5 s of alternating tick / silence
        script += [0.9, 0.0]
    script += _frames((0.9, 0.2), (0.0, 2.0))

    assert _run(script) == []


# ── the pre-roll ──────────────────────────────────────────────────────
#
# Measured 2026-08-26, the day he was given a wake word: "Jarvis, ¿qué
# día es hoy?" was transcribed as "¿Qué día es hoy?" — his name gone,
# and with it the whole turn, because the filter had nothing to match.
# The first syllable of a word routinely sits under the threshold, and
# the buffer was cleared on every frame that did, so it was thrown away
# before the turn started. That cost nothing while everything heard was
# for him; with a wake word, the syllable that gets dropped is the one
# that decides whether he answers at all.


def test_the_quiet_run_up_to_a_turn_is_kept() -> None:
    # Ten quiet frames, then speech. Each frame is stamped with its own
    # index so the emitted buffer says where it started.
    quiet = 10
    detector = UtteranceDetector(ScriptedProbe([0.0] * quiet + [1.0] * 100))
    emitted = None
    for i in range(200):
        out = detector.push(bytes([i % 256, 0]) * FRAME_SAMPLES)
        if out is not None:
            emitted = out
            break
    assert emitted is not None
    started_at = emitted[0]
    # It must begin BEFORE the first frame of speech — that is the whole
    # point — and not at the very beginning of the quiet either.
    assert started_at < quiet, f"buffer starts at frame {started_at}, speech at {quiet}"
    assert quiet - started_at >= 5  # ~0.16 s of run-up, at 32 ms a frame


def test_the_run_up_never_grows_without_bound() -> None:
    # A room that is quiet for an hour must not accumulate an hour.
    detector = UtteranceDetector(ScriptedProbe([0.0] * 5000))
    for _ in range(4000):
        detector.push(FRAME)
    assert len(detector._buffer) / 2 / 16000 <= 1.0
