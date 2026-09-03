"""CosyVoice as a Hermes StreamingTTSProvider.

Yields raw int16 little-endian mono PCM at 24 kHz — the format
CosyVoice already emits, so nothing is resampled.
"""

from __future__ import annotations

from typing import Dict, Iterator

import httpx
from loguru import logger

from . import tts
from .announce import announcement_pcm
from .bridge import iter_sync
from .markers import has_unclosed_tag

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
#
# 12 is deliberate and low. Hermes' own SentenceChunker already merges
# anything under 20 chars into the FOLLOWING sentence, so mid-reply we
# never receive a fragment shorter than that — which means this floor
# only ever fires on the last fragment of a reply, where holding is
# strictly worse than sending: held text is never spoken (100% lost),
# while sending it risks only the intermittent isolated-fragment
# failure (~33% for the worst case measured, 0% for everything from 10
# chars up in 76 calls). See stream()'s docstring for the numbers.
#
# So the floor is set just above the band where failures actually live,
# not high enough to hijack anything Hermes already considers a
# sentence. Raising it does not buy safety; it buys lost endings.
# Lowered from 40 to 12 on 2026-08-22 after a three-sentence test
# silently dropped a perfectly ordinary 38-char closing question.
MIN_CLAUSE_CHARS = 12
# Ceiling on `_pending`, so an unclosed <laughter> tag cannot swallow
# the rest of the turn: past this length the buffer is released whatever
# the tag balance, risking one malformed clause instead of silence for
# the remainder of the reply. 400 is ~2.3x CosyVoice's effective
# ~173-char reference prompt and well clear of both ordinary merges and
# MIN_CLAUSE_CHARS. Rationale in full: stream()'s docstring.
MAX_PENDING_CHARS = 400

# Failure shapes that mean "the server is not there", as opposed to
# "this clause upset the server". All three are raised before any bytes
# of the request reach CosyVoice — connection refused, no route to a
# powered-off host, no free slot in the pool — so the clause's content
# cannot possibly be the cause, and no other clause of this turn will
# fare better. Everything else in httpx.HTTPError (ReadTimeout,
# RemoteProtocolError, HTTP status errors) means the server answered,
# or started to, and stays a per-clause failure.
_UNREACHABLE = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)

# How many clauses a turn may attempt, with zero audio to show for it,
# before the turn is declared dead by the cumulative rule.
#
# 2, not 1. A single failed clause is ordinary: the isolated-fragment
# failure measured on 2026-08-22 hit 2 of 6 calls for the worst string.
# Announcing on it would talk over a reply that then speaks fine. Two
# clauses with nothing audible between them is not ordinary, and — the
# reason this threshold is cheap — by the time it fires the turn has
# already produced silence, so declaring it dead can never cost the
# user audio they would otherwise have heard.
#
# 2 alone would miss the common one-clause turn (her replies are 1-3
# sentences by design), which is exactly what `_UNREACHABLE` above
# covers: a dead server is caught on clause one, by shape rather than
# by count.
_MIN_SILENT_CLAUSES = 2

# Chunk size the announcement clip is handed out in — the same 4 KB
# `jarvis_voice.tts.stream` reads the CosyVoice response with, so the
# consumer sees the clip exactly as it sees a spoken clause.
_CLIP_CHUNK_BYTES = 4096


