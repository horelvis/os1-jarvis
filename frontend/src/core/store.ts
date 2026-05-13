import { create } from "zustand";
import type { ChatMessage, ScreenName } from "./types";

interface SamanthaState {
  screen: ScreenName;
  name: string | null;
  transcript: ChatMessage[];
  setScreen: (s: ScreenName) => void;
  setName: (n: string | null) => void;
  appendMessage: (m: ChatMessage) => void;
  patchMessage: (id: string, text: string) => void;
  resetTranscript: () => void;
}

export const useSamantha = create<SamanthaState>((set) => ({
  screen: "boot",
  name: null,
  transcript: [],
  setScreen: (s) => set({ screen: s }),
  setName: (n) => set({ name: n }),
  appendMessage: (m) =>
    set((state) => ({ transcript: [...state.transcript, m] })),
  patchMessage: (id, text) =>
    set((state) => ({
      transcript: state.transcript.map((m) =>
        m.id === id ? { ...m, text } : m,
      ),
    })),
  resetTranscript: () => set({ transcript: [] }),
}));
