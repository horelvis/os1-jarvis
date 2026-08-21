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

> **Hermes can speak through a custom adapter. It cannot listen
> through one.**

Outbound audio has a real, documented, opt-in contract on
`BasePlatformAdapter` — five methods, PCM chunks, ordered clause
playback, ~500–800 ms perceived latency. That is precisely the seam a
kiosk needs, and it is the single strongest argument for adopting.

Inbound audio has no such contract. The documented adapter interface is
text-only (`connect` / `disconnect` / `send`, plus `MessageEvent` built
with `MessageType.TEXT`). Voice *input* is wired per-surface — CLI/TUI
push-to-talk, Discord voice channels, and named messaging platforms —
none of which the kiosk is. The streaming PR says so in as many words:
the seam "handles synthesis only".

**Consequence:** adopting Hermes deletes most of Fase 3, but not all of
it. The microphone half of the voice loop stays ours either way. What
changes is that it shrinks from "build a full duplex pipeline" to
"capture audio, get text, hand Hermes a text event".

**Recommendation: adopt, with the boundary drawn at the microphone.**
Details in §5.

---

## 1. Blocking question 1 — can a custom adapter carry audio?

**Outbound: yes.** PR #73862 ("streaming TTS — clause-by-clause
synthesis for CLI voice mode and gateway adapters") adds an opt-in seam
to `gateway/platforms/base.py`:

```
supports_streaming_tts() -> bool
begin_streaming_tts(handle: StreamingTTSHandle, format: AudioFormat)
write_streaming_tts(handle: StreamingTTSHandle, pcm_chunk: bytes)
finish_streaming_tts(handle: StreamingTTSHandle)
abort_streaming_tts(handle: StreamingTTSHandle)
```

`AudioFormat` carries sample_rate / channels / sample_width.
`StreamingTTSHandle` is opaque with `audible` / `aborted` flags — i.e.
**abort is part of the contract**, which is what barge-in needs. A
`StreamingTTSConsumer` bridges agent deltas to the adapter's audio sink
through the existing `SentenceChunker` and serialises clause playback in
order. All five methods default to no-op, so the contract is additive.

Claimed effect: perceived voice latency ~2–3.5 s → ~500–800 ms.

This maps onto Samantha's existing transport almost exactly: our kiosk
WebSocket already carries binary PCM out and JSON control text.

**Inbound: no.** The developer guide for adding a platform adapter
documents only `connect()`, `disconnect()`, `send()` as abstract, with
`send_typing()` and `get_chat_info()` optional, and inbound arriving as:

```python
event = MessageEvent(
    text=content,
    message_type=MessageType.TEXT,
    source=source,
    message_id=msg_id,
)
await self.handle_message(event)
```

No microphone, no audio ingress, no STT routing. The per-platform voice
work named in the release notes (Feishu, DingTalk, LINE, QQ, WhatsApp,
Weixin) is platform-specific inbound classification, not a generic
capability a new adapter inherits.

**Stability:** the adapter guide makes **no** stability statement either
way. Note this corrects the 2026-08-07 research note in the ledger,
which said the contract "explicitly excludes voice/audio and may change
without deprecation" — that was about the *relay connector*, and it is
now stale on both counts.

**Not verified:** whether `MessageType` has an AUDIO/VOICE member that
an adapter could populate. The guide does not list the enum. Worth 10
minutes in `gateway/platforms/base.py` before the design is finalised —
if it exists, the inbound story improves materially.

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

1. **Python plugin provider overriding `stream()`** — the docs state
   plugin providers may "override `stream()` to deliver audio bytes
   chunked for streaming delivery". This is the only route that keeps
   both our voice *and* the 500–800 ms streaming win. It is also the
   only one that requires writing real code against a plugin API.
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
| Fase 3 — inbound half (mic capture, VAD, endpointing) | none for custom adapters | **keep**, but shrink to capture → text |
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

## 4. What Hermes does not solve, and what it puts at risk

**Does not cover at all:** the OS1 interface — the terracotta screen,
the line, the first encounter, the six questions, the Spanish register.
That is Samantha. Hermes replaces plumbing under it, never it.

**Puts at risk:**

- **The voice.** Covered in §2. Route 1 or we do not sound like her.
- **"Samantha never forgets."** That is a standing user directive
  (2026-05-12) and our store is append-only by design, with a
  multilingual embedder chosen because Spanish recall was weak.
  Hermes's memory system has its own model. Migrating 279 real chunks —
  including the onboarding answers and the name correction — is a
  design problem, not a config flag. **Do not assume this migrates.**
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

## 5. Recommendation

**Adopt Hermes, with the boundary at the microphone.**

- Hermes owns: the LLM turn, the reply stream, outbound audio through a
  custom adapter implementing the streaming TTS seam, and STT via local
  faster-whisper.
- We own: microphone capture, VAD and endpointing in the kiosk, the
  WebSocket transport, the entire OS1 frontend, and — through a plugin
  provider — the CosyVoice voice.
- Memory stays ours until a separate spike says otherwise.

**Do not dispatch Fase 3 (Tasks 14-19) as written.** Its outbound half
is now dead work. Re-scope, do not resume.

**Cheapest next step, before any design is finalised:** ~30 minutes in
the actual v0.20.5 source answering the two things the docs leave open —
(a) does `MessageType` have an audio member a custom adapter can
populate, and (b) what exactly does the TTS plugin provider `stream()`
interface require. Both change the shape of the design, and neither is
answerable from the documentation.

---

## Sources

Primary, read directly:

- Releases index and v0.20.0 notes —
  https://github.com/NousResearch/hermes-agent/releases
- PR #73862, streaming TTS adapter seam —
  https://github.com/NousResearch/hermes-agent/pull/73862
- `website/docs/user-guide/features/tts.md`
- `website/docs/user-guide/features/voice-mode.md`
- Adding a Platform Adapter (developer guide)
- Wake Word (user guide)

Deliberately **not** used: the aggregator write-ups of the Herald
release (digg, gradually.ai, releasebot, the-agent-report, Medium).
They report ~3,650 commits and 650+ contributors in the two weeks
between v0.19.0 and v0.20.0, which is not credible; the ledger had
already flagged this outlet's numbers as implausible on 2026-08-07.
