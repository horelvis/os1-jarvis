"""Entry point: python -m samantha_widget.

Three threads and one rule. The GTK main thread owns every widget; one
asyncio thread owns the WebSocket and the HTTP client to CosyVoice;
PortAudio's callback thread does nothing but push frames. Everything
that has to reach the UI goes through GLib.idle_add, and that is the
only bridge there is.
"""

from __future__ import annotations

import asyncio
import os
import sys
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")

from gi.repository import Gdk, GLib, Gtk  # noqa: E402

from .wave_model import WaveState  # noqa: E402

# Set to any of the four state names to freeze the wave there and skip
# the voice loop entirely — how each state gets photographed, since
# xdotool is not installed and a keystroke cannot be sent.
_DEMO_STATE = os.environ.get("SAMANTHA_WIDGET_STATE")

# Skip opening the microphone. On a box with no microphone plugged in
# there is nothing to open, and it makes the difference between "she
# cannot hear" and "the process is broken" visible in one variable.
_NO_MIC = os.environ.get("SAMANTHA_WIDGET_NO_MIC") == "1"

# Say this once, a few seconds after starting, and show the speaking
# wave while it plays. The only way to hear the widget's real voice path
# — its own threads, its own queue, its own player — on a machine with
# no microphone, where no turn can ever begin.
_SAY_ON_START = os.environ.get("SAMANTHA_WIDGET_SAY")


