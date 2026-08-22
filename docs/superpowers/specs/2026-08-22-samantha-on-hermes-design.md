# Samantha on Hermes — design

**Date:** 2026-08-22
**Status:** design, approved section by section in conversation. Not yet
a plan.
**Depends on:** `2026-08-21-hermes-herald-capability-map.md` — the spike
that established what Hermes v0.20.x gives us. Every capability claim
here is sourced there; this document does not re-argue them.

---

## 1. Goal and shape

Samantha stops owning the conversation turn and becomes a set of Hermes
plugins. Hermes owns the LLM turn, transcription and the reply stream.
We keep the three things that are actually Samantha — her face, her
voice, and her memory — and ship each as a plugin rather than a fork, so
upstream releases arrive as a version bump instead of a re-merge.

Three plugins, one of which has hard code in it:

- **`samantha-voice`** — a `StreamingTTSProvider` for CosyVoice.
- **`samantha-memory`** — a `MemoryProvider` wrapping the existing
  `Memory`.
- **`samantha-kiosk`** — a `kind: platform` adapter that serves the OS1
  frontend, owns the WebSocket to it, and carries the voice loop.

Personality is not code: `SOUL.md` plus the adapter's `platform_hint`.

Audio capture stays in the browser (ruling 2026-08-22, recorded in the
capability map §4d).

**Non-goal:** replacing the OS1 interface. Hermes gives us nothing there
and it is the product.

---

## 2. Runtime topology

One process for the conversation: `hermes gateway`, with our three
plugins loaded from `~/.hermes/plugins/`. Chromium runs kiosk-mode
against the HTTP server the adapter opens in `connect()`.

```
Chromium (kiosk)
  │  HTTP  → frontend/dist (served by the adapter)
  │  WS    → binary PCM both ways + JSON control
  ▼
samantha-kiosk  (kind: platform, inside `hermes gateway`)
  │  MessageEvent(VOICE|TEXT) → handle_message()
  ▼
Hermes core ── faster-whisper (local STT)
  │         ── LLM turn
  │         ── prefetch()/sync_turn() → samantha-memory → Chroma + ring
  ▼
StreamingTTSConsumer → samantha-voice → CosyVoice on the 4090
  │  PCM chunks
  ▼
adapter.write_streaming_tts() → WS → browser playback
```

The existing FastAPI backend keeps running untouched until step 7 of
§8. There is a working Samantha at every point in the migration.

> **Note added 2026-08-22:** this diagram and §5 predate a probe into
> Hermes' own web surface. Hermes actually has three independent server
> surfaces, and none hosts another: `hermes dashboard` serves Hermes'
> SPA but hosts no platform adapters; `hermes serve` is headless (no
> SPA, no adapters); `hermes gateway` hosts platform adapters but serves
> no SPA. Our systemd unit runs `hermes gateway`
> (`systemd/samantha-hermes.service:31`), which is why the diagram above
> is correct as drawn — but it means the SPA has to come from somewhere,
> and it isn't the dashboard.
>
> The design's choice stands: `samantha-kiosk` opens its own HTTP server
> for the OS1 frontend inside the gateway process, rather than shipping
> the UI as a plugin into `hermes dashboard`. This was a considered
> choice, not an oversight — the user reaffirmed it on 2026-08-22 after
> being offered the dashboard-plugin alternative explicitly. Reason: the
> OS1 interface is the product, and the dashboard shell paints a
> persistent HERMES wordmark on every route with no chromeless mode;
> hosting our screen there would mean winning the look back by covering
> theirs, every release. See
> `docs/superpowers/specs/2026-08-22-hermes-dashboard-probe.md` for the
> full comparison.

---

## 3. `samantha-voice` — the CosyVoice provider

The riskiest piece and the one that carries her identity. Contract, from
`tools/tts_streaming.py`:

```python
class StreamingTTSProvider(ABC):
    sample_rate: int = 24000
    channels: int = 1
    sample_width: int = 2

    @staticmethod
    def available() -> bool: ...
    def stream(self, text: str) -> Iterator[bytes]: ...
```

Registered with `@register("cosyvoice")`; selected via
`tts.streaming.provider`. CosyVoice already emits 24 kHz mono, so the
format matches without resampling.

**Synthesis call:** `inference_zero_shot` with the reference WAV *and*
its transcript. Not `cross_lingual` — that strips prosody and sounds
robotic. This is settled from earlier work; do not revisit.

