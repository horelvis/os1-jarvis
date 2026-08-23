"""Entry point: python -m samantha_widget."""

import os
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")

from gi.repository import Gdk, Gtk  # noqa: E402


class SamanthaApp(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id="com.horelvis.samantha.widget")

    def do_activate(self) -> None:
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

        def on_key(_controller, keyval, _code, _state) -> bool:
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

        # Demo only, and the reason it exists: xdotool is not installed on
        # this box, so a screenshot of a given state cannot be driven by
        # sending a keystroke. Starting the process in the state you want
        # to photograph is the reproducible way to get all four.
        wanted = os.environ.get("SAMANTHA_WIDGET_STATE")
        if wanted:
            state = WaveState(wanted)
            wave.set_state(state)
            wave.model.set_level(0.7 if state in live else 0.0)

        window.present()


def main() -> int:
    return SamanthaApp().run(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
