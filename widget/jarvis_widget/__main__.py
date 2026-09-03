"""Entry point: python -m jarvis_widget.

Three threads and one rule. The GTK main thread owns every widget; one
asyncio thread owns the WebSocket and the HTTP client to CosyVoice;
PortAudio's callback thread does nothing but push frames. Everything
that has to reach the UI goes through GLib.idle_add, and that is the
only bridge there is.
"""

from __future__ import annotations

import asyncio
import os
import signal
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
    from .ficha import FichaModel
    from .photo_area import PhotoArea

# Set to any of the four state names to freeze the wave there and skip
# the voice loop entirely — how each state gets photographed, since
# xdotool is not installed and a keystroke cannot be sent.
_DEMO_STATE = os.environ.get("JARVIS_WIDGET_STATE")

# Skip opening the microphone. On a box with no microphone plugged in
# there is nothing to open, and it makes the difference between "she
# cannot hear" and "the process is broken" visible in one variable.
_NO_MIC = os.environ.get("JARVIS_WIDGET_NO_MIC") == "1"

# Say this once, a few seconds after starting, and show the speaking
# wave while it plays. The only way to hear the widget's real voice path
# — its own threads, its own queue, its own player — on a machine with
# no microphone, where no turn can ever begin.
_SAY_ON_START = os.environ.get("JARVIS_WIDGET_SAY")

# Speak this INTO the widget, as if into a microphone: it is synthesised,
# resampled to 16 kHz and pushed through the same on_frame the real
# microphone calls. Everything after that is real — Silero, Whisper, the
# WebSocket to Hermes, and her reply spoken back. Only the air is faked.
_FAKE_MIC_TEXT = os.environ.get("JARVIS_WIDGET_FAKE_MIC")
# His name, and how long a conversation stays open after he answers.
_WAKE_WORD = os.environ.get("JARVIS_WIDGET_WAKE_WORD", "jarvis")
# Hear his name instead of reading it (user, 2026-08-26). Empty disables
# the acoustic detector and leaves only `wake.py`'s filter over the
# transcript. `JARVIS_WIDGET_HOTWORD_SENSITIVITY` moves the threshold;
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
_HOTWORD_MODEL = os.environ.get("JARVIS_WIDGET_HOTWORD", "")
# Diagnostic: log what the microphone hears WHILE he is speaking.
_TRACE_MIC = os.environ.get("JARVIS_WIDGET_TRACE_MIC") == "1"

# How loud the room has to be, WHILE he is speaking, before a frame may
# start a turn.
#
# Until 2026-09-01 this was 0.05 and was asked to separate his own echo
# from a person, which the measurements below show it cannot do:
#
#   the user's voice                            0.054-0.088
#   his echo, speakers moved away, volume 0.50  0.027-0.035
#   his echo, speakers beside it, volume 0.54   0.178  ← louder than a
#       person, and no threshold survives that
#
# It is now a SILENCE floor and nothing more — separating sound from no
# sound, which any scalar can do. Whether a sound is him or somebody
# else is decided on words, in `build_is_a_person`.
try:
    _BARGE_RMS = float(os.environ.get("JARVIS_WIDGET_BARGE_RMS", "0.01"))
except ValueError:
    _BARGE_RMS = 0.01
_trace = {"n": 0}
# Whether he was speaking on the previous frame, so `.room` can be reset
# once when he stops rather than thirty-one times a second.
_busy = {"was": False}
# Whether the microphone was on for the previous frame, so `.turn` can be
# cleared once when it is switched off rather than thirty-one times a
# second. `Stream.reset()` constructs a recognizer.
_mic = {"was_on": True}
try:
    _HOTWORD_SENSITIVITY = float(
        os.environ.get("JARVIS_WIDGET_HOTWORD_SENSITIVITY", "")
    )
except ValueError:
    _HOTWORD_SENSITIVITY = HOTWORD_SENSITIVITY
# Log every score above this, to calibrate against a real voice.
try:
    _HOTWORD_TRACE = float(os.environ.get("JARVIS_WIDGET_HOTWORD_TRACE", ""))
except ValueError:
    _HOTWORD_TRACE = 0.0

# Start with these switches already off: "mic", "voice", or both. The
# counterpart of JARVIS_WIDGET_STATE for the two glyphs at the end of
# the strip — the struck-through state cannot be photographed otherwise,
# because there is no way to send a click to this window (xdotool is not
# installed, CLAUDE.md §5).
_SWITCHES_OFF = {
    s.strip() for s in os.environ.get("JARVIS_WIDGET_SWITCHES", "").split(",")
}
try:
    _WAKE_WINDOW = float(os.environ.get("JARVIS_WIDGET_WAKE_WINDOW", ""))
except ValueError:
    _WAKE_WINDOW = WINDOW_SECONDS

# Show these photos (comma-separated paths) a couple of seconds after
# starting, exactly as if the gateway had pushed them. The only way to
# photograph the band on a box where making him actually look at a
# camera takes a whole live turn — the counterpart of JARVIS_WIDGET_SAY
# for the half of him you can see.
_SHOW_ON_START = os.environ.get("JARVIS_WIDGET_PHOTO")

