"""Cut the reply into clauses, synthesise each, play it as it arrives.

Waiting for `done` before speaking makes her feel dead; synthesising
every token makes CosyVoice stutter. The rule in between comes from
what jarvis-voice measured against the live server.

The widget synthesises rather than waiting for the gateway to send
audio (spec §5.1). It is a Python process on the same machine as
CosyVoice, so the binary WebSocket protocol that a browser would have
needed is never written.
"""

from __future__ import annotations

import asyncio
import re
import unicodedata

try:
    from Hermes.plugins.jarvis_voice.markers import has_unclosed_tag
except ImportError:  # repo root not on PYTHONPATH

    def has_unclosed_tag(text: str) -> bool:
        return text.count("<laughter>") > text.count("</laughter>")


_HARD_STOPS = ".?!…\n"
_SOFT_STOPS = ",;:"
# Below this CosyVoice clips the clause; hold it and let it merge forward.
_MIN_CLAUSE_CHARS = 12
# A comma only earns a cut when there is a real phrase behind it.
_MIN_SOFT_CLAUSE_CHARS = 25

# Hermes narrates itself through ordinary `token` frames — in English,
# with emoji, to a person who has no keyboard. Measured verbatim:
#
#   📬 No home channel is set for JARVIS_Kiosk … Type /sethome
#   ↪ Redirected current run (iteration 1/9223372036854775807)
#   💡 First-time tip — I redirected the current run…
#   ⚠️ Couldn't deliver the audio attachment.
#   ⚡ Interrupting current task. I'll respond to your message shortly.
#   💾 Self-improvement review: User profile updated
#
# The first five were a fixed list until the sixth turned up, spoken
# aloud, during the agentic probe. Enumerating them is a losing game:
# any Hermes release can add another, and the cost of missing one is
# that she reads it out.
#
# So the rule is the shape, not the list: a frame that OPENS with a
# symbol or pictograph is Hermes talking about itself. Nothing of hers
# starts that way — the personality spec bans emoji outright, and her
# own expression markers are `[laughter]`, `[breath]`, `[sigh]` and
# `<laughter>`, all ASCII. It fails safe: the worst case is staying
# quiet about something that was not hers to say.
_SPEAKABLE_LEADING_PUNCTUATION = "¿¡\"'«—-…("


def is_system_message(text: str) -> bool:
    """True for a frame the gateway wrote about itself. Never spoken."""
    stripped = text.strip()
    if not stripped:
        return True

    first = stripped[0]
    if first in _SPEAKABLE_LEADING_PUNCTUATION:
        return False
    # So = symbol/other (most emoji), Cs = surrogate, Sk/Sm = other
    # symbol classes that pictographs fall into.
    return unicodedata.category(first) in {"So", "Sk", "Sm", "Cs"}


# A cron delivery does not arrive as her words. It arrives wrapped:
#
#   Cronjob Response: Prueba ha salido bien
#   (job_id: 03c8676840af)
#   -------------
#   La prueba ha salido bien.
#
#   To stop or manage this job, send me a new message (e.g. "stop
#   reminder Prueba ha salido bien").
#
# Measured on 2026-08-23, and she read ALL of it out loud — the hex job
# id, the row of dashes, and the closing instruction in English. Exactly
# the "visible agent" CLAUDE.md §1 forbids. Only the body is hers.
#
# This is not `is_system_message`'s job: the frame IS a real delivery
# with something to say, not chatter to drop.
_CRON_HEADER = re.compile(
    r"^\s*Cronjob Response:[^\n]*\n(?:\(job_id:[^)]*\)\s*\n)?-{3,}\s*\n",
    re.IGNORECASE,
)
_CRON_FOOTER = re.compile(
    r"\n\s*To stop or manage this job.*\Z", re.IGNORECASE | re.DOTALL
)


def unwrap_delivery(text: str) -> str:
    """Strip the scaffolding off a scheduled delivery. Idempotent."""
    body = _CRON_HEADER.sub("", text)
    body = _CRON_FOOTER.sub("", body)
    return body.strip()


