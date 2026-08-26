"""What she would SAY about what the camera sees.

The model itself is exercised by hand against BarnDoor's recordings —
it needs an 8 MB file and there is no camera on this machine. What is
tested here is the part that decides whether she opens her mouth, and
what comes out when she does.
"""

import itertools

import numpy as np
import pytest

from Hermes.plugins.samantha_vision.vision import (
    WATCHED_CLASSES,
    CameraStream,
    Detection,
    Watcher,
    _deduplicate,
    describe,
)


def person(confidence: float = 0.8, x: float = 0.5) -> Detection:
    return Detection(label="persona", confidence=confidence, x=x, y=0.5)


def test_nothing_seen_is_nothing_said() -> None:
    """Silence is the default. A camera that sees an empty driveway all
    day must not produce a single word."""
    assert describe([]) == ""


def test_one_person_is_somebody_not_a_class_name() -> None:
    """ "persona 0.81" is a detection; "alguien" is something she can say."""
    assert describe([person()]) == "alguien"


def test_two_people_are_counted() -> None:
    said = describe([person(0.9, 0.2), Detection("persona", 0.8, 0.7, 0.5)])

    assert said == "2 personas"


def test_objects_keep_their_own_name() -> None:
    assert describe([Detection("coche", 0.7, 0.5, 0.5)]) == "coche"


def test_a_person_and_a_car_read_as_a_sentence() -> None:
    said = describe([person(), Detection("coche", 0.7, 0.2, 0.5)])

    assert said == "alguien y coche"


def test_three_things_use_commas_and_a_final_and() -> None:
    said = describe(
        [
            person(),
            Detection("coche", 0.7, 0.2, 0.5),
            Detection("perro", 0.6, 0.9, 0.5),
        ]
    )

    assert said == "alguien, coche y perro"


# ── deduplication ─────────────────────────────────────────────────────


def test_the_same_thing_seen_twice_is_said_once() -> None:
    """YOLO returns overlapping boxes for one person. Spoken aloud,
    three boxes and one box are the same fact."""
    result = _deduplicate([person(0.6), person(0.9), person(0.7)])

    assert len(result) == 1
    assert result[0].confidence == 0.9


def test_different_things_all_survive() -> None:
    result = _deduplicate([person(), Detection("perro", 0.6, 0.1, 0.2)])

    assert len(result) == 2


def test_the_most_confident_wins() -> None:
    result = _deduplicate([person(0.5, x=0.1), person(0.95, x=0.9)])

    assert result[0].x == 0.9


def test_results_come_back_most_confident_first() -> None:
    result = _deduplicate(
        [Detection("coche", 0.5, 0.1, 0.2), person(0.9), Detection("perro", 0.7, 0, 0)]
    )

    # persona 0.9 > perro 0.7 > coche 0.5 — confidence, not the order
    # they arrived in.
    assert [d.label for d in result] == ["persona", "perro", "coche"]


# ── what is worth watching ────────────────────────────────────────────


def test_a_house_watches_people_vehicles_and_pets() -> None:
    labels = set(WATCHED_CLASSES.values())

    assert {"persona", "coche", "perro", "gato"} <= labels


def test_person_is_coco_class_zero() -> None:
    """If this ever stops being true, every detection is mislabelled and
    nothing errors — she just starts announcing bicycles as people."""
    assert WATCHED_CLASSES[0] == "persona"


def test_the_watch_list_is_short() -> None:
    """80 COCO classes exist. A driveway does not need to be told about
    a potted plant, and every extra class is another way to interrupt
    somebody for nothing."""
    assert len(WATCHED_CLASSES) <= 12


@pytest.mark.parametrize("missing", ["maceta", "silla", "tostadora"])
def test_household_clutter_is_not_watched(missing: str) -> None:
    assert missing not in WATCHED_CLASSES.values()


# ── when it is worth saying anything at all ───────────────────────────


def test_the_same_thing_again_is_not_news() -> None:
    """Someone standing in the driveway is one event, not one every
    three seconds."""
    from Hermes.plugins.samantha_vision.vision import Watcher

    watcher = Watcher()
    assert watcher.worth_saying([person()], now=1000.0, hour=12, camera="fuera")
    assert watcher.worth_saying([person()], now=1010.0, hour=12, camera="fuera") == []


def test_the_same_thing_much_later_is_news_again() -> None:
    from Hermes.plugins.samantha_vision.vision import ANTI_SPAM_SECONDS, Watcher

    watcher = Watcher()
    watcher.worth_saying([person()], now=1000.0, hour=12, camera="fuera")
    later = 1000.0 + ANTI_SPAM_SECONDS + 1

    assert watcher.worth_saying([person()], now=later, hour=12, camera="fuera")


