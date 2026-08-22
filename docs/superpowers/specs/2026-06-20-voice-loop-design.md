# Phase 11 — Server-side Voice Loop (Pipecat)

**Date:** 2026-06-20  
**Status:** Approved — ready for implementation plan

---

## 1. Problem

The current voice interaction is choreographed entirely in the browser:
`react-speech-recognition` handles STT (via Web Speech API), `useBargeIn`
runs a WASM VAD to detect interruptions, and `tts.ts speak()` drives TTS
playback via HTTP `/speak`. This produces a class of bugs that can't be
fully fixed at the browser level (Tasks 2/3/4 of the 2026-06-11 sweep):
mic restart races, echo loops, barge-in losing the first words. Moving the
loop server-side eliminates this entire class.

---

## 2. Decisions (locked)

| Decision | Choice | Rationale |
|---|---|---|
| STT | faster-whisper in-process | Already in `pyproject.toml [real]`; STT and TTS don't overlap (sequential), so no VRAM conflict |
| Audio uplink format | 48 kHz int16 PCM mono | Browser's native `AudioContext` rate; no frontend downsampling needed; backend resamples 48k→16k |
| Concurrency | Single-client `/voice` | Kiosk is single-user; new connection displaces previous one |
| Pipeline framework | `pipecat-ai` | Provides VAD, STT, LLM, TTS service abstractions + `FastAPIWebsocketTransport` |
| TTS backend | CosyVoice 3 only | XTTS and Piper removed (2026-06-20 refactor) |
| Integration point | `/voice` inside existing FastAPI process | Shares `Memory` singleton; no extra port/service |

---

## 3. Architecture

```
Browser                              FastAPI :7777
──────                               ─────────────
AudioWorklet (mic 48kHz PCM)      →  /voice  (WebSocket binary)
                                          │
                                   Pipecat Pipeline
                              ┌─────────────────────────────┐
                              │ FastAPIWebsocketTransport    │
                              │   ↓ AudioRawFrame 48kHz      │
                              │ Resample48kTo16kProcessor    │
                              │   ↓ AudioRawFrame 16kHz      │
                              │ SileroVADAnalyzer            │
                              │   ↓ AudioRawFrame (on speech)│
                              │ WhisperSTTService            │
                              │   ↓ TranscriptionFrame       │
                              │ SamanthaLLMService           │
                              │   ↓ TextFrame (per token)    │
                              │ CosyVoiceTTSService          │
                              │   ↓ AudioRawFrame 24kHz      │
                              │ FastAPIWebsocketTransport    │
                              └─────────────────────────────┘
                                          │
                              ← bytes (PCM 24kHz) + JSON frames
```

The WebSocket carries two frame types on the same connection:
- **`ArrayBuffer`** — raw PCM audio (uplink: 48 kHz int16; downlink: 24 kHz int16)
- **JSON string** — control frames (transcript, token, error, barge_in)

Browser distinguishes by `event.data instanceof ArrayBuffer`.

---

## 4. Components

### 4.1 `backend/samantha/voice_pipeline.py` (new)

**`Resample48kTo16kProcessor`** — `FrameProcessor` subclass.
Receives `AudioRawFrame` at 48 kHz, resamples to 16 kHz using numpy
`np.interp` (same linear interpolation used previously in `_piper_to_pcm`),
emits `AudioRawFrame` at 16 kHz.

**`SamanthaLLMService`** — `LLMService` subclass.
On `TranscriptionFrame`:
1. Sends `{"type":"transcript","text":"..."}` JSON to browser.
2. Calls `_gather_context(mem, text, user_id)` via `asyncio.to_thread`
   (facts + semantic recall + short-term ring; same function as `/chat`).
3. Calls `real_llm.stream_reply(...)`, emitting one `TextFrame` per token
   and `{"type":"token","text":"..."}` JSON to browser.
4. On `LLMResponseEndFrame`: persists the full reply in memory.

**`CosyVoiceTTSService`** — `TTSService` subclass.
Receives accumulated `TextFrame`, calls `tts.stream(text)` (existing
CosyVoice 3 async generator), emits one `AudioRawFrame` per PCM chunk.
Checks `tts.is_available()` at construction; if False, sends
`{"type":"error","code":"tts_unavailable"}` and short-circuits.

**`build_pipeline(websocket, mem, user_id)`** — assembles the pipeline:
```python
transport = FastAPIWebsocketTransport(websocket, ...)
pipeline = Pipeline([
    transport.input(),
    Resample48kTo16kProcessor(),
    SileroVADAnalyzer(),
    WhisperSTTService(model="large-v3-turbo", language="es"),
    SamanthaLLMService(mem=mem, user_id=user_id),
    CosyVoiceTTSService(),
    transport.output(),
])
return PipelineTask(pipeline)
```

### 4.2 `backend/samantha/api.py` — new endpoint

```python
_active_voice_task: PipelineTask | None = None

@app.websocket("/voice")
async def voice_endpoint(websocket: WebSocket):
    global _active_voice_task
    if _active_voice_task is not None:
        await _active_voice_task.cancel()   # displace previous client
    await websocket.accept()
    mem = await asyncio.to_thread(get_memory)
    task = build_pipeline(websocket, mem, user_id="primary")
    _active_voice_task = task
    try:
        await task.run()
    except WebSocketDisconnect:
        pass
    finally:
        _active_voice_task = None
```

### 4.3 Frontend — `useVoiceSocket.ts` (new hook)

