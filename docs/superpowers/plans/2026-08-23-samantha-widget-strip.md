# samantha-widget (plan 1) — the strip on the screen

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A borderless terracotta strip floating above everything at the
bottom of the screen, with Samantha's wave animating through her four
states, started by systemd at login.

**Architecture:** One GTK4 application window, decoration off, placed and
kept above by EWMH `ClientMessage`s sent over `ctypes`/`libX11` — GTK4
has no API for either. The wave is a `Gtk.DrawingArea` drawn with Cairo
on the compositor's frame clock. Every piece that can be tested without
a display lives in a module that does not import `gi`.

**Tech Stack:** Python 3.12, PyGObject 3.48 / GTK 4.14 (system packages,
reached through a `--system-site-packages` venv), Cairo, `ctypes`,
pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-08-23-samantha-widget-gtk4-design.md`
(§3 the window, §4 the wave, §6 structure, §7 build order). Read §1 for
why any of this exists.

## Global Constraints

- **X11 only.** The session is X11 on `DISPLAY=:1`. Wayland is out of
  scope (spec §8) — `gtk4-layer-shell` is Wayland-only and is not used.
- **No new runtime dependency beyond PyGObject.** EWMH goes through
  `ctypes` against `libX11.so.6`. `python-xlib`, `wmctrl` and `xdotool`
  are not installed on this box and must not become requirements.
- **`_NET_WM_STATE` carries at most TWO properties per message**
  (`data[1]`, `data[2]`). A third is dropped silently. Send them in
  pairs.
- **The venv must be created with `--system-site-packages`**, because
  `python3-gi` and `gir1.2-gtk-4.0` live in the system Python.
  `backend/.venv` is not such a venv and must not be reused.
- **Colour is exactly `#d1684e`** (CLAUDE.md §10). One colour, one wave.
- **No module that is unit-tested may import `gi`.** `geometry.py`,
  `wave_model.py` and `ewmh.py` are import-clean; `window.py`,
  `wave.py` and `__main__.py` are not and are verified by screenshot.
- **Every visual claim is verified with a screenshot**, captured with
  `ffmpeg -f x11grab -video_size 1920x1080 -i :1 -frames:v 1 out.png`
  and then actually looked at. A visual claim with no screenshot is
  not verified.
- Identifiers and comments in **English**; any user-facing string in
  **Spanish** (CLAUDE.md §2.9). This plan has almost no user-facing
  strings — that is deliberate.
- `ruff check` and `ruff format` pass before every commit.
- **New top-level directory `widget/`** — needs the user's approval
  under CLAUDE.md §3 before Task 1. The precedent is `Hermes/`,
  approved the same way on 2026-08-22.
- **Nothing in this plan removes anything.** The Chromium kiosk still
  exists and still works throughout; `systemctl --user start
  samantha-ui.service` is the fallback at every point.

## What has already been run

Written 2026-08-23. The display-free code in this plan was extracted and
executed against its own tests before the plan was committed:
`geometry.py` (4 tests), `ewmh.py`'s `build_state_event` (5) and
`wave_model.py` (8) — **17 passed**. The numbers in `_IDLE_GAIN` and
friends are therefore known to satisfy the assertions, not guessed at.

Everything touching GTK, X11 or the frame clock — `window.py`,
`wave.py`, `__main__.py` — has **not** been run. It is checked by
screenshot, and the screenshot steps are where this plan can still
surprise you.

---

## File Structure

| File | Responsibility |
|---|---|
| `widget/pyproject.toml` | Package metadata, pytest + ruff config. |
| `widget/README.md` | How to create the venv and run it. |
| `widget/samantha_widget/__init__.py` | Version marker only. |
| `widget/samantha_widget/theme.py` | The colour, the CSS, the geometry constants. No logic. |
| `widget/samantha_widget/geometry.py` | Pure: monitor rectangle → strip rectangle. No `gi`. |
| `widget/samantha_widget/ewmh.py` | Pure-ish: builds and sends `_NET_WM_STATE` messages and `XMoveResizeWindow`, over `ctypes`. No `gi`. |
| `widget/samantha_widget/wave_model.py` | Pure: (state, level, time) → the polyline. No `gi`. |
| `widget/samantha_widget/wave.py` | `Gtk.DrawingArea` subclass; Cairo drawing + tick callback. |
| `widget/samantha_widget/window.py` | The `Gtk.ApplicationWindow`: CSS, decoration off, EWMH on map. |
| `widget/samantha_widget/__main__.py` | `Gtk.Application`, the demo keybindings, entry point. |
| `widget/tests/` | pytest, no display, no audio. |
| `systemd/samantha-widget.service` | Starts it in the graphical session. |

---

## Task 1: The package, the venv, and a window that opens

**Files:**
- Create: `widget/pyproject.toml`
- Create: `widget/README.md`
- Create: `widget/samantha_widget/__init__.py`
- Create: `widget/samantha_widget/__main__.py`
- Create: `widget/tests/__init__.py`
- Create: `widget/tests/test_imports.py`

**Interfaces:**
- Consumes: nothing.
- Produces: the `samantha_widget` package, importable from
  `widget/.venv`; `python -m samantha_widget` opens a window.

- [ ] **Step 1: Confirm the top-level directory is approved**

Do not create `widget/` until the user has said yes (Global
Constraints). If this plan is being executed, that approval has
presumably been given — confirm it in one line and move on.

- [ ] **Step 2: Create the venv with system site packages**

```bash
cd widget
python3 -m venv --system-site-packages .venv
.venv/bin/pip install --upgrade pip
```

The flag is the whole point: without it `import gi` fails and nothing
in this plan can run.

- [ ] **Step 3: Write the failing test**