def test_a_different_thing_is_always_news() -> None:
    """Anti-spam is per label: a car arriving while somebody stands
    there is a separate fact."""
    from Hermes.plugins.samantha_vision.vision import Watcher

    watcher = Watcher()
    watcher.worth_saying([person()], now=1000.0, hour=12, camera="fuera")
    car = Detection("coche", 0.9, 0.5, 0.5)

    assert watcher.worth_saying([car], now=1001.0, hour=12, camera="fuera")


def test_a_person_at_night_beats_the_anti_spam() -> None:
    """The second time somebody is in the garden at 3am is MORE worth
    saying than the first.

    Updated 2026-08-24: the 180 s window is still beaten, but there is
    now a 30 s floor under it, so the second mention lands at 31 s rather
    than at 10 s. What is tested is unchanged — the night rule beats the
    anti-spam — only the number it beats it by.
    """
    from Hermes.plugins.samantha_vision.vision import ANTI_SPAM_SECONDS, Watcher

    watcher = Watcher()
    watcher.worth_saying([person()], now=1000.0, hour=3, camera="fuera")

    said_again_at = 1031.0
    assert said_again_at - 1000.0 < ANTI_SPAM_SECONDS  # still inside the window
    assert watcher.worth_saying([person()], now=said_again_at, hour=3, camera="fuera")


def test_a_car_at_night_does_not_beat_the_anti_spam() -> None:
    """Only people. A car parked in view would otherwise talk all night."""
    from Hermes.plugins.samantha_vision.vision import Watcher

    watcher = Watcher()
    car = Detection("coche", 0.9, 0.5, 0.5)
    watcher.worth_saying([car], now=1000.0, hour=3, camera="fuera")

    assert watcher.worth_saying([car], now=1010.0, hour=3, camera="fuera") == []


def test_quiet_hours_wrap_around_midnight() -> None:
    from Hermes.plugins.samantha_vision.vision import is_quiet_hours

    assert is_quiet_hours(23) is True
    assert is_quiet_hours(3) is True
    assert is_quiet_hours(6) is True
    assert is_quiet_hours(7) is False
    assert is_quiet_hours(15) is False


def test_the_threshold_matches_what_the_cameras_taught_barndoor() -> None:
    """0.45 was a guess; 0.7 is what a system running against these
    cameras settled on."""
    from Hermes.plugins.samantha_vision.vision import DEFAULT_THRESHOLD

    assert DEFAULT_THRESHOLD == 0.7


# ── the anti-spam key learns there is more than one camera ────────────


def test_anti_spam_is_per_camera() -> None:
    """Somebody walking from one camera to the other is two events."""
    watcher = Watcher()
    assert watcher.worth_saying([person()], now=0.0, hour=12, camera="fuera")
    # Same label, same second, different camera: still worth saying.
    assert watcher.worth_saying([person()], now=0.0, hour=12, camera="entrada")


def test_anti_spam_still_silences_the_same_camera() -> None:
    watcher = Watcher()
    assert watcher.worth_saying([person()], now=0.0, hour=12, camera="fuera")
    assert not watcher.worth_saying([person()], now=10.0, hour=12, camera="fuera")


def test_the_same_camera_speaks_again_after_the_window() -> None:
    watcher = Watcher()
    watcher.worth_saying([person()], now=0.0, hour=12, camera="fuera")
    assert watcher.worth_saying([person()], now=181.0, hour=12, camera="fuera")


def test_a_person_at_night_beats_the_anti_spam_per_camera() -> None:
    """Updated 2026-08-24: 1.0 s became 31.0 s when the night floor
    arrived. The window it beats is still the 180 s one."""
    watcher = Watcher()
    assert watcher.worth_saying([person()], now=0.0, hour=3, camera="fuera")
    assert watcher.worth_saying([person()], now=31.0, hour=3, camera="fuera")


def test_a_car_at_night_does_not_beat_the_anti_spam_per_camera() -> None:
    watcher = Watcher()
    car = Detection(label="coche", confidence=0.9, x=0.5, y=0.5)
    assert watcher.worth_saying([car], now=0.0, hour=3, camera="fuera")
    assert not watcher.worth_saying([car], now=1.0, hour=3, camera="fuera")


