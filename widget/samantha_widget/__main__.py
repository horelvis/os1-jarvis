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
import time
from typing import TYPE_CHECKING

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")

from gi.repository import Gdk, GLib, Gtk  # noqa: E402

from .vad import FRAME_SAMPLES, INPUT_RATE  # noqa: E402
from .hotword import SENSITIVITY as HOTWORD_SENSITIVITY  # noqa: E402
from .echo import EchoFilter  # noqa: E402
from .hotword import Hotword  # noqa: E402
from .wake import WINDOW_SECONDS, WakeWord  # noqa: E402
from .wave_model import WaveState  # noqa: E402

if TYPE_CHECKING:
    from .photo_area import PhotoArea

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
# His name, and how long a conversation stays open after he answers.
_WAKE_WORD = os.environ.get("SAMANTHA_WIDGET_WAKE_WORD", "jarvis")
# Hear his name instead of reading it (user, 2026-08-26). Empty disables
# the acoustic detector and leaves only `wake.py`'s filter over the
# transcript. `SAMANTHA_WIDGET_HOTWORD_SENSITIVITY` moves the threshold;
# the model is trained on English and the phrase is said with a Spanish
# accent, so the right value is a measurement, not a constant.
# Empty by default, and the reason is a measurement rather than a
# preference. openWakeWord's bundled `hey_jarvis` is trained on English:
# the user saying "Hey Jarvis" into the real microphone scored 0.25-0.29
# against the 0.6 threshold, and synthesised Spanish peaked at 0.359.
# There is no gap left to put a threshold in — 0.25 would fire on the
# television — and it costs ~6 points of CPU on every frame, all day, to
# never fire. Set it to `hey_jarvis` (or a path to a model trained on
# this voice) to turn it back on; `wake.py`'s filter over the transcript
# is what actually works here today.
_HOTWORD_MODEL = os.environ.get("SAMANTHA_WIDGET_HOTWORD", "")
# Diagnostic: log what the microphone hears WHILE he is speaking.
_TRACE_MIC = os.environ.get("SAMANTHA_WIDGET_TRACE_MIC") == "1"

# How loud the room has to be, WHILE he is speaking, before a frame is
# allowed to start a turn. This is the partial version of
# SAMANTHA_WIDGET_MIC_GATE: that dropped every frame and made him
# impossible to interrupt; this drops only the quiet ones, so his own
# voice coming back through the room cannot start a turn while somebody
# talking near the microphone still can.
#
# Measured 2026-08-26, and the calibration is as much physical as it is
# numeric. The user's voice sits at RMS 0.054-0.088 in the dumped
# utterances. His own echo measured:
#
#   speaker beside the microphone, volume 0.54 → 0.178  (LOUDER than
#       the person in the room: no threshold can separate that)
#   the same, volume 0.25                      → 0.011-0.026
#   speakers moved away from it, volume 0.50   → 0.027-0.035
#
# Moving them apart is what made this workable at a normal volume; the
# user did that. 0.05 sits above the echo and below a person talking,
# with the margin the 0.035 of the first attempt did not have.
try:
    _BARGE_RMS = float(os.environ.get("SAMANTHA_WIDGET_BARGE_RMS", "0.05"))
except ValueError:
    _BARGE_RMS = 0.05
_trace = {"n": 0}
try:
    _HOTWORD_SENSITIVITY = float(
        os.environ.get("SAMANTHA_WIDGET_HOTWORD_SENSITIVITY", "")
    )
except ValueError:
    _HOTWORD_SENSITIVITY = HOTWORD_SENSITIVITY
# Log every score above this, to calibrate against a real voice.
try:
    _HOTWORD_TRACE = float(os.environ.get("SAMANTHA_WIDGET_HOTWORD_TRACE", ""))
except ValueError:
    _HOTWORD_TRACE = 0.0

