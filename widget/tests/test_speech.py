"""Where to cut her reply so CosyVoice sounds like a person, and what
never to say out loud at all.

The chunk sizes come from what jarvis-voice already measured against
the live server (docs/…-samantha-on-hermes-design.md §3.1): very short
clauses are synthesised badly, and a clause cut inside an expression
marker hands CosyVoice an opening tag with no close.

The filter comes from what the gateway actually sent on 2026-08-23
(docs/…-widget-gateway-probe.md §3): Hermes narrates itself through
ordinary token frames, in English, with emoji.
"""

from jarvis_widget.speech import ClauseChunker, is_system_message


def _feed(text: str) -> list[str]:
    chunker = ClauseChunker()
    out: list[str] = []
    for char in text:  # one token per character: the worst case
        out += chunker.push(char)
    return out + chunker.flush()


# ── chunking ──────────────────────────────────────────────────────────


def test_a_sentence_is_emitted_at_the_full_stop() -> None:
    assert _feed("Hola, me alegro de oírte de nuevo.") == [
        "Hola, me alegro de oírte de nuevo."
    ]


def test_two_sentences_become_two_clauses() -> None:
    assert len(_feed("Claro que sí. ¿Y tú qué tal estás hoy?")) == 2


def test_a_short_fragment_is_held_and_merged_forward() -> None:
    """ "Ya." alone makes CosyVoice clip. It waits for company."""
    clauses = _feed("Ya. Entiendo perfectamente lo que quieres decir.")

    assert clauses[0].startswith("Ya.")
    assert len(clauses[0]) >= 12


def test_a_comma_only_cuts_when_there_is_enough_behind_it() -> None:
    long_enough = _feed("Estuve pensando en lo que dijiste ayer, y creo que sí.")
    too_short = _feed("Sí, claro que te entiendo perfectamente.")

    assert len(long_enough) == 2
    assert len(too_short) == 1


def test_an_open_laughter_tag_is_never_cut() -> None:
    """<laughter>Ya. Claro</laughter> must not split at the full stop."""
    clauses = _feed("<laughter>Ya. Claro</laughter> te entiendo del todo.")

    for clause in clauses:
        assert clause.count("<laughter>") == clause.count("</laughter>")


def test_inline_markers_survive_intact() -> None:
    clauses = _feed("Vale [breath] lo pensaré con calma esta noche.")

    assert "[breath]" in " ".join(clauses)


def test_flush_releases_a_reply_with_no_final_punctuation() -> None:
    """Models end mid-thought. It still has to be said out loud."""
    assert _feed("Creo que sí aunque no estoy del todo segura") != []


def test_nothing_in_produces_nothing_out() -> None:
    assert _feed("") == []


def test_newline_ends_a_clause() -> None:
    assert len(_feed("Primero esto que ya es bastante largo\ny luego lo otro\n")) == 2


def test_a_whole_message_arrives_as_one_token() -> None:
    """What the gateway actually does: whole messages, not word by word."""
    chunker = ClauseChunker()
    out = chunker.push("La lluvia no pide permiso. Llega, lava todo un poco, y se va.")

    assert len(out) >= 2


# ── the system-message filter ─────────────────────────────────────────


def test_hermes_narrating_itself_is_not_said_out_loud() -> None:
    """Verbatim from the gateway probe. Spoken aloud these are gibberish."""
    for text in (
        "📬 No home channel is set for JARVIS_Kiosk. A home channel is where…",
        "↪ Redirected current run (iteration 1/9223372036854775807).",
        "💡 First-time tip — I redirected the current run using your message.",
        "⚠️ Couldn't deliver the audio attachment.",
        "⚡ Interrupting current task. I'll respond to your message shortly.",
        # The one that got through a fixed list of markers and was read
        # out loud during the agentic probe.
        "💾 Self-improvement review: User profile updated",
        # Not observed, but the same shape — the rule has to cover the
        # ones Hermes has not shipped yet.
        "🔧 Tool call failed, retrying",
        "✅ Done",
    ):
        assert is_system_message(text) is True, text