# ── he stops repeating himself ────────────────────────────────────────
#
# Measured on the live gateway 2026-08-24: `entrada: alguien` five times
# in 35 minutes, which is ~480 spoken turns and ~480 model calls a day.
# The 180 s window stops three-SECOND spam; nothing stopped three-MINUTE
# spam. The floor stays 180 s and stays BarnDoor's; the widening is ours.


def _watcher():
    from Hermes.plugins.samantha_vision.vision import Watcher

    return Watcher()


def test_a_first_sighting_is_never_suppressed() -> None:
    """Whatever the escalation does, it may not cost the first word."""
    watcher = _watcher()
    assert watcher.worth_saying([person()], now=0.0, hour=12, camera="entrada")


def test_a_repeat_inside_the_window_says_nothing() -> None:
    watcher = _watcher()
    watcher.worth_saying([person()], now=0.0, hour=12, camera="entrada")
    assert watcher.worth_saying([person()], now=90.0, hour=12, camera="entrada") == []


def test_the_first_repeat_still_costs_only_the_calibrated_window() -> None:
    """180 s is the FLOOR, not something the escalation may raise."""
    from Hermes.plugins.samantha_vision.vision import ANTI_SPAM_SECONDS, Watcher

    watcher = Watcher()
    watcher.worth_saying([person()], now=0.0, hour=12, camera="entrada")
    assert watcher.worth_saying(
        [person()], now=ANTI_SPAM_SECONDS + 1, hour=12, camera="entrada"
    )


def test_it_keeps_saying_it_every_window_while_it_is_there() -> None:
    """BarnDoor's rule is flat: somebody who will not move is mentioned
    once per window, for as long as they are there.

    From 2026-08-24 to 2026-08-26 an escalation of ours widened that
    window on consecutive re-fires — 180 s, then 15 min, then hourly —
    and the user asked for BarnDoor's rule back (`no es práctico si solo
    mira cada cierto tiempo`). This is the test that pins the difference:
    the gaps are all the calibrated window, and none of them grows.
    """
    from Hermes.plugins.samantha_vision.vision import ANTI_SPAM_SECONDS, Watcher

    watcher = Watcher()
    spoke: list[float] = []
    for tick in range(0, 6 * 3600, 30):
        now = float(tick)
        if watcher.worth_saying([person()], now=now, hour=12, camera="entrada"):
            spoke.append(now)

    gaps = [b - a for a, b in itertools.pairwise(spoke)]
    assert spoke[0] == 0.0
    assert all(g == ANTI_SPAM_SECONDS for g in gaps), gaps
    # And the cost of that, stated rather than discovered: six hours of
    # somebody standing in view is 120 mentions, not eight.
    assert len(spoke) == 120, len(spoke)


def test_the_window_is_per_camera_and_per_label() -> None:
    """One camera going quiet must not quieten the other, or the car."""
    from Hermes.plugins.samantha_vision.vision import Watcher

    watcher = Watcher()
    for tick in range(0, 2000, 30):
        watcher.worth_saying([person()], now=float(tick), hour=12, camera="entrada")

    # Neither of these shares `entrada`/persona's key, so both are a
    # first sighting and neither is gated.
    assert watcher.worth_saying([person()], now=2000.0, hour=12, camera="fuera")
    car = Detection("coche", 0.9, 0.5, 0.5)
    assert watcher.worth_saying([car], now=2000.0, hour=12, camera="entrada")


def test_a_person_at_night_beats_a_window_that_just_fired() -> None:
    """The night rule is outside the anti-spam: the only thing that gates
    it is the 30 s floor."""
    from Hermes.plugins.samantha_vision.vision import Watcher

    watcher = Watcher()
    watcher.worth_saying([person()], now=0.0, hour=12, camera="fuera")
    # Ten seconds later it is 03:00 and somebody is in the garden. The
    # daylight window has not expired; the night rule does not care.
    assert watcher.worth_saying([person()], now=40.0, hour=3, camera="fuera")


def test_two_cameras_seeing_the_same_thing_inside_the_window_both_speak() -> None:
    """Task 4's keying, in the shape that actually broke it: not the same
    instant, but one camera silenced while the other is heard."""
    from Hermes.plugins.samantha_vision.vision import Watcher

    watcher = Watcher()
    assert watcher.worth_saying([person()], now=0.0, hour=12, camera="fuera")
    # 100 s later — well inside the 180 s window — the SAME label at the
    # OTHER camera. Under label-only keying this was silence, and somebody
    # could walk from the gate to the door unannounced.
    assert watcher.worth_saying([person()], now=100.0, hour=12, camera="entrada")
    # And the first camera is still, correctly, quiet.
    assert watcher.worth_saying([person()], now=100.0, hour=12, camera="fuera") == []


