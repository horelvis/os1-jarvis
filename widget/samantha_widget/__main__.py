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

from .vad import FRAME_SAMPLES, INPUT_RATE  # noqa: E402
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

# Speak this INTO the widget, as if into a microphone: it is synthesised,
# resampled to 16 kHz and pushed through the same on_frame the real
# microphone calls. Everything after that is real — Silero, Whisper, the
# WebSocket to Hermes, and her reply spoken back. Only the air is faked.
_FAKE_MIC_TEXT = os.environ.get("SAMANTHA_WIDGET_FAKE_MIC")

# Show these photos (comma-separated paths) a couple of seconds after
# starting, exactly as if the gateway had pushed them. The only way to
# photograph the band on a box where making him actually look at a
# camera takes a whole live turn — the counterpart of SAMANTHA_WIDGET_SAY
# for the half of him you can see.
_SHOW_ON_START = os.environ.get("SAMANTHA_WIDGET_PHOTO")

# Write every utterance the VAD closes to this directory as a WAV.
# Diagnostic only: when a transcription comes back as nonsense there is
# no way to tell from the text whether the audio was bad or Whisper was.
_DUMP_DIR = os.environ.get("SAMANTHA_WIDGET_DUMP")


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
        from .photo_area import PhotoArea
        from .wave import WaveArea
        from .window import StripWindow

        window = StripWindow(self)
        wave = WaveArea()
        window.set_content(wave)
        # The band drives the window's size directly: it is the only
        # thing that knows how tall it wants to be, and `resize_to` is
        # the only thing that can move the top edge up to make room.
        band = PhotoArea(on_resize=window.resize_to)
        window.set_band(band)
        self._add_demo_keys(window, wave)
        window.present()

        if _SHOW_ON_START:
            paths = [p.strip() for p in _SHOW_ON_START.split(",") if p.strip()]

            def _show_them() -> bool:
                for path in paths:
                    print(f"foto de prueba: {path}", file=sys.stderr, flush=True)
                    band.show_photo(path, "prueba")
                return False  # GLib.SOURCE_REMOVE

            GLib.timeout_add(2000, _show_them)

        if _DEMO_STATE:
            state = WaveState(_DEMO_STATE)
            wave.set_state(state)
            wave.set_task_count(int(os.environ.get("SAMANTHA_WIDGET_TASKS", "0")))
            wave.model.set_level(0.7 if state in _LIVE else 0.0)
            return

        self._start_voice_loop(wave, band)

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

    def _start_voice_loop(self, wave, band) -> None:
        import numpy as np

        from .audio import Microphone, Player, describe_devices
        from .gateway import GatewayClient
        from .speech import (
            ClauseChunker,
            Speaker,
            is_system_message,
            unwrap_delivery,
        )
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
            seconds = len(pcm) / 2 / INPUT_RATE
            print(
                f"oído: {seconds:.1f}s de voz (whisper listo: {transcriber.ready})",
                file=sys.stderr,
                flush=True,
            )
            if _DUMP_DIR:
                _dump_utterance(pcm)
            text = await asyncio.to_thread(transcriber.transcribe, pcm)
            if not text:
                # Either Whisper is not up yet, or it heard nothing it
                # believed. Both end the turn quietly; neither is an error
                # the user should hear about.
                print("transcripción vacía", file=sys.stderr, flush=True)
                machine.error("")
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
            print(f"← {token}", file=sys.stderr, flush=True)
            # A scheduled delivery arrives wrapped in scaffolding — job
            # id, dashes, an English footer — and she would read all of
            # it aloud.
            token = unwrap_delivery(token)
            if not token:
                return
            machine.token(token)
            for clause in chunker.push(token):
                print(f"  dice: {clause}", file=sys.stderr, flush=True)
                speaker.enqueue(clause)

        def on_done(_ms: int) -> None:
            for clause in chunker.flush():
                print(f"  dice: {clause}", file=sys.stderr, flush=True)
                speaker.enqueue(clause)
            machine.done()

        def on_error(message: str) -> None:
            if message:
                speaker.enqueue(message)
            machine.error(message)

        def on_photo(path: str, camera: str) -> None:
            # Straight to the GTK thread. Everything else the gateway
            # sends goes through the turn machine; a photo does not — it
            # is not part of what he says, and it must appear whether or
            # not a turn is in flight (a reminder can push one).
            print(f"foto: {camera} -> {path}", file=sys.stderr, flush=True)
            GLib.idle_add(band.show_photo, path, camera)

        client.on_token = on_token
        client.on_done = on_done
        client.on_error = on_error
        client.on_photo = on_photo

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

        def _load_whisper() -> None:
            import time

            started = time.monotonic()
            try:
                transcriber.load()
            except Exception as exc:
                # A daemon thread that raises takes the traceback with it
                # and the strip just never hears anything.
                print(f"whisper NO cargó: {exc!r}", file=sys.stderr, flush=True)
                return
            print(
                f"whisper listo en {time.monotonic() - started:.0f}s",
                file=sys.stderr,
                flush=True,
            )

        threading.Thread(target=_load_whisper, daemon=True).start()

        if _FAKE_MIC_TEXT:
            threading.Thread(
                target=_feed_fake_mic,
                args=(_FAKE_MIC_TEXT, on_frame, transcriber),
                name="fake-microphone",
                daemon=True,
            ).start()
        elif _NO_MIC:
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
                # In a real turn the gateway sends `done` and the wave
                # settles. Nothing sends one here, so without this the
                # strip stays in `speaking` forever, frozen on the last
                # thing it drew — which looks exactly like a bug.
                GLib.timeout_add(200, _settle_when_quiet)

            watch = {"started": False, "quiet_ticks": 0}
            # 200 ms per tick. Long enough to outlast the gap between two
            # clauses, which is however long CosyVoice takes to
            # synthesise the next one — during that gap the player is
            # empty and looks exactly like "finished".
            quiet_ticks_needed = 10

            def _settle_when_quiet() -> bool:
                # Wait for it to START before watching for it to stop:
                # the first clause takes about a second to synthesise,
                # and until then "not busy" means "not begun".
                if player.busy:
                    watch["started"] = True
                    watch["quiet_ticks"] = 0
                    return True
                if not watch["started"]:
                    return True
                watch["quiet_ticks"] += 1
                if watch["quiet_ticks"] < quiet_ticks_needed:
                    return True
                machine.done()
                return False

            # After _boot, so the Speaker's worker is already running.
            loop.call_soon_threadsafe(loop.call_later, 3.0, _say_it)