def test_her_own_words_are_not_filtered() -> None:
    for text in (
        "La lluvia no pide permiso. Llega, lava todo un poco, y se va.",
        "Sí, te oigo.",
        "[breath] Estaba pensando en lo que dijiste.",
        "¿Y tú qué tal?",
        "…y entonces me quedé pensando.",
        # Spanish opens with these constantly, and they are punctuation,
        # not pictographs — the rule must not eat them.
        "¿Y tú qué tal has dormido?",
        "¡Claro que me acuerdo!",
        "«Esto lo dijiste tú», me acuerdo bien.",
        "— Y entonces me callé.",
        '"Café solo", apuntado.',
    ):
        assert is_system_message(text) is False, text


def test_leading_whitespace_does_not_smuggle_one_through() -> None:
    assert is_system_message("\n  ⚠️ Couldn't deliver the audio attachment.") is True


def test_an_empty_frame_is_filtered() -> None:
    assert is_system_message("") is True
    assert is_system_message("   ") is True


# ── scheduled deliveries ──────────────────────────────────────────────

CRON_DELIVERY = """Cronjob Response: Prueba ha salido bien
(job_id: 03c8676840af)
-------------
La prueba ha salido bien.

To stop or manage this job, send me a new message (e.g. "stop reminder Prueba ha salido bien")."""


def test_only_her_words_survive_a_scheduled_delivery() -> None:
    """Measured verbatim: she read the job id, the dashes and an English
    instruction out loud. Only the body is hers."""
    from jarvis_widget.speech import unwrap_delivery

    assert unwrap_delivery(CRON_DELIVERY) == "La prueba ha salido bien."


def test_unwrapping_is_idempotent() -> None:
    from jarvis_widget.speech import unwrap_delivery

    once = unwrap_delivery(CRON_DELIVERY)
    assert unwrap_delivery(once) == once


def test_an_ordinary_reply_passes_through_untouched() -> None:
    from jarvis_widget.speech import unwrap_delivery

    plain = "Hola. Hay un momento, al final de la playa, en que todo calla."
    assert unwrap_delivery(plain) == plain


def test_a_delivery_with_no_job_id_line_still_unwraps() -> None:
    from jarvis_widget.speech import unwrap_delivery

    text = "Cronjob Response: Regar\n-------------\nRiega las plantas."
    assert unwrap_delivery(text) == "Riega las plantas."


def test_a_multi_sentence_body_is_kept_whole() -> None:
    from jarvis_widget.speech import unwrap_delivery

    text = (
        "Cronjob Response: X\n(job_id: abc)\n-------------\n"
        "Riega las plantas. Y abre la ventana, que hace bueno.\n\n"
        'To stop or manage this job, send me a new message (e.g. "stop X").'
    )
    assert (
        unwrap_delivery(text) == "Riega las plantas. Y abre la ventana, que hace bueno."
    )


# ── routing ──────────────────────────────────────────────────────────


def test_say_takes_an_explicit_destination_none_means_the_room() -> None:
    """Since 2026-09-06 there is no shared "current sink" to point
    anywhere — see the class docstring for why. `say(clause, None)`
    is the room; anything else is written straight to that object."""
    from jarvis_widget.speech import Speaker

    class Sink:
        def __init__(self) -> None:
            self.written: list[bytes] = []

        def write(self, pcm: bytes) -> None:
            self.written.append(pcm)

    home = Sink()
    speaker = Speaker(home)

    # Nothing to assert yet — queueing is silent — but neither call
    # should raise, and there is no `sink` attribute left to inspect.
    speaker.say("Hola.", None)
    assert not hasattr(speaker, "sink")
    assert not hasattr(speaker, "route_to")
    assert not hasattr(speaker, "route_home")


async def test_a_clause_bound_to_a_phone_reaches_it(monkeypatch) -> None:
    """The interface `route_to`/`route_home` used to give: a clause
    destined for a phone is written to the phone, not the room."""
    import asyncio

    from Hermes.plugins.jarvis_voice import tts

    from jarvis_widget.speech import Speaker

    class Sink:
        def __init__(self) -> None:
            self.written: list[bytes] = []

        def write(self, pcm: bytes) -> None:
            self.written.append(pcm)

    async def fake_stream(_clause, client=None):
        yield b"\x01\x02", "fake"

    monkeypatch.setattr(tts, "new_client", lambda: object())
    monkeypatch.setattr(tts, "stream", fake_stream)

    home, phone = Sink(), Sink()
    speaker = Speaker(home)

    speaker.say("Hola, señor.", phone)

    speaker.start()
    for _ in range(200):
        if phone.written:
            break
        await asyncio.sleep(0)
    for worker in speaker._workers:
        worker.cancel()

    assert phone.written == [b"\x01\x02"]
    assert home.written == []