class ClauseChunker:
    def __init__(self) -> None:
        self._buffer = ""

    def push(self, token: str) -> list[str]:
        out: list[str] = []
        for char in token:
            self._buffer += char
            if self._ready(char):
                out.append(self._buffer.strip())
                self._buffer = ""
        return [c for c in out if c]

    def flush(self) -> list[str]:
        """Release whatever is left — a reply that ended mid-thought."""
        rest, self._buffer = self._buffer.strip(), ""
        return [rest] if rest else []

    def pending_chars(self) -> int:
        """How much is buffered and unspoken, as a COUNT only.

        For a caller that wants to log a discard without ever holding
        the text — the buffer is somebody's half-finished sentence.
        """
        return len(self._buffer.strip())

    def _ready(self, char: str) -> bool:
        if has_unclosed_tag(self._buffer):
            # Cutting here would hand CosyVoice "<laughter>Ya." — an
            # opening tag with no close.
            return False
        text = self._buffer.strip()
        if char in _HARD_STOPS:
            return len(text) >= _MIN_CLAUSE_CHARS
        if char in _SOFT_STOPS:
            return len(text) >= _MIN_SOFT_CLAUSE_CHARS
        return False


class TurnChunkers:
    """One `ClauseChunker` per conversation, not one for the house.

    Until 2026-09-06 `on_token`/`on_done` fed a SINGLE `ClauseChunker`
    regardless of whose turn a token belonged to — workable while only
    one turn ever ran. With two people mid-turn together, the gateway
    can (and, measured against the real adapter, does) deliver
    `token(marta)`, `token(lucía)`, `done(marta)`, `done(lucía)` in any
    order, and a shared buffer closes a clause holding whatever both of
    them had written into it so far — half of one person's sentence
    fused to half of the other's, or, worse, one person's leftover
    buffered text released under the OTHER's `done` (CLAUDE.md, task
    13). Routing already resolves the destination fresh per batch of
    clauses (`destino_de`); this does the same for the BUFFER the
    clauses are cut from, so nothing upstream of `destino_de` can mix
    two conversations' words in the first place.

    Keyed on the same value `destino_de` already treats as identity —
    `chat_id`, normalised so an empty string and `None` (both "the
    desk") share one buffer instead of starting two.
    """

    def __init__(self) -> None:
        self._by_chat: dict[str | None, ClauseChunker] = {}

    def for_chat(self, chat_id: str | None) -> ClauseChunker:
        """The buffer for this conversation, created on first use."""
        key = chat_id or None
        chunker = self._by_chat.get(key)
        if chunker is None:
            chunker = ClauseChunker()
            self._by_chat[key] = chunker
        return chunker

    def drop(self, chat_id: str | None) -> int:
        """Forget this conversation's buffer.

        Returns how many characters were sitting in it, unspoken — a
        COUNT, never the text, so a caller can log a discard without
        ever holding somebody's half-finished sentence. 0 if there was
        nothing buffered, or no chunker had ever been created for this
        `chat_id`.

        Called on both of the per-`chat_id` ways a turn ends —
        `on_done`, `on_error` — and, for a PHONE only, as the backstop
        for a turn that ends neither way: a phone's claim always
        expires on its own ceiling even when nothing else does, so
        `RemoteDesk.on_release` calls this too. The desk (`chat_id=
        None`) has no claim to expire, so that backstop does not reach
        it — see `drop_all` for what does.

        Without any of this the dict would hold one entry per
        `chat_id` for as long as the process runs: harmless in the
        handful a household's phones reach, but a dead turn's
        half-built clause has no business surviving into that
        `chat_id`'s NEXT one, which is exactly what reusing a stale
        entry would do.
        """
        chunker = self._by_chat.pop(chat_id or None, None)
        return chunker.pending_chars() if chunker is not None else 0

    def drop_all(self) -> int:
        """Forget every conversation's buffer at once.

        The backstop `drop` cannot be, for ANY `chat_id` — including
        the desk's, which holds no claim for `drop`'s own phone-only
        backstop to ride on. Called when the gateway CONNECTION itself
        is lost (`GatewayClient.on_disconnect`), the one event neither
        `on_done` nor `on_error` is ever sent to mark. Measured against
        the desk specifically (CLAUDE.md, task 13): a room turn
        mid-reply when the socket dropped left its half-built clause
        sitting under `chat_id=None` forever, for the reply AFTER the
        reconnect to inherit. A reconnect starts a new conversation on
        the gateway's side; nothing buffered from before it will ever
        be spoken, so keeping it can only corrupt what comes next.

        Returns how many conversations had anything buffered at all —
        a COUNT of chats, not of characters and never their text, for
        the same reason `drop` returns one.
        """
        affected = sum(1 for c in self._by_chat.values() if c.pending_chars())
        self._by_chat.clear()
        return affected