# Feed the band a local video file as if the gateway had pushed it. The
# counterpart of JARVIS_WIDGET_PHOTO for the half of him that moves:
# the band, the decoder and the input region, with no gateway and no
# camera in the room.
_LIVE_ON_START = os.environ.get("JARVIS_WIDGET_LIVE")

# Write these lines into the strip's console a couple of seconds after
# starting, as if something working had produced them. The counterpart
# of JARVIS_WIDGET_PHOTO and _LIVE for the third thing the strip can
# show — separate lines with "\n", or a path to a file to read.
_CONSOLE_ON_START = os.environ.get("JARVIS_WIDGET_CONSOLE")

# Write every utterance the VAD closes to this directory as a WAV.
# Diagnostic only: when a transcription comes back as nonsense there is
# no way to tell from the text whether the audio was bad or Whisper was.
_DUMP_DIR = os.environ.get("JARVIS_WIDGET_DUMP")

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
_MIC_GATE = os.environ.get("JARVIS_WIDGET_MIC_GATE") == "1"


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


def _apply_asking_to_wake(wake: WakeWord, open_: bool, now: float) -> None:
    """Hold the wake window open while something waits for an answer.

    The gateway sends an `asking` frame when the code assistant's own
    question, a gate or the closing checkpoint starts waiting, and
    another when it stops. In between, an unnamed sentence must still
    reach the gateway: the v2 design assumed the 30-second no-name
    window covered this, and it does not — a gate waits 300 s, a
    checkpoint 600 s, and a held question has no clock at all. Past 30 s
    the answer was dropped by `wake.heard` before `_should_divert` ever
    saw it, and saying his name instead sets `wake=True`, which is
    deliberately never diverted. There was then no spoken sentence that
    could answer at all.

    Takes `wake` and `now` rather than reading them from a closure for
    the reason `_apply_error_to_wake_window` does: the whole decision,
    not only its predicate, can then be driven from a test with a real
    `WakeWord` and no GTK app.
    """
    if open_:
        wake.hold(now)
    else:
        wake.release()


def _apply_ficha_frame(
    model: "FichaModel",
    area,
    md: str,
    tipo: str,
    fuente: str,
    correcta: str | None,
    elegida: str | None,
    now: float,
) -> None:
    """A card frame arrived from the gateway: update the state, then draw it.

    Pulled out of the closure `on_ficha` builds so the whole decision —
    not just `FichaModel.mostrar`'s predicate — can be driven from a
    test with a real `FichaModel` and a fake area, the way
    `_apply_asking_to_wake` does for the wake window. `area` is not
    typed as `FichaArea`: a test hands it a plain object recording
    calls, and the real one is imported lazily (it carries `gi`).
    """
    model.mostrar(md, tipo, fuente, correcta, elegida, now=now)
    _dibujar_ficha(model, area)


def _dibujar_ficha(model: "FichaModel", area) -> None:
    """Draw whatever page the model is on, or nothing when it is empty."""
    area.mostrar(
        model.md_pagina,
        model.tipo,
        model.fuente,
        model.correcta,
        model.elegida,
        model.height,
        pagina=model.pagina,
        paginas=model.paginas,
    )


def _apply_ficha_tick(model: "FichaModel", area, now: float) -> None:
    """One second passing on the card's clock.

    Redraws only when `FichaModel.tick` says the strip's height actually
    has to change — the same convention `PhotoModel` set. Skipping the
    redraw otherwise is not an optimisation here: it is what keeps this
    from fighting `_apply_ficha_frame` over a card that just arrived in
    the same tick.
    """
    if model.tick(now=now):
        _dibujar_ficha(model, area)


def _apply_ficha_click(model: "FichaModel", area, now: float) -> None:
    """A press on the card: the next page, or away on the last one.

    Redraws ALWAYS, unlike the tick. `FichaModel.click` returns whether
    the strip's HEIGHT changed, which is what the window needs — but a
    page turn changes the CONTENT whether or not the band resizes, and
    two pages of the same length would otherwise leave the first one on
    screen forever.
    """
    if not model.visible:
        # Nothing up: a press on empty air is not a gesture at all.
        return
    model.click(now=now)
    _dibujar_ficha(model, area)