async def test_the_destination_is_bound_when_the_clause_is_queued(monkeypatch) -> None:
    """Pins the 2026-09-01 defect against the new interface (CLAUDE.md
    §12): the destination travels WITH the clause from the instant
    `say()` is called. There is no shared "current" sink left for
    anything that happens AFTER that — a later turn, a later reply, a
    different person entirely — to move out from under a clause
    already on the queue.
    """
    import asyncio

    from Hermes.plugins.jarvis_voice import tts

    from jarvis_widget.speech import Speaker

    class Sink:
        def __init__(self) -> None:
            self.written: list[bytes] = []

        def write(self, pcm: bytes) -> None:
            self.written.append(pcm)

    async def fake_stream(_clause, client=None):
        yield b"\x01\x02", "fake"

    monkeypatch.setattr(tts, "new_client", lambda: object())
    monkeypatch.setattr(tts, "stream", fake_stream)

    home, phone = Sink(), Sink()
    speaker = Speaker(home)

    speaker.say("Hola, señor.", phone)
    # Something else happens to the room's speaker in between — the
    # closest thing left to "route_home firing first". It must not
    # touch the clause already queued for the phone.
    speaker.say("Otra cosa, para nadie en particular.", None)

    speaker.start()
    for _ in range(200):
        if phone.written and home.written:
            break
        await asyncio.sleep(0)
    for worker in speaker._workers:
        worker.cancel()

    assert phone.written == [b"\x01\x02"]
    assert home.written == [b"\x01\x02"]


async def test_worker_count_is_configurable() -> None:
    """Not an invariant — CLAUDE.md §12's Ryzen AI Halo note: a box
    where VRAM stops being the binding constraint could synthesise
    more than one clause at once. Today's default is 1 (§2.8)."""
    from jarvis_widget.speech import Speaker

    speaker = Speaker(object())
    assert speaker._worker_count == 1

    speaker = Speaker(object(), workers=3)
    speaker.start()
    assert len(speaker._workers) == 3
    for worker in speaker._workers:
        worker.cancel()


# ── one buffer per conversation, not one for the house ────────────────
#
# Until 2026-09-06 `on_token`/`on_done` fed a SINGLE `ClauseChunker`
# regardless of `chat_id`. Two people mid-turn together fed the same
# buffer, and a clause could close holding either a fusion of both
# people's words or one person's leftover text released under the
# OTHER's `done`. `_drive` below plays exactly the frame sequences the
# reviewer measured against the real adapter (CLAUDE.md, task 13),
# first against the plain shared `ClauseChunker` `on_token`/`on_done`
# used to share, to pin what was actually wrong, and then against
# `TurnChunkers`, which is the fix.


def _drive_shared(frames: list[tuple[str, str | None]]) -> list[tuple[str, str]]:
    """What `on_token`/`on_done` did before task 13: one `ClauseChunker`
    for every `chat_id`. `text=None` means a `done` for that chat_id."""
    chunker = ClauseChunker()
    out: list[tuple[str, str]] = []
    for chat_id, text in frames:
        if text is None:
            for clause in chunker.flush():
                out.append((chat_id, clause))
        else:
            for clause in chunker.push(text):
                out.append((chat_id, clause))
    return out


def _drive_per_chat(frames: list[tuple[str, str | None]]) -> list[tuple[str, str]]:
    """What `on_token`/`on_done` do since task 13: one `ClauseChunker`
    PER `chat_id`, disposed of when that chat_id's `done` arrives."""
    from jarvis_widget.speech import TurnChunkers

    chunkers = TurnChunkers()
    out: list[tuple[str, str]] = []
    for chat_id, text in frames:
        if text is None:
            for clause in chunkers.for_chat(chat_id).flush():
                out.append((chat_id, clause))
            chunkers.drop(chat_id)
        else:
            for clause in chunkers.for_chat(chat_id).push(text):
                out.append((chat_id, clause))
    return out


