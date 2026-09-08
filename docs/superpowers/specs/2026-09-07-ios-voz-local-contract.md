# Jarvis local voice v1 - P0 contract

Date: 2026-09-07. Contract revision: 1. Wire protocol: `jarvis.local-voice.v1`.
User approved the design and P0 implementation. This is the backend contract
baseline for the iOS handoff; iOS conformance acknowledgment is not yet recorded.
The endpoint is not implemented by this document.

## Sources and deliverables

- [Coordinated plan](../plans/2026-09-07-ios-voz-local.md).
- [Original iOS proposal](2026-09-07-ios-voz-local-propuesta.md).
- [Message schema](../../../widget/tests/fixtures/local_voice_v1/messages.schema.json).
- [Ordered traces](../../../widget/tests/fixtures/local_voice_v1/traces.json).
- [Binary vectors](../../../widget/tests/fixtures/local_voice_v1/binary.json).
- [Integrity manifest](../../../widget/tests/fixtures/local_voice_v1/manifest.json).
- [Offline fixture checks](../../../widget/tests/test_local_voice_contract.py).

The schema describes individual JSON messages. This document and the traces also
define ordering and side effects. A schema-valid message can still be invalid in
the current state. Fixtures use synthetic text only. Binary vectors are exact hex
octets, decoded with `bytes.fromhex` in Python or equivalent in Swift; hex strings
are test storage, never the WebSocket payload. No audio recordings are included.

## Connection, authentication and readiness

Use `wss://<paired-host>:<paired-port>/voice/local` with the paired certificate
pin and `Authorization: Bearer <token>`. Reuse the existing roster and Origin
validation; never put tokens in query strings. Resolve persona on the server.
Reject invalid authentication before upgrade with HTTP 403. Capacity refusal
before upgrade may use HTTP 503. No `enrolled` frame is sent on this endpoint.
The old `/ws` endpoint and its messages remain separate and compatible.

The client's first application message is exactly:

```json
{"type":"hello","protocol":"jarvis.local-voice.v1","processing":"local-only"}
```

The first successful server message is:

```json
{"type":"ready","protocol":"jarvis.local-voice.v1","processing":"local-only","input_rate":16000,"output_rate":24000,"format":"pcm_s16le","channels":1}
```

Server checks effective STT/LLM/TTS providers, fallback policy, persona profile,
permissions and actual readiness before `ready`. An open port or a configured
model name alone is insufficient. Local-only tools must be verified local;
general shell/file access is not evidence of isolation. Recheck policy before
dispatch; a provider or policy change that invalidates locality ends the session.

Both sides enforce 12 seconds to valid readiness, measured by monotonic clock:
from socket-open on iOS, from upgrade on server. Pings do not extend it. On expiry,
close with 1008; server may send `error(readiness_timeout)` first. A malformed
ready is failure, not permission to capture. There is no automatic legacy/cloud
fallback. iOS microphone permission denial ends locally without capture.

The client also has a 10-second pre-open connection deadline covering DNS,
TCP/TLS and WebSocket upgrade. Both peers send WebSocket pings every 20 seconds
and require their matching pong within 10 seconds; missing pong closes/cleans up
the connection. Speech silence alone is not a session timeout. These liveness
timers do not extend the independent readiness, queue or turn deadlines.

After readiness the microphone is DISABLED on both sides. iOS sends
`{"type":"microphone","enabled":true}` before opening capture and sending PCM.
No separate acknowledgment is needed: control and subsequent PCM use one ordered
client writer. Repeated microphone values are idempotent. To mute, close capture,
clear unsent PCM, then send `enabled:false`; server discards pre-roll/incomplete
utterance and cancels that capturing turn. Muting does not cancel an answer.
Unsent PCM must never cross a mute/re-enable boundary. PCM received while disabled
or before ready is a protocol failure. In-flight PCM preceding disable on the
ordered wire is discarded with the incomplete utterance.

## Turn identity, admission and ordering