class VoskSwitch:
    """Vosk's on/off switch, and the only thing that ever throws it.

    The invariant this whole feature is built on is **failure is
    silence, never deafness**: if the engine misbehaves he waits the old
    1.2 s and interrupts on the old terms, but the microphone keeps
    working. Nothing in `endpoint.py` can promise that on its own —
    `Stream.push` runs `AcceptWaveform` plus `json.loads`, and
    `Stream.reset` constructs a `KaldiRecognizer`. Either can raise (a
    truncated model, a memory failure, a version mismatch), and an
    exception raised there propagates out of the frame callback into
    `audio.py`'s `_pump`, which calls it OUTSIDE its own `try`. The
    thread returns, the microphone is never read again, and he is deaf
    while looking perfectly healthy — with one traceback in the journal.
    That is not hypothetical: it is exactly how a Whisper model that
    would not fit cost three days on 2026-08-27 (CLAUDE.md §2.5).

    So every Vosk call the microphone thread makes goes through `run()`.
    The first failure takes the feature out of the path for good — off
    is a state it never comes back from, because a recognizer that has
    started raising has no reason to stop — and says so ONCE, not
    thirty-one times a second.
    """

    def __init__(self, on: bool) -> None:
        self.on = on

    def alive(self) -> bool:
        """For `build_may_close` and `build_is_a_person`, which hold the
        streams directly and must fall back the moment this goes off."""
        return self.on

    def run(self, call, *args) -> None:
        """One Vosk call. Never raises, whatever the engine does."""
        if not self.on:
            return
        try:
            call(*args)
        except Exception as exc:
            self.on = False
            print(
                f"endpointing apagado, Vosk falló: {exc!r}",
                file=sys.stderr,
                flush=True,
            )


def build_may_close(stream, rule, alive=lambda: True):
    """The question `vad.py` asks at 0.35 s of quiet.

    `stream` is the `.turn` stream, or None when Vosk did not load.
    `alive` is `VoskSwitch.alive`, which goes False the first time the
    engine raises anywhere — this holds the stream directly, so without
    it a switched-off Vosk would still be questioned here.

    Answers False for every reason a question can go wrong — no model, a
    switch thrown, a raising engine, nothing heard yet — because False is
    exactly today's behaviour and the 1.2 s threshold is still
    underneath it.
    """

    def may_close() -> bool:
        if stream is None or not alive():
            return False
        try:
            return rule.looks_complete(stream.partial())
        except Exception as exc:
            print(f"endpointing falló: {exc!r}", file=sys.stderr, flush=True)
            return False

    return may_close


def build_is_a_person(stream, echo, alive=lambda: True):
    """While HE is talking: is this sound somebody else, or his own echo?

    `stream` is `VoskPartials.room` — the one fed ONLY while he speaks —
    or None when Vosk did not load. `alive` is `VoskSwitch.alive`: once
    the engine has raised anywhere, this stream is no longer being fed,
    so its words are stale and the answer must go back to True.

    Before 2026-09-01 this was a loudness threshold, and it could not
    work. The user's voice measures RMS 0.054-0.088; his own echo with
    the speakers beside the microphone measures 0.178 — LOUDER than the
    person — so no threshold separates them, and with the speakers moved
    away a person cleared the gate by 0.004. Speaking normally instead of
    loudly was enough to stop existing, which is exactly what was
    reported: "no se calla, sigue hablando".

    Words settle it where volume cannot, using the unfair advantage
    `echo.py` already has: the widget knows what it just said. Anything
    left after his own lines are cut out is somebody else.

    Cost, stated: ~300 ms of speech must reach Vosk before there are
    words to judge, against the 32 ms of a single frame. He talks a
    little longer over an interruption than the old gate did in the
    cases where the old gate worked at all.
    """

    def is_a_person(now: float) -> bool:
        if stream is None or not alive():
            # No Vosk: back to the old world, where the RMS floor is the
            # only gate. Erring towards interrupting, because refusing to
            # is the bug this replaces.
            return True
        try:
            heard = stream.partial()
        except Exception:
            return True
        if not heard.strip():
            return False
        return bool(echo.clean(heard, now).strip())

    return is_a_person


def _room_bookkeeping(was_busy: bool, busy: bool) -> tuple[bool, bool]:
    """One frame's worth of `.room`'s busy/quiet housekeeping.

    Returns `(should_reset, next_was_busy)`. Extracted as the SINGLE
    decision the callback makes about `.room`'s lifecycle, so a whole
    SEQUENCE of frames can be driven through it in a test — with no
    player, no detector, no audio — and the property that matters
    checked directly: reset fires once on the frame busy genuinely ends,
    never mid-reply, never mid-interruption.

    Round 1 fixed firing on every frame of an interruption in progress
    (`player.busy` and `detector.speaking` both True): this function
    depends on neither the branch structure above it nor
    `detector.speaking`, only on `busy` going True → False, so that
    class of bug cannot recur here.

    Round 2's CRITICAL bug lived one level up, in the CALLER: the
    assignment feeding `next_was_busy` back into `_busy["was"]` sat below
    a branch that returns early on every frame of an ordinary,
    uninterrupted reply (the quiet frame and the his-own-echo frame both
    return before reaching it) — so across a whole reply `_busy["was"]`
    was never actually updated, the reset never fired, and `.room` grew
    without bound until `EchoFilter`'s 45 s window no longer recognised
    its own contents as his — the exact regression this task exists to
    prevent, arriving from the fix meant to guard against it. The
    contract this function makes explicit — call it once, unconditionally,
    before anything can return — is what closes that.
    """
    return (was_busy and not busy, busy)