# Each case is `(chat_id, text)`, `text=None` standing for a `done`.
# Verbatim from the reviewer's measurement (CLAUDE.md, task 13).
_A_SHORT_REPLY_UNDER_THE_MINIMUM = [
    ("marta", "Sí, señor."),
    ("lucía", "Sí, hay huevos en la nevera."),
    ("marta", None),
    ("lucía", None),
]
_NO_FINAL_PUNCTUATION = [
    ("marta", "La cita con el médico es el martes a las nueve"),
    ("lucía", "Hay huevos en la nevera."),
    ("marta", None),
    ("lucía", None),
]
_A_TRAILING_SHORT_FRAGMENT = [
    ("marta", "He apagado la luz del salón."),
    ("marta", None),
    ("lucía", "Vale"),
    ("lucía", "Quedan dos yogures."),
    ("lucía", None),
]
_AN_UNCLOSED_LAUGHTER_MARKER = [
    ("marta", "Claro que sí."),
    ("lucía", "<laughter>El niño ya está dormido."),
    ("marta", None),
    ("lucía", None),
]

_ALL_FOUR_ORDERINGS = [
    _A_SHORT_REPLY_UNDER_THE_MINIMUM,
    _NO_FINAL_PUNCTUATION,
    _A_TRAILING_SHORT_FRAGMENT,
    _AN_UNCLOSED_LAUGHTER_MARKER,
]


def test_a_single_shared_chunker_mixes_two_peoples_words() -> None:
    """Pins the bug itself, against the code as it was: `_drive_shared`
    is exactly what `on_token`/`on_done` did with one `ClauseChunker`
    for the house. Every ordering the reviewer tried produced at least
    one clause that is not solely one person's own words — either
    literally fused, or someone's sentence released under the other
    person's `chat_id`."""
    assert _drive_shared(_A_SHORT_REPLY_UNDER_THE_MINIMUM) == [
        ("lucía", "Sí, señor.Sí, hay huevos en la nevera.")
    ]
    assert _drive_shared(_NO_FINAL_PUNCTUATION) == [
        (
            "lucía",
            "La cita con el médico es el martes a las nueveHay huevos en la nevera.",
        )
    ]
    # The fourth ordering is the sharpest: lucía's own sentence is
    # spoken to marta's chat_id, and lucía never gets it at all.
    unclosed = _drive_shared(_AN_UNCLOSED_LAUGHTER_MARKER)
    assert unclosed == [
        ("marta", "Claro que sí."),
        ("marta", "<laughter>El niño ya está dormido."),
    ]
    assert not any(chat_id == "lucía" for chat_id, _ in unclosed)


def test_two_interleaved_conversations_never_share_a_clause() -> None:
    """The fix: one `ClauseChunker` per `chat_id`. Every clause a chat_id
    receives is made ENTIRELY of that chat_id's own tokens, in every
    ordering `_drive_shared` above got wrong."""
    for frames in _ALL_FOUR_ORDERINGS:
        out = _drive_per_chat(frames)
        by_chat: dict[str, list[str]] = {}
        for chat_id, clause in out:
            by_chat.setdefault(chat_id, []).append(clause)

        for chat_id, clauses in by_chat.items():
            spoken = "".join(clauses)
            own_tokens = "".join(t for c, t in frames if c == chat_id and t)
            other_tokens = "".join(t for c, t in frames if c != chat_id and t)
            # Everything said under this chat_id came from its OWN
            # tokens — nothing of the other person's leaked in.
            assert spoken.replace(" ", "") in own_tokens.replace(" ", "")
            if other_tokens:
                assert other_tokens.strip() not in spoken

    # And the sharpest case by name: lucía gets her own sentence, not
    # marta's chat_id, and marta's is untouched by it.
    fixed = _drive_per_chat(_AN_UNCLOSED_LAUGHTER_MARKER)
    assert ("marta", "Claro que sí.") in fixed
    assert ("lucía", "<laughter>El niño ya está dormido.") in fixed
    assert all(
        clause != "<laughter>El niño ya está dormido." or chat_id == "lucía"
        for chat_id, clause in fixed
    )