**Two hazards specific to clause-by-clause streaming**, both of which
come from existing knowledge and neither of which the Hermes side knows
about:

1. **Isolated short fragments.** *(Rewritten 2026-08-22 after measuring
   against the live server — see "Empirical findings" below. The
   original claim here, "CosyVoice's hifigan crashes when `tts_text` is
   much shorter than `prompt_text`", is false for this server build and
   should not be repeated.)* Short text does not crash: the server logs
   "this may lead to bad performance" and returns audio. What does fail
   is narrower and content-specific — an isolated one-or-two-word
   utterance, intermittently, arriving as a mid-response disconnect.
   A floor already exists on Hermes' side: `SentenceChunker` merges any
   fragment shorter than `min_len` (default 20 chars) into the
   *following* sentence (`~/hermes-src/tools/tts_streaming.py:95-100`).
   The provider still merges sub-threshold clauses rather than passing
   them through, but the reason is "never send a bare 'No.' alone", not
   a length cutoff — and merging costs the tail, so the threshold
   should be low (see the findings).
2. **Split expression markers.** `[laughter]` renders as a sound;
   `<laughter>palabra</laughter>` renders as smiled speech. A clause
   boundary landing inside either form produces garbage. The provider
   must not split a marker, which means it needs its own awareness of
   them at the chunk seam.

**Async/sync bridge.** `stream()` is a synchronous `Iterator[bytes]`;
our CosyVoice client is async. Run the async request on a dedicated loop
in a worker thread and yield from a queue. It must not block the
gateway's event loop, and it must terminate cleanly when the consumer
stops early on an abort.

**`available()`** must be honest and cheap. Note the existing bug it
must not repeat: our `tts.is_available()` never probes the network, so
with the server down `/speak` hangs for the full timeout instead of
failing fast. Here, `available()` is documented as making no network
calls, so cheap-and-local is correct — but the *streaming* path needs a
short connect timeout so a dead 4090 surfaces in a second, not sixty.
*(Status: not implemented. All four httpx timeout legs in
`backend/samantha/tts.py` are still `tts_cosyvoice_timeout_s` (60 s), so
with CosyVoice down every clause blocks a minute. Considered and
deferred, not overlooked.)*

### 3.1 Empirical findings against the live CosyVoice, 2026-08-22

Measured directly against the server on the 4090 during plan 1. **These
contradict the premise plan 1 was written on.** Read them before tuning
anything, and re-measure rather than trusting the numbers blindly — they
can drift with the server build.

1. **The short-text crash does not reproduce.** The server warns and
   proceeds. Its own log: `WARNING synthesis text Me alegro mucho. too
   short than prompt text You are a helpful assistant.<|endofprompt|>…,
   this may lead to bad performance`. Degraded quality, not a crash.

2. **The effective reference prompt is ~173 chars, not 130.** The server
   prepends `"You are a helpful assistant.<|endofprompt|>"` (44 chars) to
   `prompt_text` (our 130-char transcript) before the length comparison.
   Every "relative to the reference" calculation using 130/131 is off.

3. **Failures are content-specific, not length-driven.** Zero failures at
   ~15 chars (16 calls), ~30 (16), ~50 (16), ~80 (8), and at 3-4, 6-8 and
   10-13 chars (20 each). But isolated `'No.'` failed 2/6 and bare `'No'`
   1/6, while `'Sí.'`, `'Ya.'` and `'No, claro.'` never failed in 6 each.
   So it is the isolated one-or-two-word utterance, intermittently
   (~20-33%), not the length.