# ── the floor under the night rule ────────────────────────────────────
#
# `worth_saying` runs once per sampled frame, one to three times a
# second. With the window bypassed outright that is not insistence, it is
# continuous speech: 19,200 utterances over an eight-hour night, measured
# against the real Watcher before this floor existed.


def test_a_person_at_night_is_floored_at_thirty_seconds() -> None:
    from Hermes.plugins.samantha_vision.vision import Watcher

    watcher = Watcher()
    assert watcher.worth_saying([person()], now=0.0, hour=3, camera="fuera")
    assert watcher.worth_saying([person()], now=10.0, hour=3, camera="fuera") == []
    assert watcher.worth_saying([person()], now=31.0, hour=3, camera="fuera")


def test_the_night_floor_is_the_named_constant() -> None:
    """30 s is ours. It is not one of BarnDoor's four."""
    from Hermes.plugins.samantha_vision.vision import (
        ANTI_SPAM_SECONDS,
        NIGHT_FLOOR_SECONDS,
        Watcher,
    )

    assert NIGHT_FLOOR_SECONDS == 30
    assert ANTI_SPAM_SECONDS == 180
    watcher = Watcher(night_floor_seconds=5.0)
    assert watcher.worth_saying([person()], now=0.0, hour=3, camera="fuera")
    assert watcher.worth_saying([person()], now=4.0, hour=3, camera="fuera") == []
    assert watcher.worth_saying([person()], now=6.0, hour=3, camera="fuera")


def test_a_night_of_standing_there_is_not_thousands_of_utterances() -> None:
    """The number the floor exists for."""
    from Hermes.plugins.samantha_vision.vision import Watcher

    watcher = Watcher()
    spoke = 0
    tick = 0.0
    while tick < 8 * 3600:  # eight hours, sampled every 1.5 s
        if watcher.worth_saying([person()], now=tick, hour=3, camera="fuera"):
            spoke += 1
        tick += 1.5
    assert spoke == 960, spoke  # 8 h / 30 s, not 19_200


def test_the_night_does_not_carry_the_days_escalation_into_the_morning() -> None:
    """He is told at dawn, not an hour after it.

    Measured before the fix: a key escalated to the hourly level in
    daylight and present all night kept that level across the boundary,
    and the first mention after quiet hours ended came 60.0 minutes
    later. The morning is exactly when the user would want to know.
    """
    from Hermes.plugins.samantha_vision.vision import ANTI_SPAM_SECONDS, Watcher

    watcher = Watcher()
    for tick in range(0, 4000, 30):  # daylight: escalate to the top
        watcher.worth_saying([person()], now=float(tick), hour=12, camera="entrada")

    tick = 4000.0
    while tick < 4000.0 + 3600:  # an hour of night, still standing there
        watcher.worth_saying([person()], now=tick, hour=3, camera="entrada")
        tick += 1.5

    dawn = tick
    first = None
    while tick < dawn + 2 * 3600:
        if watcher.worth_saying([person()], now=tick, hour=8, camera="entrada"):
            first = tick - dawn
            break
        tick += 1.5

    assert first is not None
    assert first <= ANTI_SPAM_SECONDS, first  # ~150 s, not ~3600


# ── the tap: packets in our hands before they are decoded ─────────────


class _Packet:
    """A PyAV packet as far as the tap is concerned."""

    def __init__(self, data: bytes, *, keyframe: bool, frames: list) -> None:
        self._data = data
        self.is_keyframe = keyframe
        self._frames = frames

    def __bytes__(self) -> bytes:
        return self._data

    def decode(self):
        return self._frames


class _Frame:
    def to_ndarray(self, format: str):
        assert format == "rgb24"
        return np.zeros((4, 4, 3), dtype=np.uint8)


class _Container:
    def __init__(self, packets):
        self._packets = packets

    def demux(self, video=0):
        return iter(self._packets)

    def close(self):
        pass


def test_the_tap_sees_every_packet_and_its_keyframe_flag():
    seen = []
    stream = CameraStream("rtsp://fake")
    stream._container = _Container(
        [
            _Packet(b"aaa", keyframe=True, frames=[_Frame()]),
            _Packet(b"bbb", keyframe=False, frames=[_Frame()]),
        ]
    )

    def my_tap(data, key):
        seen.append((data, key))

    list(stream.frames(every=1, tap_for=lambda: my_tap))

    assert seen == [(b"aaa", True), (b"bbb", False)]