# ── TurnChunkers on its own ────────────────────────────────────────────


def test_each_chat_id_gets_its_own_chunker() -> None:
    from jarvis_widget.speech import TurnChunkers

    chunkers = TurnChunkers()
    assert chunkers.for_chat("marta") is chunkers.for_chat("marta")
    assert chunkers.for_chat("marta") is not chunkers.for_chat("lucía")


def test_empty_chat_id_and_none_share_the_desks_chunker() -> None:
    """`destino_de` treats `""` and `None` as the same thing — the
    desk. So must this, or the desk's own reply would split across two
    buffers depending on which falsy value happened to arrive."""
    from jarvis_widget.speech import TurnChunkers

    chunkers = TurnChunkers()
    assert chunkers.for_chat(None) is chunkers.for_chat("")


def test_dropping_a_chat_frees_a_fresh_chunker_next_time() -> None:
    """The backstop for a turn that dies mid-buffer: whatever it had
    not yet said must not bleed into that chat_id's NEXT turn."""
    from jarvis_widget.speech import TurnChunkers

    chunkers = TurnChunkers()
    unfinished = chunkers.for_chat("marta")
    unfinished.push("sin terminar, sin punto")  # never flushed
    chunkers.drop("marta")

    fresh = chunkers.for_chat("marta")
    assert fresh is not unfinished
    assert fresh.flush() == []  # nothing carried over from the dead turn


def test_has_is_false_until_a_real_token_is_pushed() -> None:
    """`has` is what `on_done`/`on_error` ask instead of
    `TurnMachine.done()`'s return value (final review, 2026-09-06,
    CLAUDE.md): that flag is shared across every conversation, so a
    `done` for one `chat_id` can silently consume it and swallow the
    settle for a different one still in flight. `_by_chat` is already
    keyed by exactly the identity that matters, so this costs nothing
    new and shares nothing between conversations.
    """
    from jarvis_widget.speech import TurnChunkers

    chunkers = TurnChunkers()
    assert chunkers.has("marta") is False

    chunkers.for_chat("marta").push("hola")
    assert chunkers.has("marta") is True
    assert chunkers.has("lucía") is False  # a different chat is untouched


def test_has_never_creates_a_chunker() -> None:
    """A peek, not a `for_chat`: asking must not conjure an entry that
    `drop` would then have to remove for nothing, and must not make a
    later `for_chat` return something other than a fresh chunker."""
    from jarvis_widget.speech import TurnChunkers

    chunkers = TurnChunkers()
    assert chunkers.has("marta") is False

    assert chunkers.drop("marta") == 0  # nothing was ever created


def test_has_treats_empty_and_none_as_the_desk() -> None:
    from jarvis_widget.speech import TurnChunkers

    chunkers = TurnChunkers()
    chunkers.for_chat(None).push("hola")

    assert chunkers.has("") is True
    assert chunkers.has(None) is True


def test_has_is_false_again_once_the_chat_is_dropped() -> None:
    from jarvis_widget.speech import TurnChunkers

    chunkers = TurnChunkers()
    chunkers.for_chat("marta").push("hola")
    chunkers.drop("marta")

    assert chunkers.has("marta") is False


def test_drop_reports_the_discarded_length_not_the_text() -> None:
    from jarvis_widget.speech import TurnChunkers

    chunkers = TurnChunkers()
    assert chunkers.drop("nadie") == 0  # nothing was ever created

    chunkers.for_chat("marta").push("doce caracteres")
    discarded = chunkers.drop("marta")

    assert isinstance(discarded, int)
    assert discarded == len("doce caracteres")


def test_drop_all_clears_every_conversation_at_once() -> None:
    """The backstop `drop` cannot be for the DESK (`chat_id=None` holds
    no phone claim to expire): the gateway CONNECTION being lost is the
    only signal there is, and it does not come with a `chat_id` to
    scope a single `drop` to — see `GatewayClient.on_disconnect`."""
    from jarvis_widget.speech import TurnChunkers

    chunkers = TurnChunkers()
    chunkers.for_chat(None).push("sin terminar, sala")
    chunkers.for_chat("marta").push("sin terminar, marta")
    chunkers.for_chat("lucía")  # created, but nothing ever buffered

    affected = chunkers.drop_all()

    assert affected == 2  # only the two with something actually pending
    assert chunkers.for_chat(None).flush() == []
    assert chunkers.for_chat("marta").flush() == []


