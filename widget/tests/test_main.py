"""The one piece of wiring in `__main__.py` worth pinning on its own.

`__main__.py` is glue — GTK, threads, a websocket — and nothing else in
this suite imports it. The two `_apply_*_to_wake*` functions are the
exception: each is a whole wake-window decision a gateway callback
makes (the predicate AND the call on `WakeWord`), pulled out as a pure
function that takes a real `WakeWord` so the effect on the window — not
just the predicate that decides it — can be driven and asserted without
a strip, a socket or a display.
"""

import json
import stat

from jarvis_widget.__main__ import (
    _apply_asking_to_wake,
    _apply_error_to_wake_window,
    _apply_ficha_click,
    _apply_ficha_frame,
    _apply_ficha_tick,
    _persona_pendiente,
    _serve_quietly,
    destino_de,
    settle_turn,
    spoken_text,
)
from jarvis_widget.ficha import ESPERA_S, FichaModel
from jarvis_widget.personas import CASA
from jarvis_widget.remote import RemoteDesk
from jarvis_widget.wake import WakeWord


def test_an_empty_error_extends_the_window():
    # adapter.py's silence() — the user's own sentence, diverted to the
    # code assistant as the answer to a gate or held question. He did
    # not speak, but the user did, and is plainly still in the
    # conversation.
    w = WakeWord("jarvis")
    _apply_error_to_wake_window(w, "", now=10.0)

    # Inside the extended window: no name needed.
    assert w.heard("y mañana", now=39.9) == "y mañana"
    # Past it: the window really was 30s from `now`, not open forever.
    assert w.heard("y el jueves", now=41.0) is None


def test_a_real_error_does_not_extend_the_window():
    # _TURN_LOST, _BAD_FRAME and every other error() carry Spanish text
    # and are genuine faults, not an answer to anything.
    w = WakeWord("jarvis")
    _apply_error_to_wake_window(w, "Algo se ha quedado a medias.", now=10.0)

    assert w.heard("y mañana", now=15.0) is None


def test_a_question_opening_holds_the_window_past_thirty_seconds():
    # The gateway's `asking` frame. Without it the answer to a gate the
    # user thought about for forty seconds is dropped by the strip and
    # never reaches `_should_divert` — see the function's docstring.
    w = WakeWord("jarvis")
    _apply_asking_to_wake(w, True, now=0.0)

    assert w.heard("sí, adelante", now=45.0) == "sí, adelante"


def test_the_question_resolving_shuts_it_again():
    w = WakeWord("jarvis")
    _apply_asking_to_wake(w, True, now=0.0)
    _apply_asking_to_wake(w, False, now=50.0)

    assert w.heard("y otra cosa", now=51.0) is None


def test_endpointing_is_wired_only_when_the_model_loaded(monkeypatch) -> None:
    """The two states this must have, and no third one.

    With a model: the detector is asked. Without: it is not, and nothing
    anywhere raises — which is the property that keeps a missing 39 MB
    file from costing a voice turn.
    """
    from jarvis_widget.__main__ import build_may_close
    from jarvis_widget.endpoint import CompletionRule

    assert build_may_close(None, CompletionRule())() is False

    class FakeStream:
        def __init__(self, text: str) -> None:
            self.text = text

        def partial(self) -> str:
            return self.text

    assert (
        build_may_close(FakeStream("enciendeme la luz del salon"), CompletionRule())()
        is True
    )
    assert (
        build_may_close(FakeStream("enciendeme la luz del"), CompletionRule())()
        is False
    )


def test_a_broken_partials_object_never_closes_a_turn() -> None:
    """Vosk throwing mid-turn must not end somebody's sentence."""
    from jarvis_widget.__main__ import build_may_close
    from jarvis_widget.endpoint import CompletionRule

    class Exploding:
        def partial(self) -> str:
            raise RuntimeError("boom")

    assert build_may_close(Exploding(), CompletionRule())() is False


def test_his_own_words_coming_back_are_not_an_interruption() -> None:
    """The measurement this replaces, from CLAUDE.md §2.8:

        the user's voice          RMS 0.054-0.088
        his echo, speakers away   RMS 0.027-0.035
        his echo, speakers beside RMS 0.178   ← louder than the person

    A single scalar cannot separate the last row from the first, and the
    file said so in its own comment. The widget knows what it just said,
    so this is decided on words instead: `EchoFilter` already returns ""
    when everything it was handed was his.
    """
    from jarvis_widget.__main__ import build_is_a_person
    from jarvis_widget.echo import EchoFilter

    echo = EchoFilter()
    echo.spoke("Buenas tardes, señor. Le cuento algo un poco más largo.", 100.0)

    class HisEcho:
        def partial(self) -> str:
            return "buenas tardes senor le cuento algo un poco mas largo"

    assert build_is_a_person(HisEcho(), echo)(101.0) is False


