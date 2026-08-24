"""What she would SAY about what the camera sees.

The model itself is exercised by hand against BarnDoor's recordings —
it needs an 8 MB file and there is no camera on this machine. What is
tested here is the part that decides whether she opens her mouth, and
what comes out when she does.
"""

import pytest

from Hermes.plugins.samantha_vision.vision import (
    WATCHED_CLASSES,
    Detection,
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
    assert watcher.worth_saying([person()], now=1000.0, hour=12)
    assert watcher.worth_saying([person()], now=1010.0, hour=12) == []


def test_the_same_thing_much_later_is_news_again() -> None:
    from Hermes.plugins.samantha_vision.vision import ANTI_SPAM_SECONDS, Watcher

    watcher = Watcher()
    watcher.worth_saying([person()], now=1000.0, hour=12)
    later = 1000.0 + ANTI_SPAM_SECONDS + 1

    assert watcher.worth_saying([person()], now=later, hour=12)


def test_a_different_thing_is_always_news() -> None:
    """Anti-spam is per label: a car arriving while somebody stands
    there is a separate fact."""
    from Hermes.plugins.samantha_vision.vision import Watcher

    watcher = Watcher()
    watcher.worth_saying([person()], now=1000.0, hour=12)
    car = Detection("coche", 0.9, 0.5, 0.5)

    assert watcher.worth_saying([car], now=1001.0, hour=12)


def test_a_person_at_night_beats_the_anti_spam() -> None:
    """The second time somebody is in the garden at 3am is MORE worth
    saying than the first."""
    from Hermes.plugins.samantha_vision.vision import Watcher

    watcher = Watcher()
    watcher.worth_saying([person()], now=1000.0, hour=3)

    assert watcher.worth_saying([person()], now=1010.0, hour=3)


def test_a_car_at_night_does_not_beat_the_anti_spam() -> None:
    """Only people. A car parked in view would otherwise talk all night."""
    from Hermes.plugins.samantha_vision.vision import Watcher

    watcher = Watcher()
    car = Detection("coche", 0.9, 0.5, 0.5)
    watcher.worth_saying([car], now=1000.0, hour=3)

    assert watcher.worth_saying([car], now=1010.0, hour=3) == []


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