# ── interrupt() is scoped to one destination ───────────────────────────
#
# Until 2026-09-06 `interrupt()` bumped one counter for the house and
# stopped the room's player — correct while the room was the only place
# any voice went, and wrong the moment a phone's answer could be queued
# alongside it: somebody clearing their throat in the room silently
# deleted a phone's entire pending reply. CLAUDE.md, task 13.


async def test_interrupting_the_room_does_not_touch_a_phones_queue(
    monkeypatch,
) -> None:
    import asyncio

    from Hermes.plugins.jarvis_voice import tts

    from jarvis_widget.speech import Speaker

    class Sink:
        def __init__(self) -> None:
            self.written: list[bytes] = []
            self.stopped = False

        def write(self, pcm: bytes) -> None:
            self.written.append(pcm)

        def stop(self) -> None:
            self.stopped = True

    async def fake_stream(_clause, client=None):
        yield b"\x01", "fake"

    monkeypatch.setattr(tts, "new_client", lambda: object())
    monkeypatch.setattr(tts, "stream", fake_stream)

    home, phone = Sink(), Sink()
    speaker = Speaker(home)

    # A phone's reply queued, then the room barges in before it starts.
    speaker.say("La cita es el martes.", phone)
    speaker.interrupt()  # the room's own barge-in — no destino given

    speaker.start()
    for _ in range(200):
        if phone.written:
            break
        await asyncio.sleep(0)
    for worker in speaker._workers:
        worker.cancel()

    # The phone's clause survived: it was never the room's to drop.
    assert phone.written == [b"\x01"]
    # The room's own player DOES stop — that is the barge-in doing its
    # job — but stopping IT must not reach the phone's queue.
    assert home.stopped is True


async def test_interrupting_the_room_drops_only_the_rooms_queue(
    monkeypatch,
) -> None:
    import asyncio

    from Hermes.plugins.jarvis_voice import tts

    from jarvis_widget.speech import Speaker

    class Sink:
        def __init__(self) -> None:
            self.written: list[bytes] = []
            self.stopped = False

        def write(self, pcm: bytes) -> None:
            self.written.append(pcm)

        def stop(self) -> None:
            self.stopped = True

    async def fake_stream(_clause, client=None):
        yield b"\x01", "fake"

    monkeypatch.setattr(tts, "new_client", lambda: object())
    monkeypatch.setattr(tts, "stream", fake_stream)

    home, phone = Sink(), Sink()
    speaker = Speaker(home)

    speaker.say("Para nadie en particular.", None)  # queued for the room
    speaker.interrupt()  # bumps the room's generation before it plays

    speaker.say("Y ahora sí, para el teléfono.", phone)

    speaker.start()
    for _ in range(200):
        if phone.written:
            break
        await asyncio.sleep(0)
    for worker in speaker._workers:
        worker.cancel()

    assert home.written == []  # the stale room clause never played
    assert home.stopped is True  # and the room's player WAS told to stop
    assert phone.written == [b"\x01"]  # the phone's is untouched


def test_interrupting_a_specific_destination_leaves_the_room_alone() -> None:
    """The other direction: interrupting a PHONE (were something ever
    to call it that way) must not stop the room's player — only the
    room's own barge-in does that."""
    from jarvis_widget.speech import Speaker

    class Sink:
        def __init__(self) -> None:
            self.stopped = False

        def write(self, pcm: bytes) -> None:
            pass

        def stop(self) -> None:
            self.stopped = True

    home = Sink()
    phone = Sink()
    speaker = Speaker(home)

    speaker.interrupt(phone)

    assert home.stopped is False


# ── raising `workers` and clause order ─────────────────────────────────