def test_sampling_still_applies_to_the_frames_yielded():
    # The tap is per PACKET; the sampling is per decoded FRAME. Changing
    # one must not change the other: YOLO's load is calibrated on it.
    stream = CameraStream("rtsp://fake")
    stream._container = _Container(
        [_Packet(b"x", keyframe=True, frames=[_Frame()]) for _ in range(10)]
    )

    yielded = list(stream.frames(every=10, tap_for=None))

    assert len(yielded) == 1


def test_no_tap_costs_nothing_and_still_decodes():
    stream = CameraStream("rtsp://fake")
    stream._container = _Container([_Packet(b"x", keyframe=True, frames=[_Frame()])])
    assert len(list(stream.frames(every=1))) == 1


def test_a_resolver_present_but_finding_no_tap_costs_no_conversion():
    """The regression this pins: `tap_for` being registered (non-`None`)
    must not by itself force `bytes(packet)` to run — only a RESOLVED
    tap may.

    Task 4 fix round 1 handed `frames()` a tap that was never `None` (an
    indirection that read `self._taps` live), which fixed liveness but
    meant `bytes(packet)` ran on every packet, of every camera,
    continuously — whether or not anyone was watching. `cameras.py`
    hands `tap_for` a live resolver on every connection, live view or
    not, so the common case in production is exactly this one: a
    resolver present, resolving to nothing. Proven with a packet whose
    `__bytes__` raises if it is ever called.
    """

    class _ExplodingPacket(_Packet):
        def __bytes__(self) -> bytes:
            raise AssertionError("bytes(packet) must not run with no tap resolved")

    stream = CameraStream("rtsp://fake")
    stream._container = _Container(
        [_ExplodingPacket(b"x", keyframe=True, frames=[_Frame()])]
    )

    assert len(list(stream.frames(every=1, tap_for=lambda: None))) == 1


# ── codec_parameters: empty extradata is legal, not an error ───────────
#
# Many RTSP cameras send SPS/PPS in-band with every keyframe instead of
# in the container's extradata, so `stream.codec_context.extradata` can
# legitimately be `None` (PyAV's own default) or `b""`. Either must come
# back as `b""`, never raise — that is the whole point of the method.


class _CodecContext:
    def __init__(self, extradata, width: int, height: int) -> None:
        self.extradata = extradata
        self.width = width
        self.height = height


class _VideoStream:
    def __init__(self, codec_context: _CodecContext) -> None:
        self.codec_context = codec_context


class _Streams:
    def __init__(self, video_stream: _VideoStream) -> None:
        self.video = [video_stream]


class _CodecContainer:
    """Stands in for `av.open(...)`, just enough for `codec_parameters()`."""

    def __init__(self, extradata, width: int = 704, height: int = 480) -> None:
        self.streams = _Streams(_VideoStream(_CodecContext(extradata, width, height)))

    def close(self):
        pass


def test_codec_parameters_reads_extradata_width_and_height():
    stream = CameraStream("rtsp://fake")
    stream._container = _CodecContainer(b"sps-pps", 704, 480)

    assert stream.codec_parameters() == (b"sps-pps", 704, 480)


def test_codec_parameters_when_extradata_is_none():
    """PyAV's own default for a stream with no out-of-band SPS/PPS."""
    stream = CameraStream("rtsp://fake")
    stream._container = _CodecContainer(None, 704, 480)

    assert stream.codec_parameters() == (b"", 704, 480)


def test_codec_parameters_when_extradata_is_empty_bytes():
    stream = CameraStream("rtsp://fake")
    stream._container = _CodecContainer(b"", 704, 480)

    assert stream.codec_parameters() == (b"", 704, 480)


# ── codec_parameters: never opens a connection ──────────────────────────
#
# `ver_en_vivo`'s handler is async and calls `fleet.codec_parameters(...)`
# directly from the gateway's event loop. `open()` is `av.open(...)`, a
# blocking RTSP call that can take up to the 5 s timeout — reachable here
# would freeze every platform, every turn, for that long. A container
# that is not open yet means the camera is not streaming: the honest
# answer is to say so, not to go make it true.


def test_codec_parameters_does_not_open_a_connection_when_none_is_open():
    stream = CameraStream("rtsp://fake")
    opened: list[bool] = []
    stream.open = lambda: opened.append(True)  # would prove it, if called

    with pytest.raises(RuntimeError):
        stream.codec_parameters()

    assert not opened, "codec_parameters() must not open a connection"
