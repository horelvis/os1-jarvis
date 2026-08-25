"""The live band as pure state: how tall, for whom, and until when.

No GTK in here, on purpose — the same split `photo.py` uses, and the
reason both are testable on a box with no screen.
"""

from samantha_widget.live import LIVE_HEIGHT, LiveModel


def test_it_opens_at_the_large_size_not_as_a_thumbnail():
    model = LiveModel()

    assert model.open("entrada", 7, now=0.0) is True

    assert model.visible is True
    assert model.height == LIVE_HEIGHT
    assert model.camera == "entrada"


def test_frames_from_an_older_view_are_refused():
    model = LiveModel()
    model.open("entrada", 7, now=0.0)

    assert model.accepts(7) is True
    assert model.accepts(6) is False


def test_closing_shrinks_the_band():
    model = LiveModel()
    model.open("entrada", 7, now=0.0)

    assert model.close(7, now=1.0) is True

    assert model.visible is False
    assert model.height == 0


def test_a_close_for_a_view_that_already_ended_changes_nothing():
    model = LiveModel()
    model.open("entrada", 7, now=0.0)
    model.close(7, now=1.0)
    model.open("fuera", 8, now=2.0)

    assert model.close(7, now=3.0) is False
    assert model.visible is True
    assert model.camera == "fuera"


def test_a_second_view_replaces_the_first_without_resizing():
    model = LiveModel()
    model.open("entrada", 7, now=0.0)

    # Same height, so the caller must not spend an EWMH round-trip —
    # the convention `PhotoModel` established.
    assert model.open("fuera", 8, now=1.0) is False
    assert model.camera == "fuera"


def test_closing_with_no_epoch_closes_whatever_is_up():
    # The socket dropped. Spec §4.2: that IS a close, and there is no
    # frame to carry an epoch.
    model = LiveModel()
    model.open("entrada", 7, now=0.0)

    assert model.close(None, now=1.0) is True
    assert model.visible is False
