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


# Below this length a clause is held and merged into the next one.
# The value is NOT empirically derived — it was picked before anything
# was measured, and the measurement (see stream()'s docstring) points
# the other way: lower it toward 20-25. Every char of this floor makes
# holding more likely, and held text at the end of a reply is never
# spoken at all. Changing the value is the user's call and has its own
# task; do not raise it.
MIN_CLAUSE_CHARS = 40
# Ceiling on `_pending`, so an unclosed <laughter> tag cannot swallow
# the rest of the turn: past this length the buffer is released whatever
# the tag balance, risking one malformed clause instead of silence for
# the remainder of the reply. 400 is ~2.3x CosyVoice's effective
# ~173-char reference prompt and well clear of both ordinary merges and
# MIN_CLAUSE_CHARS. Rationale in full: stream()'s docstring.
MAX_PENDING_CHARS = 400


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
        # tag under MAX_PENDING_CHARS. See stream()'s docstring for why.
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
        below MIN_CLAUSE_CHARS, and a 20-40 char Hermes clause is
        squarely in the range that measurement against the live server
        (2026-08-22) showed as risky. Numbers below can drift with the
        server build; re-measure rather than trust them blindly.

        The server does NOT crash on short text — it logs a warning
        ("... too short than prompt text ..., this may lead to bad
        performance") and still returns audio. Its actual reference
        prompt, `prompt_text`, is `~/.samantha/voices/ref/samantha.txt`
        (131 chars) with `"You are a helpful assistant.<|endofprompt|>"`
        (44 chars) prepended before the length comparison — an
        effective ~173 chars, not 131. So most short clauses just
        degrade quality, they don't fail.

        The real failure is narrower and content-specific, not simply
        "too short relative to the reference": isolated one-or-two-word
        utterances fail intermittently — measured `'No.'` failing 2/6
        calls and bare `'No'` 1/6 — while `'Sí.'` and `'Ya.'` never
        failed in 6 calls each, and the longer `'No, claro.'` never
        failed either. Length alone didn't predict it either: 0
        failures across 16 calls at ~15 chars, 16 at ~30, 16 at ~50, 8
        at ~80, and 20 each at 3-4, 6-8, and 10-13 chars. So the merge
        below isn't defending against a length cutoff so much as making
        sure an isolated short utterance like a bare "No." never reaches
        CosyVoice alone — the same word merged into a longer clause was
        fine every time it was tested. So merging has to happen here,
        across calls, via `self._pending`.

        And when the isolated-fragment failure does happen, it doesn't
        look like the empty-body case tts.py already detects: the
        observed failure is the server closing the connection mid-
        response (`peer closed connection without sending complete
        message body`), which httpx surfaces as `RemoteProtocolError` —
        a transport error, not an HTTP 200 with an empty body. That's
        why the except clause below has to catch `httpx.HTTPError`
        alongside `RuntimeError`, not just the latter.

        Two conditions hold a clause back rather than sending it:
        - it is still under MIN_CLAUSE_CHARS, or
        - it holds an unclosed `<laughter>` tag (see `chunking.
          has_unclosed_tag`) — the SentenceChunker knows nothing about
          this tag either, so it can split `<laughter>Ya. Claro</laughter>`
          at the period, leaving a fragment with an opening tag and no
          close — the same isolated-fragment shape measured above as
          intermittently unreliable.

        The unclosed-tag hold is capped at MAX_PENDING_CHARS: if the
        model never closes the tag, `has_unclosed_tag` stays true for
        the rest of the turn and would otherwise merge every remaining
        clause into `_pending` forever, going silent for the rest of
        the reply. Past the cap, the clause is released regardless of
        tag balance; it's released as a single malformed clause, which
        may hit the failure described above and be lost — but only that
        one clause instead of the rest of the turn. See also
        `chunking.py`'s note on the inverse case: a legitimate long
        `<laughter>` span could trip this same cap before it closes.

        LIMITATION — and for the tail, buffering is a net LOSS: there is
        no end-of-reply signal available to this provider, so a reply
        whose final clause(s) never clear the MIN_CLAUSE_CHARS condition
        (and stay under MAX_PENDING_CHARS) leaves that text stranded in
        `self._pending` forever, unspoken. Held is 100% lost; sent, for
        the worst measured string ("No."), is ~33% lost. So buffering is
        an improvement only for a clause that later clears both
        conditions, and strictly worse for one that never does. This is
        not hypothetical: the first real three-sentence test lost
        "¿Quieres que hablemos de ello un rato?" (38 chars) exactly this
        way. Lowering MIN_CLAUSE_CHARS is the cheap mitigation; do not
        invent a flush for the tail without a real end-of-turn hook from
        Hermes.
        """
        stripped = text.strip()
        if not stripped:
            return
        clause = f"{self._pending} {stripped}" if self._pending else stripped
        too_short = len(clause) < MIN_CLAUSE_CHARS
        unclosed = len(clause) < MAX_PENDING_CHARS and has_unclosed_tag(clause)
        if too_short or unclosed:
            self._pending = clause
            return
        self._pending = ""

        emitted = 0
        try:
            for chunk in iter_sync(lambda c=clause: _pcm_only(c)):
                emitted += len(chunk)
                yield chunk
        except (RuntimeError, httpx.HTTPError) as exc:
            # Both shapes a failed clause arrives as (see stream()'s
            # docstring): RuntimeError from tts.py, and httpx.HTTPError —
            # the one that actually fires, as RemoteProtocolError. Caught
            # so one lost clause doesn't abort the rest of the reply: on
            # an appliance, half a reply beats silence.
            logger.warning(f"samantha-voice: clause failed, skipping — {exc}")
        finally:
            self.bytes_yielded_per_clause.append((clause, emitted))


async def _pcm_only(clause: str):
    """Drop tts.stream()'s backend label; the provider only wants bytes."""
    async for chunk, _backend in tts.stream(clause):
        yield chunk


CosyVoiceStreamingProvider = register("cosyvoice")(CosyVoiceStreamingProvider)