def test_somebody_talking_over_him_is_an_interruption() -> None:
    from jarvis_widget.__main__ import build_is_a_person
    from jarvis_widget.echo import EchoFilter

    echo = EchoFilter()
    echo.spoke("Buenas tardes, señor. Le cuento algo un poco más largo.", 100.0)

    class APerson:
        def partial(self) -> str:
            return "para jarvis no me interesa eso ahora mismo"

    assert build_is_a_person(APerson(), echo)(101.0) is True


def test_with_no_partials_everything_is_a_person() -> None:
    """No Vosk means falling back to the old world, where the RMS floor
    is the only gate. Refusing to interrupt would be worse than
    interrupting too easily: it is the bug being fixed."""
    from jarvis_widget.__main__ import build_is_a_person
    from jarvis_widget.echo import EchoFilter

    assert build_is_a_person(None, EchoFilter())(1.0) is True


def test_nothing_heard_yet_is_not_a_person() -> None:
    """Vosk has no words yet. Not an interruption, and not an error."""
    from jarvis_widget.__main__ import build_is_a_person
    from jarvis_widget.echo import EchoFilter

    class Nothing:
        def partial(self) -> str:
            return ""

    assert build_is_a_person(Nothing(), EchoFilter())(1.0) is False


def test_room_resets_once_per_reply_never_mid_reply() -> None:
    """Fix round 1, 2026-09-01: the first draft used `elif` on the
    busy-branch guard (`player.busy and not detector.speaking`), which is
    False for every frame of an interruption in progress — `player.busy`
    stays True until playback actually stops, while `detector.speaking`
    is already True. That fired the reset every frame throughout the
    interruption: ~31 KaldiRecognizer objects a second at the exact
    moment somebody is talking over him.

    Fix round 2's CRITICAL bug lived one level up, in the CALLER rather
    than in this decision: the assignment feeding the next `was_busy`
    back into `_busy["was"]` sat below the busy branch, which returns
    early on EVERY frame of an ordinary, uninterrupted reply (the quiet
    frame and the his-own-echo frame both return before reaching it) —
    so across a whole reply `_busy["was"]` was never actually updated and
    the reset never fired at all. `.room` then grew without bound past
    `EchoFilter`'s 45 s memory, which is worse than the bug this task
    exists to fix: he starts interrupting himself with nobody in the
    room.

    A truth table over two booleans (round 1's test) cannot catch that —
    it never exercises the CALLER's wiring, only the decision in
    isolation. This drives a whole SEQUENCE of frames through
    `_room_bookkeeping`, exactly as the callback does — one call per
    frame, always applying `next_was_busy` — and counts every reset.
    """
    from jarvis_widget.__main__ import _room_bookkeeping

    # quiet, quiet — nothing has happened yet, nothing to reset
    # busy, busy, busy — one whole uninterrupted reply: never resets
    #     mid-reply, which is the frame-by-frame version of the CRITICAL
    #     bug (every one of these used to leave `was_busy` at False)
    # quiet, quiet — resets exactly once, on the frame busy ends, and
    #     not again on the quiet frame after it
    # busy — a second reply starts fresh: no leftover reset
    # quiet — resets again, once, when that one ends too
    frames = [False, False, True, True, True, False, False, True, False]

    was_busy = False
    resets = []
    for busy in frames:
        should_reset, was_busy = _room_bookkeeping(was_busy, busy)
        resets.append(should_reset)

    assert resets == [
        False,
        False,
        False,
        False,
        False,
        True,
        False,
        False,
        True,
    ]


