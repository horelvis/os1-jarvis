# Hermes "Herald" (v0.20.x) — capability map for Samantha

**Date:** 2026-08-21
**Type:** Spike. The output is an answer, not code. Nothing was built.
**Question put to it:** Hermes v0.20.0 "Herald" ships conversational
voice. What does it now give us out of the box, so we stop rebuilding
it — and can Samantha actually be mounted on top of it?
**Supersedes:** the hybrid boundary drawn in
`docs/superpowers/specs/hermes-agent-spike/REPORT.md` (2026-05-26),
which was written against v0.13.0, **before Hermes had any voice**. Its
split — "Hermes is the brain, FastAPI keeps the WebSocket and all
audio" — was correct then and is the exact line this spike redraws.

---

## TL;DR

Mounting Samantha on Hermes is viable, but not as a straight swap, and
the reason is a **hard asymmetry** the release notes do not advertise:

> **Hermes streams audio out; it takes audio in one utterance at a
> time. The asymmetry is streaming, not direction.**

Outbound has a real, opt-in contract on `BasePlatformAdapter` — five
methods, PCM chunks, ordered clause playback, ~500–800 ms perceived
latency. That is precisely the seam a kiosk needs.

Inbound has no streaming counterpart, but it is **not** text-only, which
is what the documentation alone had led me to conclude. Reading
`gateway/platforms/base.py` settles it: `MessageType` carries `AUDIO`
and `VOICE` members alongside `TEXT`, `MessageEvent` carries
`media_urls` / `media_types`, and the base class ships
`cache_audio_from_bytes()` / `cache_audio_from_url()`. So a custom
adapter *can* hand Hermes a voice message — cache the bytes, build a
`MessageEvent(message_type=MessageType.VOICE, media_urls=[...])`, call
`handle_message()` — and Hermes transcribes it with local
faster-whisper. The `pre_transcription` hook exists for exactly this
path.

**Consequence:** adopting Hermes deletes most of Fase 3. What stays ours
is **VAD and endpointing** — deciding when an utterance ends — because
that is the decision an utterance-level API forces onto the caller. What
we give up versus our Pipecat design is partial transcripts: inbound
latency becomes end-of-utterance rather than incremental. For a
companion whose felt latency is dominated by time-to-first-audio on the
reply, and where barge-in needs a local VAD anyway, that is a cheap
trade.

**Recommendation: adopt, as a set of Hermes plugins, with the boundary
drawn at the microphone.** Samantha is buildable as an *extension* —
not merely a client talking to a gateway. See §4b for the plugin
surface, which is the part that makes this worth doing; §5 for the
boundary.

---

## 1. Blocking question 1 — can a custom adapter carry audio?

