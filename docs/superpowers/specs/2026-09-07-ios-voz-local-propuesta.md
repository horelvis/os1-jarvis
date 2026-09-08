# Jarvis local voice: design proposal for backend review

Date: 2026-09-07. Status: **REVIEW ONLY — do not implement, restart services, or deploy.**

The user requests a design review before implementation. Another agent is already working in this repository; coordinate with that work. The exploratory iOS code was withdrawn and saved as an unapplied patch. It is not an approved implementation.

## Requirements

- Audio, speech recognition, conversational inference, and speech synthesis must remain on the user's devices. No OpenAI or other cloud STT/LLM/TTS, and no silent cloud fallback.
- Provide hands-free conversation, natural pauses, and interruption by speaking. Preserve QR pairing, authenticated identity, permissions, and Jarvis memory.
- Reuse resident local models. Do not load an additional GPU model before measuring the existing memory and latency budget.

## Inspected baseline

Read-only snapshot at revision `403d71f`: `widget/jarvis_widget/remote.py` provides WSS `/ws`, token authentication, `start/end/interrupt`, and untagged PCM/text/done output. Its reviewed handler does not accept `user_text`. Phone utterances bypass desktop VAD. Interruption does not establish full model-work cancellation.

Existing components include Silero/Vosk desktop endpointing, faster-whisper large-v3-turbo, Hermes, a configured `custom:local` model (`qwen3.8-27b`), and CosyVoice. Effective inference routing has not been tested. The RTX 4090 had 21,099 MiB occupied out of 24,564 MiB at inspection. Ports 7777, 8000, and 8093 were listening; the widget and mobile port 8443 were inactive. No services were started. These observations may have changed.

## Architecture and UI

Propose WSS first: iPhone capture and echo cancellation → per-phone session → local VAD/endpointing → Whisper → Hermes/local model → CosyVoice → tagged audio back to the phone. Reuse authentication and certificate pinning. Evaluate WebRTC later only if measurements justify changing transport.

iOS owns a single duplex audio graph with echo cancellation; validate on a physical device. A separate voice screen shows connection/listening/user-speaking/waiting/responding/muted/disconnected states, transcripts, and explicit stop-response, mute, and end controls. The avatar reflects state. Capture stays closed during connection checks. Initially, backgrounding, screen lock, audio interruption, or route changes end the session. No background listening or automatic replay after reconnection.

## Proposed contract — not implemented or approved

Separate endpoint: `wss://<paired-origin>/voice/local`. Keep legacy `/ws` working. Resolve identity from the authenticated server roster, never from client assertions.

Client handshake:

```json
{"type":"hello","protocol":"jarvis.local-voice.v1","processing":"local-only"}
```

Server response only after verifying actual local providers and readiness:

```json
{"type":"ready","protocol":"jarvis.local-voice.v1","processing":"local-only","input_rate":16000,"output_rate":24000,"format":"pcm_s16le","channels":1}
```

Close after 12 seconds without valid readiness. No microphone capture before readiness; no automatic legacy fallback. Reject unavailable models, incompatible audio formats, or cloud configuration.

- Input: mono 16 kHz PCM16 little-endian, approximately 20 ms frames. Bounded server pre-roll; proposed maximum utterance duration 30 seconds, not a session limit.
- Server assigns strictly increasing positive UInt32 `turn` IDs per socket, without reuse. A new socket has a new namespace.
- Output binary: four-byte big-endian UInt32 turn ID followed by mono 24 kHz PCM16 little-endian. Proposed maximum frame size: 48,004 bytes.
- Use one ordered output writer per connection for events and audio.

| Direction | Event | Meaning |
|---|---|---|
| Server → phone | `turn_started(turn)` | New utterance detected; invalidate prior playback. Must precede all output for this turn. |
| Server → phone | `speech_stopped(turn)` | Utterance closed; processing starts. |
| Server → phone | `transcript(turn,text)` | Final transcript, once, before response text. |
| Server → phone | `text(turn,delta)` | Append response fragment. |
| Server → phone | `turn_done(turn,status)` | `completed`, `cancelled`, or `failed`; after final audio frame. Does not imply playback has finished. |
| Server → phone | `error(code,turn?)` | Distinguish session incompatibility, busy, and turn failure; no secrets. |
| Phone → server | `cancel(turn)` | Cancel pending work where possible and suppress subsequent results. |
| Phone → server | `microphone(enabled)` | Disabling discards incomplete utterance and pre-roll; re-enabling starts clean. |

Allow a new utterance while cancelling an old response. Specify concurrency so tools cannot execute twice. Cancelling speech does not undo an already executed action; distinguish stopping playback from confirmed work cancellation. Both endpoints discard invalidated late audio/text/transcripts. Cancellation and terminal handling must be idempotent. Never replay old orders on reconnect.

## Privacy and bounded resources

The handshake declaration alone does not prove locality. Validate resolved STT/LLM/TTS destinations, disable cloud fallback, and test with Internet egress blocked. Tools that send conversation content outside the user's devices are disabled in this mode unless the user defines exceptions; preserve authorized local tools.

Prefer server Whisper transcripts. Any optional Apple recognition must require on-device processing and be nonessential. Do not retain audio or transcripts by default; audit existing debug dumps.

Keep each phone turn bound to its private destination after disconnect. **A missing phone destination must never fall back to room speakers.** Bound all queues; slow consumers must not block other sessions. Initial budgets to measure, not validated values: one second pending upload and eight seconds pending playback.

## Ownership and review request

iOS agent: voice screen, audio graph/AEC, permissions, bounded capture, tagged playback, lifecycle, protocol client, and state tests.

Backend agent: review compatibility with active work; propose per-session reuse of VAD/Whisper/Hermes/CosyVoice; validate turn ordering, cancellation, private routing, provider locality, and resource bounds.

Please respond with incompatibilities, proposed contract revisions, cancellation and private-routing guarantees, and a local validation plan. First agree on the design; implementation and deployment do not follow automatically from receiving this document.

## Acceptance criteria for a later implementation

1. No capture or audio transmission without valid local readiness.
2. Multiple hands-free Spanish utterances with natural pauses.
3. Speaking interrupts playback; initial target under 250 ms from voice detection, with detection latency measured separately.
4. Stale turn events and audio cannot affect the current turn.
5. Mute closes capture and clears pending microphone data; ending, network loss, or audio interruption closes capture and clears session queues.
6. Conversation and a local read-only tool work with Internet blocked; cloud configuration is rejected.
7. Phone disconnect cannot produce room audio or duplicate an action.
8. Measure end-of-speech → transcript → first text → first audio, p50/p95, false cutoffs, VRAM, and audio routes. Do not promise ChatGPT-equivalent performance without measurements.
