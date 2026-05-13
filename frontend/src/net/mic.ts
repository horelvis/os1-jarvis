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

export interface ListenOptions {
  /** Called repeatedly with the in-progress (non-final) transcript. UI
   *  should reflect it in real time so the user knows the mic is open
   *  and what's being heard. */
  onInterim?: (text: string) => void;
}

export function listen(opts: ListenOptions = {}): Promise<string> {
  return new Promise((resolve, reject) => {
    const Ctor = getRecognitionCtor();
    if (!Ctor) {
      reject(new Error("speech_recognition_unavailable"));
      return;
    }
    const recog = new Ctor();
    recog.lang = "es-ES";
    recog.continuous = false;        // stop after a single utterance
    // Interim results give us a live preview that we feed back to the
    // UI. Without this the user has no visible feedback the mic is
    // actually capturing and tends to think it's broken.
    recog.interimResults = true;
    recog.maxAlternatives = 1;

    let finalTranscript = "";
    let resolved = false;

    const finish = (text: string) => {
      if (resolved) return;
      resolved = true;
      try { recog.stop(); } catch { /* already stopped */ }
      resolve(text);
    };
    const fail = (err: Error) => {
      if (resolved) return;
      resolved = true;
      try { recog.stop(); } catch { /* already stopped */ }
      reject(err);
    };

    recog.onresult = (ev: SpeechRecognitionEvent) => {
      // Collect the latest interim+final across all results we have so
      // far. SpeechRecognitionResultList grows as the engine refines.
      let interim = "";
      for (let i = 0; i < ev.results.length; i++) {
        const result = ev.results[i];
        const text = result[0]?.transcript ?? "";
        if (result.isFinal) {
          // Always append final segments to keep them stable.
          if (!finalTranscript.includes(text)) {
            finalTranscript += text;
          }
        } else {
          interim += text;
        }
      }
      if (interim && opts.onInterim) {
        opts.onInterim((finalTranscript + interim).trim());
      }
      // If we already have a final result and the engine is winding
      // down, resolve early. Helps responsiveness.
      if (finalTranscript.trim()) {
        finish(finalTranscript.trim());
      }
    };

    recog.onerror = (ev: SpeechRecognitionErrorEvent) => {
      // Common error codes:
      //   not-allowed         → user denied permission
      //   service-not-allowed → blocked at browser/system level
      //   no-speech           → silent / mic muted / nothing heard
      //   aborted             → recog.stop() or page change
      //   network             → STT cloud unreachable
      //   audio-capture       → device unavailable / hardware issue
      console.warn("[mic] speech recognition error:", ev.error);
      fail(new Error(ev.error || "speech_recognition_error"));
    };

    recog.onend = () => {
      // End fires after either a successful recognition (we'd have
      // already resolved above) or a silent timeout. Last-chance
      // resolve / reject path.
      const trimmed = finalTranscript.trim();
      if (trimmed) finish(trimmed);
      else fail(new Error("no-speech"));
    };

    try {
      console.info("[mic] starting Web Speech API recognition (es-ES)");
      recog.start();
    } catch (e) {
      fail(e instanceof Error ? e : new Error("start_failed"));
    }
  });
}