# Start with these switches already off: "mic", "voice", or both. The
# counterpart of SAMANTHA_WIDGET_STATE for the two glyphs at the end of
# the strip — the struck-through state cannot be photographed otherwise,
# because there is no way to send a click to this window (xdotool is not
# installed, CLAUDE.md §5).
_SWITCHES_OFF = {
    s.strip() for s in os.environ.get("SAMANTHA_WIDGET_SWITCHES", "").split(",")
}
try:
    _WAKE_WINDOW = float(os.environ.get("SAMANTHA_WIDGET_WAKE_WINDOW", ""))
except ValueError:
    _WAKE_WINDOW = WINDOW_SECONDS

# Show these photos (comma-separated paths) a couple of seconds after
# starting, exactly as if the gateway had pushed them. The only way to
# photograph the band on a box where making him actually look at a
# camera takes a whole live turn — the counterpart of SAMANTHA_WIDGET_SAY
# for the half of him you can see.
_SHOW_ON_START = os.environ.get("SAMANTHA_WIDGET_PHOTO")

# Feed the band a local video file as if the gateway had pushed it. The
# counterpart of SAMANTHA_WIDGET_PHOTO for the half of him that moves:
# the band, the decoder and the input region, with no gateway and no
# camera in the room.
_LIVE_ON_START = os.environ.get("SAMANTHA_WIDGET_LIVE")

# Write these lines into the strip's console a couple of seconds after
# starting, as if something working had produced them. The counterpart
# of SAMANTHA_WIDGET_PHOTO and _LIVE for the third thing the strip can
# show — separate lines with "\n", or a path to a file to read.
_CONSOLE_ON_START = os.environ.get("SAMANTHA_WIDGET_CONSOLE")

# Write every utterance the VAD closes to this directory as a WAV.
# Diagnostic only: when a transcription comes back as nonsense there is
# no way to tell from the text whether the audio was bad or Whisper was.
_DUMP_DIR = os.environ.get("SAMANTHA_WIDGET_DUMP")

# Deafen the microphone while he speaks. Unconditional until 2026-08-25,
# when a real microphone arrived and showed what it cost: to interrupt
# him, `detector.speaking` had to be true ALREADY, and it could not
# become true while every frame was being dropped. The only voice that
# could open that latch was his own, coming back through the room — so
# the gate both let him answer himself (22.6 s of his own reply
# transcribed as the user's, measured) and made "stop" unreachable.
#
# Echo cancellation removes his voice from the input instead
# (~/.config/pipewire/pipewire.conf.d/99-echo-cancel.conf), so the
# frames can flow and cutting in works. Set this to 1 on a box without
# it, or he will hear himself and reply to it.
_MIC_GATE = os.environ.get("SAMANTHA_WIDGET_MIC_GATE") == "1"


