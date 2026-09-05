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
    """

    # How many clauses may be IN SYNTHESIS at once. A parameter, not a
    # law: it is 1 because this box's VRAM budget makes CosyVoice the
    # only thing using the GPU for speech, and because interleaving two
    # clauses' chunks in the SAME sink garbles them (§2.8) — a hazard
    # that only exists between clauses sharing a destination, not
    # between two different people's. A box where the constraint
    # loosens (CLAUDE.md §12, the Ryzen AI Halo note: unified memory,
    # no VRAM ceiling to share) may raise `workers` without anything
    # here having assumed otherwise.
    _DEFAULT_WORKERS = 1

    def __init__(self, player, workers: int = _DEFAULT_WORKERS) -> None:
        self._player = player
        self._client = None
        self._generation = 0
        self._queue: asyncio.Queue[tuple[int, str, object | None]] = asyncio.Queue()
        self._worker_count = max(1, workers)
        self._workers: list[asyncio.Task] = []

    def start(self) -> None:
        """Start the worker(s). Must be called on the asyncio loop."""
        if not self._workers:
            self._workers = [
                asyncio.ensure_future(self._run()) for _ in range(self._worker_count)
            ]

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
        self._queue.put_nowait((self._generation, clause, destino))

    async def _run(self) -> None:
        while True:
            generation, clause, destino = await self._queue.get()
            if generation != self._generation:
                continue  # queued before an interruption; drop it
            try:
                await self._synthesise(clause, destino)
            except Exception:
                # A dead CosyVoice must not kill the worker, or she goes
                # mute for the rest of the session with no error path.
                continue

    def interrupt(self) -> None:
        """Stop talking, now. Called when the user starts speaking.

        The generation counter is what makes it stick: a synthesis
        already in flight cannot be cancelled mid-HTTP-response, so it
        finishes and then finds its generation stale and throws its
        audio away instead of playing over the user. The same counter
        invalidates everything already queued.
        """
        self._generation += 1
        while not self._queue.empty():
            self._queue.get_nowait()
        self._player.stop()

    async def _synthesise(self, clause: str, destino: object | None) -> None:
        """Synthesise one clause and write it to `destino` (`None` → the room).

        `destino` is exactly what `say()` was given at queue time — see
        its docstring for why nothing here re-resolves it.
        """
        from Hermes.plugins.jarvis_voice import tts

        if self._client is None:
            # An httpx.AsyncClient may only be used on the loop that
            # created it, and this loop is not uvicorn's.
            self._client = tts.new_client()

        sink = self._player if destino is None else destino
        generation = self._generation
        async for chunk, _backend in tts.stream(clause, client=self._client):
            if generation != self._generation:
                return  # interrupted while this clause was synthesising
            sink.write(chunk)
            await asyncio.sleep(0)  # let the loop breathe between chunks