class Speaker:
    """Synthesise clauses and hand the PCM to whichever endpoint they
    are for. One clause at a time, globally — not because a sink is
    shared, but because CosyVoice measurably garbles two clauses made
    at once (CLAUDE.md §2.8).

    Several people may be mid-turn together. Only one of them is ever
    having a clause SYNTHESISED at any instant; each clause carries its
    own destination, bound at `say()` and never re-read.

    Until 2026-09-06 this had a single mutable `sink`, moved by
    `route_to`/`route_home` — workable while only one turn ever ran,
    and already the second design here: the FIRST one read the
    destination at synthesis time, and on a live iPhone (2026-09-01)
    that let the gateway's `done` send the sink home before CosyVoice
    had produced a single byte, so a private question came out of the
    room. Binding the destination to the sink fixed that for one turn
    at a time. It stops working the moment two people are answered in
    the same breath — a clause queued for one person and a `route_home`
    fired for the other would race on the same shared variable — so
    there is no shared destination left to race on at all: `say` takes
    it explicitly, an `Endpoint` or `None` for the room, and it rides
    in the queue with the clause.

    `interrupt()` is scoped the same way, since 2026-09-06 (CLAUDE.md,
    task 13). It used to bump ONE counter and stop THE player — correct
    while `_player` was the only place any voice went, and measurably
    wrong the moment a phone's answer could be queued at the same time:
    somebody clearing their throat in the room silently deleted a
    phone's entire pending reply, with nobody ever told. A phone is
    push-to-talk and cannot itself barge in, but the room's barge-in
    must not reach past the room either — so the generation that
    invalidates queued clauses, and the player that gets told to stop,
    are both per-destination now.
    """

    # How many clauses may be IN SYNTHESIS at once. A parameter, not a
    # law: it is 1 because this box's VRAM budget makes CosyVoice the
    # only thing using the GPU for speech, and because interleaving two
    # clauses' chunks in the SAME sink garbles them (§2.8) — a hazard
    # that only exists between clauses sharing a destination, not
    # between two different people's.
    #
    # Raising it is NOT free even so, and this used to claim otherwise
    # ("without anything here having assumed otherwise") — measured
    # false (CLAUDE.md, task 13): nothing serialises clauses within one
    # destination once more than one worker exists, so a later clause
    # of the SAME reply can be synthesised faster and overtake an
    # earlier one — `workers=1` gave `['uno', 'dos', 'tres']` for the
    # same three clauses that `workers=3` played back as
    # `['dos', 'tres', 'uno']`.
    # `test_raising_workers_does_not_preserve_clause_order` in
    # `tests/test_speech.py` pins that fact rather than leaving the
    # next person to discover it live. A box where the
    # VRAM constraint loosens (CLAUDE.md §12, the Ryzen AI Halo note)
    # can still raise `workers` for THROUGHPUT — several people's
    # replies synthesised at once — but needs per-destination
    # serialisation added first if it wants each person's OWN clauses
    # to keep arriving in the order they were said.
    _DEFAULT_WORKERS = 1

    def __init__(self, player, workers: int = _DEFAULT_WORKERS) -> None:
        self._player = player
        self._client = None
        # One generation per DESTINATION, not one for the house. `None`
        # is a real key here — the room — never "nobody interrupted
        # yet"; `_generation_for` is what supplies the default of 0 for
        # a destination nothing has ever invalidated.
        self._generations: dict[object | None, int] = {}
        self._queue: asyncio.Queue[tuple[object | None, int, str]] = asyncio.Queue()
        self._worker_count = max(1, workers)
        self._workers: list[asyncio.Task] = []

    def start(self) -> None:
        """Start the worker(s). Must be called on the asyncio loop."""
        if not self._workers:
            self._workers = [
                asyncio.ensure_future(self._run()) for _ in range(self._worker_count)
            ]

    def _generation_for(self, destino: object | None) -> int:
        return self._generations.get(destino, 0)

    def say(self, clause: str, destino: object | None) -> None:
        """Queue one clause for one destination. `None` is the room.

        The destination is bound HERE, at queue time, not read again
        later. That is not a style choice — see the class docstring
        and CLAUDE.md §12 (2026-09-01) for the turn this repeats: the
        destination was read when the clause was SYNTHESISED, seconds
        after the gateway's `done` had already arrived and moved a
        shared "current" sink on. There is no shared sink to move now,
        so that bug is unrepresentable rather than merely fixed.
        """
        self._queue.put_nowait((destino, self._generation_for(destino), clause))

    async def _run(self) -> None:
        while True:
            destino, generation, clause = await self._queue.get()
            if generation != self._generation_for(destino):
                continue  # queued before an interruption of THIS destino
            try:
                await self._synthesise(clause, destino, generation)
            except Exception:
                # A dead CosyVoice must not kill the worker, or she goes
                # mute for the rest of the session with no error path.
                continue

    def interrupt(self, destino: object | None = None) -> None:
        """Stop ONE destination, now. `None` is the room, as in `say()`.

        Called when THAT destination's own listener starts speaking
        over him — today, only ever the room: the desk's barge-in, the
        strip's own mute switch, and shutdown all interrupt the room,
        because a phone is push-to-talk and has no way to barge in at
        all. Scoping this by destination is what stops the room's
        barge-in from reaching a phone's queued or in-flight answer —
        measured before the fix: a cough in the room silently emptied a
        phone's whole pending reply, with the phone never told.

        The per-destination generation counter is what makes it stick:
        a synthesis already in flight cannot be cancelled
        mid-HTTP-response, so it finishes and then finds ITS
        destination's generation stale and throws its audio away
        instead of writing it out. The same counter invalidates
        whatever is already queued for this destination — and nothing
        queued for anybody else, which stays exactly where it was.
        """
        self._generations[destino] = self._generation_for(destino) + 1
        self._drop_queued_for(destino)
        if destino is None:
            self._player.stop()
        # A phone has nothing analogous to `_player.stop()` — there is
        # no in-room playback of it to silence, and audio already
        # written to its socket cannot be recalled. Whatever of ITS
        # reply is still queued was already dropped above.

    def _drop_queued_for(self, destino: object | None) -> None:
        """Discard queued clauses bound for `destino`; keep everyone
        else's, in the order they were queued."""
        kept: list[tuple[object | None, int, str]] = []
        while not self._queue.empty():
            item = self._queue.get_nowait()
            if item[0] != destino:
                kept.append(item)
        for item in kept:
            self._queue.put_nowait(item)

    async def _synthesise(
        self, clause: str, destino: object | None, generation: int
    ) -> None:
        """Synthesise one clause and write it to `destino` (`None` → the room).

        `destino` is exactly what `say()` was given at queue time, and
        `generation` is this destination's generation at that same
        moment — see `say()`'s docstring for why nothing here
        re-resolves the destination, and `interrupt()`'s for why the
        generation is per-destination rather than shared.
        """
        from Hermes.plugins.jarvis_voice import tts

        if self._client is None:
            # An httpx.AsyncClient may only be used on the loop that
            # created it, and this loop is not uvicorn's.
            self._client = tts.new_client()

        sink = self._player if destino is None else destino
        async for chunk, _backend in tts.stream(clause, client=self._client):
            if generation != self._generation_for(destino):
                return  # this destination was interrupted mid-synthesis
            sink.write(chunk)
            await asyncio.sleep(0)  # let the loop breathe between chunks