Replaces `useSpeechRecognition` + `useBargeIn` + `tts.ts speak()`:

- Opens `/voice` WebSocket on mount.
- Starts `AudioWorklet` (or `ScriptProcessor` fallback) capturing mic at
  native 48 kHz, serializes to int16, sends as `ArrayBuffer` chunks.
- On `ArrayBuffer` from server: enqueues PCM chunks into an `AudioContext`
  playback buffer (continuous, gapless). Feeds the same analyser node
  that `Wave.tsx` reads so the wave animates during Samantha's speech.
- On JSON from server: dispatches to Zustand store
  (`transcript` → user bubble, `token` → Samantha bubble streaming,
  `error` → `micErrorMessage`).
- Barge-in: if user clicks mic while `isSpeaking`, sends
  `{"type":"barge_in"}` and restarts capture.
- On unmount: closes WebSocket; browser AudioContext suspended.

### 4.4 `ConversationScreen.tsx` — swap

Replace the 5 imports/hooks at the top:
```ts
// OUT
import SpeechRecognition, { useSpeechRecognition } from "react-speech-recognition";
import { useBargeIn } from "../core/useBargeIn";
import { speak } from "../net/tts";

// IN
import { useVoiceSocket } from "../net/useVoiceSocket";
```

The visual structure (button, history panel, wave, captions) is unchanged.
`sendMessage` for text-input path still uses `/ws` chat WebSocket.

---

## 5. Data Flow (one full turn)

```
1. User presses mic
   → AudioWorklet starts, sends 48kHz int16 PCM chunks as ArrayBuffer

2. FastAPIWebsocketTransport receives bytes
   → Resample48kTo16kProcessor: 48k → 16k

3. SileroVADAnalyzer accumulates 16kHz frames
   → on speech-end (≈500ms silence): emits AudioRawFrame

4. WhisperSTTService transcribes
   → emits TranscriptionFrame{"text": "hola"}
   → server sends {"type":"transcript","text":"hola"} JSON

5. SamanthaLLMService
   → _gather_context (facts + recall + short_term)
   → stream_reply token by token
   → per token: sends {"type":"token","text":"..."} JSON
   → on end: persists in memory

6. CosyVoiceTTSService
   → tts.stream(full_reply)
   → per PCM chunk: emits AudioRawFrame 24kHz
   → FastAPIWebsocketTransport sends as ArrayBuffer

7. Browser useVoiceSocket
   → ArrayBuffer chunks → AudioContext playback buffer (gapless)
   → Wave.tsx reads analyser from same AudioContext

8. Barge-in (user presses mic mid-TTS)
   → browser sends {"type":"barge_in"}
   → CosyVoiceTTSService aborts via asyncio.Event
   → pipeline returns to step 1
```

---

## 6. Error Handling

| Failure | Server action | Browser effect |
|---|---|---|
| Whisper STT error | Send `{"type":"error","code":"stt_error"}`, continue listening | micErrorMessage in UI |
| CosyVoice unavailable | Send `{"type":"error","code":"tts_unavailable"}`, LLM reply shown as text only | Error copy in Samantha's bubble |
| LLM error | `stream_reply` catches, emits Samantha-voiced error as TextFrame → TTS | Normal error bubble with Spanish copy |
| Client disconnects | `WebSocketDisconnect` cancels PipelineTask, clears `_active_voice_task` | — |
| Barge-in | `asyncio.Event` signals CosyVoiceTTSService to stop mid-stream | TTS stops, mic reopens |

---

## 7. What Changes

### Added
- `backend/samantha/voice_pipeline.py`
- `backend/samantha/api.py` — `/voice` endpoint + single-client guard
- `frontend/src/net/useVoiceSocket.ts`
- `pyproject.toml` — `pipecat-ai[silero]`, `faster-whisper` to main deps

### Removed
- `frontend/src/core/useBargeIn.ts`
- `frontend/src/net/tts.ts`
- `frontend/package.json` — `react-speech-recognition`, `@ricky0123/vad-web`
- `backend/samantha/api.py` — `_ws_handle_listen`, `/transcribe` endpoint

### Modified
- `frontend/src/net/audio-analyser.ts` — rewired to read from the `/voice`
  downlink AudioContext instead of the speak() AudioContext

### Unchanged
- `/chat` HTTP + `/ws` text WebSocket (fallback + tests)
- `/speak` HTTP TTS (fallback + tests)
- `real_llm.py`, `memory.py`, `personality.py`
- `ConversationScreen.tsx` visual structure
- `Wave.tsx` (reads from audio-analyser, unaffected)

---

## 8. Testing

**`backend/tests/test_voice_pipeline.py`** (new):
- `test_transcript_triggers_llm_and_tts` — mock Whisper + CosyVoice; assert
  full pipeline produces AudioRawFrames after a TranscriptionFrame.
- `test_barge_in_aborts_tts` — send barge_in event mid-TTS; assert
  CosyVoiceTTSService stops and pipeline returns to listening state.
- `test_single_client_displaces_previous` — second `/voice` connection
  cancels first PipelineTask.

**`backend/tests/test_api.py`** (additions):
- `test_voice_ws_accepts_pcm_and_returns_transcript` — send silent PCM
  bytes to `/voice`, mock STT to return "hola", assert JSON transcript frame.

**Frontend** — manual smoke (no test framework per CLAUDE.md §6):
- Mic → transcript bubble appears → Samantha replies → audio plays
- Barge-in stops audio and reopens mic
- Page reload reconnects cleanly