class SamanthaApp(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id="com.horelvis.samantha.widget")
        # asyncio holds only WEAK references to running tasks, so a task
        # nobody keeps can be garbage-collected mid-await and simply stop
        # — no error, no log. Anything spawned here is kept alive until
        # it finishes.
        self._tasks: set[asyncio.Task] = set()

    def _spawn(self, coro) -> None:
        task = asyncio.ensure_future(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def do_activate(self) -> None:
        from .wave import WaveArea
        from .window import StripWindow

        window = StripWindow(self)
        wave = WaveArea()
        window.set_content(wave)
        self._add_demo_keys(window, wave)
        window.present()

        if _DEMO_STATE:
            state = WaveState(_DEMO_STATE)
            wave.set_state(state)
            wave.model.set_level(0.7 if state in _LIVE else 0.0)
            return

        self._start_voice_loop(wave)

    # ── the demo half ─────────────────────────────────────────────────

    def _add_demo_keys(self, window: Gtk.Window, wave) -> None:
        keys = {
            Gdk.KEY_1: WaveState.IDLE,
            Gdk.KEY_2: WaveState.LISTENING,
            Gdk.KEY_3: WaveState.THINKING,
            Gdk.KEY_4: WaveState.SPEAKING,
        }

        def on_key(_controller, keyval, _code, _state) -> bool:
            if keyval in keys:
                wave.set_state(keys[keyval])
                wave.model.set_level(0.7 if keys[keyval] in _LIVE else 0.0)
                return True
            if keyval == Gdk.KEY_Escape:
                self.quit()
                return True
            return False

        controller = Gtk.EventControllerKey()
        controller.connect("key-pressed", on_key)
        window.add_controller(controller)

    # ── the real half ─────────────────────────────────────────────────

    def _start_voice_loop(self, wave) -> None:
        import numpy as np

        from .audio import Microphone, Player, describe_devices
        from .gateway import GatewayClient
        from .speech import ClauseChunker, Speaker, is_system_message
        from .stt import Transcriber
        from .turn import TurnMachine
        from .vad import SileroDetector, UtteranceDetector

        # Logged once: picking the wrong device is silent, not an error.
        print(f"audio: {describe_devices()}", file=sys.stderr, flush=True)
        _preload()

        loop = asyncio.new_event_loop()
        player = Player()
        player.start()
        speaker = Speaker(player)
        chunker = ClauseChunker()
        transcriber = Transcriber()
        client = GatewayClient()

        # ── the only bridge into the UI ───────────────────────────────
        def set_state(state: WaveState) -> None:
            GLib.idle_add(wave.set_state, state)

        def set_level(level: float) -> None:
            GLib.idle_add(wave.set_level, level)

        def on_utterance(pcm: bytes) -> None:
            loop.call_soon_threadsafe(lambda: self._spawn(dispatch(pcm)))

        machine = TurnMachine(
            on_state=set_state,
            on_level=set_level,
            on_utterance=on_utterance,
            on_interrupt=speaker.interrupt,
        )

        async def dispatch(pcm: bytes) -> None:
            text = await asyncio.to_thread(transcriber.transcribe, pcm)
            if not text:
                machine.error("")  # nothing was said; settle quietly
                return
            print(f"→ {text}", file=sys.stderr, flush=True)
            await client.send_chat(text)

        # ── the gateway's replies ─────────────────────────────────────
        def on_token(token: str) -> None:
            if is_system_message(token):
                # Hermes narrating itself, in English, with emoji. Not
                # hers to say — and its `done` must not end the turn.
                print(f"(sistema) {token[:60]}", file=sys.stderr, flush=True)
                return
            machine.token(token)
            for clause in chunker.push(token):
                speaker.enqueue(clause)

        def on_done(_ms: int) -> None:
            for clause in chunker.flush():
                speaker.enqueue(clause)
            machine.done()

        def on_error(message: str) -> None:
            if message:
                speaker.enqueue(message)
            machine.error(message)

        client.on_token = on_token
        client.on_done = on_done
        client.on_error = on_error

        # ── the microphone, always open ───────────────────────────────
        detector = UtteranceDetector(SileroDetector())

        def on_frame(frame: bytes) -> None:
            if player.busy and not detector.speaking:
                # She is talking and nobody has cut in. Do not let her
                # own voice, coming back through the room, start a turn.
                return

            was_speaking = detector.speaking
            utterance = detector.push(frame)
            if detector.speaking and not was_speaking:
                machine.speech_started()
            if detector.speaking:
                samples = np.frombuffer(frame, dtype=np.int16).astype(np.float32)
                rms = float(np.sqrt(np.mean((samples / 32768.0) ** 2)))
                set_level(min(1.0, rms * 6))
            if utterance is not None:
                machine.heard(utterance)

        def _boot() -> None:
            # Both run for the lifetime of the process, on the loop that
            # owns them.
            self._spawn(client.run())
            speaker.start()

        def _drive_speaking_level() -> bool:
            """Make the line follow her own voice while she talks.

            Nothing else does. `set_level` is only ever called from the
            microphone path, and that path is deliberately gated shut
            while the player is busy (so she does not hear herself) — so
            without this the wave sits perfectly flat through every reply,
            which is not what spec §4 promises and looks broken.

            Runs on the GTK thread, so it may touch the widget directly;
            50 ms is well under the frame interval and cheap.
            """
            if machine.state is WaveState.SPEAKING:
                # The spectrum of the block going out right now, which is
                # what makes the equaliser match the voice instead of
                # merely reacting to it.
                wave.set_bands(player.bands)
                wave.set_history(player.history)
                wave.model.set_level(min(1.0, player.level * 5))
            return True  # GLib.SOURCE_CONTINUE

        GLib.timeout_add(50, _drive_speaking_level)

        threading.Thread(target=loop.run_forever, daemon=True).start()
        loop.call_soon_threadsafe(_boot)
        threading.Thread(target=transcriber.load, daemon=True).start()

        if _NO_MIC:
            print("micrófono: desactivado", file=sys.stderr, flush=True)
        else:
            Microphone(on_frame).start()

        if _SAY_ON_START:

            def _say_it() -> None:
                print(f"diciendo: {_SAY_ON_START}", file=sys.stderr, flush=True)
                machine.token(_SAY_ON_START)  # drives the wave to `speaking`
                for clause in chunker.push(_SAY_ON_START):
                    speaker.enqueue(clause)
                for clause in chunker.flush():
                    speaker.enqueue(clause)

            # After _boot, so the Speaker's worker is already running.
            loop.call_soon_threadsafe(loop.call_later, 3.0, _say_it)


_LIVE = {WaveState.LISTENING, WaveState.SPEAKING}


def _preload() -> None:
    """Import the heavy, C-extension-backed modules up front.

    faster_whisper drags in PyAV and through it all of ffmpeg; websockets
    resolves its imports lazily on first use. Doing both here costs a
    second or two of frozen UI right after the strip appears, and buys a
    first turn that is not slowed by an import.

    Historical note, because the evidence pointed the wrong way for a
    while: this function was written believing that these two imports
    landing on different threads at once was what killed the process with
    a SIGSEGV. It was not. The crash was PortAudio's `callback=` mode
    (see audio.Microphone), and it merely *surfaced* inside whichever
    import happened to be running. Preloading is still worth keeping on
    its own merits; it just never fixed anything.
    """
    import faster_whisper  # noqa: F401  (pulls in av → ffmpeg)
    import websockets

    _ = websockets.connect  # force the lazy attribute to resolve


def main() -> int:
    return SamanthaApp().run(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