def _apply_error_to_wake_window(wake: WakeWord, message: str, now: float) -> None:
    """Extend the wake window when `message` is the adapter's `silence()`.

    The gateway only ever sends an EMPTY `error` when the user's own
    sentence was diverted to the code assistant as the answer to a held
    question or gate (`adapter.py`'s `_should_divert` + `silence()`).
    Every other `error` — a lost turn, a bad frame — carries Spanish
    text and is a real fault, not an answer.

    JARVIS did not speak, but the user just did and is plainly still in
    the conversation, so an empty `error` counts as an answer for the
    wake window: needing his name again for the very next sentence
    would be exactly the friction the window exists to remove. Takes
    `wake` and `now` rather than reading them from a closure so the
    whole decision — predicate and the `answered()` call together — can
    be driven from a test with a real `WakeWord` and no GTK app.
    """
    if not message:
        wake.answered(now)


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

        if _LIVE_ON_START:

            def _feed_it() -> bool:
                threading.Thread(
                    target=_feed_live_file,
                    args=(_LIVE_ON_START, band),
                    name="fake-live",
                    daemon=True,
                ).start()
                return False  # GLib.SOURCE_REMOVE

            GLib.timeout_add(2000, _feed_it)

        if _CONSOLE_ON_START:

            def _write_them() -> bool:
                text = _CONSOLE_ON_START
                if os.path.isfile(text):
                    text = open(text, encoding="utf-8", errors="replace").read()
                window.write_console(text.replace("\\n", "\n"))
                return False  # GLib.SOURCE_REMOVE

            GLib.timeout_add(2000, _write_them)

        if _DEMO_STATE:
            state = WaveState(_DEMO_STATE)
            wave.set_state(state)
            wave.set_task_count(int(os.environ.get("SAMANTHA_WIDGET_TASKS", "0")))
            wave.model.set_level(0.7 if state in _LIVE else 0.0)
            return

        self._start_voice_loop(wave, band, window)

    # ── the demo half ─────────────────────────────────────────────────

    def _add_demo_keys(self, window: Gtk.Window, wave) -> None:
        keys = {
            Gdk.KEY_1: WaveState.IDLE,
            Gdk.KEY_2: WaveState.LISTENING,
            Gdk.KEY_3: WaveState.THINKING,
            Gdk.KEY_4: WaveState.SPEAKING,
        }

        def on_key(_controller, keyval, _code, _state) -> bool:
            if window.prompt_open():
                # While the line is open the keyboard belongs to it. The
                # demo keys would otherwise fire on "1" as you type, and
                # Escape has a better job here than closing him.
                if keyval == Gdk.KEY_Escape:
                    window.set_prompt_open(False)
                    return True
                return False
            if keyval in keys:
                wave.set_state(keys[keyval])
                wave.model.set_level(0.7 if keys[keyval] in _LIVE else 0.0)
                return True
            return False

        controller = Gtk.EventControllerKey()
        controller.connect("key-pressed", on_key)
        window.add_controller(controller)

    # ── the real half ─────────────────────────────────────────────────

    def _start_voice_loop(self, wave, band, window) -> None:
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
        # The hint carries his name so Whisper stops inventing spellings
        # of it — see `Transcriber.hint`. A house where the wake word is
        # off has nothing to bias towards.
        transcriber = Transcriber(
            hint=f"Hola {_WAKE_WORD.capitalize()}." if _WAKE_WORD else ""
        )
        client = GatewayClient()

        def on_switch(name: str, on: bool) -> None:
            """One of the two switches on the strip was pressed."""
            print(
                f"interruptor: {name} {'encendido' if on else 'apagado'}",
                file=sys.stderr,
                flush=True,
            )
            if name == "voice" and not on:
                # Silence now, not after the current sentence: the
                # reason somebody presses this is that he is talking.
                speaker.interrupt()
            if name == "mic" and not on:
                # Whatever he was told before the switch went off is not
                # a conversation any more.
                wake.close()
            if name == "text":
                # Opens the line, or closes it if it was already open.
                # Nothing else: what is typed goes out on `on_prompt`.
                window.toggle_prompt()
                return
            if name == "close":
                # He is gone until somebody starts him again from a
                # terminal — which is why it takes two presses (see
                # `switches.ARM_SECONDS`).
                #
                # `os._exit` rather than `Gtk.Application.quit`, and the
                # difference is not style: quitting properly unwinds
                # PortAudio, onnxruntime and CUDA from the GTK thread,
                # and measured 2026-08-26 that segfaults —
                # `code=dumped, status=11/SEGV`. Which would be tidy but
                # for `Restart=on-failure`: systemd read the crash as a
                # failure and started him again, so the close button
                # restarted him instead of closing him. `os._exit(0)`
                # tears nothing down, which is exactly what is wanted by
                # a process on its way out, and exits 0 so the unit
                # stays stopped. There is no state here to flush: the
                # memory that matters lives in the gateway.
                print("cerrando, señor.", file=sys.stderr, flush=True)
                speaker.interrupt()
                sys.stderr.flush()
                os._exit(0)

        def say(clause: str) -> None:
            """Speak a clause, unless his voice is switched off."""
            # Remembered even when muted: `interrupt()` can leave a
            # clause half-played, and half of one still comes back.
            echo.spoke(clause, time.monotonic())
            if not wave.switches.voice_on:
                # Dropped rather than queued: a queue that fills up
                # while he is muted would empty itself the moment he
                # is unmuted, and say a minute-old answer out loud.
                return
            speaker.enqueue(clause)

        wave.on_switch = on_switch

        def on_typed(text: str) -> None:
            """A line typed on the strip. Sent exactly as if it were said.

            Two things the spoken path does are deliberately skipped: the
            wake word (a button was pressed — he is being addressed) and
            the echo filter (nothing was heard, so nothing can be his
            own voice coming back).
            """
            print(f"⌨ {text}", file=sys.stderr, flush=True)
            machine.typed()

            async def _send() -> None:
                # Wrapped so a failure is a line in the journal instead
                # of an exception dying inside a task nobody awaits —
                # which is exactly how the first version of this looked
                # from outside: the line vanished and nothing said why.
                try:
                    await client.send_chat(text)
                except Exception as exc:
                    print(f"no se pudo enviar: {exc!r}", file=sys.stderr, flush=True)
                    machine.error("")

            loop.call_soon_threadsafe(lambda: self._spawn(_send()))

        window.on_prompt = on_typed
        if "mic" in _SWITCHES_OFF:
            wave.switches.mic_on = False
        if "voice" in _SWITCHES_OFF:
            wave.switches.voice_on = False

        # He answers to his name (user, 2026-08-26). An empty
        # SAMANTHA_WIDGET_WAKE_WORD restores the "everything heard is for
        # him" of every version before that.
        wake = WakeWord(_WAKE_WORD, window=_WAKE_WINDOW)
        hotword = Hotword(_HOTWORD_MODEL, sensitivity=_HOTWORD_SENSITIVITY)
        # His own voice, coming back through the room. See `echo.py`:
        # the canceller helps and does not clear, and the microphone has
        # to stay open or he cannot be interrupted.
        echo = EchoFilter()
        if wake.word:
            print(
                f"palabra de activación: {wake.word} (ventana {wake.window:.0f}s)",
                file=sys.stderr,
                flush=True,
            )

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
            text = echo.clean(text, time.monotonic())
            if not text.strip():
                # All of it was him. Not a turn, and not an error.
                print("(era su propio eco)", file=sys.stderr, flush=True)
                machine.error("")
                return
            spoken = wake.heard(text, time.monotonic())
            if spoken is None:
                # Somebody was talking in the room, not to him. Ending
                # the turn the same way an empty transcription does: the
                # wave goes back to listening and he never knew.
                print("(no era para él)", file=sys.stderr, flush=True)
                machine.error("")
                return
            await client.send_chat(spoken, wake=wake.named)

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
                say(clause)

        def on_done(_ms: int) -> None:
            # He has answered, so the next sentence needs no name for a
            # while: a conversation is not a sequence of commands.
            wake.answered(time.monotonic())
            for clause in chunker.flush():
                print(f"  dice: {clause}", file=sys.stderr, flush=True)
                say(clause)
            machine.done()

        def on_error(message: str) -> None:
            if message:
                say(message)
            _apply_error_to_wake_window(wake, message, time.monotonic())
            machine.error(message)

        def on_photo(path: str, camera: str) -> None:
            # Straight to the GTK thread. Everything else the gateway
            # sends goes through the turn machine; a photo does not — it
            # is not part of what he says, and it must appear whether or
            # not a turn is in flight (a reminder can push one).
            print(f"foto: {camera} -> {path}", file=sys.stderr, flush=True)
            GLib.idle_add(band.show_photo, path, camera)

        def on_live_open(
            camera: str, epoch: int, extradata: bytes, w: int, h: int
        ) -> None:
            # Opening resizes the window, so it crosses through idle_add
            # like on_photo does.
            print(f"vídeo: {camera} ({w}x{h})", file=sys.stderr, flush=True)
            GLib.idle_add(band.live_open, camera, epoch, extradata, w, h)

        # Counted per view, printed once: "the gateway is sending" and
        # "the band is painting" are separate claims, and a band that
        # opens and stays empty is the gap between them. Measured
        # 2026-08-26, when it was.
        arrived = {"epoch": 0, "n": 0}

        def on_live_frame(epoch: int, packet: bytes) -> None:
            # Deliberately NOT idle_add: this fires up to 25 times a
            # second, and `PhotoArea.live_frame` is thread-safe and never
            # blocks — see its docstring.
            if epoch != arrived["epoch"]:
                arrived["epoch"], arrived["n"] = epoch, 0
            arrived["n"] += 1
            if arrived["n"] == 1:
                print(
                    f"vídeo: primer paquete, {len(packet)} B",
                    file=sys.stderr,
                    flush=True,
                )
            band.live_frame(epoch, packet)

        def on_live_end(epoch: int, reason: str) -> None:
            print(f"vídeo terminado: {reason}", file=sys.stderr, flush=True)
            GLib.idle_add(band.live_end, epoch, reason)

        client.on_token = on_token
        client.on_done = on_done
        client.on_error = on_error

        def on_console(text: str) -> None:
            # Straight to the GTK thread, like a photo: it is not part
            # of the turn and must appear whether or not one is running.
            GLib.idle_add(window.write_console, text)

        client.on_console = on_console

        def on_console_done() -> None:
            # Only starts the clock; the console decides when to go, and
            # anything else arriving cancels it.
            GLib.idle_add(window.finish_console)

        client.on_console_done = on_console_done

        def on_console_reset() -> None:
            GLib.idle_add(window.clear_console)

        client.on_console_reset = on_console_reset
        client.on_photo = on_photo
        client.on_live_open = on_live_open
        client.on_live_frame = on_live_frame
        client.on_live_end = on_live_end

        # ── the microphone, always open ───────────────────────────────
        detector = UtteranceDetector(SileroDetector())

        def on_frame(frame: bytes) -> None:
            if hotword.heard(frame):
                # He was called by name. Open the conversation exactly as
                # an answer does, and let the utterance the VAD is
                # already collecting through when it closes.
                print("oye su nombre", file=sys.stderr, flush=True)
                wake.answered(time.monotonic())
            elif _HOTWORD_TRACE and hotword.last_score >= _HOTWORD_TRACE:
                print(f"hotword: {hotword.last_score:.2f}", file=sys.stderr, flush=True)
            if not wave.switches.mic_on:
                # The microphone switch on the strip. The stream stays
                # open — closing PortAudio from this callback is the
                # segfault CLAUDE.md §2.8 is written around — and every
                # frame is dropped instead, which is the same thing from
                # the room's side. The detector is reset so a half-heard
                # sentence does not resume when it comes back on.
                if detector.speaking:
                    detector.reset()
                return
            if _MIC_GATE and player.busy and not detector.speaking:
                # No echo cancellation on this box: he is talking and
                # nobody has cut in, so drop the frame rather than let
                # his own voice, coming back through the room, start a
                # turn. The cost of this branch is that he cannot be
                # interrupted — see _MIC_GATE.
                return

            if _TRACE_MIC and player.busy:
                # While HE is talking: what the microphone is actually
                # picking up, and whether the detector thinks somebody
                # is speaking. This is the only place that can answer
                # "why can I not interrupt him".
                import numpy as _np

                _s = _np.frombuffer(frame, dtype=_np.int16).astype(_np.float32)
                _rms = float(_np.sqrt(_np.mean((_s / 32768.0) ** 2)))
                _trace["n"] += 1
                if _trace["n"] % 15 == 0:
                    print(
                        f"mic mientras habla: rms {_rms:.4f} "
                        f"detector={'habla' if detector.speaking else 'silencio'}",
                        file=sys.stderr,
                        flush=True,
                    )

            if _BARGE_RMS > 0 and player.busy and not detector.speaking:
                import numpy as _np

                _s = _np.frombuffer(frame, dtype=_np.int16).astype(_np.float32)
                if float(_np.sqrt(_np.mean((_s / 32768.0) ** 2))) < _BARGE_RMS:
                    # Too quiet to be somebody talking over him: his own
                    # voice, back through the room. Dropped rather than
                    # fed to the detector, which would otherwise start a
                    # turn and interrupt him mid-sentence — measured,
                    # and reported as "ahora se autointerrumpe".
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

        def _load_hotword() -> None:
            # Sub-second, but on its own thread anyway: it is a model
            # load, and the GTK loop must not wait for one.
            if not _HOTWORD_MODEL:
                return
            try:
                hotword.load()
            except Exception as exc:
                # Losing the acoustic detector costs the wake word its
                # first line of defence, not the strip: `wake.py`'s
                # filter over the transcript still runs.
                print(f"hotword NO cargó: {exc!r}", file=sys.stderr, flush=True)
                return
            print(
                f"oído para '{_HOTWORD_MODEL}' (umbral {_HOTWORD_SENSITIVITY})",
                file=sys.stderr,
                flush=True,
            )

        threading.Thread(target=_load_whisper, daemon=True).start()
        threading.Thread(target=_load_hotword, daemon=True).start()

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