def test_turn_resets_once_per_mic_off_toggle_never_while_it_holds() -> None:
    """Fix round 3, 2026-09-01: un-nesting `partials.turn.reset()` from
    `if detector.speaking:` (needed because `.turn` holds preroll from
    before the detector ever calls anything speech) removed a bound that
    had only ever existed by accident — `detector.reset()` on the same
    path cleared `detector.speaking`, so the branch stopped re-entering.
    Without that accident, nothing stopped the reset firing on EVERY
    frame the mic switch stayed off: ~31 `KaldiRecognizer` constructions
    a second, indefinitely, on the PortAudio thread.

    Same defect class as round 1's finding and round 2's Critical, so the
    same shape of test: a SEQUENCE of frames driven through
    `_turn_bookkeeping` exactly as the callback does — one call per
    frame, `next_was_on` always fed back — not a truth table over the
    pure function alone.
    """
    from jarvis_widget.__main__ import _turn_bookkeeping

    # on, on — mic on, nothing to reset
    # off, off, off — switched off and left off for three frames: resets
    #     once, on the very first off frame, and never again while it
    #     stays off (this is exactly what round 3's bug got wrong)
    # on, on — switched back on: no reset, and no leftover state
    # off — switched off a second time: resets once more
    frames = [True, True, False, False, False, True, True, False]

    was_on = True
    resets = []
    for is_on in frames:
        should_reset, was_on = _turn_bookkeeping(was_on, is_on)
        resets.append(should_reset)

    assert resets == [
        False,
        False,
        True,
        False,
        False,
        False,
        False,
        True,
    ]


def test_a_raising_vosk_call_costs_the_feature_and_not_the_microphone(capsys) -> None:
    """The invariant this branch is built on: failure is silence, never
    deafness.

    `Stream.push` runs `AcceptWaveform` plus `json.loads`, and
    `Stream.reset` constructs a `KaldiRecognizer`. Either can raise, and
    an exception raised there used to propagate out of the frame
    callback into `audio.py`'s `_pump`, which calls it OUTSIDE its own
    `try`: the thread returns, the microphone is never read again, and
    he is deaf while every service around him looks healthy. That is not
    hypothetical — it is how a Whisper model that would not fit cost
    three days on 2026-08-27.
    """
    from jarvis_widget.__main__ import VoskSwitch

    calls = []

    def boom(frame: bytes) -> None:
        calls.append(frame)
        raise RuntimeError("AcceptWaveform: model is corrupt")

    switch = VoskSwitch(True)

    # It does not raise, and the feature is off from here on.
    switch.run(boom, b"\x00\x00")
    assert switch.on is False
    assert switch.alive() is False

    # And it is off for good: a thousand more frames call nothing and
    # log nothing. Once, not thirty-one times a second.
    for _ in range(1000):
        switch.run(boom, b"\x00\x00")

    assert calls == [b"\x00\x00"]
    assert capsys.readouterr().err.count("endpointing apagado") == 1


def test_after_that_he_behaves_exactly_as_he_did_before_the_branch() -> None:
    """The other half of the invariant, and the reason `alive` exists.

    `build_may_close` and `build_is_a_person` hold their streams
    directly, so turning the switch off is not enough on its own: a
    stream nobody is feeding any more would keep answering out of stale
    words — the endpointing closing turns on a sentence that is no
    longer there, and `is_a_person` refusing to interrupt him, which is
    the bug this whole branch exists to fix. Off must mean the 1.2 s
    floor and an interruptible reply, exactly as before.
    """
    from jarvis_widget.__main__ import (
        VoskSwitch,
        build_is_a_person,
        build_may_close,
    )
    from jarvis_widget.echo import EchoFilter
    from jarvis_widget.endpoint import CompletionRule

    class Stale:
        def partial(self) -> str:
            # A complete sentence, and his own words — so with Vosk ON
            # this closes the turn and reports his echo.
            return "buenas tardes"

    switch = VoskSwitch(True)
    echo = EchoFilter()
    echo.spoke("Buenas tardes.", 100.0)
    may_close = build_may_close(Stale(), CompletionRule(), switch.alive)
    is_a_person = build_is_a_person(Stale(), echo, switch.alive)

    assert may_close() is True
    assert is_a_person(101.0) is False

    def boom() -> None:
        raise RuntimeError("KaldiRecognizer: out of memory")

    switch.run(boom)

    assert may_close() is False  # the 1.2 s floor, and nothing above it
    assert is_a_person(101.0) is True  # he can be interrupted again