```python
# widget/tests/test_imports.py
"""The one thing that cannot be assumed: GTK4 reachable from this venv.

python3-gi and gir1.2-gtk-4.0 are system packages. A venv created
without --system-site-packages cannot see them, and every other test in
this suite would fail with the same confusing ImportError. This test
fails first and points at the cause.
"""


def test_gtk4_is_importable() -> None:
    import gi

    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk

    assert Gtk.get_major_version() == 4


def test_gdkx11_is_importable() -> None:
    """Needed to get the X11 window id the EWMH module addresses."""
    import gi

    gi.require_version("GdkX11", "4.0")
    from gi.repository import GdkX11  # noqa: F401
```

- [ ] **Step 4: Run it and watch it fail for the right reason**

Run: `cd widget && .venv/bin/python -m pytest tests/test_imports.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pytest'` first.
Install and re-run:

```bash
.venv/bin/pip install pytest ruff
```

Expected then: PASS. If it fails with `No module named 'gi'`, the venv
was created without `--system-site-packages`; delete it and redo Step 2.

**The flag has a second effect, measured while executing this step:**
pip treats a system-wide package as already satisfying a requirement, so
`pip install pytest` can be a silent no-op that leaves the venv depending
on the system's copy — and a system upgrade then changes the test runner
underneath the project. Check with `.venv/bin/pip list --local` (which
lists only what the venv itself holds) and force anything that must be
pinned here:

```bash
.venv/bin/pip install --ignore-installed pytest
```

That prints a dependency-conflict warning about whatever system package
wanted an older `packaging`. It is unrelated to this project and is only
visible because of `--system-site-packages`.

- [ ] **Step 5: Write `pyproject.toml`**

