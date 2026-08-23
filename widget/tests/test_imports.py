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