def test_room_is_forgotten_even_when_the_mic_is_switched_off_mid_reply() -> None:
    """Fix round 5, 2026-09-01: `_busy["was"]` was stranded by the
    mic-off early return, exactly as round 2's Critical stranded it
    below the busy branch — the bookkeeping sat AFTER a branch that
    returns, so on the frames it never reached, `was_busy` was never
    updated and the reset never fired.

    The sequence that costs it, and the one driven here: mic on, he
    speaks (`.room` fills) → mic switched off mid-reply → that reply
    ends WITH THE MIC OFF, which is the frame the old code never reached
    → a second reply begins and ends. `.room` then holds both replies;
    once the first one's lines age past `EchoFilter`'s 45 s window they
    stop matching, the residue survives `clean()`, `is_a_person` reports
    a person, and he interrupts himself with nobody in the room.

    So the bookkeeping is now the first thing the callback does, above
    EVERY branch that can return, and this drives it the same way: one
    unconditional call per frame, mic switch included.
    """
    from jarvis_widget.__main__ import _room_bookkeeping

    frames = [
        # (mic_on, player.busy)
        (True, True),  # he is answering, mic on
        (True, True),
        (False, True),  # the mic switch goes off mid-reply
        (False, False),  # reply 1 ENDS with the mic still off  ← the bug
        (False, True),  # reply 2 begins, mic still off
        (True, True),  # mic switched back on mid-reply-2
        (True, False),  # reply 2 ends
    ]

    was_busy = True
    resets = []
    for _mic_on, busy in frames:
        should_reset, was_busy = _room_bookkeeping(was_busy, busy)
        resets.append(should_reset)

    # Once per reply, on the frame it ends — including the one that ends
    # while nobody is listening.
    assert resets == [False, False, False, True, False, False, True]


def test_a_discarded_utterance_still_ends_the_detectors_turn() -> None:
    """Finding 5: `.turn` used to be reset only when an utterance
    survived, and `vad.py`'s `_emit` resets itself and returns None when
    the speech ran shorter than 0.4 s. A cough therefore left its words
    in `.turn` for the next sentence to inherit, and those words then
    answered `may_close` about audio that was no longer there.

    The callback keys the reset on the DETECTOR instead — `speaking`
    only ever goes True → False inside `reset()` — so this pins the
    signal it now watches: a discarded utterance flips it exactly as a
    kept one does.
    """
    from jarvis_widget.vad import FRAME_SAMPLES, UtteranceDetector

    frame = b"\x00\x00" * FRAME_SAMPLES
    frame_seconds = FRAME_SAMPLES / 16000

    class Scripted:
        def __init__(self, script: list[float]) -> None:
            self.script = list(script)

        def speech_probability(self, _frame: bytes) -> float:
            return self.script.pop(0) if self.script else 0.0

    # 0.16 s of speech — enough to start a turn (3 frames), far short of
    # the 0.4 s an utterance needs to survive — then 1.5 s of quiet.
    script = [0.9] * 5 + [0.0] * round(1.5 / frame_seconds)
    detector = UtteranceDetector(Scripted(script))

    flips = 0
    utterances = []
    for _ in script:
        was_speaking = detector.speaking
        utterance = detector.push(frame)
        if utterance is not None:
            utterances.append(utterance)
        if was_speaking and not detector.speaking:
            flips += 1

    assert utterances == []  # the cough was discarded, as it should be
    assert flips == 1  # and the reset the callback watches still fired


# ── whose turn is this, and what it costs to guess ────────────────────
#
# `dispatch` is one function serving two mouths. It used to ask
# `remote_desk.busy` — "is SOME phone holding the turn" — which is a
# different question, and the two answers it got wrong were both
# security-shaped: a desk sentence skipping the wake word for the whole
# of every phone turn, and a desk turn's settle freeing a phone's claim
# mid-answer.


class FakePhone:
    name = "iphone-cocina"

    def __init__(self, persona: str = CASA) -> None:
        # Who this phone belongs to. Most tests below never look at
        # this — they are about RemoteDesk's claim/release bookkeeping
        # — only the ones asserting identity (task 5) pass a real one.
        self.persona = persona
        self.written: list[bytes] = []

    def write(self, pcm: bytes) -> None:
        self.written.append(pcm)

    def refuse(self) -> None:
        pass


def test_a_desk_utterance_while_a_phone_holds_the_turn_still_needs_his_name():
    """The one that made the room an open microphone. A phone turn is
    seconds of a held button plus however long a reply takes, and for
    all of it anything said at the desk was dispatched straight to an
    agent holding a terminal — no name required."""
    wake = WakeWord("Jarvis")
    desk = RemoteDesk(on_utterance=lambda pcm, endpoint: None)
    desk.claim(FakePhone(), now=0.0)
    assert desk.busy is True

    assert spoken_text("borra todo el disco", None, wake, now=0.0) is None
    assert spoken_text("Jarvis, qué hora es", None, wake, now=0.0) == "qué hora es"


def test_a_phone_press_is_the_address_and_needs_no_name():
    wake = WakeWord("Jarvis")
    phone = FakePhone()

    assert spoken_text("qué hora es", phone, wake, now=0.0) == "qué hora es"


