"""Cut the reply into clauses, synthesise each, play it as it arrives.

Waiting for `done` before speaking makes her feel dead; synthesising
every token makes CosyVoice stutter. The rule in between comes from
what samantha-voice measured against the live server.

The widget synthesises rather than waiting for the gateway to send
audio (spec §5.1). It is a Python process on the same machine as
CosyVoice, so the binary WebSocket protocol that a browser would have
needed is never written.
"""

from __future__ import annotations

import asyncio

try:
    from Hermes.plugins.samantha_voice.markers import has_unclosed_tag
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
# with emoji, to a person who has no keyboard. Measured verbatim on
# 2026-08-23 (docs/…-widget-gateway-probe.md §3):
#
#   📬 No home channel is set for Samantha_Kiosk … Type /sethome
#   ↪ Redirected current run (iteration 1/9223372036854775807)
#   💡 First-time tip — I redirected the current run…
#   ⚠️ Couldn't deliver the audio attachment.
#   ⚡ Interrupting current task. I'll respond to your message shortly.
#
# Matching on the leading marker rather than on the text keeps this
# small and language-independent, and it fails safe: the worst case is
# staying quiet about something that was not hers to say. Her own
# replies never open with one — the personality spec's markers are
# `[laughter]`, `[breath]`, `[sigh]` and `<laughter>`, none of which is
# an emoji.
_SYSTEM_MARKERS = ("📬", "↪", "💡", "⚠️", "⚡", "🔔", "🛑")


def is_system_message(text: str) -> bool:
    """True for a frame the gateway wrote about itself. Never spoken."""
    stripped = text.strip()
    if not stripped:
        return True
    return stripped.startswith(_SYSTEM_MARKERS)


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
    """Synthesise clauses IN ORDER and hand the PCM to the player.

    The order is the whole reason this has a queue. Firing one
    `say()` per clause concurrently — which is the obvious way to write
    it — synthesises them in parallel and interleaves their chunks in
    the player, so a two-clause reply comes out shredded. Clauses are
    strictly sequential; only the *first* one's latency is on the
    critical path, and that is the latency the chunking was for.
    """

    def __init__(self, player) -> None:
        self._player = player
        self._client = None
        self._generation = 0
        self._queue: asyncio.Queue[tuple[int, str]] = asyncio.Queue()
        self._worker: asyncio.Task | None = None

    def start(self) -> None:
        """Start the worker. Must be called on the asyncio loop."""
        if self._worker is None:
            self._worker = asyncio.ensure_future(self._run())

    def enqueue(self, clause: str) -> None:
        """Queue a clause to be spoken after everything already queued."""
        self._queue.put_nowait((self._generation, clause))

    async def _run(self) -> None:
        while True:
            generation, clause = await self._queue.get()
            if generation != self._generation:
                continue  # queued before an interruption; drop it
            try:
                await self.say(clause)
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

    async def say(self, clause: str) -> None:
        from samantha import tts

        if self._client is None:
            # An httpx.AsyncClient may only be used on the loop that
            # created it, and this loop is not uvicorn's.
            self._client = tts.new_client()

        generation = self._generation
        async for chunk, _backend in tts.stream(clause, client=self._client):
            if generation != self._generation:
                return  # interrupted while this clause was synthesising
            self._player.write(chunk)
            await asyncio.sleep(0)  # let the loop breathe between chunks
