// Speech recognition via the browser's Web Speech API. Chromium ships
// SpeechRecognition (under the webkit prefix) with Google Spanish STT
// for free, no model download. See CLAUDE.md §2.8 — the offline-only
// requirement was relaxed 2026-05-13, so the simpler browser path wins
// over a local Whisper integration.
//
// listen() returns a single final transcript. The first call triggers
// a one-time mic permission prompt; production kiosk should launch
// Chromium with `--use-fake-ui-for-media-stream` to pre-grant.

// TS lib.dom omits these even in modern targets, so declare what we
// actually use.
interface SpeechRecognitionAlternative {
  transcript: string;
  confidence: number;
}
interface SpeechRecognitionResult {
  [index: number]: SpeechRecognitionAlternative;
  isFinal: boolean;
  length: number;
}
interface SpeechRecognitionResultList {
  [index: number]: SpeechRecognitionResult;
  length: number;
}
interface SpeechRecognitionEvent extends Event {
  results: SpeechRecognitionResultList;
  resultIndex: number;
}
interface SpeechRecognitionErrorEvent extends Event {
  error: string;
  message: string;
}
interface SpeechRecognitionInstance extends EventTarget {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  maxAlternatives: number;
  onresult: ((ev: SpeechRecognitionEvent) => void) | null;
  onerror: ((ev: SpeechRecognitionErrorEvent) => void) | null;
  onend: ((ev: Event) => void) | null;
  onnomatch: ((ev: Event) => void) | null;
  start(): void;
  stop(): void;
  abort(): void;
}
type SpeechRecognitionCtor = new () => SpeechRecognitionInstance;

declare global {
  interface Window {
    SpeechRecognition?: SpeechRecognitionCtor;
    webkitSpeechRecognition?: SpeechRecognitionCtor;
  }
}

function getRecognitionCtor(): SpeechRecognitionCtor | null {
  return window.SpeechRecognition ?? window.webkitSpeechRecognition ?? null;
}

export function isAvailable(): boolean {
  return getRecognitionCtor() !== null;
}

export function listen(): Promise<string> {
  return new Promise((resolve, reject) => {
    const Ctor = getRecognitionCtor();
    if (!Ctor) {
      reject(new Error("speech_recognition_unavailable"));
      return;
    }
    const recog = new Ctor();
    recog.lang = "es-ES";
    recog.continuous = false;       // stop after a single utterance
    recog.interimResults = false;   // we only care about the final result
    recog.maxAlternatives = 1;

    let finalTranscript = "";
    let resolved = false;

    const finish = (text: string) => {
      if (resolved) return;
      resolved = true;
      resolve(text);
    };
    const fail = (err: Error) => {
      if (resolved) return;
      resolved = true;
      reject(err);
    };

    recog.onresult = (ev: SpeechRecognitionEvent) => {
      // We asked for a single utterance, so the only final result is
      // results[0][0]. Concatenate just in case the engine returned
      // multiple final chunks.
      for (let i = ev.resultIndex; i < ev.results.length; i++) {
        const result = ev.results[i];
        if (result.isFinal) {
          finalTranscript += result[0]?.transcript ?? "";
        }
      }
    };
    recog.onerror = (ev: SpeechRecognitionErrorEvent) => {
      // "no-speech", "aborted", "not-allowed", "service-not-allowed"
      // are the common errors. We surface the raw code; callers can
      // distinguish if they need to.
      fail(new Error(ev.error || "speech_recognition_error"));
    };
    recog.onend = () => {
      // Browser fires `end` after either a successful recognition or
      // a silent timeout. Treat empty as no-speech.
      const trimmed = finalTranscript.trim();
      if (trimmed) finish(trimmed);
      else fail(new Error("no-speech"));
    };

    try {
      recog.start();
    } catch (e) {
      fail(e instanceof Error ? e : new Error("start_failed"));
    }
  });
}
