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