Server allocates contiguous positive UInt32 IDs starting at 1 per socket. Never
reuse or wrap: before allocating above 4294967295, end with `turn_exhausted`.
Both clients key callbacks by connection generation AND turn. The generation is
local bookkeeping, not a client-supplied identity. A new connection has new state.
Capture persona, conversation, original connection and private destination once
when admitting a turn; keep the internal Hermes request ID distinct from these.
Missing/disconnected phone output is discarded, never routed to room speakers
or another connection, including one authenticated as the same person.

The ordinary sequence is `turn_started`, `speech_stopped`, one `transcript`, zero
or more `text` and audio frames, then `turn_done`. Each JSON message uses `type`
and the exact fields in the schema. Speech detection creates `turn_started`;
`speech_stopped` closes input, not necessarily admission to a busy GPU worker.
Text/audio require a final transcript; audio also requires preceding response
text. Transcript may be empty; complete it silently with no response or audio.
Filtering/cancellation may instead close a turn before transcription. Failure
uses `error(code,turn)` followed by one `turn_done(status:failed)`.

`text.delta` appends; it may contain the entire answer in one event initially.
Token streaming from Hermes is not promised. One writer orders server JSON and
binary output. Completed follows all its audio. Cancelled/failed discard queued
output, but cannot retract frames already sent. Each admitted turn has exactly
one logical terminal; after it no text, transcript, audio or second terminal is
sent for that turn. No guarantee of terminal delivery survives connection loss.

On a newer `turn_started`, iOS immediately clears older playback and ignores its
subsequent content; an older terminal only updates bookkeeping. Already-buffered
old callbacks can still fire locally and must be ignored. Content with an unknown
future turn, or content after a terminal on the actual wire, is a protocol failure.
Local playback may continue after a completed terminal: terminal is generation
completion, not an acknowledgment that the user heard the answer.

## Interruption and action concurrency

Stop-response clears iOS playback immediately and sends `cancel(turn)`. Speaking
can clear playback locally as soon as iOS detects speech; the server detects the
replacement utterance and sends its `turn_started`, invalidating the old output.
No old action is replayed. A cancel for an active turn suppresses future output,
requests cooperative cancellation and yields a cancelled terminal. Known already
terminal IDs are a no-op, even if the terminal was completed. An unknown/future ID
is `invalid_turn`, closes with 1008, and does not allocate a new turn.

Cancelled terminals may carry `work_state:stopped|unconfirmed`. Server includes
it; clients treat omission as `unconfirmed`. `stopped` means the associated work
has settled or never started, not that an executed action was undone. `unconfirmed`
means output has stopped but underlying execution may continue. Never claim rollback.

Only one action-capable Hermes run per conversation is allowed, across sockets
and legacy/new voice paths. Hold at most one replacement turn while old work
settles. Its speech may be collected/transcribed, but do not dispatch it into
Hermes until old execution has settled. Wait at most 5 seconds after replacement
speech stops; expiry yields `busy(turn)` and failed terminal for the replacement.
An unresolved old run remains tracked and blocks new action execution until
settlement, including after disconnect/reconnect. Suppressed late callbacks do
not release another turn's ownership. If another utterance cannot be admitted,
close the session with session-level `busy` rather than silently losing speech.

## Audio and resource limits

Limits below are revision-1 implementation budgets, not measured performance.
Changing wire limits requires updating this contract and both fixture consumers.