4. **The failure mode is a transport error, not an empty body.** It
   arrives as `peer closed connection without sending complete message
   body` — httpx `RemoteProtocolError` — so a provider that catches only
   `RuntimeError` (tts.py's 200-with-no-audio case) lets it abort the
   whole reply. Catch `httpx.HTTPError` too.

5. **Merging fixes it, but a high threshold costs the tail.** `'No,
   claro.'` never failed, so merging an isolated fragment into its
   neighbour is the right guard. But held text at the end of a turn is
   *never spoken* — there is no end-of-reply hook — so for a tail, held
   = 100% lost against sent = ~33% lost. Keep the merge threshold low
   (~20-25); Hermes' own `SentenceChunker` already merges under 20.
   Confirmed in use: a 38-char final sentence, "¿Quieres que hablemos de
   ello un rato?", was held under `MIN_CLAUSE_CHARS = 40` and never
   spoken, on the very first three-sentence test.

6. **Clause-by-clause synthesis flattens the voice.** The user's verdict
   on the shipped plugin: "suena bien, un pelín artificial comparado con
   otras versiones de voz", and against an A/B with the same text
   synthesised whole, "mucho mejor" — each clause is synthesised with no
   knowledge of its neighbours, so intonation does not carry across a
   sentence. The trade is latency against naturalness; middle options
   exist (chunk by sentence rather than clause; speak sentence one fast
   and the remainder as one piece behind it). Ruled: proceed as-is, tune
   later.

7. **Hermes' environment needs our dependencies, not just PYTHONPATH.**
   `httpx` was already in Hermes' venv; `loguru` was not, and the plugin
   failed to import until it was installed there. Declare them in
   `plugin.yaml`'s `python_dependencies`. Plan 2 additionally needs
   `chromadb`, `fastembed` and `numpy`, none of which are present.

---

## 4. `samantha-memory` — the memory provider

`kind: exclusive`. Subclasses `MemoryProvider` from
`agent.memory_provider`. This is a wrapper, not a rewrite: the store,
the embedder, the ring buffer and the fact chunks all stay exactly as
they are.

- `prefetch(query)` → today's `gather_context()`: facts + semantic
  recall + short-term ring.
- `sync_turn(user, assistant, *, session_id, messages)` → today's
  writes. **Documented as MUST be non-blocking** — our Chroma work
  already runs off the event loop and must continue to.
- `is_available()` — no network calls, which suits a local store.
- `initialize(session_id)`, `get_config_schema()`, `save_config()`.
- `get_tool_schemas()` / `handle_tool_call()` — not used initially.

**"Samantha never forgets" is preserved by omission:** nothing in the
contract imposes expiry, so we simply do not implement forgetting.
`Memory.forget()` and `clear()` stay admin-only, as today.

What `sync_turn` receives is **not** what it should store — see §6.

---

## 5. `samantha-kiosk` — the platform adapter

> **Note added 2026-08-22:** see the topology note in §2 — this adapter
> runs inside `hermes gateway` and opens its own HTTP server for the
> frontend; it is not a plugin into `hermes dashboard`. That is a
> considered, reaffirmed choice, not a gap.

Modelled on `plugins/platforms/irc/`, the smallest worked example.
`plugin.yaml` with `kind: platform`; `adapter.py` exposing
`register(ctx)` which calls `ctx.register_platform(...)`.

Registration arguments that matter for us:

- `platform_hint` — the per-platform instruction injected into the
  prompt. For the kiosk this carries "you are being spoken aloud",
  which `personality.py` carries by hand today.
- `max_message_length` — a natural cap on reply length, which is half
  the battle the system prompt currently fights.
- `allowed_users_env` / `allow_all_env` — single user, always.
- `pii_safe` — this device is the user's home; set deliberately, not by
  copy-paste.

Abstract methods: `connect()` (opens the HTTP + WS server),
`disconnect()`, `send()`. Plus the opt-in streaming seam — four of the
five methods are `async def`, and `begin_streaming_tts` **returns** the
handle rather than receiving one:

```python
def supports_streaming_tts(self, chat_id, audio_format) -> bool          # → True
async def begin_streaming_tts(self, chat_id, audio_format, metadata=None) -> Optional[StreamingTTSHandle]
async def write_streaming_tts(self, handle, chunk: bytes) -> None
async def finish_streaming_tts(self, handle, *, interrupted: bool = False) -> None
async def abort_streaming_tts(self, handle, error: Optional[str] = None) -> None
```

> **Correction, 2026-08-22:** the capability map §1 this section draws
> on originally showed all five methods as plain `def`, with
> `begin_streaming_tts` receiving a handle instead of returning one and
> no `interrupted`/`error` keyword arguments. Both documents corrected
> against source; see
> `docs/superpowers/specs/hermes-contracts-v0.20.5.md` (Contract 5).
> Practically: `begin_streaming_tts` is where the adapter constructs and
> returns the `StreamingTTSHandle`; `write_streaming_tts` writes PCM
> frames to the socket keyed off that handle; `abort_streaming_tts` must
> be idempotent — late chunks arriving after abort are dropped silently,
> not raised — which our async/sync bridge (§3) must respect.

### 5.1 The WebSocket protocol

One client. A new connection replaces the old one.

**Binary frames.** Up: one complete utterance, 16 kHz int16 mono, sent
when the browser's VAD fires `onSpeechEnd`. Down: reply audio, 24 kHz
int16 mono, as `write_streaming_tts` delivers it.

**JSON text frames, up:**

- `{"type": "interrupt", "playedMs": <int>}` — barge-in. `playedMs` is
  how much of her reply was actually audible, and it drives §6.
- `{"type": "text", "text": "..."}` — typed input, so the whole system
  is testable without a microphone.

**JSON text frames, down:**

- `{"type": "transcript", "text": "..."}` — what STT heard.
- `{"type": "token", "text": "..."}` — reply text as it streams, for
  the history panel. Sourced from the `on_stream_delta` hook.
- `{"type": "state", "value": "listening"|"thinking"|"speaking"}` —
  drives the wave and the screen state machine. Sourced from
  `on_stream_start` / `on_stream_end` plus playback events.
- `{"type": "error", "text": "..."}` — Spanish, in her voice. Never a
  stack trace, never an English string.

### 5.2 Inbound audio

`cache_audio_from_bytes()` on the base class stashes the utterance;
the adapter then builds
`MessageEvent(message_type=MessageType.VOICE, media_urls=[...], source=...)`
and calls `handle_message()`. Hermes transcribes with local
faster-whisper and applies its own hallucination filter (26 known
phantom phrases) before the text reaches the model.

### 5.3 Interruption

The browser's Silero VAD is armed for **the whole turn**, not only
during playback. On `onSpeechStart` it sends `interrupt`. The adapter:

- calls `agent.interrupt()` if the turn is still generating,
- calls `abort_streaming_tts()` if audio is playing — idempotent per
  the real contract, so it is safe even if a race lets one more
  `write_streaming_tts` land after it,
- and records `playedMs` for §6.

---

## 6. Recording only what was heard

Hermes does not trim an interrupted reply. It tells the model it was cut
off and keeps the text. For a general agent that is fine. For Samantha
it is not: our store is append-only by directive, so an interruption at
word 5 of 60 would persist 55 words she never spoke, and semantic recall
would later surface them as things she said — the same failure shape as
the unresolved `name='Hore'` vs recalled "Ore" divergence.

**Rule: our store records what was heard, not what was generated.**

Implementation: `samantha-voice` knows how many PCM bytes it yielded per
clause, so the adapter can hold a running map of clause → cumulative
milliseconds. On interrupt, `playedMs` selects the last clause that
finished sounding, and the assistant text is trimmed there before it
reaches `sync_turn()`. Granularity is the clause, not the word — honest,
cheap, and good enough. Hermes' own history keeps whatever it keeps;
ours, the one that feeds recall, does not.

> **Correction, 2026-08-22:** the paragraph above is stale against the
> merged-clause code that landed after it was written
> (`Hermes/plugins/samantha_voice/provider.py`; see the decision
> record's rulings 14-17 in
> `docs/superpowers/specs/2026-08-22-samantha-voice-decision-record.md`).
> Three things plan 3 needs to know before it is written:
>
> - **Granularity is the merged clause, not the clause.** Since the
>   `_pending` buffer landed, a key in `bytes_yielded_per_clause` records
>   the *merged* clause, which can be up to `MAX_PENDING_CHARS` (400
>   characters) of text, not one clause. An interruption can only be
>   trimmed back to the start of the merged block that was sounding when
>   it was cut — so up to 400 characters of text she never actually
>   finished saying can still be recorded as heard. That is the opposite
>   direction of error from the one this section exists to prevent (the
>   risk was persisting words she never spoke); plan 3 must accept that
>   bound rather than assume single-clause precision.
> - **The map's keys are not the assistant's reply text**, and cannot be
>   reassembled into it by concatenation or substring match. Three
>   independent reasons: Hermes strips markdown before the text reaches
>   the provider (`~/hermes-src/gateway/streaming_tts_consumer.py:322`);
>   our provider merges held clauses with an inserted space
>   (`Hermes/plugins/samantha_voice/provider.py`); and text still sitting
>   in `_pending` at end of turn is never yielded at all, so it appears
>   under no key. The trim implementation needs its own mapping back to
>   the original reply text — it cannot treat the map's keys as that
>   text.
> - **Bytes yielded is not bytes heard.** This section is right to take
>   `playedMs` from the adapter (§5.1, reported by the browser) rather
>   than from `samantha-voice`'s own byte counter — that choice must
>   stay. On the speaker path Hermes prefetches audio up to three
>   sentences ahead of playback (`~/hermes-src/tools/tts_tool.py` around
>   line 4290, `_prefetch_sem = threading.Semaphore(3)`), so bytes the
>   provider has already yielded can be well ahead of what has actually
>   played. The byte counter is a synthesis-progress counter, not a
>   playback-position counter; nobody should later "simplify" the trim
>   by reading it as one.

**Resolved from source, 2026-08-22.** Read the actual call sites in
`~/hermes-src` (tag v2026.8.19) rather than the docstrings:
`gateway/streaming_tts_consumer.py` (the only caller of both methods)
and its own caller, `gateway/run.py`.

- **On barge-in, only `abort_streaming_tts` fires — never
  `finish_streaming_tts`.** `gateway/run.py:28766-28772` (repeated at
  ~29057 and ~29159) detects an interrupt, calls `agent.interrupt(...)`,
  then `consumer.abort("barge-in")`. `StreamingTTSConsumer.abort()`
  (`gateway/streaming_tts_consumer.py:384-411`) sets `self._aborted =
  True` and schedules `self._safe_abort(reason)`, which calls
  `adapter.abort_streaming_tts(handle, error=reason)`
  (`streaming_tts_consumer.py:368-373`; `error` here is literally the
  string `"barge-in"`). The drain loop's only call to
  `finish_streaming_tts` is gated by `if not self._aborted and
  self._handle is not None:` (`streaming_tts_consumer.py:275-278`) — a
  synchronous check with no `await` between it and the call, so once
  `abort()` has set `_aborted = True` that branch cannot run. Barge-in
  and normal completion are mutually exclusive paths to two different
  methods, not one method with a flag.
- **`interrupted=True` is not a signal we can use — the one call site
  that passes it is gated to never fire it.** The single call is
  `finish_streaming_tts(self._handle, interrupted=self._aborted)`
  (`streaming_tts_consumer.py:278`), reached only when the surrounding
  `if not self._aborted` (line 275) already holds — so `self._aborted`,
  and therefore `interrupted`, reads `False` on every call that actually
  happens. This corrects the capability map §1 correction's own
  speculation: the kwarg exists in the signature but is, in this call
  site, effectively dead — barring a sub-microsecond cross-thread race
  between the flag check and the argument evaluation, which no adapter
  should design around. Treat `finish_streaming_tts`'s `interrupted` as
  unusable for barge-in detection; `abort_streaming_tts` firing (or not)
  is the real signal.
- **Nothing tells the caller how much audio was played before the cut.**
  `abort_streaming_tts(handle, error=reason)` carries only a free-text
  `error` string (here, `"barge-in"`) — no duration, no byte/sample
  count. `StreamingTTSHandle.audible` is a plain bool ("was any audio
  ever written"), not an amount. No other value crosses this seam. This
  is the answer that matters most: Hermes supplies **nothing**
  quantitative about playback progress, so the trim rule below is not
  optional plumbing — it is the only source of "how much did she
  actually say", and it must be computed on our side exactly as
  described.

Confirms and sharpens the trim rule rather than replacing it:
`abort_streaming_tts` firing is when to trim; `playedMs`/the clause→ms
map (computed by us, from bytes `samantha-voice` itself wrote) is what
decides where.

---

## 7. Frontend changes

Small, and mostly subtraction.

- `useBargeIn.ts` gains `onSpeechEnd` (it becomes the endpointer, not
  just the interrupt trigger) and is armed for the whole turn.
- **Task 22 stays in scope:** vendor the Silero model and the ONNX
  runtime under `public/`. A 24/7 appliance must not fetch its VAD from
  a CDN.
- `net/wsClient.ts` speaks the §5.1 protocol.
- `net/tts.ts` `speak()` is deleted; audio arrives on the socket.
- `net/audio-analyser.ts` reads the WebAudio node playing the downlink
  instead of an `<audio>` element. Same idea, different source.
- `react-speech-recognition` and the browser Web Speech path are
  removed. This closes the largest privacy leak in the system: raw voice
  to Google.

Onboarding screens are untouched.

---

## 8. Build order

Ordered by risk, not by dependency. Steps 1 and 2 are verifiable
through Hermes' own CLI, with no kiosk in existence.

1. **`samantha-voice`.** Verify: type into the Hermes CLI and hear the
   reply in Samantha's Spanish voice, streaming. This proves the
   sync/async bridge, the short-text guard and the marker handling on
   day one, before anything depends on them.
2. **`samantha-memory`.** Verify: converse through the CLI; our Chroma
   grows, facts recall, the ring evicts, nothing is forgotten.
3. **`samantha-kiosk`, text only.** WS + static serving + a typed
   round-trip. Proves the plugin/gateway plumbing and the §5.1 protocol
   with audio out of the picture.
4. **Audio on the proven adapter.** Utterance up, PCM down.
5. **Interruption and the §6 trim.** Together; the second is meaningless
   without the first.
6. **Onboarding surface**, plus Task 13's `SAMANTHA_ADMIN_TOKEN` on
   `DELETE /profile`, which is still needed and still unimplemented.
7. **Deletion.** `/chat`, `/transcribe`, `/speak`, `/ws` and the
   FastAPI app; `voice_pipeline.py` and its 7 tests; the Pipecat
   dependency.

Steps 1–6 leave today's Samantha running. Only step 7 removes it.

### 8.1 Consequences for the improvement sweep

- Fase 3 (Tasks 14–19) dies.
- Tasks 20 and 24 are re-scoped against this design before dispatch.
- Tasks 13 and 22 survive unchanged.
- Fase 5 largely survives; Task 29 (CLAUDE.md consolidation) grows.
- This work goes on a new branch, not `improvement-sweep-2026-08-04`.

---

## 9. Scope

**In:** the three plugins, the protocol, the trim rule, the frontend
changes above, and the deletions.

**Out, deliberately:**

- Wake word — Hermes runs it on CLI/TUI/desktop only, and we chose the
  browser.
- Native audio capture — reconsider only if wake word is ever asked
  for.
- Full-duplex speech-to-speech (Moshi, Step-Audio and friends). It
  would take her cloned voice, her Spanish, and most of this design
  with it. It is a product bet and deserves its own spike, not a
  smuggled-in component swap.
- Onboarding as agent tools. Tempting — the six questions really are a
  conversation — but it changes proven behaviour and is a separate
  decision.
- Hermes' own memory system, and its agentic tools.

---

## 10. Testing

- **Unit, ours:** the CosyVoice provider's chunk guard (short clause,
  marker at a seam, abort mid-stream); the clause→ms map and the trim
  in §6; the protocol encoder/decoder.
- **Integration, through Hermes:** steps 1 and 2 of §8 are themselves
  integration tests and should be kept as repeatable scripts.
- **Manual, the kiosk:** a spoken round trip; an interruption early in
  a long reply, followed by checking that the stored turn contains only
  what was heard; a 4090-down run confirming a fast, in-character error
  rather than a minute of silence.
- No CI exists (Task 32 declined), so upgrade day is a manual gate.
  Pin a known-good Hermes version; do not track `main`.

---

## 11. Risks and open questions

- **The voice is the whole bet.** If the short-text guard cannot be made
  reliable, streaming clause-by-clause with CosyVoice may not be
  viable, and we would fall back to whole-utterance synthesis — losing
  the latency win but keeping her voice. Step 1 exists to find this out
  first.
- **No stability guarantee anywhere.** No Hermes page or file consulted
  carries an API-stability or deprecation statement. Pinning is
  mandatory, not cautious.
- **`agent.interrupt()` reachability** from a platform adapter is
  inferred from PR #74223's description, not read in the adapter
  context. Confirm during step 5.
- **Room acoustics.** The browser VAD is tuned against this room's
  speakers and laptop mic. The kiosk is different hardware; thresholds
  will need re-tuning and should stay configurable.
- **Unowned, and untouched by this design:** the `Hore`/`Ore`
  divergence. Nothing here fixes it; §6 only stops us making more of
  the same kind of damage.

---

## 12. Decision-log entries owed

If this is adopted, CLAUDE.md needs updating — these are spec changes,
not drift:

- **§1** says Samantha is explicitly *not* "an agentic tool-using
  system". Mounting her on an agent runtime contradicts that.
- **§1** also promises "the device IS Samantha". Already conceded on
  2026-08-07 when everything moved to the 4090; one entry can cover
  both.
- **§2.4** — FastAPI as the fullstack backend ends.
- **§2.8** — the audio decision is revisited: Web Speech goes, browser
  capture stays, and the reasoning changes underneath both.