_LIVE = {WaveState.LISTENING, WaveState.SPEAKING}


def _dump_utterance(pcm: bytes) -> None:
    import wave
    from pathlib import Path

    directory = Path(_DUMP_DIR)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"utterance-{len(list(directory.glob('*.wav'))):02d}.wav"
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(INPUT_RATE)
        out.writeframes(pcm)
    print(f"volcado: {path}", file=sys.stderr, flush=True)


def _feed_fake_mic(text: str, on_frame, transcriber) -> None:
    """Push synthesised speech through the microphone path, in real time.

    The pacing matters. Dumping every frame at once would hand Silero a
    whole utterance in a millisecond, and the VAD's timing — 3 frames to
    start, 0.7 s of silence to end — is expressed in frames, so it would
    still work but nothing else would be tested at a realistic rate.
    One frame per 32 ms is what the hardware would do.
    """
    import time

    from .fake_mic import frames_for

    print(f"micrófono falso: {text!r}", file=sys.stderr, flush=True)

    # Wait for Whisper. A real person talks whenever they like and a turn
    # that arrives too early is simply lost — documented behaviour, and
    # exactly what happened the first time this test ran: the utterance
    # reached a transcriber that was not up, came back empty, and the
    # whole thing looked like silence.
    waited = 0.0
    while not transcriber.ready and waited < 180:
        time.sleep(1.0)
        waited += 1.0
    if not transcriber.ready:
        print(
            "micrófono falso: whisper nunca estuvo listo", file=sys.stderr, flush=True
        )
        return
    try:
        frames = list(frames_for(text))
    except Exception as exc:
        print(f"micrófono falso falló: {exc}", file=sys.stderr, flush=True)
        return

    print(f"micrófono falso: {len(frames)} frames", file=sys.stderr, flush=True)
    period = FRAME_SAMPLES / INPUT_RATE
    next_at = time.monotonic()
    for frame in frames:
        on_frame(frame)
        next_at += period
        delay = next_at - time.monotonic()
        if delay > 0:
            time.sleep(delay)


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
