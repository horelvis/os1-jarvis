"""The EWMH message layout, tested with no X server in sight.

The one that matters is the two-property cap. `_NET_WM_STATE` carries
exactly two atoms per message, in data[1] and data[2]. A third is
dropped SILENTLY — no error, no warning; during the 2026-08-22 spike
SKIP_PAGER simply never applied and it was only caught by reading
`xprop`. A silent drop deserves a loud test.
"""

import pytest

from samantha_widget.ewmh import (
    MAX_PROPS_PER_MESSAGE,
    NET_WM_STATE_ADD,
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