async def test_raising_workers_does_not_preserve_clause_order(monkeypatch) -> None:
    """The comment above `_DEFAULT_WORKERS` used to claim raising
    `workers` cost nothing "without anything here having assumed
    otherwise". Measured false (CLAUDE.md, task 13): with `workers=1`
    the room heard `['uno', 'dos', 'tres']`; with `workers=3`, the same
    three clauses came back as `['dos', 'tres', 'uno']`. Pinned here so
    the next person to raise `_DEFAULT_WORKERS` meets this as a known
    fact, not a surprise on a live turn.
    """
    import asyncio

    from Hermes.plugins.jarvis_voice import tts

    from jarvis_widget.speech import Speaker

    class Sink:
        def __init__(self) -> None:
            self.written: list[bytes] = []

        def write(self, pcm: bytes) -> None:
            self.written.append(pcm)

    # "uno" takes measurably longer to synthesise than "dos" or "tres" —
    # exactly the shape that lets a later clause of the SAME reply
    # overtake an earlier one when nothing serialises them.
    delays = {"uno": 0.03, "dos": 0.0, "tres": 0.0}

    async def fake_stream(clause, client=None):
        await asyncio.sleep(delays.get(clause, 0.0))
        yield clause.encode(), "fake"

    monkeypatch.setattr(tts, "new_client", lambda: object())
    monkeypatch.setattr(tts, "stream", fake_stream)

    home = Sink()
    speaker = Speaker(home, workers=3)
    speaker.say("uno", None)
    speaker.say("dos", None)
    speaker.say("tres", None)

    speaker.start()
    for _ in range(500):
        if len(home.written) == 3:
            break
        await asyncio.sleep(0.001)
    for worker in speaker._workers:
        worker.cancel()

    assert [c.decode() for c in home.written] == ["dos", "tres", "uno"]


# ── the end of a turn, said out loud on the wire ──────────────────────


async def test_finish_tells_the_destination_after_its_last_clause(monkeypatch) -> None:
    """A phone cannot tell "he has stopped" from "he is synthesising the
    next clause": both are silence on the socket. So the box has to say
    so, and it has to say so AFTER the last byte of audio — a `done`
    that overtook a clause would rearm the microphone into the middle of
    his own sentence."""
    import asyncio

    from Hermes.plugins.jarvis_voice import tts

    from jarvis_widget.speech import Speaker

    class Phone:
        def __init__(self) -> None:
            self.eventos: list[str] = []

        def write(self, pcm: bytes) -> None:
            self.eventos.append("audio")

        def done(self) -> None:
            self.eventos.append("fin")

    async def fake_stream(_clause, client=None):
        yield b"\x01\x02", "fake"

    monkeypatch.setattr(tts, "new_client", lambda: object())
    monkeypatch.setattr(tts, "stream", fake_stream)

    phone = Phone()
    speaker = Speaker(object())
    speaker.start()
    speaker.say("Una.", phone)
    speaker.say("Dos.", phone)
    speaker.finish(phone)
    for _ in range(50):
        await asyncio.sleep(0.01)
        if "fin" in phone.eventos:
            break

    assert phone.eventos == ["audio", "audio", "fin"]


async def test_an_interrupted_phone_is_told_the_turn_is_over() -> None:
    """Otherwise barge-in leaves it waiting for a `done` that the
    dropped clauses will never produce — `interrupt` empties this
    destination's queue, and the end-of-turn marker sitting in it goes
    with everything else."""
    from jarvis_widget.speech import Speaker

    class Phone:
        def __init__(self) -> None:
            self.fines = 0

        def write(self, pcm: bytes) -> None:
            pass

        def done(self) -> None:
            self.fines += 1

    phone = Phone()
    speaker = Speaker(object())
    speaker.say("Una.", phone)
    speaker.interrupt(phone)

    assert phone.fines == 1


def test_the_room_is_never_told_a_turn_ended() -> None:
    """`None` is the room, and the room is a `Player` — it has no
    `done()` and needs none: somebody sitting here can hear that he
    stopped. Calling one on it would be an AttributeError inside the
    speaker's worker, which is the shape of failure that goes mute for
    a whole session."""
    from jarvis_widget.speech import Speaker

    class Player:
        def write(self, pcm: bytes) -> None:
            pass

        def stop(self) -> None:
            pass

    speaker = Speaker(Player())
    speaker.finish(None)
    speaker.interrupt(None)