def _turn_bookkeeping(was_on: bool, is_on: bool) -> tuple[bool, bool]:
    """(should_reset, next_was_on) — the mic-on→off transition only.

    Same shape as `_room_bookkeeping`, for the same reason: before this,
    `partials.turn.reset()` in the mic-off branch was nested under
    `if detector.speaking:`, which happened to bound it to once by
    accident — `detector.reset()` on the same path cleared
    `detector.speaking`, so the branch stopped re-entering. Un-nesting it
    (so `.turn`'s preroll, held before the detector ever calls anything
    speech, is cleared even when the mic goes off before that) removed
    that accidental bound: with nothing else guarding it, the reset fired
    on EVERY frame for as long as the switch stayed off — ~31
    `KaldiRecognizer` constructions a second on the PortAudio thread,
    indefinitely. This is the transition guard that was missing, in the
    same shape as `.room`'s.
    """
    return (was_on and not is_on, is_on)


class TurnOrigin:
    """Whether the turn in flight was asked for on a phone, and by which.

    Nothing else in the process knows. `dispatch` is one function
    serving two mouths, and until this existed it asked
    `remote_desk.busy` — "is SOME phone holding the turn" — which is a
    different question and answers it wrongly in both directions:

    - a sentence said at the DESK while a phone held the turn skipped
      the wake word, so for the whole of every phone turn the room was
      an open microphone dispatching turns to an agent that holds a
      terminal;
    - and a desk turn settling — an empty transcription and an
      all-echo one, the two commonest desk outcomes — called
      `route_home()` and `release()`, which freed the phone's claim
      MID-ANSWER and sent every clause queued after it into the room. A
      question asked privately on a phone, finished out loud in the
      house.

    One turn runs at a time, so one slot each is enough and no turn
    identity has to travel over the wire. `pending` is written the
    instant a phone's audio is handed up and read-and-cleared by
    `dispatch`; `current` is what that turn is, for as long as it is
    settling — `on_done` and `on_error` arrive long after `dispatch`
    has returned. Both `None` means the desk, which is also what an
    UNPROMPTED turn is: a cron reminder or a camera alert now settles
    without touching a phone's claim, which it used to take away.
    """

    def __init__(self) -> None:
        self.pending: object | None = None
        self.current: object | None = None

    def arriving(self, endpoint: object) -> None:
        """A phone's utterance is on its way into `dispatch`."""
        self.pending = endpoint

    def take(self) -> object | None:
        """The endpoint this turn belongs to, or None for the desk."""
        self.current = self.pending
        self.pending = None
        return self.current

    def settle(self) -> object | None:
        """The endpoint the turn being settled belonged to, and forget it."""
        current, self.current = self.current, None
        return current


def spoken_text(
    text: str, phone: object | None, wake: WakeWord, now: float
) -> str | None:
    """What he was actually told, or None if it was not for him.

    A phone's press IS the address — the button did what the wake word
    does at the desk — so a phone turn skips it. A DESK utterance always
    goes through the wake word, whatever any phone is doing: the two
    microphones are in different rooms and only one of them was pressed.
    """
    if phone is not None:
        return text
    return wake.heard(text, now)


def settle_turn(phone: object | None, speaker, desk) -> None:
    """Give the voice and the phone's claim back — if it was a phone's.

    Called on every way a turn can end. A desk turn settles nothing on
    the phone side: it never held the claim, and taking it away is how
    an empty desk transcription used to end a phone's answer halfway
    through. The endpoint is passed to `release` so its own identity
    guard applies too, in case the claim has moved on since.
    """
    if phone is None:
        return
    speaker.route_home()
    desk.release(phone)


async def _serve_quietly(coro) -> None:
    """Await `coro`, and survive it failing.

    `serve()` opens sockets and may make a certificate: the interface
    not up yet at boot, PORT already busy, openssl missing. None of
    those is a reason for the strip, the desk microphone and the
    gateway to go with it. Spawned bare, the exception is also never
    retrieved — asyncio reports it only if and when the task is
    collected — so the phone surface would be simply absent, with
    nothing said anywhere.
    """
    try:
        await coro
    except Exception as exc:
        print(f"móvil: sin superficie ({exc!r})", file=sys.stderr, flush=True)