def test_a_desk_turn_settling_does_not_release_a_phones_claim():
    """An empty transcription and an all-echo one are the two commonest
    things the desk microphone produces, and each of them used to end a
    phone's answer halfway through — every clause queued after it
    played out loud in the room."""
    desk = RemoteDesk(on_utterance=lambda pcm, endpoint: None)
    phone = FakePhone()
    desk.claim(phone, now=0.0)

    settle_turn(None, desk)  # the desk's turn, not the phone's

    assert desk.holders.get(CASA) is phone


def test_a_phone_turn_settling_gives_the_room_back():
    desk = RemoteDesk(on_utterance=lambda pcm, endpoint: None)
    phone = FakePhone()
    desk.claim(phone, now=0.0)

    settle_turn(phone, desk)

    assert desk.holders.get(CASA) is None


def test_a_settle_from_a_turn_that_is_no_longer_the_holders_is_ignored():
    """Pins `RemoteDesk.release`'s own identity guard in isolation, not
    any turn-closing behaviour: it ignores an endpoint that no longer
    holds ITS PERSON's claim. This is what still matters for the three
    `settle_turn` calls inside `dispatch`, which pass the endpoint that
    ORIGINATED the turn — a claim a re-press can steal before that
    first press's turn is ever settled. It does nothing for
    `on_done`/`on_error`: those resolve fresh through `destino_de`,
    which only ever names whoever CURRENTLY holds the claim (or
    `None`), so there the guard can never actually reject anything."""
    desk = RemoteDesk(on_utterance=lambda pcm, endpoint: None)
    old, new = FakePhone(), FakePhone()
    desk.claim(new, now=0.0)

    settle_turn(old, desk)

    assert desk.holders.get(CASA) is new


def test_two_overlapping_phone_turns_release_the_right_claim_each():
    """Task 14. Until 2026-09-06 `TurnOrigin` also kept `current` — a
    SECOND shared slot, written by `take()` and read back by a since
    -removed `settle()` — because `on_done`/`on_error` arrive long
    after `dispatch` has returned and had no other way to learn whose
    turn they were closing. A second phone's utterance arriving (and
    being `take()`n) before the first phone's turn had settled
    overwrote that slot, so the FIRST phone's close resolved to the
    SECOND phone's endpoint and released the wrong claim.

    Each closer now resolves its own endpoint from its own turn's
    `chat_id`, through `destino_de` — there is no shared slot left to
    overwrite, so the two turns below cannot cross regardless of which
    one settles first.
    """
    desk = RemoteDesk(on_utterance=lambda pcm, endpoint: None)
    marta, lucia = FakePhone(persona="marta"), FakePhone(persona="lucía")
    desk.claim(marta, now=0.0)
    desk.claim(lucia, now=0.0)

    # Both turns are in flight at once — the overlap two per-person
    # claims are meant to allow. Marta's is the one whose reply
    # finishes and settles first, resolved from HER OWN chat_id.
    settle_turn(destino_de(desk, "marta"), desk)

    assert desk.holders.get("marta") is None  # her own claim, given back
    assert desk.holders.get("lucía") is lucia  # Lucía's, untouched

    # Lucía's settles afterwards, from HER OWN chat_id, and is
    # unaffected by Marta's having already gone.
    settle_turn(destino_de(desk, "lucía"), desk)

    assert desk.holders.get("lucía") is None


def test_an_unprompted_turn_does_not_take_a_phones_claim():
    """A cron reminder and a camera alert carry no `chat_id` of their
    own, so `destino_de` resolves them to the room exactly as a desk
    turn does. They used to send the sink home and free whichever
    phone was mid-answer."""
    desk = RemoteDesk(on_utterance=lambda pcm, endpoint: None)
    phone = FakePhone()
    desk.claim(phone, now=0.0)

    settle_turn(destino_de(desk, None), desk)  # the reminder's own `done`

    assert desk.holders.get(CASA) is phone