```toml
[project]
name = "samantha-widget"
version = "0.1.0"
description = "Samantha as a floating desktop strip (GTK4/X11)"
requires-python = ">=3.12"
# PyGObject is deliberately NOT listed: it comes from the system
# packages python3-gi + gir1.2-gtk-4.0, reached through a venv created
# with --system-site-packages. Listing it here would make pip try to
# build it from source against GObject headers.
dependencies = []

[project.optional-dependencies]
dev = ["pytest>=8", "ruff>=0.6"]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
include = ["samantha_widget*"]

[tool.ruff]
line-length = 88

[tool.ruff.lint]
# E402 is off in ruff's default set, and every GTK module here needs it:
# gi.require_version() has to run BEFORE the import it guards, so the
# imports cannot be at the top of the file. Enabling the rule is what
# makes the `# noqa: E402` on those lines honest — with the rule off,
# ruff flags the noqa itself as unused (RUF100) and the file fails lint
# for suppressing a warning it was right to suppress.
select = ["E4", "E7", "E9", "E402", "F", "RUF"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 6: Write the package init and a window that opens**

```python
# widget/samantha_widget/__init__.py
"""Samantha as a floating desktop strip."""

__version__ = "0.1.0"
```

```python
# widget/samantha_widget/__main__.py
"""Entry point: python -m samantha_widget."""

import sys

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import Gtk  # noqa: E402


class SamanthaApp(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id="com.horelvis.samantha.widget")

    def do_activate(self) -> None:
        window = Gtk.ApplicationWindow(application=self)
        window.set_default_size(600, 96)
        window.present()


def main() -> int:
    return SamanthaApp().run(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 7: See it**

```bash
DISPLAY=:1 .venv/bin/python -m samantha_widget &
sleep 2
ffmpeg -y -f x11grab -video_size 1920x1080 -i :1 -frames:v 1 /tmp/step7.png
```

Look at `/tmp/step7.png`. Expected: an ordinary decorated window,
somewhere on screen. It is supposed to look wrong — the next three
tasks are what make it a strip. Kill it afterwards.

- [ ] **Step 8: Write the README**

```markdown
# samantha-widget

Samantha as a floating strip at the bottom of the screen. GTK4 on X11.

## Setup

    python3 -m venv --system-site-packages .venv
    .venv/bin/pip install -e ".[dev]"

`--system-site-packages` is required: PyGObject and the GTK4 typelib
come from the system (`python3-gi`, `gir1.2-gtk-4.0`), not from pip.

## Run

    DISPLAY=:1 .venv/bin/python -m samantha_widget

## Test

    .venv/bin/python -m pytest -v
    .venv/bin/ruff check . && .venv/bin/ruff format --check .
```

- [ ] **Step 9: Commit**

```bash
cd .. && git add widget/ && git commit -m "feat(widget): a GTK4 package and a window that opens"
```

---

## Task 2: EWMH — always above, and placed to the pixel

**Files:**
- Create: `widget/samantha_widget/ewmh.py`
- Create: `widget/tests/test_ewmh.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `class Ewmh` with `__init__(self, display_name: str | None = None)`,
    `add_state(self, xid: int, *names: str) -> None`,
    `move_resize(self, xid: int, x: int, y: int, w: int, h: int) -> None`,
    `flush(self) -> None`.
  - `build_state_event(root: int, xid: int, atoms: list[int], action: int) -> XEvent`
    — pure, and what the tests actually exercise.
  - `MAX_PROPS_PER_MESSAGE = 2`.

- [ ] **Step 1: Write the failing tests**

```python
# widget/tests/test_ewmh.py
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
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd widget && .venv/bin/python -m pytest tests/test_ewmh.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'samantha_widget.ewmh'`.

- [ ] **Step 3: Write `ewmh.py`**

```python
# widget/samantha_widget/ewmh.py
"""Always-above and pixel placement, via EWMH over ctypes/libX11.

GTK4 removed the APIs that would make this a two-line file: there is no
`set_keep_above`, no `move`, no `set_position` and no `get_position` on
a GTK4 window — verified with `hasattr` against a real one during the
2026-08-22 spike. The modern replacement, gtk4-layer-shell, is
Wayland-only and this box runs X11.

So the window manager is asked directly, the way every panel and dock
does it: a `_NET_WM_STATE` ClientMessage sent to the root window, plus
an `XMoveResizeWindow` for the geometry. ctypes against libX11 is
enough; python-xlib, wmctrl and xdotool are not installed here and none
of them is needed for ~50 lines of this.
"""

from __future__ import annotations

import ctypes
import ctypes.util

# _NET_WM_STATE actions (EWMH 1.5, §7.5)
NET_WM_STATE_REMOVE = 0
NET_WM_STATE_ADD = 1
NET_WM_STATE_TOGGLE = 2

# data[1] and data[2]. There is no data[5] for a third atom: the message
# is five longs and the rest are spoken for.
MAX_PROPS_PER_MESSAGE = 2

# Event masks the root window needs for the WM to act on the message.
_SUBSTRUCTURE_NOTIFY = 1 << 19
_SUBSTRUCTURE_REDIRECT = 1 << 20

_CLIENT_MESSAGE = 33


class _XClientMessageEvent(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_int),
        ("serial", ctypes.c_ulong),
        ("send_event", ctypes.c_int),
        ("display", ctypes.c_void_p),
        ("window", ctypes.c_ulong),
        ("message_type", ctypes.c_ulong),
        ("format", ctypes.c_int),
        ("data", ctypes.c_long * 5),
    ]


class XEvent(ctypes.Union):
    """XEvent is a union sized by its largest member.

    The padding member is not decoration: XSendEvent reads a full XEvent
    (24 longs) regardless of which member was filled in, and a structure
    that is merely large enough for a ClientMessage would have it read
    past the end of our allocation.
    """

    _fields_ = [
        ("type", ctypes.c_int),
        ("xclient", _XClientMessageEvent),
        ("pad", ctypes.c_long * 24),
    ]


def build_state_event(
    root: int, xid: int, atoms: list[int], action: int
) -> XEvent:
    """Build one `_NET_WM_STATE` ClientMessage.

    `atoms` must hold one or two atoms. Three is a ValueError rather than
    a silent drop — see the module docstring of the tests.
    """
    if not atoms:
        raise ValueError("a _NET_WM_STATE message with no atoms does nothing")
    if len(atoms) > MAX_PROPS_PER_MESSAGE:
        raise ValueError(
            f"_NET_WM_STATE carries two properties per message, got "
            f"{len(atoms)} — send them in pairs. A third atom is dropped "
            f"silently by the window manager."
        )

    event = XEvent()
    event.type = _CLIENT_MESSAGE
    event.xclient.type = _CLIENT_MESSAGE
    event.xclient.send_event = True
    event.xclient.window = xid
    event.xclient.format = 32
    event.xclient.data[0] = action
    event.xclient.data[1] = atoms[0]
    event.xclient.data[2] = atoms[1] if len(atoms) > 1 else 0
    event.xclient.data[3] = 1  # source indication: a normal application
    event.xclient.data[4] = 0
    del root  # addressed at send time, not build time; kept for symmetry
    return event


class Ewmh:
    """A thin, live connection to the X server for the two things GTK4 lost."""

    def __init__(self, display_name: str | None = None) -> None:
        path = ctypes.util.find_library("X11") or "libX11.so.6"
        self._x11 = ctypes.CDLL(path)
        self._x11.XOpenDisplay.restype = ctypes.c_void_p
        self._x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
        self._x11.XInternAtom.restype = ctypes.c_ulong
        self._x11.XInternAtom.argtypes = [
            ctypes.c_void_p,
            ctypes.c_char_p,
            ctypes.c_int,
        ]
        self._x11.XDefaultRootWindow.restype = ctypes.c_ulong
        self._x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]

        name = display_name.encode() if display_name else None
        self._display = self._x11.XOpenDisplay(name)
        if not self._display:
            raise RuntimeError(f"cannot open X display {display_name or '$DISPLAY'}")
        self._root = self._x11.XDefaultRootWindow(self._display)
        self._atoms: dict[str, int] = {}

    def atom(self, name: str) -> int:
        if name not in self._atoms:
            self._atoms[name] = self._x11.XInternAtom(
                self._display, name.encode(), False
            )
        return self._atoms[name]

    def add_state(self, xid: int, *names: str) -> None:
        """Add up to two `_NET_WM_STATE` properties, in one message."""
        event = build_state_event(
            root=self._root,
            xid=xid,
            atoms=[self.atom(n) for n in names],
            action=NET_WM_STATE_ADD,
        )
        event.xclient.display = self._display
        event.xclient.message_type = self.atom("_NET_WM_STATE")
        self._x11.XSendEvent(
            ctypes.c_void_p(self._display),
            ctypes.c_ulong(self._root),
            ctypes.c_int(False),
            ctypes.c_long(_SUBSTRUCTURE_REDIRECT | _SUBSTRUCTURE_NOTIFY),
            ctypes.byref(event),
        )

    def move_resize(self, xid: int, x: int, y: int, w: int, h: int) -> None:
        self._x11.XMoveResizeWindow(
            ctypes.c_void_p(self._display),
            ctypes.c_ulong(xid),
            ctypes.c_int(x),
            ctypes.c_int(y),
            ctypes.c_uint(w),
            ctypes.c_uint(h),
        )

    def flush(self) -> None:
        self._x11.XFlush(ctypes.c_void_p(self._display))
```

- [ ] **Step 4: Run the tests**

Run: `cd widget && .venv/bin/python -m pytest tests/test_ewmh.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
cd .. && git add widget/ && git commit -m "feat(widget): EWMH over ctypes, with the two-atom cap made loud"
```

---

## Task 3: Geometry — where the strip goes

**Files:**
- Create: `widget/samantha_widget/theme.py`
- Create: `widget/samantha_widget/geometry.py`
- Create: `widget/tests/test_geometry.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `theme.TERRACOTTA = "#d1684e"`, `theme.STRIP_HEIGHT = 96`,
    `theme.STRIP_MAX_WIDTH = 1100`, `theme.SIDE_MARGIN = 48`,
    `theme.BOTTOM_MARGIN = 48`, `theme.CSS: str`.
  - `geometry.strip_rect(monitor_x, monitor_y, monitor_w, monitor_h) -> tuple[int, int, int, int]`
    returning `(x, y, width, height)` in root-window coordinates.

- [ ] **Step 1: Write the failing tests**

```python
# widget/tests/test_geometry.py
"""Where the strip sits. Pure arithmetic, so it is worth pinning exactly.

Monitor coordinates are root-window coordinates: on a multi-head setup
the second monitor's origin is not (0, 0), and a strip that ignores that
lands on the wrong screen. That is the only multi-monitor behaviour this
plan promises (spec §8 puts placement rules out of scope).
"""

from samantha_widget import theme
from samantha_widget.geometry import strip_rect


def test_centred_on_a_1080p_screen() -> None:
    x, y, w, h = strip_rect(0, 0, 1920, 1080)

    assert w == theme.STRIP_MAX_WIDTH  # 1100 fits in 1920 - 2*48
    assert h == theme.STRIP_HEIGHT
    assert x == (1920 - 1100) // 2
    assert y == 1080 - theme.STRIP_HEIGHT - theme.BOTTOM_MARGIN


def test_narrow_screen_clamps_to_the_side_margins() -> None:
    x, y, w, h = strip_rect(0, 0, 1000, 700)

    assert w == 1000 - 2 * theme.SIDE_MARGIN
    assert x == theme.SIDE_MARGIN
    del y, h


def test_monitor_origin_is_respected() -> None:
    """A second monitor to the right of the first."""
    x, y, _w, _h = strip_rect(1920, 0, 1920, 1080)

    assert x == 1920 + (1920 - theme.STRIP_MAX_WIDTH) // 2
    assert y == 1080 - theme.STRIP_HEIGHT - theme.BOTTOM_MARGIN


def test_absurdly_small_screen_still_produces_a_positive_size() -> None:
    """A VM at 640x480 must not produce a negative width."""
    _x, _y, w, h = strip_rect(0, 0, 640, 480)

    assert w > 0
    assert h > 0
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd widget && .venv/bin/python -m pytest tests/test_geometry.py -v`
Expected: FAIL — no module `samantha_widget.geometry`.

- [ ] **Step 3: Write `theme.py`**

```python
# widget/samantha_widget/theme.py
"""The one colour, the geometry constants, and the CSS.

These are the numbers that get tuned by eye against a screenshot, so
they live together in one block rather than scattered through the
window code.
"""

from __future__ import annotations

# The exact background colour from the film (CLAUDE.md §10).
TERRACOTTA = "#d1684e"
# The wave, drawn on it. A single warm off-white; no second hue.
LINE = "#f6ece7"

STRIP_HEIGHT = 96
STRIP_MAX_WIDTH = 1100
SIDE_MARGIN = 48
BOTTOM_MARGIN = 48
CORNER_RADIUS = 18

# GTK4 paints a shadow around the window even with decoration off — in a
# screenshot it reads as a grey halo, and a halo is what makes a thing
# look like a window instead of an object. Both the `decoration` node and
# the window node are cleared because which one carries the shadow
# depends on whether the compositor gave us client-side decorations.
CSS = f"""
window,
window.csd,
window.solid-csd {{
  background: transparent;
  box-shadow: none;
  border: none;
}}

window decoration {{
  box-shadow: none;
  border: none;
  margin: 0;
  background: transparent;
}}

.samantha-strip {{
  background-color: {TERRACOTTA};
  border-radius: {CORNER_RADIUS}px;
}}
"""
```

- [ ] **Step 4: Write `geometry.py`**

```python
# widget/samantha_widget/geometry.py
"""Monitor rectangle in, strip rectangle out. No GTK, no X, no state."""

from __future__ import annotations

from . import theme


def strip_rect(
    monitor_x: int, monitor_y: int, monitor_w: int, monitor_h: int
) -> tuple[int, int, int, int]:
    """Where the strip goes, in root-window coordinates.

    Returns (x, y, width, height). The monitor origin is added back in so
    that a second monitor gets the strip on itself rather than on the
    first one.
    """
    available = monitor_w - 2 * theme.SIDE_MARGIN
    width = min(theme.STRIP_MAX_WIDTH, available)
    # A tiny screen must not produce a zero or negative width; below this
    # the strip stops obeying the margins rather than disappearing.
    width = max(width, 240)
    height = theme.STRIP_HEIGHT

    x = monitor_x + (monitor_w - width) // 2
    y = monitor_y + monitor_h - height - theme.BOTTOM_MARGIN
    return x, y, width, height
```

- [ ] **Step 5: Run the tests**

Run: `cd widget && .venv/bin/python -m pytest tests/test_geometry.py -v`
Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
cd .. && git add widget/ && git commit -m "feat(widget): the strip's geometry and the one colour"
```

---

## Task 4: The window — borderless, terracotta, above, placed

**Files:**
- Create: `widget/samantha_widget/window.py`
- Modify: `widget/samantha_widget/__main__.py` (use it)

**Interfaces:**
- Consumes: `theme.CSS`, `theme.TERRACOTTA`, `geometry.strip_rect`,
  `ewmh.Ewmh`.
- Produces: `class StripWindow(Gtk.ApplicationWindow)` with
  `__init__(self, app: Gtk.Application)` and
  `set_content(self, widget: Gtk.Widget) -> None`.

- [ ] **Step 1: Write `window.py`**

There is no unit test here — every claim it makes is visual, and Step 3
is how they are checked.

```python
# widget/samantha_widget/window.py
"""The strip itself: a GTK4 window that tries hard not to look like one."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("GdkX11", "4.0")

from gi.repository import Gdk, GdkX11, Gtk  # noqa: E402

from . import theme  # noqa: E402
from .ewmh import Ewmh  # noqa: E402
from .geometry import strip_rect  # noqa: E402


class StripWindow(Gtk.ApplicationWindow):
    def __init__(self, app: Gtk.Application) -> None:
        super().__init__(application=app)

        self.set_decorated(False)
        self.set_resizable(False)
        # Out of the alt-tab list and off the taskbar: this is furniture,
        # not an application the user switches to.
        self.set_title("Samantha")

        self._ewmh: Ewmh | None = None

        self._frame = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self._frame.add_css_class("samantha-strip")
        self._frame.set_hexpand(True)
        self._frame.set_vexpand(True)
        self.set_child(self._frame)

        self._install_css()

        # The X11 window id does not exist until the window is realized,
        # so every EWMH call has to wait for the map. Doing it in
        # __init__ silently does nothing: xid is 0 and the WM never hears
        # about it.
        self.connect("map", self._on_map)

    def set_content(self, widget: Gtk.Widget) -> None:
        child = self._frame.get_first_child()
        if child is not None:
            self._frame.remove(child)
        widget.set_hexpand(True)
        widget.set_vexpand(True)
        self._frame.append(widget)

    def _install_css(self) -> None:
        provider = Gtk.CssProvider()
        provider.load_from_data(theme.CSS.encode("utf-8"), -1)
        display = Gdk.Display.get_default()
        Gtk.StyleContext.add_provider_for_display(
            display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def _on_map(self, _widget: Gtk.Widget) -> None:
        surface = self.get_surface()
        if not isinstance(surface, GdkX11.X11Surface):
            # Wayland. Out of scope (spec §8): the strip will still draw,
            # it just will not be placed or kept above.
            return

        xid = surface.get_xid()
        monitor = Gdk.Display.get_default().get_monitor_at_surface(surface)
        rect = monitor.get_geometry()
        x, y, w, h = strip_rect(rect.x, rect.y, rect.width, rect.height)

        self.set_default_size(w, h)

        self._ewmh = Ewmh()
        # Two at a time. A third atom in one message is dropped silently
        # — that is the whole reason ewmh.py refuses more than two.
        self._ewmh.add_state(xid, "_NET_WM_STATE_ABOVE", "_NET_WM_STATE_SKIP_TASKBAR")
        self._ewmh.add_state(xid, "_NET_WM_STATE_SKIP_PAGER", "_NET_WM_STATE_STICKY")
        self._ewmh.move_resize(xid, x, y, w, h)
        self._ewmh.flush()
```

- [ ] **Step 2: Use it from `__main__.py`**

Replace the body of `do_activate`:

```python
    def do_activate(self) -> None:
        from .window import StripWindow

        window = StripWindow(self)
        window.present()
```

- [ ] **Step 3: Look at it**

```bash
cd widget
DISPLAY=:1 .venv/bin/python -m samantha_widget &
sleep 2
ffmpeg -y -f x11grab -video_size 1920x1080 -i :1 -frames:v 1 /tmp/strip.png
```

Open `/tmp/strip.png` and check all four, one by one:
1. A terracotta strip at the bottom, centred, rounded corners.
2. No title bar, no border.
3. **No grey halo around it.** If there is one, the CSS did not take —
   add `window { background: none; }` and look again.
4. It is above other windows (open something first to be sure).

- [ ] **Step 4: Confirm the states actually applied**

```bash
DISPLAY=:1 xprop -name Samantha _NET_WM_STATE
```

Expected: `_NET_WM_STATE(ATOM) = _NET_WM_STATE_ABOVE,
_NET_WM_STATE_SKIP_TASKBAR, _NET_WM_STATE_SKIP_PAGER, _NET_WM_STATE_STICKY`

All four must be there. A missing one means a message was dropped —
the spike's exact failure. Check they were sent two at a time.

- [ ] **Step 5: Confirm it survives a workspace switch**

Switch workspaces and back, then re-capture. The strip must still be
there, still on top, still in the same place (that is what `STICKY`
buys). If it moved, re-assert on `notify::monitor` too.

- [ ] **Step 6: Commit**

```bash
cd .. && git add widget/ && git commit -m "feat(widget): a strip that does not look like a window"
```

---

## Task 5: The wave model — pure, testable, no GTK

**Files:**
- Create: `widget/samantha_widget/wave_model.py`
- Create: `widget/tests/test_wave_model.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `class WaveState(str, Enum)` with `IDLE`, `LISTENING`, `THINKING`,
    `SPEAKING`.
  - `class WaveModel` with `state: WaveState`,
    `set_level(self, level: float) -> None`,
    `advance(self, dt: float) -> None`,
    `points(self, width: float, height: float, count: int = 120) -> list[tuple[float, float]]`.

- [ ] **Step 1: Write the failing tests**

```python
# widget/tests/test_wave_model.py
"""The wave, as arithmetic. No GTK, no display, no Cairo.

Everything visual about the strip is verified by screenshot, but the
*behaviour* of the line — that it answers the voice, that it smooths,
that the thinking packet travels — is arithmetic and belongs here where
it can fail fast.
"""

from samantha_widget.wave_model import WaveModel, WaveState

WIDTH = 1000.0
HEIGHT = 96.0


def _amplitude(model: WaveModel) -> float:
    """Peak deviation from the centre line, in pixels."""
    centre = HEIGHT / 2
    return max(abs(y - centre) for _x, y in model.points(WIDTH, HEIGHT))


def test_points_span_the_full_width() -> None:
    model = WaveModel()
    points = model.points(WIDTH, HEIGHT)

    assert points[0][0] == 0.0
    assert points[-1][0] == WIDTH
    assert len(points) >= 2


def test_idle_is_nearly_flat() -> None:
    model = WaveModel()
    model.state = WaveState.IDLE

    for _ in range(200):
        model.advance(1 / 60)

    assert _amplitude(model) < 4.0


def test_listening_follows_the_level() -> None:
    quiet, loud = WaveModel(), WaveModel()
    for model, level in ((quiet, 0.05), (loud, 0.9)):
        model.state = WaveState.LISTENING
        for _ in range(120):  # two seconds: past any smoothing
            model.set_level(level)
            model.advance(1 / 60)

    assert _amplitude(loud) > 3 * _amplitude(quiet)


def test_a_sudden_level_is_smoothed_not_snapped() -> None:
    """A door slam must not make the line jump to full height in one frame."""
    model = WaveModel()
    model.state = WaveState.LISTENING
    model.set_level(1.0)
    model.advance(1 / 60)
    after_one_frame = _amplitude(model)

    for _ in range(120):
        model.set_level(1.0)
        model.advance(1 / 60)
    settled = _amplitude(model)

    assert after_one_frame < settled / 2


def test_the_thinking_packet_travels() -> None:
    model = WaveModel()
    model.state = WaveState.THINKING

    def peak_x() -> float:
        centre = HEIGHT / 2
        return max(model.points(WIDTH, HEIGHT), key=lambda p: abs(p[1] - centre))[0]

    model.advance(0.1)
    first = peak_x()
    model.advance(0.4)
    second = peak_x()

    assert second > first


def test_the_thinking_packet_wraps_instead_of_leaving() -> None:
    model = WaveModel()
    model.state = WaveState.THINKING

    for _ in range(600):  # ten seconds — several crossings
        model.advance(1 / 60)

    centre = HEIGHT / 2
    assert max(abs(y - centre) for _x, y in model.points(WIDTH, HEIGHT)) > 2.0


def test_speaking_ignores_a_stale_level_once_it_stops_arriving() -> None:
    """When playback ends the line must fall back, not freeze mid-shout."""
    model = WaveModel()
    model.state = WaveState.SPEAKING
    for _ in range(120):
        model.set_level(0.9)
        model.advance(1 / 60)
    loud = _amplitude(model)

    model.set_level(0.0)
    for _ in range(120):
        model.advance(1 / 60)

    assert _amplitude(model) < loud / 2


def test_level_is_clamped() -> None:
    model = WaveModel()
    model.state = WaveState.LISTENING
    model.set_level(50.0)
    for _ in range(120):
        model.advance(1 / 60)

    assert _amplitude(model) <= HEIGHT / 2
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd widget && .venv/bin/python -m pytest tests/test_wave_model.py -v`
Expected: FAIL — no module `samantha_widget.wave_model`.

- [ ] **Step 3: Write `wave_model.py`**

```python
# widget/samantha_widget/wave_model.py
"""The line, as arithmetic.

Samantha is a horizontal line, not an orb and not a spectrum
(CLAUDE.md §12, 2026-05). This module turns (state, level, time) into a
polyline; drawing it is Cairo's job and looking right is a screenshot's.

Nothing here imports gi, on purpose — it is the half of the wave that
can be tested with no display.
"""

from __future__ import annotations

import math
from enum import Enum


class WaveState(str, Enum):
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"


# How fast the drawn amplitude chases the requested one, per second.
# Attack is fast enough to feel immediate, decay slow enough that the
# line falls rather than drops.
_ATTACK = 9.0
_DECAY = 3.5

# Peak amplitude as a fraction of half the strip height.
_IDLE_GAIN = 0.05
_LIVE_GAIN = 0.85
_THINKING_GAIN = 0.45

_IDLE_BREATH_HZ = 0.18
_RIPPLE_HZ = 2.3
_PACKET_SECONDS = 1.6  # one crossing, left to right
_PACKET_WIDTH = 0.14  # as a fraction of the strip width


class WaveModel:
    def __init__(self) -> None:
        self.state = WaveState.IDLE
        self._level = 0.0  # requested, 0..1
        self._smoothed = 0.0  # drawn, 0..1
        self._t = 0.0

    def set_level(self, level: float) -> None:
        """Set the current RMS, 0..1. Values outside are clamped."""
        self._level = min(1.0, max(0.0, level))

    def advance(self, dt: float) -> None:
        self._t += dt
        target = self._level if self.state in _LIVE_STATES else 0.0
        rate = _ATTACK if target > self._smoothed else _DECAY
        # Exponential approach, framerate-independent: a dropped frame
        # changes the timing, never the shape.
        self._smoothed += (target - self._smoothed) * min(1.0, rate * dt)

    def points(
        self, width: float, height: float, count: int = 120
    ) -> list[tuple[float, float]]:
        centre = height / 2
        span = height / 2
        out: list[tuple[float, float]] = []
        for i in range(count + 1):
            u = i / count
            out.append((u * width, centre - span * self._displacement(u)))
        return out

    def _displacement(self, u: float) -> float:
        """Signed displacement at position u (0..1), in -1..1."""
        # Both ends are pinned so the line meets the edge of the strip
        # cleanly instead of ending in mid-air.
        edge = math.sin(math.pi * u)

        if self.state is WaveState.THINKING:
            head = (self._t / _PACKET_SECONDS) % 1.0
            d = (u - head) / _PACKET_WIDTH
            packet = math.exp(-d * d)
            carrier = math.sin(2 * math.pi * 6 * (u - head))
            return _THINKING_GAIN * edge * packet * carrier

        if self.state is WaveState.IDLE:
            breath = math.sin(2 * math.pi * _IDLE_BREATH_HZ * self._t)
            return _IDLE_GAIN * edge * breath * math.sin(2 * math.pi * 1.5 * u)

        # LISTENING and SPEAKING: two ripples at different rates so the
        # line reads as alive rather than as a single sine.
        ripple = 0.65 * math.sin(2 * math.pi * (3.0 * u - _RIPPLE_HZ * self._t))
        ripple += 0.35 * math.sin(2 * math.pi * (7.0 * u + 1.6 * self._t))
        return _LIVE_GAIN * edge * self._smoothed * ripple


_LIVE_STATES = frozenset({WaveState.LISTENING, WaveState.SPEAKING})
```

- [ ] **Step 4: Run the tests**

Run: `cd widget && .venv/bin/python -m pytest tests/test_wave_model.py -v`
Expected: 8 passed. If `test_idle_is_nearly_flat` fails, `_IDLE_GAIN`
is too high for a 96 px strip — lower it, do not loosen the test.

- [ ] **Step 5: Commit**

```bash
cd .. && git add widget/ && git commit -m "feat(widget): the wave as arithmetic, testable without a screen"
```

---

## Task 6: Drawing the wave

> **Executed 2026-08-23, and it did not go as written.** The Cairo code
> below fails on this machine with
> `TypeError: Couldn't find foreign struct converter for 'cairo.Context'`
> — raised inside the draw callback, where GTK swallows it, so the strip
> appears and never draws a line. The cause is the missing system package
> `python3-gi-cairo` (`python3-cairo` alone is not enough). The
> implementation that landed uses `Gsk.PathBuilder` +
> `Gtk.Snapshot.append_stroke` instead, which needs no extra package and
> composites on the GPU; see `widget/samantha_widget/wave.py` and the
> revision note in spec §4. Steps 1 and 2 below are kept as written so
> the reasoning is legible; the shipped code is the GSK one.
>
> Task 6 also gained two things the plan did not anticipate:
> `SAMANTHA_WIDGET_STATE`, because `xdotool` is not installed and a
> keystroke cannot be sent to photograph a state; and
> `widget/tools/render_wave.py`, which renders each state to a PNG with
> no window at all — the screen locked itself mid-verification and every
> screenshot silently captured the lock screen instead of the strip.

**Files:**
- Create: `widget/samantha_widget/wave.py`
- Modify: `widget/samantha_widget/__main__.py`

**Interfaces:**
- Consumes: `WaveModel`, `WaveState`, `theme.LINE`.
- Produces: `class WaveArea(Gtk.DrawingArea)` with
  `model: WaveModel` and `set_state(self, state: WaveState) -> None`.

- [ ] **Step 1: Write `wave.py`**

```python
# widget/samantha_widget/wave.py
"""The wave, drawn.

Cairo rather than GL or GSK: the line is an arbitrary path that changes
every frame, which is exactly what Cairo is comfortable with and exactly
what GSK's render nodes are not. It rasterises on the CPU — for one
1100x96 strip that is not a cost worth optimising. If the OS1 3D ribbon
ever comes back, that is when this becomes a Gtk.GLArea (spec §4).

The tick callback, not a timer: it fires on the compositor's frame
clock, so the animation cannot drift out of step with the screen.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import Gdk, Gtk  # noqa: E402

from . import theme  # noqa: E402
from .wave_model import WaveModel, WaveState  # noqa: E402


class WaveArea(Gtk.DrawingArea):
    def __init__(self) -> None:
        super().__init__()
        self.model = WaveModel()
        self._last_frame_us: int | None = None
        self.set_draw_func(self._draw)
        self.add_tick_callback(self._tick)

    def set_state(self, state: WaveState) -> None:
        self.model.state = state

    def _tick(self, _widget: Gtk.Widget, clock: Gdk.FrameClock) -> bool:
        now = clock.get_frame_time()  # microseconds
        if self._last_frame_us is not None:
            dt = (now - self._last_frame_us) / 1_000_000
            # A suspended laptop or a stalled compositor hands back a
            # gap of minutes. Advancing the model by that would teleport
            # the thinking packet; clamp to a couple of frames.
            self.model.advance(min(dt, 0.05))
        self._last_frame_us = now
        self.queue_draw()
        return True  # GLib.SOURCE_CONTINUE

    def _draw(self, _area: Gtk.DrawingArea, cr, width: int, height: int) -> None:
        rgba = Gdk.RGBA()
        rgba.parse(theme.LINE)

        points = self.model.points(float(width), float(height))
        cr.set_source_rgba(rgba.red, rgba.green, rgba.blue, 1.0)
        cr.set_line_width(2.0)
        cr.set_line_cap(1)  # cairo.LINE_CAP_ROUND, without importing cairo
        cr.set_line_join(1)  # cairo.LINE_JOIN_ROUND

        cr.move_to(*points[0])
        for x, y in points[1:]:
            cr.line_to(x, y)
        cr.stroke()
```

- [ ] **Step 2: Put it in the window and add demo keys**

```python
# widget/samantha_widget/__main__.py  — replace do_activate
    def do_activate(self) -> None:
        from gi.repository import Gdk

        from .wave import WaveArea
        from .wave_model import WaveState
        from .window import StripWindow

        window = StripWindow(self)
        wave = WaveArea()
        window.set_content(wave)

        # Demo only: plan 2 replaces these with the real turn. Keys 1-4
        # walk the four states so each can be photographed.
        live = {WaveState.LISTENING, WaveState.SPEAKING}
        keys = {
            Gdk.KEY_1: WaveState.IDLE,
            Gdk.KEY_2: WaveState.LISTENING,
            Gdk.KEY_3: WaveState.THINKING,
            Gdk.KEY_4: WaveState.SPEAKING,
        }

        def on_key(_ctl, keyval, _code, _state) -> bool:
            if keyval in keys:
                wave.set_state(keys[keyval])
                # The demo has no microphone, so fake a level for the two
                # states that would otherwise be driven by one.
                wave.model.set_level(0.7 if keys[keyval] in live else 0.0)
                return True
            if keyval == Gdk.KEY_Escape:
                self.quit()
                return True
            return False

        controller = Gtk.EventControllerKey()
        controller.connect("key-pressed", on_key)
        window.add_controller(controller)
        window.present()
```

- [ ] **Step 3: Photograph all four states**

```bash
cd widget
DISPLAY=:1 .venv/bin/python -m samantha_widget &
sleep 2
for k in 1 2 3 4; do
  DISPLAY=:1 xdotool key --window "$(DISPLAY=:1 xdotool search --name Samantha | head -1)" "$k" 2>/dev/null || \
    echo "no xdotool — press $k by hand, then continue"
  sleep 1
  ffmpeg -y -f x11grab -video_size 1920x1080 -i :1 -frames:v 1 "/tmp/wave-$k.png"
done
```

`xdotool` is not installed on this box (spike finding), so expect the
manual path: click the strip, press 1/2/3/4 by hand, capture between
presses. Look at all four images:

1. `idle` — a nearly flat line, breathing.
2. `listening` — a live, rippling line filling most of the height.
3. `thinking` — a packet crossing left to right, and it must **wrap**,
   not vanish at the edge.
4. `speaking` — like listening; it is the state, not the shape, that
   differs today.

- [ ] **Step 4: Confirm the CPU cost is not silly**

```bash
top -b -n 3 -p "$(pgrep -f samantha_widget | head -1)" | tail -5
```

Expected: single-digit percent of one core. If it is above ~15%, drop
`points(count=…)` from 120 to 60 and re-measure — do not reach for GL.

- [ ] **Step 5: Commit**

```bash
cd .. && git add widget/ && git commit -m "feat(widget): draw her, in Cairo, on the frame clock"
```

---

## Task 7: A systemd unit, and the fallback left intact

**Files:**
- Create: `systemd/samantha-widget.service`
- Modify: `widget/README.md`

**Interfaces:**
- Consumes: `widget/.venv`.
- Produces: `samantha-widget.service`, enabled in the graphical session.

- [ ] **Step 1: Write the unit**

```ini
# systemd/samantha-widget.service
[Unit]
Description=Samantha (desktop strip, GTK4)
# The strip is furniture in a graphical session, not a boot service:
# without a display server it exits immediately and systemd restarts it
# forever. PartOf ties it to the session's lifetime.
After=graphical-session.target
PartOf=graphical-session.target

[Service]
Type=simple
# X11 only (spec §8). :1 is this box's session; on another display this
# is the one line that changes.
Environment=DISPLAY=:1
# Unbuffered, so `journalctl --user -u samantha-widget -f` shows a
# traceback at the moment it happens rather than at exit.
Environment=PYTHONUNBUFFERED=1
ExecStart=%h/git/os1-samantha/widget/.venv/bin/python -m samantha_widget
Restart=on-failure
RestartSec=3

[Install]
WantedBy=graphical-session.target
```

- [ ] **Step 2: Install and start it**

```bash
cp systemd/samantha-widget.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now samantha-widget.service
systemctl --user status samantha-widget.service --no-pager
```

Expected: `active (running)`.

- [ ] **Step 3: Confirm the kiosk is still there**

```bash
systemctl --user is-enabled samantha-ui.service
```

Expected: `enabled`. **Nothing in this plan disables it.** The kiosk is
the fallback until plan 3, and plan 3 is not written until the widget
has convinced (spec §7).

- [ ] **Step 4: Confirm it comes back after a restart**

```bash
systemctl --user restart samantha-widget.service
sleep 3
ffmpeg -y -f x11grab -video_size 1920x1080 -i :1 -frames:v 1 /tmp/after-restart.png
```

Look at it: the strip must be back, in the same place, still above.

- [ ] **Step 5: Document it in the README**

Append to `widget/README.md`:

```markdown
## As a service

    cp ../systemd/samantha-widget.service ~/.config/systemd/user/
    systemctl --user daemon-reload
    systemctl --user enable --now samantha-widget.service
    journalctl --user -u samantha-widget -f

`DISPLAY=:1` is hard-coded in the unit — it is this box's session, and
it is the one line to change on another display.

The Chromium kiosk (`samantha-ui.service`) is deliberately left enabled.
It is the fallback until the widget has replaced it for real.
```

- [ ] **Step 6: Final gate — the whole suite, clean**

```bash
cd widget
.venv/bin/python -m pytest -v
.venv/bin/ruff check .
.venv/bin/ruff format --check .
```

Expected: all tests pass, ruff clean. Then confirm the backend suite is
untouched:

```bash
cd ../backend && .venv/bin/python -m pytest -q
```

Expected: same result as before this plan — 75 passed, 1 pre-existing
failure (`test_synth_produces_riff_wave`, piper not installed here).
A different number means this plan broke something it never touched.

- [ ] **Step 7: Commit**

```bash
cd .. && git add systemd/ widget/ && git commit -m "feat(widget): run the strip as a user service"
```

- [ ] **Step 8: Update PROGRESS.md**

Add a dated entry at the top of `PROGRESS.md` following the house
format (`## 2026-08-23 — Widget plan 1: the strip ✅`), listing the
changed files, the test counts, and — as Notes — the screenshots that
were actually looked at and what each one showed.

**Do not touch CLAUDE.md §12.** The decision-log entries are owed at
plan 3, when the kiosk is actually retired (spec §11). Writing them now
would record a decision that has not taken effect.

- [ ] **Step 9: Commit**

```bash
git add PROGRESS.md && git commit -m "docs: record what the strip looks like and what proved it"
```

---

## Done when

- A terracotta strip sits at the bottom of the screen, above everything,
  with no halo and no title bar, and a screenshot proves each of those.
- `xprop -name Samantha _NET_WM_STATE` lists all four states.
- The wave animates through four visibly distinct states.
- `systemctl --user restart samantha-widget` brings it back unchanged.
- `pytest` is green in `widget/`, and `backend/` is exactly as it was.
- The Chromium kiosk still starts, because nothing here removed it.

Plan 2 (`docs/superpowers/plans/2026-08-23-samantha-widget-voice-turn.md`)
makes it listen and answer.
