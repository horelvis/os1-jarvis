"""The EWMH message layout, tested with no X server in sight.

The one that matters is the two-property cap. `_NET_WM_STATE` carries
exactly two atoms per message, in data[1] and data[2]. A third is
dropped SILENTLY — no error, no warning; during the 2026-08-22 spike
SKIP_PAGER simply never applied and it was only caught by reading
`xprop`. A silent drop deserves a loud test.
"""

from dataclasses import dataclass, field

import pytest

from jarvis_widget.ewmh import (
    MAX_PROPS_PER_MESSAGE,
    NET_WM_STATE_ADD,
    Ewmh,
    build_state_event,
)


def test_two_atoms_land_in_data_1_and_2() -> None:
    event = build_state_event(root=1, xid=42, atoms=[7, 9], action=NET_WM_STATE_ADD)

    assert event.xclient.window == 42
    assert event.xclient.format == 32
    assert event.xclient.data[0] == NET_WM_STATE_ADD
    assert event.xclient.data[1] == 7
    assert event.xclient.data[2] == 9
    # Source indication: 1 = a normal application. Some window managers
    # treat 0 ("unspecified", the legacy value) as untrusted and ignore
    # the request outright.
    assert event.xclient.data[3] == 1


def test_one_atom_leaves_the_second_slot_empty() -> None:
    event = build_state_event(root=1, xid=42, atoms=[7], action=NET_WM_STATE_ADD)

    assert event.xclient.data[1] == 7
    assert event.xclient.data[2] == 0


def test_three_atoms_are_refused_loudly() -> None:
    """The spike's silent failure, turned into an exception."""
    with pytest.raises(ValueError, match="two"):
        build_state_event(root=1, xid=42, atoms=[7, 9, 11], action=NET_WM_STATE_ADD)


def test_the_cap_is_two() -> None:
    assert MAX_PROPS_PER_MESSAGE == 2


def test_no_atoms_is_refused() -> None:
    with pytest.raises(ValueError):
        build_state_event(root=1, xid=42, atoms=[], action=NET_WM_STATE_ADD)


# ── set_input_region: the XShape mechanism, faked at the ctypes boundary ──
#
# `Ewmh.set_input_region` is the one method in this file that talks to a
# second library, libXext, which is not guaranteed to be present
# (CLAUDE.md §2.3's Cairo trap is the reason it goes through ctypes at
# all rather than `Gdk.Surface.set_input_region`). These fakes stand in
# for both libX11 and libXext so the test runs with no X server and no
# real libXext in sight — the same reason `build_state_event` above is
# tested with no ctypes call made at all.


@dataclass
class _Call:
    name: str
    rects: list[tuple[int, int, int, int]] | None = None


class _FakeLibX11:
    """Only `XFlush` is reached through this from `set_input_region`."""

    def XFlush(self, display: object) -> None:
        del display


class _FakeLibXext:
    """Records XShape calls, decoding the rectangle array back to plain
    tuples so a test can assert on it without touching ctypes itself."""

    def __init__(self) -> None:
        self.calls: list[_Call] = []

    def XShapeCombineRectangles(
        self,
        display: object,
        xid: object,
        dest_kind: object,
        x_off: object,
        y_off: object,
        rect_array: object,
        n_rects: object,
        op: object,
        ordering: object,
    ) -> None:
        del display, xid, dest_kind, x_off, y_off, n_rects, op, ordering
        rects = [(r.x, r.y, r.width, r.height) for r in rect_array]
        self.calls.append(_Call(name="XShapeCombineRectangles", rects=rects))

    def XShapeCombineMask(
        self,
        display: object,
        xid: object,
        dest_kind: object,
        x_off: object,
        y_off: object,
        src: object,
        op: object,
    ) -> None:
        del display, xid, dest_kind, x_off, y_off, src, op
        self.calls.append(_Call(name="XShapeCombineMask"))


@dataclass
class _FakeX:
    libx11: _FakeLibX11 = field(default_factory=_FakeLibX11)
    libxext: _FakeLibXext = field(default_factory=_FakeLibXext)


@pytest.fixture
def fake_x() -> _FakeX:
    return _FakeX()


def test_set_input_region_sends_the_rectangles_it_was_given(fake_x: _FakeX) -> None:
    ewmh = Ewmh(xid=0x1234, x11=fake_x.libx11, xext=fake_x.libxext)

    assert ewmh.set_input_region([(0, 0, 900, 384)]) is True

    call = fake_x.libxext.calls[-1]
    assert call.name == "XShapeCombineRectangles"
    assert call.rects == [(0, 0, 900, 384)]


def test_set_input_region_sends_every_rectangle_given(fake_x: _FakeX) -> None:
    ewmh = Ewmh(xid=0x1234, x11=fake_x.libx11, xext=fake_x.libxext)

    assert ewmh.set_input_region([(10, 20, 654, 368), (0, 384, 900, 96)]) is True

    call = fake_x.libxext.calls[-1]
    assert call.rects == [(10, 20, 654, 368), (0, 384, 900, 96)]


def test_an_empty_region_restores_the_whole_window(fake_x: _FakeX) -> None:
    ewmh = Ewmh(xid=0x1234, x11=fake_x.libx11, xext=fake_x.libxext)

    assert ewmh.set_input_region([]) is True

    assert fake_x.libxext.calls[-1].name == "XShapeCombineMask"


def test_a_missing_xext_is_false_not_a_crash() -> None:
    # libXext is not guaranteed anywhere. Losing the input region costs
    # clicks; raising costs the strip.
    ewmh = Ewmh(xid=0x1234, x11=object(), xext=None)
    assert ewmh.set_input_region([(0, 0, 10, 10)]) is False


def test_a_missing_xid_is_false_not_a_crash(fake_x: _FakeX) -> None:
    ewmh = Ewmh(x11=fake_x.libx11, xext=fake_x.libxext)  # no xid given
    assert ewmh.set_input_region([(0, 0, 10, 10)]) is False
    assert fake_x.libxext.calls == []
