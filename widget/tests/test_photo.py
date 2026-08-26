"""The photo band, as pure state.

No `gi` anywhere in here or in the module it exercises — that is the
whole point of splitting `photo.py` (the state) from `photo_area.py`
(the GTK widget), the same split `wave_model.py` / `wave.py` already
makes.
"""

from samantha_widget.photo import (
    MAX_PHOTOS,
    NATIVE,
    PAD,
    THUMB,
    hits,
    PhotoModel,
    tile_rects,
)


def test_it_starts_hidden():
    m = PhotoModel()
    assert not m.visible and m.height == 0


def test_one_camera_is_shown_at_the_default_camera_size():
    # A camera asked for by name arrives alone, and a camera the user
    # asked to see is shown at the size a camera is worth looking at —
    # the one a click used to be needed for (user, 2026-08-26).
    m = PhotoModel()
    assert m.show("/tmp/a.jpg", "entrada", now=0.0) is True
    assert m.visible and m.height == NATIVE


def test_it_fades_on_its_own():
    m = PhotoModel()
    m.show("/tmp/a.jpg", "entrada", now=0.0)
    assert m.tick(now=14.0) is False
    assert m.tick(now=16.0) is True
    assert not m.visible and m.height == 0


def test_a_click_on_a_row_makes_it_native_and_resets_the_clock():
    # Two or more still start small — four at 480 do not fit — so the
    # click that enlarges them is still there for a row.
    m = PhotoModel()
    m.show("/tmp/a.jpg", "entrada", now=0.0)
    m.show("/tmp/b.jpg", "fuera", now=0.05)
    assert m.height == THUMB
    assert m.click(now=10.0) is True
    assert m.height == NATIVE
    assert m.tick(now=20.0) is False  # the clock restarted at 10.0


def test_a_second_click_on_a_row_dismisses_it():
    m = PhotoModel()
    m.show("/tmp/a.jpg", "entrada", now=0.0)
    m.show("/tmp/b.jpg", "fuera", now=0.05)
    m.click(now=1.0)
    assert m.click(now=2.0) is True
    assert not m.visible


def test_one_camera_needs_only_one_click_to_go_away():
    # It arrives at the size the click used to give, so there is nothing
    # left for a first click to do but put it away.
    m = PhotoModel()
    m.show("/tmp/a.jpg", "entrada", now=0.0)
    assert m.click(now=1.0) is True
    assert not m.visible


def test_a_second_photo_makes_the_band_a_row_again():
    # Asking with no camera named looks at all of them (spec §4.3), so two
    # frames arrive milliseconds apart. Replacing would mean you only ever
    # see the last camera. Spec §5. The first of them was shown at the
    # camera size; the second turns the band back into a row, because
    # four at 480 do not fit in 900.
    m = PhotoModel()
    m.show("/tmp/a.jpg", "entrada", now=0.0)
    assert m.show("/tmp/b.jpg", "fuera", now=0.05) is True  # native -> thumb
    assert [p.path for p in m.photos] == ["/tmp/a.jpg", "/tmp/b.jpg"]
    assert m.height == THUMB


def test_a_photo_after_the_batch_starts_a_new_one():
    # A separate question, not the second half of the same one.
    m = PhotoModel()
    m.show("/tmp/a.jpg", "entrada", now=0.0)
    m.show("/tmp/b.jpg", "fuera", now=30.0)
    assert [p.path for p in m.photos] == ["/tmp/b.jpg"]


def test_a_fifth_photo_pushes_the_first_out():
    # Four at 174 px already fill most of 900. A fifth makes them
    # unreadable rather than informative, so the row is capped and the
    # strip does not grow wider.
    m = PhotoModel()
    for i in range(5):
        m.show(f"/tmp/{i}.jpg", "entrada", now=i * 0.1)
    assert len(m.photos) == MAX_PHOTOS
    assert [p.path for p in m.photos] == [f"/tmp/{i}.jpg" for i in range(1, 5)]


def test_a_new_batch_of_several_shrinks_an_enlarged_one_back_down():
    m = PhotoModel()
    m.show("/tmp/a.jpg", "entrada", now=0.0)
    m.show("/tmp/b.jpg", "fuera", now=0.05)
    m.click(now=1.0)
    assert m.height == NATIVE
    assert m.show("/tmp/c.jpg", "fuera", now=30.0) is False  # one, still native
    m.show("/tmp/d.jpg", "entrada", now=30.05)
    assert m.height == THUMB


def test_a_click_on_nothing_does_nothing():
    m = PhotoModel()
    assert m.click(now=1.0) is False
    assert not m.visible


def test_ticking_a_hidden_band_never_asks_for_a_resize():
    m = PhotoModel()
    m.show("/tmp/a.jpg", "entrada", now=0.0)
    assert m.tick(now=16.0) is True
    assert m.tick(now=17.0) is False
    assert m.tick(now=1000.0) is False


def test_the_second_photo_of_a_batch_does_not_restart_the_fade():
    # Otherwise a camera that keeps answering keeps the band alive.
    m = PhotoModel()
    m.show("/tmp/a.jpg", "entrada", now=0.0)
    m.show("/tmp/b.jpg", "fuera", now=1.0)
    assert m.tick(now=15.5) is True


# ── the layout ────────────────────────────────────────────────────────


def test_one_thumbnail_is_as_tall_as_the_band_allows():
    (x, y, w, h) = tile_rects(900, THUMB, 1)[0]
    assert h == THUMB - 2 * PAD
    assert abs(w / h - 16 / 9) < 0.01
    assert x > 0 and y == PAD


def test_four_thumbnails_fit_inside_900():
    rects = tile_rects(900, THUMB, 4)
    assert len(rects) == 4
    assert rects[0][0] >= 0
    right = rects[-1][0] + rects[-1][2]
    assert right <= 900


def test_two_enlarged_photos_are_the_widest_pair_that_fits():
    rects = tile_rects(900, NATIVE, 2)
    right = rects[-1][0] + rects[-1][2]
    assert right <= 900
    # Wider than a thumbnail, narrower than one photo on its own.
    alone = tile_rects(900, NATIVE, 1)[0][2]
    assert tile_rects(900, THUMB, 2)[0][2] < rects[0][2] < alone


def test_no_photos_no_rectangles():
    assert tile_rects(900, THUMB, 0) == []


def test_the_model_never_imports_gtk():
    """`import gi` here would make the strip's state untestable headless.

    Not a style rule: `wave_model.py` and `bars_model.py` keep the same
    line, and it is the reason any of this can be exercised at all.
    """
    import pathlib

    import samantha_widget.photo as module

    source = pathlib.Path(module.__file__).read_text(encoding="utf-8")
    assert "import gi" not in source
    assert "gi.repository" not in source


def test_only_the_picture_answers_a_press():
    rects = tile_rects(900, THUMB, 1)
    x, y, w, h = rects[0]
    assert hits(x + w / 2, y + h / 2, rects) is True
    assert hits(x - 20, y + h / 2, rects) is False  # transparent air beside it
    assert hits(x + w / 2, 2, rects) is False  # above it, still inside the band
    assert hits(x + w, y + h / 2, rects) is False  # just off the right edge


def test_a_press_with_nothing_on_the_band_hits_nothing():
    assert hits(450, 50, tile_rects(900, THUMB, 0)) is False
