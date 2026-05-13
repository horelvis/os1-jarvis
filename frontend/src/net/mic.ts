import { getWSClient } from "./wsClient";

// Per CLAUDE.md §2.8: browser never opens getUserMedia. listen() asks
// the backend to capture audio via sounddevice and returns the STT
// result. Mock mode returns a canned phrase; Phase 5 wires Whisper.
export async function listen(): Promise<string> {
  return getWSClient().listen();
}