class SilentTurnError(Exception):
    """No clause in an entire speaking turn produced any audio.

    Deliberately NOT a RuntimeError: `stream()` catches RuntimeError as
    "one clause failed, keep going", and `jarvis_voice.tts` raises
    RuntimeError for exactly that. A turn-level failure must never be
    mistaken for a clause-level one by a future edit to that handler.
    """


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
        # and JARVIS' permanent memory gets corrupted with no
        # exception raised anywhere to catch it. Re-check that call site
        # before upgrading the pinned Hermes commit.
        self.bytes_yielded_per_clause: list[tuple[str, int]] = []
        # Text carried over from a previous stream() call because,
        # merged with everything seen so far this turn, it was still
        # either under MIN_CLAUSE_CHARS or held an unclosed <laughter>
        # tag under MAX_PENDING_CHARS. See stream()'s docstring for why.
        self._pending: str = ""
        # Set once this turn has been declared dead, so the announcement
        # plays once and the exception is raised once. Same per-turn
        # lifetime as bytes_yielded_per_clause above, and correct for
        # the same reason: Hermes builds a fresh provider per turn.
        self._turn_declared_dead: bool = False

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
        prompt, `prompt_text`, is `~/.jarvis/voices/ref/jarvis-ref.txt`
        (130 chars once stripped) with
        `"You are a helpful assistant.<|endofprompt|>"` (44 chars)
        prepended before the length comparison — an effective ~173
        chars, not 130. So most short clauses just
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

        A FAILED CLAUSE IS SWALLOWED; A SILENT TURN IS NOT. Skipping a
        clause is deliberate and stays. But the same `except` against a
        dead server swallowed all 15 clauses of a reply and raised
        nothing, which on an appliance is indistinguishable from
        thinking. `_turn_is_dead` separates the two: one clause failing
        is ordinary, a whole turn producing no audio is not. When it
        fires, `_announce_dead_turn` plays a pre-recorded clip in
        JARVIS' voice and raises `SilentTurnError`. Read `announce.
        py` before touching that path — the clip being pre-recorded is a
        ruling, not an implementation detail.

        Two conditions hold a clause back rather than sending it:
        - it is still under MIN_CLAUSE_CHARS, or
        - it holds an unclosed `<laughter>` tag (see `markers.
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
        `markers.py`'s note on the inverse case: a legitimate long
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
        failure: BaseException | None = None
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
            logger.warning(f"jarvis-voice: clause failed, skipping — {exc}")
            failure = exc
        finally:
            self.bytes_yielded_per_clause.append((clause, emitted))

        # Reached only on a normal exit from the block above — a
        # GeneratorExit from a barge-in re-raises out of the `finally`
        # and never gets here, so an interruption is never mistaken for
        # a dead server.
        if failure is not None and self._turn_is_dead(failure):
            yield from self._announce_dead_turn(failure)

    def _turn_is_dead(self, failure: BaseException) -> bool:
        """True when `failure` means the whole turn is lost, not one clause.

        Two independent signals, because neither covers the other's case:

        - the failure never reached the server (`_UNREACHABLE`), which
          is true of a powered-off 4090 on the very first clause of a
          one-sentence reply;
        - this turn has attempted `_MIN_SILENT_CLAUSES` clauses and has
          yielded zero bytes across all of them, which catches the
          shapes where the server does answer but never with audio.

        Only ever True once per turn: after the first time, the
        announcement has played and the exception has been raised, and
        repeating either adds noise, not information.
        """
        if self._turn_declared_dead:
            return False
        if isinstance(failure, _UNREACHABLE):
            self._turn_declared_dead = True
            return True
        attempted = len(self.bytes_yielded_per_clause)
        audible = sum(count for _, count in self.bytes_yielded_per_clause)
        if attempted >= _MIN_SILENT_CLAUSES and audible == 0:
            self._turn_declared_dead = True
            return True
        return False

    def _announce_dead_turn(self, failure: BaseException) -> Iterator[bytes]:
        """Say it out loud, then raise.

        The clip's PCM is yielded into this very stream because that is
        the only channel out of here that reaches the person in the
        room. Both of Hermes' call sites swallow an exception from
        `stream()` into a log line — `_enqueue_audio` and
        `_consume_to_queue` in `tools/tts_tool.py`, `_synthesise_and_
        write` in `gateway/streaming_tts_consumer.py` — which is the
        same not-enough we already had. Audio is not swallowed.

        The exception still follows, for the caller that can use it: on
        the gateway path a turn that stayed inaudible clears
        `_suppress_whole_file`, so the reply is retried through the
        whole-file provider, which raises into a visible error envelope
        (`sync_provider.py`'s docstring). Nothing here ever reaches
        another TTS backend — see `announce.py` on why that would be
        the failure rather than a fallback.

        The clip's bytes are NOT added to `bytes_yielded_per_clause`:
        that list maps clause text to the audio for that text, and the
        announcement is not something JARVIS said. Plan 3's trim
        therefore under-counts the audible bytes of a dead turn by the
        clip's length — harmless, since a dead turn has no spoken words
        to trim.
        """
        clip = announcement_pcm()
        if clip:
            logger.error(
                "jarvis-voice: no audio this turn — playing the "
                f"pre-recorded announcement ({len(clip)} bytes of PCM)"
            )
            # Same 4 KB chunk size `jarvis_voice.tts.stream` reads with, so
            # the clip reaches the consumer the way a clause does
            # rather than as one large write.
            for start in range(0, len(clip), _CLIP_CHUNK_BYTES):
                yield clip[start : start + _CLIP_CHUNK_BYTES]
        raise SilentTurnError(
            "jarvis-voice: the whole turn produced no audio "
            f"({len(self.bytes_yielded_per_clause)} clause(s) attempted, "
            f"0 bytes yielded); last failure: {failure!r}"
        )


async def _pcm_only(clause: str):
    """Drop tts.stream()'s backend label; the provider only wants bytes.

    An httpx.AsyncClient may only be used on the event loop that created
    it. `iter_sync` runs every clause on a NEW loop in a worker thread,
    so `tts`'s shared module-global client — correct for the FastAPI
    backend, which lives on one uvicorn loop forever — is bound to a
    loop that is already closed by the time the second clause of a turn
    asks for it. That failure surfaces as a transport error that
    `stream()` catches and logs as "clause failed, skipping": measured
    against the live CosyVoice server on 2026-08-22, 7 of 15 clauses
    yielded zero bytes, and half the reply went unspoken with every test
    still green.

    So each clause owns its client: created on this loop, closed on this
    loop. The cost is one TCP handshake per clause to a LAN server;
    measured failure rate with a per-clause client was 0 of 15.
    """
    async with tts.new_client() as client:
        async for chunk, _backend in tts.stream(clause, client=client):
            yield chunk


CosyVoiceStreamingProvider = register("cosyvoice")(CosyVoiceStreamingProvider)