def _feed_live_file(path: str, area: PhotoArea) -> None:
    """Push a local video file into the band, as if the gateway had.

    The counterpart of `_feed_fake_mic`: no gateway, no camera, only the
    band, the decoder and (once the input region lands) the X11 region —
    the way `SAMANTHA_WIDGET_PHOTO` lets the thumbnail half be built and
    photographed with neither.

    Runs on its own thread so opening the file and pacing the packets
    never touches the GTK main loop. `live_open`/`live_end` resize the
    window, so — exactly like the gateway's own wiring — they cross
    through `idle_add`; `live_frame` does not, because the real path
    never does either.
    """
    import time

    import av

    print(f"vídeo de prueba: {path}", file=sys.stderr, flush=True)
    try:
        container = av.open(path)
        stream = container.streams.video[0]
        extradata = bytes(stream.codec_context.extradata or b"")
        width = int(stream.codec_context.width)
        height = int(stream.codec_context.height)
        rate = float(stream.average_rate or 15)
    except Exception as exc:
        print(f"vídeo de prueba no abrió: {exc!r}", file=sys.stderr, flush=True)
        return

    GLib.idle_add(area.live_open, "prueba", 1, extradata, width, height)

    period = 1.0 / rate if rate > 0 else 1.0 / 15.0
    next_at = time.monotonic()
    sent = 0
    try:
        for packet in container.demux(stream):
            data = bytes(packet)
            if not data:
                # The flush packet demux() yields at end of stream.
                continue
            area.live_frame(1, data)
            sent += 1
            next_at += period
            delay = next_at - time.monotonic()
            if delay > 0:
                time.sleep(delay)
    except Exception as exc:
        # A mid-stream failure here must still reach live_end — the real
        # camera tap can drop out mid-view too, and the alternative is
        # the band stuck open at 900x480 on a frozen frame with no way
        # to tell it apart from a genuinely live one.
        print(f"vídeo de prueba falló a mitad: {exc!r}", file=sys.stderr, flush=True)
    finally:
        container.close()
    print(f"vídeo de prueba: {sent} paquetes enviados", file=sys.stderr, flush=True)
    GLib.idle_add(area.live_end, 1, "asked")


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