def test_two_conversations_dones_interleaved_release_both_claims():
    """The final review (2026-09-06): `TurnMachine` is the one piece of
    state `on_done` still shared across every conversation. Gating
    `settle_turn` on `machine.done()`'s return value — as `on_done` did
    before this fix — means whichever `chat_id`'s `done` reaches the
    machine FIRST consumes its one `_heard_token` and settles; a
    SECOND `chat_id`'s `done`, arriving after, finds the flag already
    spent and reports it did not settle, even though ITS OWN real
    token arrived. Reproduced with the exact interleaving `send()`'s
    two separate `await self._push(...)` calls make possible in
    production: `token(marta)`, `token(lucía)`, `done(marta)`,
    `done(lucía)`.

    `on_done` now asks `chunkers.has(chat_id)` — read before that
    chat's buffer is flushed and dropped — instead of `machine.done()`,
    so each conversation's settle is decided from its OWN frames and
    cannot be swallowed by another's."""
    from jarvis_widget.speech import TurnChunkers
    from jarvis_widget.turn import TurnMachine

    desk = RemoteDesk(on_utterance=lambda pcm, endpoint: None)
    marta, lucia = FakePhone(persona="marta"), FakePhone(persona="lucía")
    desk.claim(marta, now=0.0)
    desk.claim(lucia, now=0.0)

    chunkers = TurnChunkers()
    machine = TurnMachine(on_state=lambda _s: None, on_level=lambda _lv: None)

    def _on_done(chat_id: str | None) -> object | None:
        """`__main__.on_done`'s decision, minus GTK/print/say: resolve
        the destination, decide from THIS chat's own frames whether it
        settles, flush and drop its buffer, and — only if it was
        real — give its claim back. Returns whichever endpoint was
        released, or `None`."""
        destino = destino_de(desk, chat_id)
        real_reply = chunkers.has(chat_id)
        chunkers.for_chat(chat_id).flush()
        chunkers.drop(chat_id)
        machine.done()  # still drives the shared wave, unconditionally
        if real_reply:
            settle_turn(destino, desk)
            return destino
        return None

    machine.heard(b"\x00\x00" * 16000)  # a turn is open on the shared wave
    chunkers.for_chat("marta").push("Hola, marta.")
    chunkers.for_chat("lucía").push("Hola, lucía.")

    assert _on_done("marta") is marta
    assert _on_done("lucía") is lucia  # NOT swallowed by marta's done above

    assert desk.holders.get("marta") is None
    assert desk.holders.get("lucía") is None


# `TurnOrigin` — the `arriving()`/`take()` hand-off that used to carry a
# phone's endpoint into `dispatch` on its own, a scheduling gap away
# from the audio it belonged to — is gone (task 14, round 2). The
# endpoint now travels as an ordinary argument, bound to its own `pcm`
# in the same call, all the way from `TurnMachine.heard()` through to
# `dispatch`. `tests/test_turn.py` pins that: `heard()` carries the
# endpoint through to `on_utterance` unchanged
# (`test_an_utterance_reaches_the_caller`), and two utterances scheduled
# out of order still pair correctly because nothing is shared between
# them (`test_two_utterances_scheduled_out_of_order_do_not_cross`).


# ── where a reply's clauses go ────────────────────────────────────────
#
# This is the task that repeats a bug already paid for once (CLAUDE.md
# §12, 2026-09-01): reading the destination at SYNTHESIS time, after the
# turn that owned it had already ended, sent a private question out
# loud into the room. `destino_de` is what `on_token`/`on_done`/
# `on_error` call, once per batch of clauses, to bind a destination that
# is then never re-read.


def test_destino_de_is_the_room_when_there_is_no_chat_id():
    desk = RemoteDesk(on_utterance=lambda pcm, endpoint: None)

    assert destino_de(desk, None) is None
    assert destino_de(desk, "") is None


def test_destino_de_finds_the_claim_for_its_own_chat_id():
    desk = RemoteDesk(on_utterance=lambda pcm, endpoint: None)
    telefono = FakePhone(persona="marta")
    desk.claim(telefono, now=0.0)

    assert destino_de(desk, "marta") is telefono


def test_destino_de_falls_back_to_the_room_once_the_claim_is_gone():
    """The residue recorded on 2026-09-01, preserved rather than fixed:
    a phone that drops mid-answer resolves to `None` from here on, and
    the rest of the reply is spoken in the room."""
    desk = RemoteDesk(on_utterance=lambda pcm, endpoint: None)
    telefono = FakePhone(persona="marta")
    desk.claim(telefono, now=0.0)
    desk.release(telefono)

    assert destino_de(desk, "marta") is None


def test_two_conversations_do_not_cross():
    """Two people mid-turn at once: each clause must reach the endpoint
    its OWN chat_id names, never the other's."""
    entregado: list[tuple[str, str | None]] = []

    class FakeSpeaker:
        def say(self, clause: str, destino) -> None:
            entregado.append((clause, getattr(destino, "persona", None)))

    desk = RemoteDesk(on_utterance=lambda pcm, endpoint: None)
    marta, lucia = FakePhone(persona="marta"), FakePhone(persona="lucía")
    desk.claim(marta, now=0.0)
    desk.claim(lucia, now=0.0)

    hablante = FakeSpeaker()
    hablante.say("una", destino_de(desk, "marta"))
    hablante.say("dos", destino_de(desk, "lucía"))
    hablante.say("tres", destino_de(desk, "marta"))

    assert entregado == [("una", "marta"), ("dos", "lucía"), ("tres", "marta")]