class JARVISApp(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id="com.horelvis.jarvis.widget")
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
        from .ficha import FichaModel
        from .ficha_area import FichaArea
        from .photo_area import PhotoArea
        from .wave import WaveArea
        from .window import StripWindow

        window = StripWindow(self)
        wave = WaveArea()
        window.set_content(wave)

        # The lesson's card: a question, a syllabus or something being
        # explained. It needs no wiring to `client` to be dismissed — a
        # press is decided entirely by the model and the area, so it is
        # wired here rather than inside `_start_voice_loop`. Set BEFORE
        # the band, below: `set_band`/`set_ficha` both prepend, so
        # whichever is called second ends up outermost, and the band
        # belongs there — a photo or a live view is a transient
        # interruption that arrives unbidden and leaves on its own,
        # while the card is the content of something the user
        # deliberately started and stays while they read it, so it
        # belongs nearer the wave.
        ficha_model = FichaModel()
        ficha_area = FichaArea(on_resize=window.resize_ficha)
        window.set_ficha(ficha_area)

        def on_ficha_click() -> None:
            _apply_ficha_click(ficha_model, ficha_area, time.monotonic())

        window.on_ficha_click = on_ficha_click

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
            wave.set_task_count(int(os.environ.get("JARVIS_WIDGET_TASKS", "0")))
            wave.model.set_level(0.7 if state in _LIVE else 0.0)
            return

        self._start_voice_loop(wave, band, window, ficha_model, ficha_area)

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

    def _start_voice_loop(self, wave, band, window, ficha_model, ficha_area) -> None:
        import numpy as np

        from .audio import Microphone, Player, SpectrumAnalyser, describe_devices
        from .gateway import GatewayClient
        from .speech import (
            ClauseChunker,
            Speaker,
            is_system_message,
            unwrap_delivery,
        )
        from .stt import Transcriber, build_hint
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
        # The hint carries his name and the words this box actually
        # says, so Whisper stops inventing spellings of both — see
        # `stt.build_hint`.
        transcriber = Transcriber(hint=build_hint(_WAKE_WORD))
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
        # JARVIS_WIDGET_WAKE_WORD restores the "everything heard is for
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

        def set_bands(bands: list[float]) -> None:
            GLib.idle_add(wave.set_bands, bands)

        def on_utterance(pcm: bytes) -> None:
            loop.call_soon_threadsafe(lambda: self._spawn(dispatch(pcm)))

        machine = TurnMachine(
            on_state=set_state,
            on_level=set_level,
            on_utterance=on_utterance,
            on_interrupt=speaker.interrupt,
        )

        from .certs import lan_address
        from .remote import HOSTNAME, PORT, Enrolment, RemoteDesk, serve
        from .remote_auth import Guard, load_or_create_secret

        def on_remote_utterance(pcm: bytes, endpoint) -> None:
            """A phone released its button.

            Two things the desk path does are deliberately skipped, and
            for the same reasons `on_typed` skips them: the wake word (a
            button was pressed — he is being addressed) and the VAD (the
            button is the utterance boundary). The echo filter still
            runs inside `dispatch`, and costs nothing here because the
            phone's microphone is closed while he answers.

            The marker goes down immediately before the audio is handed
            up, and `dispatch` takes it: it is the only thing that tells
            that one function whether the mouth it is serving is in the
            room or in somebody's hand.
            """
            speaker.route_to(endpoint)
            origin.arriving(endpoint)
            machine.heard(pcm)

        origin = TurnOrigin()
        remote_desk = RemoteDesk(
            on_utterance=on_remote_utterance,
            # The claim and the voice go home together, on every way a
            # claim can end — including the one nobody calls: a claim
            # that simply expires. Without it the sink went on pointing
            # at a phone that had dropped, and the next reply, to
            # anybody, was written into a dead socket while the room
            # heard nothing.
            on_release=lambda: speaker.route_home(),
        )
        # Closed until the QR is actually shown (below) — the welcome
        # page it points at hands the shared secret to whoever asks,
        # over plain HTTP, with no check of its own (remote.py).
        enrolment = Enrolment()

        async def dispatch(pcm: bytes) -> None:
            # Wrapped whole: `transcriber.transcribe` can raise (a
            # starved GPU has left him deaf before — CLAUDE.md §12,
            # 2026-08-30) and so can `client.send_chat`, the same reason
            # `on_typed`'s `_send` wraps its own call. Unlike a typed
            # turn, this one may be holding a phone's claim on
            # `remote_desk` with no expiry left to save it —
            # `_claimed_at` is already `None` by the time `dispatch`
            # runs — so an uncaught exception here would lock every
            # phone in the house out until the widget restarts.
            # Read and cleared at the top, and bound for the life of
            # this turn: everything below asks THIS, never
            # `remote_desk.busy` — see `TurnOrigin` for the two
            # different bugs that question caused.
            phone = origin.take()
            try:
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
                    # believed. Both end the turn quietly; neither is an
                    # error the user should hear about.
                    print("transcripción vacía", file=sys.stderr, flush=True)
                    machine.error("")
                    # A phone can reach this with nothing said (a press
                    # released instantly): without giving the turn back
                    # here too, it never reaches on_error and the desk
                    # stays locked to a phone that already fell silent.
                    # Only if it WAS the phone's turn, though — an empty
                    # desk transcription is the commonest event in the
                    # room, and it used to end a phone's answer halfway.
                    settle_turn(origin.settle(), speaker, remote_desk)
                    return
                print(f"→ {text}", file=sys.stderr, flush=True)
                text = echo.clean(text, time.monotonic())
                if not text.strip():
                    # All of it was him. Not a turn, and not an error.
                    print("(era su propio eco)", file=sys.stderr, flush=True)
                    machine.error("")
                    settle_turn(origin.settle(), speaker, remote_desk)
                    return
                # A phone's press IS the address, and ONLY a phone's.
                # This asked `remote_desk.busy` until 2026-09-01, which
                # made the room a wake-word-free microphone for the
                # whole of every phone turn — the "rare (both speaking
                # at once)" that ruling assumed was in fact every one of
                # them. Reversed on review.
                spoken = spoken_text(text, phone, wake, time.monotonic())
                if spoken is None:
                    # Somebody was talking in the room, not to him.
                    # Ending the turn the same way an empty transcription
                    # does: the wave goes back to listening and he never
                    # knew. Only ever reached at the desk — a phone turn
                    # never asks the wake word — but the origin is
                    # forgotten here too, or the NEXT turn to settle
                    # would inherit it.
                    print("(no era para él)", file=sys.stderr, flush=True)
                    machine.error("")
                    origin.settle()
                    return
                await client.send_chat(spoken, wake=wake.named)
            except Exception as exc:
                print(f"turno fallido: {exc!r}", file=sys.stderr, flush=True)
                machine.error("")
                settle_turn(origin.settle(), speaker, remote_desk)

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
            if machine.done():
                # Give the room — and any phone waiting its turn — back.
                # This is the recovery path for a held turn, not
                # bookkeeping: without it, a reply that hangs or crashes
                # locks every phone in the house out until the widget
                # restarts. Gated on the real settle, not on every
                # `done`: the gateway emits one after each of its own
                # system messages too (turn.py, one measured turn
                # carried six), and releasing on THAT one would send the
                # sink home and free the desk before the real tokens
                # ever arrive — a question asked on a phone, answered
                # out loud in the room.
                #
                # And gated on the ORIGIN of the turn being settled: a
                # desk turn gives nothing back, so an unprompted one — a
                # cron reminder, a camera alert — no longer takes a
                # phone's claim away either.
                settle_turn(origin.settle(), speaker, remote_desk)

        def on_error(message: str) -> None:
            if message:
                say(message)
            _apply_error_to_wake_window(wake, message, time.monotonic())
            machine.error(message)
            settle_turn(origin.settle(), speaker, remote_desk)

        def on_photo(path: str, camera: str) -> None:
            # Straight to the GTK thread. Everything else the gateway
            # sends goes through the turn machine; a photo does not — it
            # is not part of what he says, and it must appear whether or
            # not a turn is in flight (a reminder can push one).
            print(f"foto: {camera} -> {path}", file=sys.stderr, flush=True)
            GLib.idle_add(band.show_photo, path, camera)

        def on_ficha(
            md: str, tipo: str, fuente: str, correcta: str | None, elegida: str | None
        ) -> None:
            # Like `on_photo`: this does not go through the turn machine.
            # A card is not something he said.
            def dibujar() -> bool:
                _apply_ficha_frame(
                    ficha_model,
                    ficha_area,
                    md,
                    tipo,
                    fuente,
                    correcta,
                    elegida,
                    time.monotonic(),
                )
                return False  # GLib.SOURCE_REMOVE

            GLib.idle_add(dibujar)

        def _ficha_tick() -> bool:
            _apply_ficha_tick(ficha_model, ficha_area, time.monotonic())
            return True  # GLib.SOURCE_CONTINUE

        GLib.timeout_add_seconds(1, _ficha_tick)

        from pathlib import Path

        def _show_qr() -> bool:
            # The band already draws a PNG for the cameras; this is the
            # same gesture, not a new one — `remote.serve()` writes the
            # QR to this same path once at startup. `band` only exists
            # from `do_activate` onward, which is why this cannot sit
            # beside `_SWITCHES_OFF` and the other module-level switches
            # above: nothing named `band` exists there at all.
            #
            # The QR itself is harmless — it encodes only a LAN URL, no
            # secret — so its going away with the band's own fade
            # (`photo.FADE_S`, 15 s) is not what protects anything.
            # What DOES need bounding is the plain-HTTP page it points
            # at, which hands over the shared secret to whoever asks;
            # `enrolment.open_enrolment` starts that window at the exact
            # moment the QR becomes something a phone could scan, not at
            # `serve()`'s startup, so the window is not open for however
            # long the widget has simply been running.
            enrolment.open_enrolment(time.monotonic())
            band.show_photo(str(Path.home() / ".jarvis" / "enrol-qr.png"), "alta")
            return False  # GLib.SOURCE_REMOVE

        if os.getenv("JARVIS_WIDGET_SHOW_QR") == "1":
            # Shows the code a few seconds after startup — a shortcut for
            # exercising the path with no phone in the room. The normal
            # way in is the signal below, which needs no flag and no
            # restart.
            GLib.timeout_add_seconds(3, _show_qr)

        def _on_enrol_signal(*_args: object) -> None:
            """Open enrolment for a few minutes and show the code.

            A signal rather than a route: nothing on the network can send
            one, so the window cannot be opened by the people it exists
            to keep out. `systemctl --user kill -s USR1
            jarvis-widget.service` is the whole ritual.

            `add_signal_handler`'s callback runs on whatever thread is
            executing `loop.run_forever()` — the asyncio thread started
            below, never the GTK one — so, like `on_photo`, this crosses
            through `GLib.idle_add` rather than touching the band
            directly.
            """
            GLib.idle_add(_show_qr)

        loop.add_signal_handler(signal.SIGUSR1, _on_enrol_signal)

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

        def on_asking(open_: bool) -> None:
            # Not a turn and nothing drawn: it only decides whether an
            # unnamed sentence is still worth sending on. The gateway
            # holds the answer to the code assistant's question, and 30
            # seconds is not how long somebody takes to decide whether a
            # `git push` may run.
            print(
                "esperan respuesta" if open_ else "ya no esperan respuesta",
                file=sys.stderr,
                flush=True,
            )
            _apply_asking_to_wake(wake, open_, time.monotonic())

        client.on_asking = on_asking
        client.on_photo = on_photo
        client.on_ficha = on_ficha
        client.on_live_open = on_live_open
        client.on_live_frame = on_live_frame
        client.on_live_end = on_live_end

        # ── the microphone, always open ───────────────────────────────
        from .endpoint import CompletionRule, load_partials

        partials = load_partials()
        rule = CompletionRule()
        # Every Vosk call below goes through this, and the first failure
        # turns the feature off rather than killing the microphone
        # thread. See `VoskSwitch` for what that thread's death looks
        # like from outside: perfectly healthy, and deaf.
        vosk = VoskSwitch(partials is not None)
        print(
            "endpointing: activo" if partials else "endpointing: apagado",
            file=sys.stderr,
            flush=True,
        )
        detector = UtteranceDetector(
            SileroDetector(),
            may_close=build_may_close(
                partials.turn if partials else None, rule, vosk.alive
            ),
        )
        # Decided on words, not loudness — see `build_is_a_person`'s own
        # docstring for why a scalar could never do this job.
        is_a_person = build_is_a_person(
            partials.room if partials else None, echo, vosk.alive
        )
        # One analyser per source, because it holds the sliding window
        # and the two rates differ: 16 kHz here against the player's 24.
        mic_spectrum = SpectrumAnalyser(INPUT_RATE)

        def on_frame(frame: bytes) -> None:
            if hotword.heard(frame):
                # He was called by name. Open the conversation exactly as
                # an answer does, and let the utterance the VAD is
                # already collecting through when it closes.
                print("oye su nombre", file=sys.stderr, flush=True)
                wake.answered(time.monotonic())
            elif _HOTWORD_TRACE and hotword.last_score >= _HOTWORD_TRACE:
                print(f"hotword: {hotword.last_score:.2f}", file=sys.stderr, flush=True)
            # `.turn`'s on/off bookkeeping — computed every frame, on the
            # transition only, the same shape as `.room`'s below. Without
            # this, un-nesting the reset from `detector.speaking` (needed
            # because `.turn` holds preroll from before the detector ever
            # calls anything speech) leaves nothing bounding it: it would
            # fire, and construct a fresh `KaldiRecognizer`, on every
            # single frame for as long as the mic switch stayed off.
            _should_reset_turn, _mic["was_on"] = _turn_bookkeeping(
                _mic["was_on"], wave.switches.mic_on
            )
            # `.room`'s busy/quiet bookkeeping — computed and APPLIED
            # here, above EVERY branch that can return, which is the
            # whole of the contract `_room_bookkeeping`'s docstring asks
            # for. It sat below the mic-off branch until 2026-09-01, and
            # that branch strands it exactly as the busy branch did in
            # round 2: switch the mic off mid-reply and `_busy["was"]`
            # stops being updated, so the frame on which he actually
            # stops talking never resets `.room`. A second reply then
            # lands on top of the first, the first ages past
            # `EchoFilter`'s 45 s window, the residue stops matching, and
            # he interrupts himself with nobody in the room.
            # `audible`, not `busy`: `busy` goes False for ~0.36 s between
            # clauses while CosyVoice makes the next one and the speaker is
            # still sounding. Resetting `.room` there would throw away the
            # echo context in the middle of his own sentence, and gating on
            # it left those gaps with no gate at all — the feedback loop of
            # 2026-09-01. `audio.py:audible` carries the measurement.
            _audible = player.audible(time.monotonic())
            _should_reset_room, _busy["was"] = _room_bookkeeping(_busy["was"], _audible)
            if vosk.on and _should_reset_room:
                # He just stopped. Whatever `.room` collected was his; the
                # next answer starts from nothing.
                vosk.run(partials.room.reset)
            if not wave.switches.mic_on:
                # The microphone switch on the strip. The stream stays
                # open — closing PortAudio from this callback is the
                # segfault CLAUDE.md §2.8 is written around — and every
                # frame is dropped instead, which is the same thing from
                # the room's side. The detector is reset so a half-heard
                # sentence does not resume when it comes back on.
                if detector.speaking:
                    detector.reset()
                if vosk.on and _should_reset_turn:
                    # `.turn` is fed preroll before the detector ever
                    # calls anything speech (see the comment where it is
                    # pushed, below) — NOT nested under
                    # `detector.speaking` for that reason: the mic can go
                    # off mid-preroll, before the detector has said
                    # anything, and those words must not survive into the
                    # next turn either. Guarded by the transition flag so
                    # it fires once per toggle, not every frame the
                    # switch stays off.
                    vosk.run(partials.turn.reset)
                return
            if _MIC_GATE and _audible and not detector.speaking:
                # No echo cancellation on this box: he is talking and
                # nobody has cut in, so drop the frame rather than let
                # his own voice, coming back through the room, start a
                # turn. The cost of this branch is that he cannot be
                # interrupted — see _MIC_GATE.
                return

            if _TRACE_MIC and _audible:
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

            if _audible and not detector.speaking:
                # He is talking and nobody has cut in yet. Feed `.room`
                # FIRST: every path below can return, and a stream that
                # is only fed after the gates never hears the sentence
                # the gates are asking about.
                if vosk.on:
                    vosk.run(partials.room.push, frame)

                import numpy as _np

                _s = _np.frombuffer(frame, dtype=_np.int16).astype(_np.float32)
                _rms = float(_np.sqrt(_np.mean((_s / 32768.0) ** 2)))
                if _BARGE_RMS > 0 and _rms < _BARGE_RMS:
                    # Silence. Not him, not anybody.
                    return
                if not is_a_person(time.monotonic()):
                    # Loud enough, but the words are his own coming back
                    # through the room. Dropped rather than fed to the
                    # detector, which would start a turn and interrupt
                    # him mid-sentence — reported once as "ahora se
                    # autointerrumpe".
                    return

            if vosk.on:
                # The same frames the detector is holding, so the rule is
                # asked about exactly that audio. Fed even before the
                # detector calls it speech: the preroll matters here for
                # the same reason it matters for the wake word (§2.8).
                #
                # Reached while he is NOT speaking, AND on the frame that
                # interrupts him: the busy branch above returns early only
                # for silence or his own echo (`is_a_person` false). A
                # frame judged to be a person falls through it with
                # `audible` still True and lands here, so `.turn`
                # starts hearing the interruption on the same frame
                # `.room` judged it — it does not wait for `audible`
                # to clear.
                vosk.run(partials.turn.push, frame)

            was_speaking = detector.speaking
            utterance = detector.push(frame)
            if detector.speaking and not was_speaking:
                machine.speech_started()
            if detector.speaking:
                samples = np.frombuffer(frame, dtype=np.int16).astype(np.float32)
                samples /= 32768.0
                rms = float(np.sqrt(np.mean(samples**2)))
                set_level(min(1.0, rms * 6))
                # And the SPECTRUM, which is what makes the bars belong
                # to the voice. Without it `wave.set_level` above is the
                # only thing the strip hears, and `BarsModel.set_level`
                # says what that looks like in its own docstring: a
                # "fallback for callers with no spectrum" that moves
                # every band together in a fixed arch. Reported
                # 2026-08-30 as "una onda uniforme que nada tiene que
                # ver con la voz". It must come AFTER set_level, which
                # feeds both models and would otherwise overwrite this.
                set_bands(mic_spectrum.analyse(samples))
            if utterance is not None:
                machine.heard(utterance)
            if was_speaking and not detector.speaking and vosk.on:
                # The detector has just reset itself, so `.turn` must
                # too. Keyed on the DETECTOR rather than on `utterance`,
                # which is not the same question: `vad.py`'s `_emit`
                # resets and returns None when the speech was shorter
                # than 0.4 s, so a cough used to leave its words in
                # `.turn` for the next sentence to inherit — and those
                # words then answer `may_close` about audio that is no
                # longer there. `detector.speaking` only ever goes True →
                # False inside `reset()`, which makes this exactly "the
                # detector forgot; forget with it".
                vosk.run(partials.turn.reset)

        def _boot() -> None:
            # All three run for the lifetime of the process, on the loop
            # that owns them.
            self._spawn(client.run())
            speaker.start()
            secret = load_or_create_secret()
            # Both ways in: the name, and the address it resolves to.
            # mDNS is not guaranteed on a house network — the LAN IP is
            # the design's own fallback — and a browser sends the origin
            # it was loaded from, so a Guard bound to the name alone
            # refuses every connection the fallback ever makes.
            guard = Guard(
                secret,
                f"https://{HOSTNAME}:{PORT}",
                f"https://{lan_address()}:{PORT}",
            )
            self._spawn(_serve_quietly(serve(remote_desk, guard, enrolment, loop)))

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
    the way `JARVIS_WIDGET_PHOTO` lets the thumbnail half be built and
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
    return JARVISApp().run(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
