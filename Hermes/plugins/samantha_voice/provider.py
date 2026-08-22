"""CosyVoice as a Hermes StreamingTTSProvider.

Yields raw int16 little-endian mono PCM at 24 kHz — the format
CosyVoice already emits, so nothing is resampled.
"""

from __future__ import annotations

from typing import Dict, Iterator

import httpx
from loguru import logger

from samantha import tts

from .bridge import iter_sync
from .chunking import has_unclosed_tag

try:  # Hermes is absent on dev machines that only run the unit tests.
    from tools.tts_streaming import StreamingTTSProvider, register
except ImportError:  # pragma: no cover - exercised only without Hermes
    # Minimal shim matching Contract 1's __init__ exactly (see
    # docs/superpowers/specs/hermes-contracts-v0.20.5.md). Plain `object`
    # doesn't work here: `object.__init__` rejects the extra positional
    # args a `super().__init__(tts_config, section)` call would pass it.
    class StreamingTTSProvider:  # type: ignore[no-redef]
        def __init__(self, tts_config: Dict, section: Dict) -> None:
            self.tts_config = tts_config
            self.section = section

    def register(_name):
        return lambda cls: cls


MIN_CLAUSE_CHARS = 40


class CosyVoiceStreamingProvider(StreamingTTSProvider):
    sample_rate: int = tts.OUTPUT_SAMPLE_RATE
    channels: int = 1
    sample_width: int = 2

    def __init__(self, tts_config: Dict, section: Dict) -> None:
        # Contract 1 (docs/superpowers/specs/hermes-contracts-v0.20.5.md):
        # Hermes constructs every StreamingTTSProvider with these two
        # positional args and expects them stored as-is.
        super().__init__(tts_config, section)
        # (clause_text, pcm_bytes_yielded) in emission order. Plan 3
        # turns this into milliseconds to trim an interrupted reply to
        # what the user actually heard — see spec §6. Every clause
        # attempted is recorded here, including one that failed and
        # yielded zero bytes.
        #
        # LOAD-BEARING ASSUMPTION: this list is never reset after
        # construction, which is only correct because Hermes builds a
        # fresh provider per speaking turn — resolve_streaming_provider()
        # is called (and its result assigned to a local, not cached) at
        # the top of stream_tts_to_speaker(), tools/tts_tool.py:4069, on
        # every turn. If a future Hermes version caches the streamer
        # across turns instead, this list keeps growing across turns,
        # the trim in Plan 3 walks stale entries from a previous reply,
        # and Samantha's permanent memory gets corrupted with no
        # exception raised anywhere to catch it. Re-check that call site
        # before upgrading the pinned Hermes commit.
        self.bytes_yielded_per_clause: list[tuple[str, int]] = []
        # Text carried over from a previous stream() call because,
        # merged with everything seen so far this turn, it was still
        # either under MIN_CLAUSE_CHARS or held an unclosed <laughter>
        # tag. See stream()'s docstring for why.
        self._pending: str = ""

    @staticmethod
    def available() -> bool:
        return tts.is_available()

    def stream(self, text: str) -> Iterator[bytes]:
        """Yield PCM chunks for `text`, merging clauses across calls until
        each is safe to hand to CosyVoice.

        Hermes calls stream() once per already-atomic clause — its
        SentenceChunker is constructed with no arguments at all three
        call sites (tools/tts_tool.py:4107, hermes_cli/web_server.py:5404,
        gateway/streaming_tts_consumer.py:79), so its `min_len=20` floor
        is hardcoded and out of reach for this plugin. That floor sits
        below MIN_CLAUSE_CHARS: CosyVoice's hifigan vocoder crashes
        (silent 200 + empty body) when `tts_text` is much shorter than
        the ~131-char reference transcript, and a 20-40 char Hermes
        clause is squarely in that danger band. So merging has to happen
        here, across calls, via `self._pending`.

        Two conditions hold a clause back rather than sending it:
        - it is still under MIN_CLAUSE_CHARS, or
        - it holds an unclosed `<laughter>` tag (see `chunking.
          has_unclosed_tag`) — the SentenceChunker knows nothing about
          this tag either, so it can split `<laughter>Ya. Claro</laughter>`
          at the period, and a fragment with an opening tag and no close
          hits the same silent CosyVoice failure as a too-short clause.

        LIMITATION: there is no end-of-reply signal available to this
        provider, so a reply whose final clause(s) never clear both
        conditions leaves that text stranded in `self._pending` forever,
        unspoken — including a reply that ends with the tag still open,
        which is malformed model output this provider cannot repair
        either way. This is not a regression: today (pre-fix) such a
        clause reaches CosyVoice as-is and dies with the empty-body
        RuntimeError below, so it goes unheard either way. Buffering is
        a strict improvement for every clause that does clear both
        conditions. Do not invent a flush for the tail without an actual
        end-of-turn hook from Hermes.
        """
        stripped = text.strip()
        if not stripped:
            return
        clause = f"{self._pending} {stripped}" if self._pending else stripped
        if len(clause) < MIN_CLAUSE_CHARS or has_unclosed_tag(clause):
            self._pending = clause
            return
        self._pending = ""

        emitted = 0
        try:
            for chunk in iter_sync(lambda c=clause: _pcm_only(c)):
                emitted += len(chunk)
                yield chunk
        except (RuntimeError, httpx.HTTPError) as exc:
            # RuntimeError: tts.py raises this for a non-200 response and
            # for the documented CosyVoice-returns-200-with-no-audio case.
            # httpx.HTTPError: the base for every httpx transport failure
            # (timeout, connection refused, protocol error) — none of
            # which are RuntimeError subclasses, so without this they'd
            # propagate past this try and abort the whole reply instead
            # of just this clause. On an appliance meant to keep talking,
            # a half-spoken reply beats a silent one; losing one clause
            # beats losing the rest of what's already been generated.
            logger.warning(f"samantha-voice: clause failed, skipping — {exc}")
        finally:
            self.bytes_yielded_per_clause.append((clause, emitted))


async def _pcm_only(clause: str):
    """Drop tts.stream()'s backend label; the provider only wants bytes."""
    async for chunk, _backend in tts.stream(clause):
        yield chunk


CosyVoiceStreamingProvider = register("cosyvoice")(CosyVoiceStreamingProvider)
