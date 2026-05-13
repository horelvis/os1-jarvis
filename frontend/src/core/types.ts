// The four top-level screens (state machine in store.ts).
export type ScreenName = "boot" | "onboarding" | "ambient" | "conversation";

// The wave's animation state. Each maps to a different traveling-
// pulse pattern in the canvas. Threaded from store → Wave component.
export type WaveMode = "idle" | "listening" | "thinking" | "speaking";

export interface ProfileAnswer {
  q: string;
  a: string | null;
}

export interface Profile {
  name: string;
  onboarding_completed_at: number;
  answers: ProfileAnswer[];
}

export interface PingResponse {
  status: "ok";
  version: string;
  timestamp: number;
  mode: "mock" | "real";
  has_profile: boolean;
}

export type Role = "user" | "samantha";

export interface ChatMessage {
  id: string;
  role: Role;
  text: string;
  timestamp: number;
}

// WebSocket protocol mirrors backend/samantha/api.py:_ws_handler.
export type WSClientToServer =
  | { type: "chat"; message: string; user_id: string }
  | { type: "listen" };

export type WSServerToClient =
  | { type: "token"; token: string }
  | { type: "done"; thinking_ms: number }
  | { type: "transcription"; text: string }
  | { type: "error"; error: string };
