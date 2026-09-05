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