| Item | Limit / representation |
| --- | --- |
| Client binary PCM | Mono 16 kHz signed PCM16 LE, no header; 2..3200 even bytes |
| Normal input packet | 640 bytes = 20 ms; smaller final packets allowed |
| Server binary PCM | 4-byte UInt32 BE turn, then 2..48000 even PCM bytes at mono 24 kHz |
| Server binary message total | 6..48004 bytes; no empty-audio packet |
| WebSocket text message | At most 16384 UTF-8 bytes, one JSON object |
| Transcript / delta value | At most 2048 Unicode code points each; empty delta forbidden |
| Total response text | At most 65536 UTF-8 bytes per turn |
| Input queue | 32000 pending PCM bytes per connection |
| Pre-roll | 16000 PCM bytes = 500 ms, included in utterance limit |
| Utterance | 960000 PCM bytes = 30 seconds; fail `utterance_too_long`, never truncate and execute |
| Output audio queue | 384000 PCM bytes, with at most 256 pending events total |
| Output JSON queue | 65536 serialized UTF-8 bytes; separate from PCM byte budget |
| Reserved terminal/error space | Four of the 256 event slots and 2048 JSON bytes |
| Client pending playback | 384000 PCM bytes including scheduled-but-unplayed audio |
| Sessions | Three total; one local-voice connection per authenticated persona |
| Shared compute admission | At most three waiting jobs per STT/LLM/TTS stage, one executing per stage initially |
| Admission / blocked writer timeout | 5 seconds each, independent of the readiness deadline |
| Turn processing deadline | 120 seconds from `speech_stopped`, including queue waits |

Bounds include application queues; implementations must also bound transport and
audio-engine buffering. WebSocket compression is disabled. Reject non-UTF-8 JSON,
duplicate JSON keys, nonfinite numbers, wrong field types, unknown fields/events,
odd PCM length, missing headers and turn zero. JSON integers must not be booleans.
The JSON Schema permits integer-valued JSON numbers; both clients validate numeric
value/range without coercing strings. Oversized WS messages close with 1009.

If a queue stays blocked for 5 seconds, signal `overloaded` where possible and
close 1013; no indefinite blocking of shared workers or other phones. At input
overflow fail immediately rather than drop audio silently. Terminal reservation
does not guarantee delivery to a dead socket. Physical audio, echo and endpointing
validation belong to B4/F2/J1, not to these synthetic contract fixtures.

## Errors and shutdown

`error` contains a stable code and optional turn only; no exception text or secrets.
iOS maps codes to its Spanish UI. A turn-scoped error does not close the socket
unless stated; it is followed by failed terminal. Session errors close and cancel
all open turns locally; if writer space exists, send their terminals before close.

| Codes | Scope | Close / behavior |
| --- | --- | --- |
| `protocol_mismatch`, `invalid_message`, `invalid_turn`, `audio_disabled`, `readiness_timeout` | Session | 1008 |
| `local_only_required`, `profile_unavailable`, `policy_changed` | Session | 1008; never fallback |
| `provider_unavailable` | Session | 1013; reconnect only through new handshake |
| `turn_exhausted` | Session | 1000; fresh connection required |
| `overloaded` | Session | 1013; clear buffers |
| `busy` | Session or turn | 1013 for session; failed terminal for turn |
| `utterance_too_long`, `turn_timeout`, `turn_failed` | Turn | Failed terminal |

Schema errors from the client map to `invalid_message`; wrong hello protocol or
processing values use `protocol_mismatch` / `local_only_required` respectively.
Invalid server messages make iOS close 1008 and clear local state; iOS does not
send a server-style error. UTF-8 errors may close 1007 at WebSocket level.

End, backgrounding, screen lock, audio interruption or audio route changes stop
capture/playback, clear queues and close normally (1000). Socket loss has the same
local cleanup even without a close frame. The server cancels session work and
retains unresolved action ownership until settlement. Reconnecting requires a
fresh handshake and explicit microphone enable; never replay previous orders.

Keep authorized Hermes memory under the correct profile; raw audio and extra
transcript debug dumps are off by default. Transcript display is ephemeral UI,
not consent to additional storage. Existing Hermes history retention must be
documented in B3. Until playback acknowledgment is designed, history must not
claim the complete generated answer was heard after interruption.

## Validation boundary and handoff

P0 checks schema consistency, exact binary encoding and ordered synthetic traces.
It does not implement an endpoint or prove provider locality, Hermes cancellation,
profile isolation, acoustic quality or latency. B1-B4 and F1-F2 consume these cases
against their real implementations. J1 measures the integrated system.

Any change to required fields, event meaning, binary layout or limits requires
joint fixture/spec revision before implementation diverges. Record iOS repository,
branch and fixture acceptance in the shared plan. User design approval is recorded
there separately from iOS conformance acknowledgment.