async def test_the_destination_is_bound_when_the_clause_is_queued(monkeypatch):
    """The failure this pins: reading the destination at SYNTHESIS time
    let the turn end, the claim go home, and the clause be written into
    the room instead of the phone. `Speaker.say` is given the resolved
    destination once, up front — exactly as `on_token`/`on_done` do —
    and nothing that happens to the claim afterwards can reach a clause
    already on the queue.
    """
    import asyncio

    from Hermes.plugins.jarvis_voice import tts

    from jarvis_widget.speech import Speaker

    async def fake_stream(_clause, client=None):
        yield b"\x01\x02", "fake"

    monkeypatch.setattr(tts, "new_client", lambda: object())
    monkeypatch.setattr(tts, "stream", fake_stream)

    room = FakePhone(persona=CASA)
    speaker = Speaker(room)
    desk = RemoteDesk(on_utterance=lambda pcm, endpoint: None)
    telefono = FakePhone(persona="marta")
    desk.claim(telefono, now=0.0)

    destino = destino_de(desk, "marta")
    speaker.say("hola", destino)
    # The turn ends here, and the phone lets go — before the worker has
    # even looked at the queue.
    desk.release(telefono)
    assert destino_de(desk, "marta") is None  # the NEXT clause would go home

    speaker.start()
    for _ in range(200):
        if telefono.written:
            break
        await asyncio.sleep(0)
    for worker in speaker._workers:
        worker.cancel()

    assert telefono.written == [b"\x01\x02"]
    assert room.written == []


async def test_the_phone_surface_failing_does_not_take_the_widget_down(capsys):
    """The interface not up at boot, the port busy, openssl missing.
    Spawned bare, the exception is never even retrieved."""

    async def refuses() -> None:
        raise OSError("address already in use")

    await _serve_quietly(refuses())

    assert "sin superficie" in capsys.readouterr().err


# ── the card, wired ─────────────────────────────────────────────────────
#
# `FichaArea` carries `gi` and cannot be imported into this suite (see the
# module docstring), so these drive a real `FichaModel` — the state a
# card actually has — against a plain fake standing in for the widget,
# recording exactly what it was told to draw. That is also the specific
# thing Task 11 is required to get right: the model deciding a card is
# gone is not, on its own, what shrinks the strip — the AREA has to be
# told, with `alto=0`, because `resize_ficha` (and `_resize`'s sum) only
# ever hears from `FichaArea.mostrar`'s own `on_resize` call. A test that
# only asked the model would pass even if that second step were missing.


class FakeFichaArea:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.pages: list[tuple[int, int]] = []

    def mostrar(
        self, md, tipo, fuente, correcta, elegida, alto, pagina=0, paginas=1
    ) -> None:
        self.calls.append((md, tipo, fuente, correcta, elegida, alto))
        self.pages.append((pagina, paginas))


def test_a_ficha_frame_updates_the_model_and_draws_it() -> None:
    model = FichaModel()
    area = FakeFichaArea()

    _apply_ficha_frame(
        model, area, "- a\n- b\n", "pregunta", "Cambridge", None, None, now=0.0
    )

    assert model.md == "- a\n- b\n" and model.tipo == "pregunta"
    assert area.calls == [
        ("- a\n- b\n", "pregunta", "Cambridge", None, None, model.height)
    ]


def test_the_cards_clock_leaves_it_alone_before_the_limit() -> None:
    model = FichaModel()
    area = FakeFichaArea()
    model.mostrar("## T\n\n- a\n", "pregunta", "", None, None, now=0.0)

    _apply_ficha_tick(model, area, now=1.0)

    assert area.calls == []
    assert model.visible


def test_the_cards_clock_collapses_the_strip_when_it_gives_up() -> None:
    """The failure this pins would be invisible to every other test and
    very visible on the desktop: `FichaModel.tick` clearing its own state
    is not the whole of what has to happen — the area must be told the
    new height is zero, or the window (which only ever hears from the
    area's `on_resize`) stays grown around a card that is no longer
    there."""
    model = FichaModel()
    area = FakeFichaArea()
    model.mostrar("## T\n\n- a\n", "pregunta", "", None, None, now=0.0)

    _apply_ficha_tick(model, area, now=ESPERA_S + 1)

    assert not model.visible
    assert area.calls == [("", "", "", None, None, 0)]


