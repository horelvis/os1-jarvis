"""Entry point: python -m jarvis_widget.

Three threads and one rule. The GTK main thread owns every widget; one
asyncio thread owns the WebSocket and the HTTP client to CosyVoice;
PortAudio's callback thread does nothing but push frames. Everything
that has to reach the UI goes through GLib.idle_add, and that is the
only bridge there is.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import stat
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")

from gi.repository import Gdk, GLib, Gtk  # noqa: E402

from .vad import FRAME_SAMPLES, INPUT_RATE  # noqa: E402
from .hotword import SENSITIVITY as HOTWORD_SENSITIVITY  # noqa: E402
from .echo import EchoFilter  # noqa: E402
from .hotword import Hotword  # noqa: E402
from .personas import CASA, normalizar  # noqa: E402
from .wake import WINDOW_SECONDS, WakeWord  # noqa: E402
from .wave_model import WaveState  # noqa: E402

if TYPE_CHECKING:
    import numpy as np

    from .casa import Registro
    from .encuentro import Encuentro, Respuesta
    from .ficha import FichaModel
    from .photo_area import PhotoArea
    from .voz import Huellas

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


PERSONA_PENDIENTE = Path.home() / ".jarvis" / "enrolamiento.json"

# Where the house register and the passphrase live — the same
# `~/.jarvis` root every other module in this package uses
# (`vad.py`, `remote_auth.py`, `PERSONA_PENDIENTE` above). `casa.py`
# derives its own voiceprints directory (`voces/`) as a SIBLING of
# `RUTA_CASA`, so nothing here needs to name it separately.
RUTA_CASA = Path.home() / ".jarvis" / "casa.json"
RUTA_FRASE = Path.home() / ".jarvis" / "frase.txt"

# How long the new amo's name stays on the band after pairing closes,
# before it empties for good. Long enough to outlast the presentation he
# gives at that moment (`encuentro._TEXTO_PRESENTACION`, six clauses,
# ~25 s spoken through CosyVoice) and no longer: the band is zero pixels
# tall by default, and a name left up for ever would make it permanent
# furniture. Not a measurement of his speech — nothing reports when he
# stops talking (see `_vaciar_bienvenida`) — so it is deliberately
# generous rather than tight.
SEGUNDOS_BIENVENIDA_FINAL = 30


def _persona_pendiente(ruta: Path = PERSONA_PENDIENTE) -> str:
    """The person `tools/enrolar.py` asked to enrol, consumed once.

    Runs on the asyncio loop's SIGUSR1 handler, with nobody to catch a
    traceback and nothing that may block it — the same constraints
    `remote_auth._read_roster_file` is written against, and for the same
    reason: `stat` rules out a node whose `open()` could hang forever
    (a FIFO with no writer never raises, it just waits) before anything
    is opened at all.

    The file is removed on every way out of this function — found
    malformed, found empty, or read clean — so a second SIGUSR1 with
    nothing freshly written can never replay a name. A missing,
    unreadable or malformed file means `CASA`: never the owner, never
    whoever was enrolled last.
    """
    try:
        try:
            info = ruta.stat()
        except OSError:
            return CASA
        if not stat.S_ISREG(info.st_mode):
            return CASA
        try:
            datos = json.loads(ruta.read_text())
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return CASA
        if not isinstance(datos, dict):
            return CASA
        return normalizar(datos.get("persona"))
    finally:
        try:
            ruta.unlink()
        except OSError:
            pass


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


# `TurnOrigin` lived here until 2026-09-06 (task 14, round 2) — a class
# with a `pending` slot, written by `arriving()` on a phone's utterance
# and read-and-cleared by `take()` at the top of `dispatch`. It looked
# safe (a single value, cleared the instant it was read) but `arriving()`
# and `take()` were separated by two real scheduling hops in production
# — `loop.call_soon_threadsafe`, then the spawned task actually
# starting — and two phones are two concurrent handler tasks on the same
# loop, so a SECOND phone's `arriving()` landing before the FIRST
# phone's `dispatch` had reached `take()` was ordinary, not exotic. It
# crossed their identities: the first phone's turn settled holding the
# second phone's claim, and the second's sat forgotten until its own
# ceiling. Round 1 of this task had already removed a SECOND such slot
# (`current`, read by a now-gone `settle()`) in favour of resolving
# `on_done`/`on_error` fresh from each reply's own `chat_id`
# (`destino_de`) — but left this first one standing, with a docstring
# that called it safe.
#
# The fix is not a bigger or safer slot: it is not having one.
# `TurnMachine.heard(pcm, endpoint)` now takes the endpoint as an
# ordinary argument, bound to THIS `pcm` in THIS call, and passes it
# straight through `on_utterance`'s own closure into `dispatch` — a
# fresh pair, captured fresh, every time. Nothing is written anywhere
# for a second utterance to land in before the first is read. See
# `TurnMachine.heard`'s docstring for the mechanism and `on_utterance`
# below for where the pair is captured on its way to being scheduled.
#
# Two bugs this shape must keep closed, both measured on 2026-09-01
# against the OLDER `remote_desk.busy` design and pinned by
# `test_a_desk_utterance_while_a_phone_holds_the_turn_still_needs_his_name`
# and `test_a_desk_turn_settling_does_not_release_a_phones_claim`:
#
# - a sentence said at the DESK while a phone held a turn skipping the
#   wake word, leaving the room an open microphone in front of an agent
#   that holds a terminal;
# - a desk turn settling — an empty transcription and an all-echo one,
#   the two commonest desk outcomes — freeing a phone's claim
#   MID-ANSWER and finishing a private question out loud in the house.


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


def destino_de(remote_desk, chat_id: str | None) -> object | None:
    """The endpoint a reply belongs to, or `None` for the room.

    Resolved from the frame's own `chat_id` — the persona `dispatch`
    sent as `chat_id` when the turn began (task 9) — through
    `RemoteDesk.endpoint_for` rather than by reaching into its
    bookkeeping directly: the desk is the only thing that gets to
    decide whose claim is still live, and that question has to be
    answered in one place now that turns can end while audio for them
    is still being made.

    Called once per batch of clauses, at the moment they are about to
    be queued on the `Speaker` — never re-read afterwards, which is
    the whole of the fix for the defect CLAUDE.md §12 records on
    2026-09-01: reading the destination later, at SYNTHESIS time, let
    the turn end and the reply's sink move on first, and a question
    asked on a phone came out of the room instead.

    This resolves by PERSON, not by device — `RemoteDesk` keeps one
    claim per `persona` (`remote.py`'s `_claims`), and `endpoint_for`
    hands back whichever `Endpoint` currently holds that persona's
    claim. That is the same device only for as long as one device
    holds a given persona. Corrected 2026-09-06 (final review,
    CLAUDE.md): this used to say a phone dropping mid-answer is the
    only way a reply goes somewhere OTHER than where it was asked for
    — false whenever a SECOND device holds the same persona's claim.
    Reproduced: `papá`'s reply, mid-answer, resolved to `iphone-hija`,
    who received his private answer while his own phone received
    nothing.

    It is reachable TODAY, on this box, and not merely in theory:
    `remote_auth._adopted_or_fresh_secret()` deliberately carries the
    pre-upgrade `remote.token` forward as `casa`'s secret, so every
    iPhone enrolled before this branch — all three, in this house —
    authenticates as the SAME persona, `casa`. Enrolling each phone to
    its own person (`tools/enrolar.py <persona>`) is what closes this;
    it is operational, not a code change, and nothing here does it for
    you.

    A phone dropping mid-answer with nobody else holding its persona
    is the residue this docstring used to describe in full: this
    returns `None` and the REST of that reply is spoken in the room.
    That half is still known, deliberate residue (CLAUDE.md §12,
    2026-09-01) and this function does not try to fix it — see
    PROGRESS.md, task 12.
    """
    if not chat_id:
        return None
    return remote_desk.endpoint_for(chat_id)


def settle_turn(phone: object | None, desk) -> None:
    """Give the phone's claim back — if it was a phone's.

    Called on every way a turn can end. A desk turn settles nothing on
    the phone side: it never held the claim, and taking it away is how
    an empty desk transcription used to end a phone's answer halfway
    through. The endpoint is passed to `release` so its own identity
    guard applies too, in case the claim has moved on since.

    Used to also send the voice home (`speaker.route_home()`): with a
    single shared sink, giving up a claim and giving up the voice were
    the same event. They are not any more — `destino_de` resolves
    fresh from `remote_desk` on every batch of clauses, so a claim
    ending here is already enough; there is no separate sink left to
    reset.
    """
    if phone is None:
        return
    desk.release(phone)


def huellas_actualizadas(registro: "Registro", cache: dict[str, object]) -> "Huellas":
    """The register's voiceprints, re-read from disk only when
    `registro.amo` has changed since the last utterance — not on every
    one, which would mean reading every enrolled person's `.npy` file
    off disk on every single desk turn for a floor that essentially
    never moves once the house has its first amo: the founding act
    happens exactly once (`casa.Registro.emparejar`'s own docstring),
    so `amo` itself only ever transitions `None` -> a person id, a
    single time, for the life of this process.

    `cache` is passed in rather than read from a module-level global —
    the same reason `build_may_close`/`build_is_a_person` take their
    state as an argument instead of closing over one: a test can drive
    this with its own dict and never leak state into another test.
    """
    amo = registro.amo
    if cache.get("amo") != amo:
        cache["amo"] = amo
        cache["huellas"] = registro.huellas()
    return cache["huellas"]  # type: ignore[return-value]


def persona_de(
    phone: object | None, vector: "np.ndarray | None", huellas: "Huellas | None"
) -> str:
    """Who a desk utterance belongs to, or a phone's own identity.

    A phone's press already carries an identity that cannot lie — the
    button IS the address, the same reasoning `spoken_text` uses for
    skipping the wake word — so a phone's `persona` is returned
    directly and `vector`/`huellas` are never even consulted (voice
    identification on a phone is out of this plan's scope entirely —
    see `encuentro.py`'s own module docstring and the plan's "what part
    A does not do").

    At the desk, `CASA` covers every reason a voice cannot be
    attributed: nobody enrolled yet, nobody close enough, two people
    equally close (`voz.Huellas.quien`'s own three-in-one contract), or
    `vector` itself being `None` — an utterance too short to embed, a
    speaker model that never loaded, or one that raised when asked to
    run (`locutor.Locutor.vector` never raises; `None` is its whole
    failure mode). This function cannot and must not tell those apart:
    treating a broken embedder differently from an honest "I don't
    know" is exactly how a guess turns into an identity.
    """
    if phone is not None:
        return phone.persona  # type: ignore[attr-defined]
    if vector is None or huellas is None:
        return CASA
    return huellas.quien(vector)


def turno_del_encuentro(
    encuentro: "Encuentro",
    texto: str,
    vector: "np.ndarray | None",
    decir: Callable[[str], None],
) -> "Respuesta | None":
    """The whole of "no amo -> he answers, and nothing is ever sent".

    `dispatch` calls this INSTEAD of `client.send_chat` for as long as
    `registro.amo` is `None`: nothing here touches the gateway, and
    there is no `chat_id` to carry even if it tried — `decir` is a
    plain `str -> None` callable, not `speaker.say(clause, destino)`,
    so a test can hand it a list to append to and assert nothing else
    happened.

    Returns whatever `Encuentro.oye` returned, so the caller can act on
    `.terminado` — the phrase's file must be consumed, and the band
    must go away, on the exact utterance that finishes pairing —
    without re-reading `registro.amo` a second time to find out.
    """
    respuesta = encuentro.oye(texto, vector)
    if respuesta is not None:
        decir(respuesta.habla)
    return respuesta


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

        # The passphrase band: the first thing anybody sees on a box
        # with no amo, gone for good once one exists. Built here,
        # alongside the ficha and the photo band, so it is up and
        # already showing (or not) the moment the window is presented
        # — not only once `_start_voice_loop` finishes wiring the
        # gateway and the microphone, which can take a while longer.
        from .bienvenida_area import BienvenidaArea
        from .casa import Registro
        from .encuentro import ROTULO_ESPERANDO
        from .frase import cargar_o_crear

        registro = Registro(RUTA_CASA)
        bienvenida_area = BienvenidaArea(on_resize=window.resize_bienvenida)
        window.set_bienvenida(bienvenida_area)

        # Loaded once, at boot, and only while there is still no amo:
        # `cargar_o_crear` reuses whatever phrase is already on disk,
        # so restarting the strip mid-onboarding shows the exact same
        # phrase, never a fresh one that would strand whoever already
        # read the old one off the screen. A box that already has an
        # amo has no reason to mint one at all.
        frase_actual = cargar_o_crear(RUTA_FRASE) if registro.amo is None else ""

        # NOT called here, synchronously — that is exactly the trap
        # task 8's own report hit during its verification: before
        # `window.present()`, `_ewmh`/`_xid`/`_rect` are still `None`
        # (they are set in `StripWindow._on_map`, which has not fired
        # yet), so `resize_bienvenida`'s call into `window._resize()`
        # returns early and does nothing — the band still SHOWS (GTK's
        # own natural-size layout draws it) but the window is never
        # actually grown to hold it, which squeezes the wave — the only
        # sign he is listening at all — out of the visible strip
        # entirely. Deferred onto the window's own "map" signal
        # instead: `StripWindow.__init__` connects its OWN "map"
        # handler first (in `__init__`, before this line ever runs),
        # and GTK calls handlers in the order they were connected, so
        # by the time this one runs `_ewmh`/`_xid`/`_rect` are already
        # set and the real EWMH resize path — the one `resize_ficha`/
        # `resize_to` already use in production — runs instead of a
        # guess at how long mapping takes.
        def _mostrar_bienvenida(*_args: object) -> None:
            if registro.amo is None:
                # The one call that does not come from a `Respuesta`:
                # nobody has said anything yet, so the state is
                # `ESPERANDO` by construction and its header is the one
                # to show.
                bienvenida_area.mostrar(frase_actual, ROTULO_ESPERANDO)
            else:
                bienvenida_area.ocultar()

        window.connect("map", _mostrar_bienvenida)

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

        self._start_voice_loop(
            wave,
            band,
            window,
            ficha_model,
            ficha_area,
            registro,
            frase_actual,
            bienvenida_area,
        )

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

    def _start_voice_loop(
        self,
        wave,
        band,
        window,
        ficha_model,
        ficha_area,
        registro: "Registro",
        frase_actual: str,
        bienvenida_area,
    ) -> None:
        import numpy as np

        from .audio import Microphone, Player, SpectrumAnalyser, describe_devices
        from .bienvenida import BIENVENIDA, NECESIDAD
        from .encuentro import Encuentro
        from .frase import consumir
        from .gateway import GatewayClient
        from .locutor import Locutor
        from .speech import (
            Speaker,
            TurnChunkers,
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
        # One buffer per conversation, not one for the house — see
        # `TurnChunkers`. `on_token`/`on_done`/`on_error` fetch the one
        # for their own `chat_id` and `on_done`/`on_error` dispose of it
        # once that turn has settled.
        chunkers = TurnChunkers()
        # The hint carries his name and the words this box actually
        # says, so Whisper stops inventing spellings of both — see
        # `stt.build_hint`.
        transcriber = Transcriber(hint=build_hint(_WAKE_WORD))
        client = GatewayClient()

        # The first encounter: while `registro.amo` is `None`, every
        # utterance goes here instead of the gateway (see `dispatch`,
        # below). `frase_actual` was loaded once at boot in
        # `do_activate` — passed straight through rather than reloaded
        # here, so a restart mid-onboarding and this live attempt never
        # disagree about which phrase is the right one.
        encuentro = Encuentro(registro, frase_actual)
        # The impure half of speaker identification (`locutor.py`):
        # loaded once, lazily, inside its own constructor, and never
        # raises afterwards — `.vector()` returning `None` is the whole
        # of its failure mode (CLAUDE.md §2.8).
        locutor = Locutor()
        # Re-read from the register only when `registro.amo` changes —
        # see `huellas_actualizadas`'s own docstring.
        huellas_cache: dict[str, object] = {"amo": None, "huellas": None}

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

        def say(clause: str, destino: object | None) -> None:
            """Speak a clause, unless his voice is switched off.

            `destino` is resolved once per batch of clauses by the
            caller (`destino_de`, from that turn's `chat_id`) and
            passed straight through to `Speaker.say` — never looked up
            again here.
            """
            # Remembered even when muted: `interrupt()` can leave a
            # clause half-played, and half of one still comes back.
            echo.spoke(clause, time.monotonic())
            if not wave.switches.voice_on:
                # Dropped rather than queued: a queue that fills up
                # while he is muted would empty itself the moment he
                # is unmuted, and say a minute-old answer out loud.
                return
            speaker.say(clause, destino)

        wave.on_switch = on_switch

        def _vaciar_bienvenida() -> bool:
            """Empty the band once he has finished presenting himself.

            A fixed clock, not a "he stopped speaking" signal, because
            there is no such signal to use: `speech.Speaker` drains an
            asyncio queue and tells nobody when it runs dry, and giving
            it a drained-callback is more surface than this one moment
            is worth. The same fixed-clock resource the photo band and
            the live view's ceiling already use.

            It fires exactly once per pairing (`GLib` drops a timeout
            that returns False), and `ocultar` is idempotent, so a
            person who quit the strip in between costs nothing.
            """
            bienvenida_area.ocultar()
            return False

        def _atendido_por_encuentro(
            texto: str, vector: "np.ndarray | None", destino: object | None
        ) -> bool:
            """THE gate every entrance to `client.send_chat` must pass
            through. `True` means `texto` was handled by `Encuentro` and
            the caller must send it nowhere else; `False` means a house
            already exists and the caller is free to proceed to the
            gateway.

            There is exactly one copy of "is there an amo" in this
            process, and this is it — `dispatch` (voice, and a phone's
            own turn) and `on_typed` (the keyboard) both call ONLY this,
            never their own check. The keyboard used to have no check at
            all: a typed line went straight to `client.send_chat` on an
            unpaired box, which is how Hermes ended up improvising
            "anotado en mi lugar" for a name nothing had actually
            recorded. `registro.amo` is read fresh from disk on every
            call (never cached — `casa.Registro`'s own contract), so a
            pairing that finishes on one path is seen by the other on
            its very next line.
            """
            if registro.amo is not None:
                return False
            respuesta = turno_del_encuentro(
                encuentro, texto, vector, lambda habla: say(habla, destino)
            )
            # One line per state, in the journal that already carries
            # every other turn's `oído:`/`→` — without this, a stuck
            # flow is invisible: `_en_pidiendo` refusing an invalid name
            # and asking again looks, from the log alone, identical to
            # nothing having happened at all.
            print(f"encuentro: {encuentro.estado.value}", file=sys.stderr, flush=True)
            if respuesta is not None:
                if respuesta.terminado:
                    # This utterance is the one that finished pairing:
                    # the band's phrase is spent, and the file behind it
                    # must go too, or a restart would show — and
                    # accept — it again.
                    #
                    # The band does NOT go blank here any more (owner,
                    # 2026-09-06, the minute after pairing for real: it
                    # dropped from his name to nothing in one step,
                    # measured 240 px to 96). It keeps the name under a
                    # greeting of its own while he says what he is for,
                    # and empties on a clock afterwards.
                    GLib.idle_add(
                        bienvenida_area.mostrar, respuesta.lectura, respuesta.rotulo
                    )
                    GLib.timeout_add_seconds(
                        SEGUNDOS_BIENVENIDA_FINAL, _vaciar_bienvenida
                    )
                    consumir(RUTA_FRASE)
                elif respuesta.lectura is not None:
                    # `Respuesta.lectura` is set, deliberately, by every
                    # handler in `encuentro.py` — the passphrase in
                    # `ESPERANDO`, the confirmation sentence in
                    # `BORRANDO`, the numbered passage in `PIDIENDO`, the
                    # candidate name in `CONFIRMANDO` — never left to
                    # default by omission. This is now the ONLY source
                    # of what the band shows; `frase_actual` is not
                    # read here at all any more. `rotulo` — the line
                    # saying what that phrase is for — travels with it
                    # from the same `Respuesta`, so the header can never
                    # be left over from the previous state.
                    GLib.idle_add(
                        bienvenida_area.mostrar, respuesta.lectura, respuesta.rotulo
                    )
                else:
                    # `lectura is None` here means exactly "nothing to
                    # show" — `encuentro.py`'s own docstring is explicit
                    # that this is deliberate at the one moment it fires
                    # outside `terminado` (PIDIENDO, samples done, now
                    # asking for a name): showing the last passage, or
                    # the long-spent passphrase, would repeat the
                    # owner's own reported bug in miniature. Hide, not
                    # "leave whatever was there".
                    GLib.idle_add(bienvenida_area.ocultar)
            return True

        def on_typed(text: str) -> None:
            """A line typed on the strip. Sent exactly as if it were said.

            Two things the spoken path does are deliberately skipped: the
            wake word (a button was pressed — he is being addressed) and
            the echo filter (nothing was heard, so nothing can be his
            own voice coming back). The gate is NOT one of them —
            unpaired, this goes to `Encuentro` exactly like a spoken
            line, through `_atendido_por_encuentro`.
            """
            print(f"⌨ {text}", file=sys.stderr, flush=True)
            machine.typed()

            if _atendido_por_encuentro(text, None, None):
                return

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

        def on_utterance(pcm: bytes, endpoint: object | None = None) -> None:
            """`TurnMachine.heard()` calls this once, synchronously, with
            exactly the `(pcm, endpoint)` pair that arrived together —
            never a shared slot (task 14, round 2; see `TurnMachine.heard`).
            `endpoint` is recaptured fresh in THIS lambda, paired with
            THIS `pcm`, so two utterances scheduled back to back cannot
            cross no matter which of their spawned tasks the loop
            actually runs first.
            """
            loop.call_soon_threadsafe(lambda: self._spawn(dispatch(pcm, endpoint)))

        machine = TurnMachine(
            on_state=set_state,
            on_level=set_level,
            on_utterance=on_utterance,
            on_interrupt=speaker.interrupt,
        )

        from .certs import lan_address
        from .remote import HOSTNAME, PORT, QR_PATH, Enrolment, RemoteDesk, serve
        from .remote_auth import Guard, load_or_create_roster

        def on_remote_utterance(pcm: bytes, endpoint) -> None:
            """A phone released its button.

            Two things the desk path does are deliberately skipped, and
            for the same reasons `on_typed` skips them: the wake word (a
            button was pressed — he is being addressed) and the VAD (the
            button is the utterance boundary). The echo filter still
            runs inside `dispatch`, and costs nothing here because the
            phone's microphone is closed while he answers.

            `endpoint` travels with `pcm` from here all the way into
            `dispatch`, as an ordinary argument — through `heard()`, then
            `on_utterance`'s own closure — and nothing in between stores
            it. Nothing routes the voice here either — `destino_de`
            resolves that fresh, per batch of clauses, from that turn's
            own `chat_id`.
            """
            machine.heard(pcm, endpoint)

        remote_desk = RemoteDesk(
            on_utterance=on_remote_utterance,
            # Until 2026-09-06 a claim ending — including the one
            # nobody calls: a claim that simply expires — had to send
            # the speaker's single shared sink home too, or it went on
            # pointing at a phone that had dropped and the next reply,
            # to anybody, was written into a dead socket while the room
            # heard nothing. There is no shared sink left to send home:
            # `destino_de` asks THIS desk fresh on every batch of
            # clauses, so a claim that is gone simply resolves to
            # `None` (the room) on its own, with nothing to wire up
            # for THAT any more.
            #
            # What IS wired here now is a different backstop, and only
            # for a PHONE: a person's `TurnChunkers` entry is normally
            # dropped by `on_done`/`on_error`, but a turn that dies with
            # neither — the gateway's socket drops mid-answer — would
            # otherwise leave that buffer sitting there to be reused,
            # half-built, by their NEXT turn. A phone's claim expires on
            # its own ceiling even when nothing else does (`RemoteDesk`'s
            # own docstring), and `on_release` fires on every way a claim
            # ends — released, stolen, or the socket dropping under it —
            # so it is the one place guaranteed to run even then, FOR A
            # PHONE. The desk (`chat_id=None`) holds no claim, so this
            # covers nothing for it — see `client.on_disconnect` below
            # for the desk's own version of this same backstop.
            #
            # And it is sharper than "the dead phone's own buffer" the
            # moment two devices hold the SAME persona — see
            # `destino_de`'s docstring for why that is reachable today,
            # not merely hypothetical. `chunkers.drop` is keyed on
            # `endpoint.persona`, not on `endpoint` itself, so ONE
            # device of that persona disconnecting drops the buffer for
            # the WHOLE persona — including a reply mid-flight to the
            # OTHER device still holding that persona's claim. Closing
            # this needs the same operational fix as `destino_de`'s:
            # one secret per person (`tools/enrolar.py <persona>`).
            on_release=lambda endpoint: chunkers.drop(endpoint.persona),
        )
        # Closed until the QR is actually shown (below). The QR itself
        # carries the token now (`enrol.sobre`) rather than pointing at
        # a page that hands one out; the plain-HTTP welcome page still
        # exists as a typed-address fallback for a phone with no app,
        # and it is this same window that gates whether IT answers too
        # (remote.py).
        enrolment = Enrolment()

        async def dispatch(pcm: bytes, phone: object | None = None) -> None:
            # Wrapped whole: `transcriber.transcribe` can raise (a
            # starved GPU has left him deaf before — CLAUDE.md §12,
            # 2026-08-30) and so can `client.send_chat`, the same reason
            # `on_typed`'s `_send` wraps its own call. Unlike a typed
            # turn, this one may be holding a phone's claim on
            # `remote_desk` with no expiry left to save it —
            # `_claimed_at` is already `None` by the time `dispatch`
            # runs — so an uncaught exception here would lock every
            # phone in the house out until the widget restarts.
            # `phone` arrives as an ordinary argument, paired with THIS
            # `pcm` all the way from `heard()` — never read from
            # `remote_desk.busy`, which answers a DIFFERENT question and
            # answers it wrongly in both directions (see the module
            # docstring history, CLAUDE.md §12, 2026-09-01).
            try:
                seconds = len(pcm) / 2 / INPUT_RATE
                print(
                    f"oído: {seconds:.1f}s de voz (whisper listo: {transcriber.ready})",
                    file=sys.stderr,
                    flush=True,
                )
                if _DUMP_DIR:
                    _dump_utterance(pcm)
                # Whisper and the speaker embedder, back to back, in the
                # ONE thread hop this already pays for transcription —
                # identification must never sit in FRONT of the answer
                # (§1.4), which a second `asyncio.to_thread` round trip
                # would. Skipped for a phone (`vector` stays `None`): a
                # phone's press is already an identity that cannot lie,
                # and voice adds nothing there (`persona_de`'s own
                # docstring).
                necesita_voz = phone is None

                def _oir_e_identificar() -> tuple[str, "np.ndarray | None", float]:
                    texto = transcriber.transcribe(pcm)
                    inicio = time.monotonic()
                    vector = locutor.vector(pcm) if necesita_voz else None
                    return texto, vector, (time.monotonic() - inicio) * 1000.0

                text, vector, embed_ms = await asyncio.to_thread(_oir_e_identificar)
                if necesita_voz:
                    # The number task 9's report is built from: the
                    # milliseconds this adds between the end of the
                    # utterance and `send_chat`, measured on every desk
                    # turn rather than assumed once and left stale.
                    print(
                        f"identificación de voz: {embed_ms:.1f} ms",
                        file=sys.stderr,
                        flush=True,
                    )
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
                    settle_turn(phone, remote_desk)
                    return
                print(f"→ {text}", file=sys.stderr, flush=True)
                text = echo.clean(text, time.monotonic())
                if not text.strip():
                    # All of it was him. Not a turn, and not an error.
                    print("(era su propio eco)", file=sys.stderr, flush=True)
                    machine.error("")
                    settle_turn(phone, remote_desk)
                    return
                # Unpaired: nothing reaches Hermes, and this branch
                # never even tries — see `_atendido_por_encuentro`, the
                # ONE gate this and `on_typed` both call.
                if _atendido_por_encuentro(text, vector, phone):
                    settle_turn(phone, remote_desk)
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
                    # never asks the wake word, so `phone` is always
                    # `None` here and there is no claim to give back.
                    print("(no era para él)", file=sys.stderr, flush=True)
                    machine.error("")
                    return
                # Who this was: a phone's own identity, the voice
                # embedded above, or `casa` when unsure — see
                # `persona_de`. `huellas` is re-read from the register
                # only when it changes (`huellas_actualizadas`), never
                # on every utterance. This moves a desk turn's `chat_id`
                # from ABSENT to a person id (`casa` at minimum) — a
                # DIFFERENT Hermes chat than before (CLAUDE.md §5,
                # `adapter.py`'s `CHAT_ID_DEFAULT`), by design: per
                # -person memory is the point.
                huellas = (
                    None
                    if phone is not None
                    else huellas_actualizadas(registro, huellas_cache)
                )
                persona = persona_de(phone, vector, huellas)
                await client.send_chat(spoken, wake=wake.named, chat_id=persona)
            except Exception as exc:
                print(f"turno fallido: {exc!r}", file=sys.stderr, flush=True)
                machine.error("")
                settle_turn(phone, remote_desk)

        def on_disconnect() -> None:
            """The gateway connection itself was lost, mid-turn or not.

            `gateway.py`'s `run()` reconnects on its own and neither
            calls `on_done` nor `on_error` for whatever was in flight —
            it cannot, there is no `chat_id` left to address either
            with. `RemoteDesk.on_release` is the equivalent backstop
            for a PHONE claim (see the comment where `remote_desk` is
            built); the desk holds no claim, so nothing dropped ITS
            buffer on a socket drop until this. `drop_all` clears every
            `chat_id`, phones included, since a reconnect is a new
            gateway session and nothing buffered from before it will
            ever be spoken — see CLAUDE.md, task 13.
            """
            discarded = chunkers.drop_all()
            if discarded:
                print(
                    f"pasarela: {discarded} conversación(es) con texto "
                    "sin decir, descartado por la reconexión",
                    file=sys.stderr,
                    flush=True,
                )

        # ── the gateway's replies ─────────────────────────────────────
        #
        # All three accept a trailing `chat_id`, threaded from
        # gateway.py's `_dispatch`: whose reply this is, or None for the
        # desk. Resolved through `destino_de` exactly once per callback
        # — at the moment its clauses are about to be queued — and
        # passed straight into every `say()` that batch makes. See
        # `destino_de`'s own docstring for why that timing is the whole
        # of the fix CLAUDE.md §12 (2026-09-01) records.
        def on_token(token: str, chat_id: str | None = None) -> None:
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
            destino = destino_de(remote_desk, chat_id)
            for clause in chunkers.for_chat(chat_id).push(token):
                print(f"  dice: {clause}", file=sys.stderr, flush=True)
                say(clause, destino)

        def on_done(_ms: int, chat_id: str | None = None) -> None:
            # He has answered, so the next sentence needs no name for a
            # while: a conversation is not a sequence of commands.
            wake.answered(time.monotonic())
            destino = destino_de(remote_desk, chat_id)
            # Whether THIS `chat_id` actually said something, as opposed
            # to one of the gateway's own system messages (turn.py, one
            # measured turn carried six `done`s of those). Read BEFORE
            # `for_chat`/`drop` below touch this same `chat_id` — see
            # `TurnChunkers.has`'s own docstring for why this replaces
            # `machine.done()`'s return value here (final review,
            # 2026-09-06, CLAUDE.md): `machine` has ONE `_heard_token`
            # for the whole house, and a `done` for one `chat_id`
            # consuming it could make a DIFFERENT `chat_id`'s `done`,
            # arriving after — or the desk's own `machine.error("")` for
            # an empty transcription, arriving between the two — find
            # nothing left and report it did not settle, even though a
            # real reply of its own had arrived. Reproduced with the
            # exact interleaving `send()`'s two separate `await
            # self._push(...)` calls make possible in production:
            # token(marta), token(lucía), done(marta), done(lucía) left
            # lucía's claim held for the full 600s ceiling.
            real_reply = chunkers.has(chat_id)
            for clause in chunkers.for_chat(chat_id).flush():
                print(f"  dice: {clause}", file=sys.stderr, flush=True)
                say(clause, destino)
            # This conversation's buffer has said everything it had —
            # see `TurnChunkers.drop` for why it must not linger.
            chunkers.drop(chat_id)
            # Still drives the shared wave exactly as before — the wave
            # is a picture of the room, not a ledger of who owes whom a
            # settle, so ANY conversation's `done` is entitled to move
            # it. Its return value is no longer read: see `real_reply`
            # above for what decides whether a CLAIM is given back.
            machine.done()
            if real_reply:
                # Give the room — and any phone waiting its turn — back.
                # This is the recovery path for a held turn, not
                # bookkeeping: without it, a reply that hangs or crashes
                # locks every phone in the house out until the widget
                # restarts. Gated on THIS chat's own real settle, not on
                # every `done`: releasing on one of the gateway's system
                # -message `done`s would free the desk before the real
                # tokens ever arrive — a question asked on a phone,
                # answered out loud in the room.
                #
                # And it settles the endpoint this SAME callback already
                # resolved above, from this turn's own `chat_id` — never
                # a shared slot. An unprompted turn — a cron reminder, a
                # camera alert — carries no `chat_id` at all, so
                # `destino` is already `None` here and gives nothing
                # back; a desk turn is the same. Two phones overlapping
                # cannot cross here either, because each `on_done` only
                # ever asks after ITS OWN `chat_id`, and `real_reply` is
                # read from that SAME `chat_id`'s own buffer — nothing
                # shared for a second conversation's `done` to consume.
                #
                # `settle_turn`'s own identity guard (`release` ignoring
                # an endpoint that no longer holds the claim) is vacuous
                # here: `destino_de` just asked `remote_desk` who holds
                # this persona's claim RIGHT NOW, so `destino` can only
                # ever be the current holder or `None` — never stale.
                # It is the three `settle_turn` calls inside `dispatch`
                # (above) that pass the ORIGINATING endpoint, which a
                # re-press CAN steal the claim out from under before the
                # first press's turn ever gets here; the guard does real
                # work only there.
                settle_turn(destino, remote_desk)

        def on_error(message: str, chat_id: str | None = None) -> None:
            destino = destino_de(remote_desk, chat_id)
            if message:
                say(message, destino)
            _apply_error_to_wake_window(wake, message, time.monotonic())
            machine.error(message)
            # This is the OTHER way a turn ends, and its buffer is just
            # as dead as one `on_done` would have flushed — whatever it
            # still held was cut short by the error, not a real clause,
            # so it is dropped rather than spoken. Logged by LENGTH
            # only, never the text — that buffer is somebody's
            # half-finished sentence.
            discarded = chunkers.drop(chat_id)
            if discarded:
                quien = chat_id or "la sala"
                print(
                    f"turno con error: {discarded} caracteres sin decir "
                    f"descartados ({quien})",
                    file=sys.stderr,
                    flush=True,
                )
            settle_turn(destino, remote_desk)

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

        def _mostrar_qr() -> bool:
            # The band already draws a PNG for the cameras; this is the
            # same gesture, not a new one. But the file itself is no
            # longer `remote.serve()`'s doing: since 2026-09-06 it is
            # `Enrolment.abrir` that writes this path, per person, at
            # the exact moment their window opens — there is nothing
            # here at startup any more. `band` only exists from
            # `do_activate` onward, which is why this cannot sit beside
            # `_SWITCHES_OFF` and the other module-level switches above:
            # nothing named `band` exists there at all.
            #
            # The QR is no longer harmless: it now carries that
            # person's token (`enrol.sobre`), not a bare LAN URL, so
            # whoever holds the PNG holds the credential. The band's
            # own fade (`photo.FADE_S`, 15 s) and the enrolment window
            # (`ENROLMENT_SECONDS`) only bound how long the CODE is on
            # screen to be scanned or photographed — neither bounds the
            # TOKEN itself, which stays valid forever once minted.
            # Revoking one today means editing `personas.json` by hand
            # AND restarting `jarvis-widget.service`: `Guard.secretos`
            # is read once, at boot, and never again, so the edit alone
            # leaves this running process — and that person's phone —
            # none the wiser.
            band.show_photo(str(QR_PATH), "alta")
            return False  # GLib.SOURCE_REMOVE

        if os.getenv("JARVIS_WIDGET_SHOW_QR") == "1":
            # Shows the code a few seconds after startup — a shortcut for
            # exercising the path with no phone in the room and nobody
            # at this keyboard naming a person. `CASA` is the only safe
            # default here: it must never silently become the owner.
            # The normal way in is the signal below, which needs no
            # flag and no restart.
            def _show_qr_dev() -> bool:
                enrolment.abrir(CASA, time.monotonic())
                return _mostrar_qr()

            GLib.timeout_add_seconds(3, _show_qr_dev)

        def _on_enrol_signal(*_args: object) -> None:
            """Open enrolment for whoever `tools/enrolar.py` named, and
            show the code.

            A signal rather than a route: nothing on the network can send
            one, so the window cannot be opened by the people it exists
            to keep out. `systemctl --user kill -s USR1
            jarvis-widget.service` is the whole ritual, and it is always
            preceded by `tools/enrolar.py <persona>` writing who it is
            for — read once, here, and deleted so a second signal cannot
            replay it.

            `add_signal_handler`'s callback runs on whatever thread is
            executing `loop.run_forever()` — the asyncio thread started
            below, never the GTK one — so, like `on_photo`, this crosses
            through `GLib.idle_add` rather than touching the band
            directly.
            """

            def _abrir_y_mostrar() -> bool:
                enrolment.abrir(_persona_pendiente(), time.monotonic())
                return _mostrar_qr()

            GLib.idle_add(_abrir_y_mostrar)

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

        client.on_disconnect = on_disconnect
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

        def on_working(on: bool) -> None:
            """He picked up a tool, or put the last one down.

            Straight to the turn machine and nowhere else: this changes
            what the wave DRAWS and never what he says. `GLib.idle_add`
            because the frame arrives on the gateway's own loop thread
            and the wave belongs to GTK — the same crossing every other
            frame here makes.
            """
            GLib.idle_add(machine.working, on)

        client.on_working = on_working
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

        # How many times, and how far apart, `_saludar_sin_amo` checks
        # whether CosyVoice has started answering before giving up
        # quietly. 10 x 2s = 20s of grace for a container this widget
        # does not control the startup order of; past that, the band
        # stays correct and this run simply says nothing.
        _SALUDO_INTENTOS = 10
        _SALUDO_ESPERA_S = 2.0

        async def _saludar_sin_amo() -> None:
            """Say the band's own welcome once, out loud — the owner's
            ruling of 2026-09-06: "veo el mensaje pero no habla Jarvis"
            is the exact complaint this closes, and they chose speaking
            on every login over a quieter "first time ever" flag,
            knowing that cost.

            Reuses `BIENVENIDA`/`NECESIDAD` — the two lines the band
            already shows — rather than a third wording of the same
            fact, so the screen and the voice can never say two
            different things.

            **Never the phrase itself.** That is not a style choice: the
            phrase's entire value is that saying it PROVES the speaker
            has read this machine's own screen. A JARVIS who reads it
            aloud hands the house to anybody within earshot, to a
            recording, to a phone left running in the room — so this
            function must never import, read or touch `frase_actual` /
            `RUTA_FRASE`, and neither should whatever replaces it later.

            Waits for an actual response from CosyVoice rather than a
            fixed delay — a sentence spoken into a server that has not
            answered yet is a lost sentence, which is the exact bug
            being fixed here, aimed at a container instead of at
            silence. The probe is a plain GET to CosyVoice's own base
            URL: there is no `/health` route to ask (measured
            2026-09-06 — the container's OWN Docker healthcheck fails
            for the same reason, `curl` missing from its image), so any
            response at all — even an error page — is treated as
            "listening", and only a connection failure is retried.

            Called exactly once, from `_boot`, which itself runs exactly
            once per process — see `_boot`'s own single call site. Every
            `registro.amo` check inside is a fresh disk read (never
            cached), so pairing completing WHILE this waits or retries
            still cancels it.

            Wrapped whole, like every other coroutine `_boot` spawns
            (`_serve_quietly`): nothing here may raise into `_boot`
            (CLAUDE.md §2.8) — a greeting that crashes the strip is a
            far worse bug than a silent one.
            """
            if registro.amo is not None:
                return
            try:
                from Hermes.plugins.jarvis_voice import tts
                from Hermes.plugins.jarvis_voice.tts_config import config

                probe = tts.new_client()
                try:
                    llegó = False
                    for _intento in range(_SALUDO_INTENTOS):
                        if registro.amo is not None:
                            return  # paired while this was waiting
                        try:
                            await probe.get(config.url, timeout=2.0)
                            llegó = True
                            break
                        except Exception:
                            await asyncio.sleep(_SALUDO_ESPERA_S)
                    if not llegó:
                        print(
                            "saludo inicial: CosyVoice no respondió; no se dice nada",
                            file=sys.stderr,
                            flush=True,
                        )
                        return
                finally:
                    await probe.aclose()

                if registro.amo is not None:
                    return  # paired in the instant between the probe and here
                print(
                    "saludo inicial: diciendo la bienvenida",
                    file=sys.stderr,
                    flush=True,
                )
                say(f"{BIENVENIDA} {NECESIDAD}", None)
            except Exception as exc:
                print(f"saludo inicial falló: {exc!r}", file=sys.stderr, flush=True)

        def _boot() -> None:
            # All three run for the lifetime of the process, on the loop
            # that owns them.
            self._spawn(client.run())
            speaker.start()
            roster = load_or_create_roster()
            # Both ways in: the name, and the address it resolves to.
            # mDNS is not guaranteed on a house network — the LAN IP is
            # the design's own fallback — and a browser sends the origin
            # it was loaded from, so a Guard bound to the name alone
            # refuses every connection the fallback ever makes.
            guard = Guard(
                roster,
                f"https://{HOSTNAME}:{PORT}",
                f"https://{lan_address()}:{PORT}",
            )
            self._spawn(
                _serve_quietly(serve(remote_desk, guard, enrolment, registro, loop))
            )
            # Once per process — this function's own single call site.
            # If an amo already exists, `_saludar_sin_amo` returns
            # immediately without saying anything.
            self._spawn(_saludar_sin_amo())

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
                greeting = chunkers.for_chat(None)  # always the room
                for clause in greeting.push(_SAY_ON_START):
                    speaker.say(clause, None)
                for clause in greeting.flush():
                    speaker.say(clause, None)
                chunkers.drop(None)
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
