# Hermes Authority Migration

Date: 2026-09-08. Status: approved direction; M2/M3 complete and M4 partial.

## Decision

Hermes is the authority for client admission, turn lifecycle, cancellation,
session/profile selection, and outbound delivery. The GTK widget and iOS client
are peripherals: they capture or render media and submit events to Hermes. They
do not decide a turn's destination or terminal state.

This supersedes the implementation split, not the product contract. The local
voice v1 contract remains the public wire baseline and its security guarantees
become Hermes-owned.

## Why

Today a desktop turn spans two independent state machines:

- The widget owns phone authentication, endpoint claims, reply routing, direct
  TTS, playback completion, and a local request ID.
- Hermes owns the agent task, durable transcript, tools, and a second request
  lifecycle keyed by an adapter WebSocket.

The resulting Hermes -> widget -> phone relay makes a dropped or uncorrelated
frame able to affect another system's active turn. It also treats `chat_id` as
both routing and identity despite all conversations using the same privileged
Hermes profile.

Hermes already supplies the safer harness: authenticated platform adapters,
durable sessions, task cancellation, delivery bookkeeping, profile routing,
tool policy, and a streaming consumer. Turn authority must use those facilities
instead of replicating them in the widget.

## Target Boundary

Hermes owns an immutable internal turn record at admission:

```
turn_id, client_id, connection_generation, persona, profile_id,
session_id, input_source, delivery_targets, cancellation_state
```

- `turn_id` is allocated by Hermes and is mandatory on every turn-scoped event.
- `client_id` and `connection_generation` identify a specific desktop or phone
  connection. A reconnected person is never a destination for an old turn.
- `persona` selects an explicitly authorized Hermes profile and tool policy;
  it is not a sufficient authorization mechanism by itself.
- `delivery_targets` are immutable. A missing private target discards output;
  it never falls back to the room or another device.
- Hermes emits the one terminal event after all events it owns have been
  accepted by the ordered client writer. A client may keep playing buffered
  audio after that terminal.

The widget retains desktop microphone capture, VAD, local Whisper, GTK drawing,
speaker playback, and optionally a local TTS worker during transition. iOS
retains native capture/playback. Neither retains agent-session or destination
state.

## Migration Phases

### M0: Restore The Legacy Baseline

Do not migrate on a failing turn path. Remove the experimental delivery change
or repair it with a green regression suite, then prove one desktop text/voice
turn reaches the current widget. Capture a short latency trace as the baseline.

### M1: Hermes Turn Broker

Add a generic broker within the JARVIS Hermes platform surface. Desktop and
mobile transports submit `turn.submit` and `turn.cancel`; the broker creates the
immutable record and serializes all resulting events through a per-client writer.
Keep the existing widget WebSocket as a compatibility transport, but stop it
from owning request routing or terminal state.

Acceptance: a dropped desktop socket, a phone reconnect, a cancel, and a late
agent callback cannot change another turn's delivery or execution state.

### M2: Hermes-Owned Mobile Admission

Move the LAN TLS listener, bearer verification, pairing-derived client identity,
connection registry, and private delivery from `widget/remote.py` to Hermes.
Reuse the existing certificate and roster format initially. The phone connects
directly to Hermes; the widget is no longer a phone relay.

Acceptance: a private phone disconnect suppresses only that phone's output,
without affecting the desktop or another phone.

### M3: Profile And Capability Policy

Before treating a persona as a separate session, configure and test Hermes-side
profile/tool policy. The current default profile includes `terminal` and must not
be implicitly shared merely because a different `chat_id` was supplied. Resolve
effective local model, STT, TTS, memory retention, and allowed tools at handshake
and fail closed if the policy cannot be honored.

Acceptance: synthetic personas cannot access another persona's memory or an
unapproved capability, and a provider/policy change invalidates a new turn.

### M4: Ordered Media Delivery

Make the local-voice v1 `/voice/local` contract a Hermes endpoint. Hermes
serializes text, cards, images, PCM, cancellation, and terminal events per
client. Select one of two implementations after measuring M1/M2:

- Hermes owns CosyVoice streaming and sends addressed PCM directly.
- Hermes brokers an addressed local TTS worker; the worker never decides a
  destination or terminal.

The first option is the intended end state. The second is a temporary migration
step if resident GPU placement requires it.

**Partial implementation, 2026-09-08:** `/voice/local` is an opt-in TLS route
with M2 authentication before upgrade. Its dedicated v1 module validates strict
JSON and PCM, encodes turn-prefixed PCM, and owns a bounded ordered writer with
terminal reservation. No Hermes-local STT/VAD worker is installed, so readiness
fails explicitly with `provider_unavailable`; it does not relay PCM to the widget
or a cloud provider. Direct Hermes text-to-addressed-PCM delivery remains pending
the local STT admission path and a safe CosyVoice integration test.

**Desktop transition, 2026-09-08:** An upgraded desktop opts into
`pcm_s16le/24000` on `turn.submit`. For that turn the adapter freezes the
desktop target, emits `pcm.start`, text, ordered `JPCM` binary frames addressed
with the Hermes turn id, then its terminal. It streams only
`jarvis_voice.tts` (local CosyVoice); unavailable or failed local synthesis
ends the turn with a Spanish error and never selects Edge or another cloud
provider. The widget plays addressed PCM only after `pcm.start`; an old gateway
without that marker retains the existing widget synthesis path until both ends
are upgraded. Mobile direct output remains on its legacy path pending shared
mobile TTS delivery and local STT/VAD admission.

### M5: Peripheral Simplification

Remove widget `ReplyRoutes`, `RemoteDesk` turn claims, mobile TLS serving, and
gateway-side response ownership. Keep only capture, local device controls, and
rendering. Retire the legacy `/ws` path after desktop and iOS use the broker
contract and joint physical acceptance passes.

## Security Gates

- Authenticate before WebSocket upgrade; no token in query strings.
- Resolve persona and profile server-side; never trust a client `chat_id`.
- Bind authorization, tools, and memory to the Hermes profile, not process-wide
  environment state or UI identity.
- Keep every private target immutable and fail closed on disconnect.
- Preserve the local-only policy checks from the voice contract at readiness and
  before dispatch; no cloud fallback.
- Bound every connection writer and shared STT/LLM/TTS queue. A slow client must
  not retain GPU work or block another client indefinitely.

## Evidence Required Before Rollout

- Green legacy regression suite before M1.
- Deterministic broker tests for two phones plus the room, reconnect, cancellation,
  late callbacks, slow consumers, and tool execution ownership.
- Profile and capability isolation tests with synthetic personas.
- Joint iOS/desktop physical measurements: end-of-speech to first text, first
  audio, playback stop, queue peaks, GPU memory, p50/p95, and failures.
- Opt-in rollout and rollback: legacy transport remains available until M5.