**Outbound: yes.** The source comment directly above these methods cites
`(#60671)` ("streaming TTS — clause-by-clause synthesis for CLI voice
mode and gateway adapters"); this spike originally cited PR #73862,
which does not match the source comment (see correction note below).
This adds an opt-in seam to `gateway/platforms/base.py`:

```python
def supports_streaming_tts(self, chat_id: str, audio_format: AudioFormat) -> bool

async def begin_streaming_tts(
    self,
    chat_id: str,
    audio_format: AudioFormat,
    metadata: Optional[Dict[str, Any]] = None,
) -> Optional[StreamingTTSHandle]

async def write_streaming_tts(self, handle: StreamingTTSHandle, chunk: bytes) -> None

async def finish_streaming_tts(self, handle: StreamingTTSHandle, *, interrupted: bool = False) -> None

async def abort_streaming_tts(self, handle: StreamingTTSHandle, error: Optional[str] = None) -> None
```

> **Correction, 2026-08-22:** every signature originally shown here was
> wrong — all five were shown as plain `def` (four of the five are
> actually `async def`), `supports_streaming_tts()` was shown taking no
> arguments (it takes `chat_id`/`audio_format`), `begin_streaming_tts`
> was shown *receiving* a handle (it **returns**
> `Optional[StreamingTTSHandle]` — the adapter constructs the handle,
> the caller does not hand it one), and `finish_streaming_tts`/
> `abort_streaming_tts` were shown with no keyword arguments (they carry
> `interrupted: bool = False` and `error: Optional[str] = None`
> respectively). Corrected against source; see
> `docs/superpowers/specs/hermes-contracts-v0.20.5.md` (Contract 5),
> captured verbatim and independently re-verified.

`AudioFormat` carries sample_rate / channels / sample_width.
`StreamingTTSHandle` is opaque with `audible` / `aborted` flags — i.e.
**abort is part of the contract**, which is what barge-in needs;
`abort_streaming_tts` must be idempotent (late chunks arriving after
abort are dropped silently, not raised). `finish_streaming_tts` carries
`interrupted: bool = False` — Hermes' own seam for signalling that a
reply was cut off, relevant to the design doc's §6 "record only what was
heard" rule. A `StreamingTTSConsumer` bridges agent deltas to the
adapter's audio sink through the existing `SentenceChunker` and
serialises clause playback in order. All five methods default to
no-op/False/None, so the contract is additive.

Claimed effect: perceived voice latency ~2–3.5 s → ~500–800 ms.

This maps onto Samantha's existing transport almost exactly: our kiosk
WebSocket already carries binary PCM out and JSON control text.

**Inbound: yes, but only per utterance.** *(Corrected 2026-08-21 after
reading the source. The documentation alone had me conclude "no"; that
was wrong.)* The developer guide documents only `connect()`,
`disconnect()`, `send()` as abstract, with `send_typing()` and
`get_chat_info()` optional, and shows inbound only as text:

```python
event = MessageEvent(
    text=content,
    message_type=MessageType.TEXT,
    source=source,
    message_id=msg_id,
)
await self.handle_message(event)
```

The guide never goes past `MessageType.TEXT`. The code does:

```python
class MessageType(Enum):
    """Types of incoming messages."""
    TEXT = "text"
    LOCATION = "location"
    PHOTO = "photo"
    VIDEO = "video"
    AUDIO = "audio"
    VOICE = "voice"
    DOCUMENT = "document"
    STICKER = "sticker"
    COMMAND = "command"
```

`MessageEvent` carries `media_urls` and `media_types` (alongside
`raw_message`, `metadata`, reply threading and `allow_gateway_control`),
and the base class provides `cache_audio_from_bytes()` and
`cache_audio_from_url()` to stash a voice attachment locally, classified
by MIME type at cache time. There is no dedicated audio field and no
streaming ingress — audio rides the generic media arrays — but the route
exists and is the same one the messaging platforms use.

So the per-platform voice work in the release notes (Feishu, DingTalk,
LINE, QQ, WhatsApp, Weixin) is inbound *classification and routing* on
top of a shared mechanism, not a private capability we are locked out
of.

**Stability:** the adapter guide makes **no** stability statement either
way. Note this corrects the 2026-08-07 research note in the ledger,
which said the contract "explicitly excludes voice/audio and may change
without deprecation" — that was about the *relay connector*, and it is
now stale on both counts.

**What is genuinely missing** is not a direction but a *shape*: there is
no inbound analogue of the streaming-TTS seam. Nothing lets an adapter
push PCM frames in as they arrive and receive partial transcripts back.
Everything inbound is a completed utterance with a cached media file.
That is what pins VAD and endpointing to our side of the line.

---

## 2. Blocking question 2 — can STT and TTS stay in the house?

**STT: yes, cleanly.** "If `faster-whisper` is installed, voice mode
works with **zero API keys** for STT." Models `tiny` … `large-v3`.
Provider priority is local > Groq > OpenAI, so local wins by default. A
local `whisper` CLI is also accepted, and `HERMES_LOCAL_STT_COMMAND`
takes a custom command. The autonomy goal survives.

**TTS: yes, but not with our voice, not for free.** Three local
providers ship — `neutts`, `kittentts`, `piper` — none of which is
CosyVoice, and **we deliberately dropped Piper** (commit `2f7d6cf`,
"drop xtts and piper backends, CosyVoice 3 only"). Samantha's voice is
a zero-shot clone driven from `~/.samantha/voices/ref/samantha.wav`.
Regressing to Piper is not a technical downgrade, it is a different
person. This is identity, not plumbing.

Three routes to keep CosyVoice, in descending order of quality:

1. **A `StreamingTTSProvider` subclass** — confirmed contract, read
   from `tools/tts_streaming.py`:

   ```python
   class StreamingTTSProvider(ABC):
       """Yields raw int16, little-endian, mono PCM chunks at ``sample_rate``."""
       sample_rate: int = 24000
       channels: int = 1
       sample_width: int = 2
   ```

   Two methods: static `available()` ("True when this provider's
   credentials/SDK are usable right now") and abstract
   `stream(text: str)` yielding `bytes` — raw int16 LE mono PCM.
   Providers register with an `@register("name")` decorator;
   `resolve_streaming_provider()` picks one from
   `tts.streaming.provider` (or `auto`), and the code is documented as
   never silently swapping providers.

   This fits CosyVoice well — it already emits 24 kHz — and it is the
   only route that keeps both our voice *and* the streaming win.

   **Caveat worth pricing in:** `stream()` is a *synchronous*
   `Iterator[bytes]`, while our `tts.stream()` is async. The provider
   will need a bridge, and it must not block the event loop.

   **And the finding that matters most here:** the four providers that
   implement streaming today are ElevenLabs, OpenAI, Gemini and xAI —
   **all four are cloud**. None of the local providers (piper, neutts,
   kittentts) stream. So "local voice" and "streaming voice" are
   currently mutually exclusive in stock Hermes, and the only way to
   have both is to write this provider ourselves. That is not a
   nice-to-have; it is the price of keeping her voice and the autonomy
   goal at the same time.
2. **`openai` provider with `base_url`** pointed at an
   OpenAI-compatible shim in front of CosyVoice. CosyVoice's HTTP API
   is not OpenAI-shaped, so this means writing and running a shim —
   a second service on the 4090 for no gain over route 1.
3. **`type: command` custom provider** — Hermes writes text to a temp
   file and runs a shell command. Simplest, and **file-based, so it
   forfeits streaming**: back to waiting for whole utterances.

Also worth noting against the "clause-by-clause" headline: the TTS docs
say built-in providers "deliver complete audio files" and that Hermes
"splits longer replies into ordered, sentence-aware chunks". The
streaming is chunk-and-play-in-order, not streamed synthesis, unless the
provider implements `stream()`. Route 1 again.

---

## 3. Capability map — keep / replace / adapt

| Samantha today | Hermes Herald equivalent | Verdict |
|---|---|---|
| Fase 3 voice pipeline (Pipecat, Tasks 14-19) — outbound half | streaming TTS adapter seam + `StreamingTTSConsumer` | **replace** — this is the wheel we were reinventing |
| Fase 3 — inbound half (mic capture, VAD, endpointing) | utterance-level only: `MessageType.VOICE` + `cache_audio_from_bytes()`; no streaming ingress | **keep** VAD/endpointing, **replace** transcription |
| `tts.py` CosyVoice client | provider registry, no CosyVoice | **adapt** — becomes a plugin provider (route 1) |
| `stt.py` / browser Web Speech | faster-whisper, zero-key, local | **replace** — and it also kills the Google Web Speech network hop, which serves the autonomy goal |
| Task 22 (vendoring Silero VAD + onnxruntime off the CDN) | n/a — VAD stays ours | **keep**, still needed |
| Tasks 20 / 24 (TTS watchdog, cancellable turns) | `abort_streaming_tts` + `aborted` flag | **re-check** — partly obviated, do not dispatch as written |
| Wake word | on-device, CLI/TUI/desktop **only**, explicitly "does not run in the messaging gateway" | **not available** to a custom adapter |
| `personality.py` system prompt | `~/.hermes/SOUL.md`, injected as prompt slot #1 | **adapt** — clean fit, already validated in the v0.13 spike |
| `real_llm.py` OpenAI-compatible client | Hermes gateway on :8642, OpenAI-compatible + SSE | **replace** |
| Memory: ChromaDB + SQLite ring + facts, multilingual embedder | Hermes memory system + context files | **open question** — see §4 |
| Frontend: OS1 UI, wave, onboarding, Spanish voice | nothing | **keep** — this is the product |

---

## 4b. Samantha as a Hermes *extension* — the plugin surface

Reviewed after the first pass, on the user's prompt. It is the strongest
version of the adoption and it changes the shape of the recommendation:
Samantha is not a client that talks to a Hermes gateway, she is a set of
plugins that Hermes loads.

Plugins are discovered from four places — bundled `<repo>/plugins/`,
user `~/.hermes/plugins/`, project `.hermes/plugins/` (gated behind
`HERMES_ENABLE_PROJECT_PLUGINS=true`), and pip `hermes_agent.plugins`
entry points. Each carries a `plugin.yaml` manifest.

Kinds that matter to us:

- **`kind: platform`** — this is the piece I missed in the first pass.
  An adapter ships as a plugin directory with `plugin.yaml` and an
  `adapter.py` exposing `register(ctx)`, which calls
  `ctx.register_platform()`. That one call "handles adapter creation,
  config parsing, user authorization, env auto-enable, cron delivery,
  and CLI UI integration automatically". So the kiosk adapter needs no
  fork of Hermes and no core patch.
- **Memory providers** — a first-class plugin kind, single-select, that
  *replaces* built-in memory. This is the clean answer to the risk in
  §4: ChromaDB + the SQLite ring + the fact chunks + the multilingual
  embedder survive intact as a memory provider, and "Samantha never
  forgets" stops being a migration problem.
- **Context engines** — single-select, replaces the built-in
  compressor. Relevant later if Hermes's compaction fights our recall.
- **Model providers** — multi-register. Only interesting if we ever
  want the 4090's llama-server registered natively.
- **General plugins** — `ctx.register_tool()`, `register_hook()`,
  `register_command()`, `register_cli_command()`, `register_skill()`.

The hook catalogue is the other pleasant surprise: 26 lifecycle events
in `hermes_cli.plugins.VALID_HOOKS`, including `pre_llm_call`,
`post_llm_call`, `transform_llm_output`, `pre_gateway_dispatch` and —
notably — **`pre_transcription`**. A transcription hook existing at all
is evidence that inbound audio does flow through the core somewhere,
which is the best lead we have against the §1 finding. It does not
prove a custom adapter can feed it.

So the extension shape is roughly:

| Samantha piece | Delivered as |
|---|---|
| kiosk WebSocket transport | `kind: platform` plugin + the streaming-TTS seam |
| memory (Chroma + ring + facts) | memory provider plugin |
| CosyVoice voice | TTS plugin provider overriding `stream()` |
| personality | `~/.hermes/SOUL.md` + `transform_llm_output` hook |
| spoken-text shaping (the CosyVoice expression markers, isolated-fragment merge guard) | `pre_transcription` / output hooks |
| OS1 frontend | stays ours, unchanged |

**The cost of this shape, stated plainly:** it binds Samantha's identity
to a plugin API with **no backward-compatibility guarantee**. The docs
carry `manifest_version` and `api_version` fields but no stability
statement; the hook catalogue is described as "the 26 lifecycle events
*currently* accepted"; plugin middleware is called out as "a separate
registry/surface" that is still moving. Against a project shipping
weekly (five releases in the sixteen days after v0.20.0), that is a
standing maintenance tax, and it lands on the pieces that *are*
Samantha rather than on plumbing we would happily let churn.

**The argument in favour, which is the decisive one (user, 2026-08-21):
Hermes updates transparently.** Staying out of the core is what buys
this. Every upstream release — new voice work, new providers, latency
wins like the streaming-TTS seam (source comment cites `#60671`; this
document originally cited PR #73862 from a web search — corrected
2026-08-22 against `docs/superpowers/specs/hermes-contracts-v0.20.5.md`)
— arrives by upgrading a dependency, not by re-merging a fork. Against a
project shipping weekly, the compounding
difference between "plugin" and "fork" is not close, and it is the
whole reason to prefer the extension shape over vendoring pieces of
Hermes into our backend.

The letter of it: transparent updates hold exactly as far as the
surfaces we bind to are stable, and stability here is a function of how
many other plugins share the surface, not of a promise in the docs.
Tools, hooks and `SOUL.md` are crowded surfaces — if they break, they
break loudly for everyone and get fixed upstream. A WebSocket kiosk
platform adapter carrying streaming PCM is a population of one; if the
seam shifts, it shifts under us alone and we find out at runtime.

So the mitigation is not "avoid plugins", it is: bind shallowly where
we can, pin `api_version` and a known-good Hermes version rather than
tracking `main`, upgrade deliberately, and keep one end-to-end smoke
test that actually speaks and listens. Note we have no CI to run that
in — Task 32 was declined — so it is a manual gate on upgrade day.

### 4b.1 The `MemoryProvider` contract (read 2026-08-21)

This is the one that decides whether Samantha's memory survives, and it
maps onto what we already have almost line for line. Subclass
`MemoryProvider` from `agent.memory_provider`:

- `name` (property), `is_available()` — "Check if this provider can
  activate. NO network calls."
- `initialize(session_id, **kwargs)` — once at agent startup.
- `prefetch(query)` — **before each API call**, returns recalled
  context. This is `gather_context()`: facts + semantic recall + the
  short-term ring.
- `sync_turn(user, assistant, *, session_id="", messages=None)` —
  **after each completed turn**, persists. Receives user/assistant
  messages plus tool calls and results. Documented as MUST be
  non-blocking, which suits us: our Chroma writes already go off the
  event loop.
- `get_tool_schemas()` / `handle_tool_call(...)` — memory may expose
  tools to the agent.
- `get_config_schema()` / `save_config(values, hermes_home)`.

Two consequences worth stating. First, **the provider owns persistence
outright** — there is no forget/expiry the core imposes, so "Samantha
never forgets" is ours to keep by simply not implementing forgetting.
Second, the split is exactly our current one, so the port is a wrapper
over `Memory`, not a redesign.

Memory plugins are `kind: exclusive` (single active). The documented
`kind` values seen so far are `standalone`, `backend`, `platform` and
`exclusive`; the docs never enumerate them in one place.

### 4b.2 Bundled plugins — what already exists

The built-in set is mostly unrelated to us (`disk-cleanup`,
`security-guidance`, `observability/langfuse`, `spotify`,
`image_gen/*`, `kanban/dashboard`, `hermes-achievements`,
`teams_pipeline`). One matters enormously:

> **`google_meet`** — "Join Meet calls, live-caption transcription,
> optional realtime duplex audio"

That looked like the strongest evidence yet against the §1 finding — a
bundled plugin getting audio *in* on a non-CLI surface. **Checked, and
it is not.** `plugins/google_meet/` (`meet_bot.py`, `audio_bridge.py`,
`realtime/openai_client.py`, a `node/` client-server pair) gets its
duplex audio by **bypassing the gateway adapter contract entirely**:

- Inbound is OS-level plumbing, not a Hermes API — a PulseAudio
  null-sink on Linux, BlackHole on macOS, with Chrome pointed at the
  fake mic. The documented path is
  `OpenAI Realtime WS → speaker.pcm → paplay → null-sink ← Chrome fake mic`.
- The audio goes to **OpenAI's Realtime API over its own WebSocket**,
  not through Hermes STT. For us that is the autonomy goal inverted:
  raw voice to a cloud vendor, the exact leak we are closing.
- The `node/` split exists to run all of this on a separate machine
  from the gateway, which underlines that it is a side-channel rather
  than a platform capability.

So it is a workaround, not a pattern to copy, and **§1 stands**: there
is no supported route for inbound audio through a custom adapter. The
microphone stays ours. That is not fatal — it is the boundary in §5 —
but the hoped-for shortcut is closed.

### 4b.3 Confirmed from `hermes_cli/plugins.py` (2026-08-21)

The manifest shape, previously second-hand, checks out and is richer
than the docs show:

- **Metadata:** `name`, `version`, `description`, `author`, `license`,
  `homepage`, `tags`.
- **Dependencies:** `requires_env`, `requires_plugins`,
  `python_dependencies`, `external_dependencies`.
- **Capabilities:** `provides_tools`, `provides_hooks`, `capabilities`
  (declared-consent metadata — note `tools.override` and
  `llm.model_override` are gated behind it).
- **Manifest v2:** `manifest_version` (file format), `api_version`
  (runtime API), `config_schema`, `emits`, `listens`.

`kind` values: `standalone`, `backend`, `exclusive`, `platform`,
`model-provider`.

`PluginContext` registration methods seen: `register_tool` (gated by
the `override` capability), `register_hook`, `register_command`,
`register_cli_command`, `register_context_engine`,
**`register_memory_provider`**, `register_image_gen_provider`,
`register_dashboard_auth_provider`, `register_approval_transport`,
`register_context_reference`.

**`register_platform()` confirmed** (the earlier listing was partial).
`plugins/platforms/` holds 22 worked examples — a2a, buzz, dingtalk,
discord, email, feishu, google_chat, homeassistant, irc, line, matrix,
mattermost, ntfy, photon, raft, simplex, slack, sms, teams, telegram,
wecom, whatsapp. `irc` is the smallest (stdlib asyncio only) and is the
template to copy. Its `__init__.py` is just
`from .adapter import register`, and `adapter.py` ends with:

```python
def register(ctx):
    ctx.register_platform(
        name="irc",
        label="IRC",
        adapter_factory=lambda cfg: IRCAdapter(cfg),
        check_fn=check_requirements,
        validate_config=validate_config,
        is_connected=is_connected,
        required_env=["IRC_SERVER", "IRC_CHANNEL", "IRC_NICKNAME"],
        install_hint="No extra packages needed (stdlib only)",
        setup_fn=interactive_setup,
        env_enablement_fn=_env_enablement,
        cron_deliver_env_var="IRC_HOME_CHANNEL",
        standalone_sender_fn=_standalone_send,
        allowed_users_env="IRC_ALLOWED_USERS",
        allow_all_env="IRC_ALLOW_ALL_USERS",
        max_message_length=450,
        emoji="💬",
        pii_safe=False,
        allow_update_command=True,
        platform_hint="You are chatting via IRC. IRC does not support markdown formatting — use plain text only.",
    )
```

Two things there we want. `platform_hint` is a per-platform string fed
into the prompt — for the kiosk it becomes "you are being spoken aloud",
which is exactly the instruction our replies need and currently carry
in `personality.py`. And `max_message_length` gives us a natural place
to keep replies short enough to speak.

The real `plugin.yaml` for a platform (from `irc`) is:
`name`, `label`, `kind: platform`, `version`, `description`, `author`,
`requires_env` and `optional_env` (each entry with `name`,
`description`, `prompt`, `password`). Note it carries **no**
`manifest_version` or `api_version` — those are optional v2 additions,
not required.

Reference implementations for memory live in `plugins/memory/`:
byterover, hindsight, holographic, honcho, mem0, openviking, retaindb,
supermemory. `mem0` is the one we already evaluated and rejected in
2026-05, so it is the most legible starting point for us.

The hook catalogue is also larger than the plugins page said — 60+, not
26. Ones we would actually use: `on_stream_start` / `on_stream_delta` /
`on_stream_end` (drive the wave and the token stream to the UI),
`transform_llm_output` (personality and spoken-text shaping),
`pre_transcription`, `pre_gateway_dispatch`, `gateway_platform_event`,
and `on_session_start` / `on_session_end`.

**Still not verified:** no page or file consulted carries any
API-stability, deprecation or version-compatibility statement. The
absence is consistent across the plugins page, the adapter guide, the
memory-provider guide and the manifest fields themselves — `api_version`
exists as a field, but nothing says what changing it obliges anyone to
do. Treat pinning as mandatory, not cautious.

## 4. What Hermes does not solve, and what it puts at risk

**Does not cover at all:** the OS1 interface — the terracotta screen,
the line, the first encounter, the six questions, the Spanish register.
That is Samantha. Hermes replaces plumbing under it, never it.

**Puts at risk:**

- **The voice.** Covered in §2. Route 1 or we do not sound like her.
- **"Samantha never forgets."** Largely defused by §4b.1: as a
  `MemoryProvider` we keep our own store, our own embedder and our own
  write policy, and nothing in the contract forces expiry. The residual
  risk is narrower — that Hermes's context engine compacts history in a
  way that fights our recall, which is what the context-engine plugin
  kind exists to override. The 279 real chunks stay where they are.
- **CLAUDE.md §1**, which says Samantha is explicitly *not* "an agentic
  tool-using system". Mounting her on an agent runtime whose whole
  point is tools and skills contradicts that. It may well be the right
  call now, but it is a spec change and needs a decision-log entry, not
  a silent drift.
- **CLAUDE.md §1's appliance promise** ("the device IS Samantha") was
  already conceded on 2026-08-07 when everything moved to the 4090.
  Same entry can cover both.
- **Thread-safety and packaging.** The May spike found the library is
  not thread-safe with no published wheel. Not re-verified today; if we
  run Hermes as a daemon on :8642 (as before) it does not bite.

**One unresolved defect of ours survives either path:** the stored fact
says `name='Hore'`, recall says "Ore", and nothing reconciles them. No
Hermes feature fixes that; it is our data model.

---

## 4c. Interruption: how Hermes does it, and what it does NOT do

Investigated because the design needs to know what happens to a reply
the user cut off. Reference point: OpenAI's Realtime API, where the mic
stays open, a server-side VAD (optionally `semantic_vad`, a classifier
scoring *the probability the user is done* from the words spoken, with
an `eagerness` knob) fires `input_audio_buffer.speech_started`, the
in-flight response is cancelled, and the client sends
`conversation.item.truncate` so **the unplayed tail is removed from the
conversation**. That last step is the one that matters: without it the
model believes it said words the user never heard.

**Hermes has the first two and not the third.**

PR #74223 (`fix(voice): full-duplex turn listener`) adds
`full_duplex_listen()` to `tools/voice_mode.py` — importable, not
CLI-bound — with `_voice_full_duplex_listener` in `cli.py` and
`_arm_full_duplex_listener` in `tui_gateway/server.py`. It corrects an
earlier note in this document: **Hermes' voice loop is no longer
half-duplex.** One listener instance spans the whole turn, generation
*and* playback, explicitly to remove "the silent gap during LLM
generation" and avoid a re-arm race at the transition.

How it survives its own speakers, and this is the interesting part:
**not with echo cancellation.** Phase-aware RMS thresholds instead —
`voice.barge_in_threshold_multiplier` (default 3.0) and
`voice.barge_in_grace_seconds` (default 0.5), and during playback the
trigger is clamped to a 1500-RMS floor "so speaker bleed alone cannot
trip detection", while genuine speech at 3000–8000 RMS still gets
through. A pre-roll keeps the first syllable of the interjection.

Interrupting during **generation** goes through `agent.interrupt()` —
the same seam as a typed Ctrl+C — and kills the pending TTS so the
stale reply never plays. Interrupting during **playback** stops the
streaming pipeline, the fallback speak stop events and the file player,
then submits the capture as the next turn.

**What is missing:** nothing trims the assistant message to what was
actually spoken. The release notes describe the softer mechanism — "the
next message carries a short note telling the model its spoken reply was
cut off". So after an interruption at word 5 of 60, the history holds 60
words she never said, plus a note that she was cut off.

For Samantha that is worse than for a generic agent, because **our
memory is append-only by user directive**: those 55 unspoken words are
persisted forever and will surface in later semantic recall as things
she said. This is the same failure shape as the unresolved `name='Hore'`
vs recalled "Ore" divergence — a stored record that never matched what
actually passed between them. Left alone, frequent barge-in would seed
that divergence continuously.

**Design consequence:** we should track spoken-so-far on our side (the
`StreamingTTSHandle` already carries `audible`/`aborted`, and our TTS
provider knows how many PCM chunks it yielded) and trim the assistant
text before it reaches our `MemoryProvider.sync_turn()`. Hermes' own
history can keep whatever it keeps; *our* store, the one that feeds
recall, records only what was heard. This is a small, well-bounded piece
of work and it belongs in the design, not in a later sweep.

## 4d. Ruling 2026-08-22 — audio stays in the browser

The user chose the browser path over Hermes' native `full_duplex_listen()`.
Recorded so it is not re-litigated.

What it keeps: the Silero VAD instance already tuned against this room's
speakers (positive 0.85, 300 ms sustained, 600 ms warm-up), and
`getUserMedia`'s echo cancellation — a different and stronger mechanism
than Hermes' RMS floor, and one we have already proven here.

What it costs: nothing on interruption coverage, as long as the VAD is
armed for **the whole turn** rather than only during playback, which is
a small change to `useBargeIn`. Speech detected while she is still
generating sends the same interrupt frame; the adapter routes it to
`agent.interrupt()`. The generation-phase gap that motivated PR #74223
does not apply to us.

What stays in scope as a result: Task 22 (vendor the Silero + ONNX
assets — a 24/7 appliance must not fetch its VAD from a CDN), and
`useBargeIn.ts` itself, which gains `onSpeechEnd` as the endpointer.
Wake word remains unavailable; revisit only if it is ever asked for.

## 5. Recommendation

**Adopt Hermes as a set of plugins, boundary at the microphone.**
Extension, not fork, and not a client-of-a-gateway either — the plugin
route is what makes upstream upgrades a dependency bump instead of a
re-merge (§4b).

- Hermes owns: the LLM turn, the reply stream, outbound audio through a
  `kind: platform` plugin implementing the streaming TTS seam, and
  transcription via local faster-whisper — fed by us as complete
  utterances (`MessageType.VOICE` + `cache_audio_from_bytes()`).
- We own, but ship *as plugins*: the kiosk WebSocket adapter, memory
  (Chroma + ring + facts, via `register_memory_provider`), and the
  CosyVoice voice (TTS provider overriding `stream()`).
- We own outright: microphone capture, **VAD and endpointing** — the
  utterance-level inbound API forces this on us — and the entire OS1
  frontend.
- Pin a known-good Hermes version and `api_version`; do not track
  `main`. Upgrading is a deliberate act gated on a manual voice smoke
  test, because there is no CI (Task 32 declined).

**Do not dispatch Fase 3 (Tasks 14-19) as written.** Its outbound half
is now dead work. Re-scope, do not resume.

**All four blocking unknowns are now closed against source** —
`MessageType` audio members, the real `plugin.yaml` shape,
`ctx.register_platform()`, and the `StreamingTTSProvider` contract.
Nothing else needs reading before the design.

The design should open on the three pieces that carry real work, in
this order: the kiosk platform adapter (copy `irc`, add the five
streaming-TTS methods), the CosyVoice `StreamingTTSProvider` (the only
way to have a local *and* streaming voice), and the `MemoryProvider`
wrapper over our existing `Memory` (copy `mem0` for shape). Both change the shape of the design, and neither is
answerable from the documentation.

---

## Sources

Primary, read directly:

- Releases index and v0.20.0 notes —
  https://github.com/NousResearch/hermes-agent/releases
- PR #73862, streaming TTS adapter seam —
  https://github.com/NousResearch/hermes-agent/pull/73862 —
  **correction, 2026-08-22:** this number came from a web search and
  does not match the source. The comment directly above the methods in
  `gateway/platforms/base.py` cites `(#60671)`; see
  `docs/superpowers/specs/hermes-contracts-v0.20.5.md`. Left here,
  struck through in effect rather than deleted, so the record of what
  was cited and why shows the correction rather than silently
  disappearing.
- `website/docs/user-guide/features/tts.md`
- `website/docs/user-guide/features/voice-mode.md`
- Adding a Platform Adapter (developer guide)
- Wake Word (user guide)

Deliberately **not** used: the aggregator write-ups of the Herald
release (digg, gradually.ai, releasebot, the-agent-report, Medium).
They report ~3,650 commits and 650+ contributors in the two weeks
between v0.19.0 and v0.20.0, which is not credible; the ledger had
already flagged this outlet's numbers as implausible on 2026-08-07.