def test_a_press_puts_the_card_away_and_tells_the_area() -> None:
    model = FichaModel()
    area = FakeFichaArea()
    model.mostrar("## T\n\n- a\n", "pregunta", "", None, None, now=0.0)

    _apply_ficha_click(model, area, now=1.0)

    assert not model.visible
    assert area.calls == [("", "", "", None, None, 0)]


def test_a_press_with_nothing_up_touches_the_area_not_at_all() -> None:
    model = FichaModel()
    area = FakeFichaArea()

    _apply_ficha_click(model, area, now=1.0)

    assert area.calls == []


def test_a_press_on_a_long_card_turns_the_page_instead_of_closing_it() -> None:
    # Eleven syllabus points: three pages. The first two presses have to
    # advance and redraw — a page turn changes the CONTENT even when the
    # band is the same height, and `FichaModel.click` reports only
    # whether the HEIGHT changed.
    model = FichaModel()
    area = FakeFichaArea()
    md = "## Temario\n\n" + "\n".join(f"{i + 1}. Punto {i + 1}" for i in range(11))
    model.mostrar(md, "plan", "", None, None, now=0.0)

    _apply_ficha_click(model, area, now=1.0)

    assert model.visible
    assert model.pagina == 1
    assert area.pages[-1] == (1, 3)
    assert "Punto 6" in area.calls[-1][0]


def test_the_last_press_is_the_one_that_puts_it_away() -> None:
    model = FichaModel()
    area = FakeFichaArea()
    md = "## Temario\n\n" + "\n".join(f"{i + 1}. Punto {i + 1}" for i in range(11))
    model.mostrar(md, "plan", "", None, None, now=0.0)

    for instante in (1.0, 2.0, 3.0):
        _apply_ficha_click(model, area, now=instante)

    assert not model.visible
    assert area.calls[-1] == ("", "", "", None, None, 0)


def test_no_pending_file_enrols_casa(tmp_path) -> None:
    """The normal state between `enrolar.py` invocations. Never the
    owner, never whoever was enrolled last."""
    assert _persona_pendiente(tmp_path / "no-existe.json") == CASA


def test_the_pending_person_is_read_and_the_file_removed(tmp_path) -> None:
    ruta = tmp_path / "enrolamiento.json"
    ruta.write_text(json.dumps({"persona": "marta", "escrito": 0}))

    assert _persona_pendiente(ruta) == "marta"
    assert not ruta.exists()


def test_a_second_signal_cannot_replay_the_name(tmp_path) -> None:
    """`tools/enrolar.py` writes the file once per invocation; a second
    SIGUSR1 with nothing freshly written must enrol CASA, not repeat
    the last person read."""
    ruta = tmp_path / "enrolamiento.json"
    ruta.write_text(json.dumps({"persona": "marta"}))

    assert _persona_pendiente(ruta) == "marta"
    assert _persona_pendiente(ruta) == CASA


def test_malformed_json_enrols_casa_and_still_removes_the_file(tmp_path) -> None:
    ruta = tmp_path / "enrolamiento.json"
    ruta.write_text("{esto no es json")

    assert _persona_pendiente(ruta) == CASA
    assert not ruta.exists()


def test_a_json_array_is_not_a_pending_person(tmp_path) -> None:
    """The top level must be an object; anything else is malformed in
    the way that matters here, same as `_read_roster_file`'s own
    guard."""
    ruta = tmp_path / "enrolamiento.json"
    ruta.write_text(json.dumps(["marta"]))

    assert _persona_pendiente(ruta) == CASA


def test_a_name_that_does_not_survive_normalizar_enrols_casa(tmp_path) -> None:
    ruta = tmp_path / "enrolamiento.json"
    ruta.write_text(json.dumps({"persona": "../papá"}))

    assert _persona_pendiente(ruta) == CASA


def test_a_directory_at_the_path_is_left_untouched(tmp_path) -> None:
    """`stat` rules this out before anything is opened — the same guard
    `_read_roster_file` uses, and for the same reason: a node that is
    not a regular file must never be attempted with a blocking read."""
    ruta = tmp_path / "enrolamiento.json"
    ruta.mkdir()

    assert _persona_pendiente(ruta) == CASA
    assert stat.S_ISDIR(ruta.stat().st_mode)
