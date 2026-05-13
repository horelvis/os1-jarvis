import { useEffect, useRef, useState } from "react";
import SpeechRecognition, { useSpeechRecognition } from "react-speech-recognition";
import { Wave } from "../components/Wave";
import { useRoute } from "../core/router";
import { useSamantha } from "../core/store";
import { useKeys } from "../core/useKeys";
import { speak } from "../net/tts";
import { getWSClient } from "../net/wsClient";
import type { WaveMode } from "../core/types";

const IDLE_TIMEOUT_MS = 5 * 60 * 1000;

// How long a user's pause has to be before we treat the utterance as
// "complete" and ship it to the LLM. Web Speech API commits a final
// segment on its own ~1.5s of silence, but it sometimes splits a long
// sentence into multiple finals; this debounce stitches them.
const TRANSCRIPT_DEBOUNCE_MS = 800;

// Minimum characters before a punctuation mark is allowed to flush a
// sentence to TTS. Without this, the very first token like "Sí." or
// "Mmm." would get its own /speak round-trip, which is wasteful and
// chops Samantha's cadence.
const SENTENCE_MIN_CHARS = 20;

function micErrorMessage(code: string): string {
  switch (code) {
    case "not-allowed":
    case "service-not-allowed":
      return "No tengo permiso. Permite el micrófono en el navegador.";
    case "no-speech":
      return "No te he oído. Vuelve a intentarlo.";
    case "network":
      return "Sin red — el reconocimiento de voz pasa por el navegador.";
    case "audio-capture":
      return "No encuentro el micrófono.";
    case "aborted":
      return "Captura cancelada.";
    case "ws_not_connected":
      return "Conexión perdida. Vuelvo a intentarlo en un segundo.";
    case "speech_recognition_unavailable":
      return "Tu navegador no soporta reconocimiento de voz.";
    default:
      return `Mic: ${code}`;
  }
}

/** Pull every completed sentence off the front of `buffer`. A sentence
 *  ends with `. ! ? \n` but only counts as complete if it has at least
 *  `SENTENCE_MIN_CHARS` characters — otherwise the LLM is too early in
 *  its reply and splitting hurts cadence.
 *
 *  Returns [ready, remainder]. */
function flushSentences(buffer: string): [string[], string] {
  const out: string[] = [];
  let rest = buffer;
  // Greedy: pull all complete sentences in one pass.
  // Pattern: anything up to and including the next .!?\n followed by space.
  const re = /^([\s\S]*?[.!?\n]+)\s*/;
  while (rest.length >= SENTENCE_MIN_CHARS) {
    const m = re.exec(rest);
    if (!m) break;
    const sentence = m[1].trim();
    if (sentence.length < SENTENCE_MIN_CHARS) break;
    out.push(sentence);
    rest = rest.slice(m[0].length);
  }
  return [out, rest];
}

// Three input modes share the same surface:
//   - mic (default): tap → start continuous conversation. Tap again
//     to stop. Mic auto-pauses during Samantha's TTS so the wave
//     doesn't echo back into the recognizer.
//   - text (T-key): typing fallback for noisy rooms / kiosk testing.
//   - history (H-key): scrollable transcript over a dimmed wave.
// 5-min inactivity rolls back to Ambient.
export function ConversationScreen() {
  const route = useRoute();
  const transcript = useSamantha((s) => s.transcript);
  const appendMessage = useSamantha((s) => s.appendMessage);
  const patchMessage = useSamantha((s) => s.patchMessage);

  const [showHistory, setShowHistory] = useState(false);
  const [showTextInput, setShowTextInput] = useState(false);
  const [textValue, setTextValue] = useState("");
  const [waveMode, setWaveMode] = useState<WaveMode>("idle");
  const [micError, setMicError] = useState<string | null>(null);
  // Conversation mode = "we're in a phone call with Samantha". One tap
  // enters, another exits. Auto-resumes listening after each TTS turn.
  const [conversationActive, setConversationActive] = useState(false);
  // While true, the mic must NOT be open — chat in flight or TTS playing.
  const [busy, setBusy] = useState(false);

  const lastActivityRef = useRef<number>(Date.now());
  const activeRef = useRef(false);
  const busyRef = useRef(false);

  const {
    interimTranscript,
    finalTranscript,
    listening,
    resetTranscript,
    browserSupportsSpeechRecognition,
  } = useSpeechRecognition();

  useEffect(() => { activeRef.current = conversationActive; }, [conversationActive]);
  useEffect(() => { busyRef.current = busy; }, [busy]);

  const bump = () => { lastActivityRef.current = Date.now(); };

  // Idle → Ambient.
  useEffect(() => {
    const tick = setInterval(() => {
      if (Date.now() - lastActivityRef.current > IDLE_TIMEOUT_MS) {
        SpeechRecognition.stopListening();
        route("ambient");
      }
    }, 30_000);
    return () => clearInterval(tick);
  }, [route]);

  // Stop the singleton listener if we unmount mid-conversation.
  useEffect(() => {
    return () => { SpeechRecognition.stopListening(); };
  }, []);

  // Reflect listening state on the wave when we aren't busy with a
  // backend turn — busy turns take over the wave mode themselves.
  useEffect(() => {
    if (busy) return;
    setWaveMode(listening ? "listening" : "idle");
  }, [listening, busy]);

  useKeys({
    Escape: () => {
      if (showTextInput) setShowTextInput(false);
      else if (conversationActive) toggleConversation();
      else route("ambient");
    },
    h: () => { bump(); setShowHistory((v) => !v); },
    H: () => { bump(); setShowHistory((v) => !v); },
    t: () => { bump(); setShowTextInput((v) => !v); },
    T: () => { bump(); setShowTextInput((v) => !v); },
  });

  const sendMessage = async (msg: string) => {
    bump();
    const trimmed = msg.trim();
    if (!trimmed) return;
    appendMessage({
      id: crypto.randomUUID(),
      role: "user",
      text: trimmed,
      timestamp: Date.now(),
    });
    setBusy(true);
    setWaveMode("thinking");

    const replyId = crypto.randomUUID();
    appendMessage({ id: replyId, role: "samantha", text: "", timestamp: Date.now() });

    // ── Sentence-streaming TTS ───────────────────────────────────
    // As LLM tokens arrive we look for sentence boundaries (.!?\n)
    // and ship each completed sentence to /speak as soon as it's
    // ready. A worker plays one WAV at a time, so the user hears
    // Samantha's first sentence within ~500 ms of the LLM starting
    // instead of waiting for the whole reply.
    let buffer = "";
    const speakQueue: string[] = [];
    let workerRunning = false;
    const runWorker = async (): Promise<void> => {
      if (workerRunning) return;
      workerRunning = true;
      while (speakQueue.length > 0) {
        const sentence = speakQueue.shift()!;
        try { await speak(sentence); } catch (e) { console.warn("speak failed", e); }
      }
      workerRunning = false;
    };

    try {
      let started = false;
      const result = await getWSClient().chat(trimmed, (token) => {
        if (!started) { started = true; setWaveMode("speaking"); }
        // Live transcript patch for the history view.
        const current = useSamantha.getState().transcript.find((m) => m.id === replyId);
        const next = (current?.text ?? "") + token;
        patchMessage(replyId, next);

        // Try to flush completed sentences.
        buffer += token;
        const [ready, rest] = flushSentences(buffer);
        if (ready.length > 0) {
          speakQueue.push(...ready);
          buffer = rest;
          void runWorker();
        }
      });
      patchMessage(replyId, result.reply);

      // Flush whatever trails the final period (or no period at all).
      const tail = buffer.trim();
      if (tail) {
        speakQueue.push(tail);
        void runWorker();
      }
      // Wait until everything has actually played out.
      while (workerRunning || speakQueue.length > 0) {
        await new Promise((r) => setTimeout(r, 50));
      }
    } catch (e) {
      console.warn("chat failed", e);
      setMicError(micErrorMessage(e instanceof Error ? e.message : "unknown"));
    } finally {
      setBusy(false);
      setWaveMode("idle");
    }
  };

  // Debounced commit of the recognizer's final transcript. Web Speech
  // API often emits multiple "final" chunks per utterance (one per
  // pause); waiting TRANSCRIPT_DEBOUNCE_MS after the last update keeps
  // them stitched into one user message.
  useEffect(() => {
    if (!finalTranscript) return;
    if (busy) return;
    const handle = setTimeout(() => {
      const text = finalTranscript.trim();
      resetTranscript();
      if (!text) return;
      // Mute the mic during chat + TTS so Samantha's voice doesn't
      // get re-recognized as user speech (the echo-loop trap).
      SpeechRecognition.stopListening();
      void sendMessage(text).then(() => {
        if (activeRef.current) {
          // Conversation still active → resume listening.
          SpeechRecognition.startListening({
            continuous: true,
            language: "es-ES",
          });
        }
      });
    }, TRANSCRIPT_DEBOUNCE_MS);
    return () => clearTimeout(handle);
  }, [finalTranscript, busy, resetTranscript]);

  const toggleConversation = () => {
    bump();
    setMicError(null);
    if (!browserSupportsSpeechRecognition) {
      setMicError(micErrorMessage("speech_recognition_unavailable"));
      return;
    }
    if (conversationActive) {
      setConversationActive(false);
      SpeechRecognition.stopListening();
    } else {
      setConversationActive(true);
      try {
        SpeechRecognition.startListening({
          continuous: true,
          language: "es-ES",
        });
      } catch (e) {
        const code = e instanceof Error ? e.message : "unknown";
        setMicError(micErrorMessage(code));
        setConversationActive(false);
      }
    }
  };

  const onTextSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const v = textValue;
    setTextValue("");
    setShowTextInput(false);
    void sendMessage(v);
  };

  const lastSamantha = [...transcript].reverse().find((m) => m.role === "samantha");
  // What to show under Samantha's line: live interim transcript when
  // listening, otherwise the error message if any.
  const liveCaption = listening ? interimTranscript.trim() : "";

  return (
    <div className="screen" onClick={bump}>
      <div style={{ position: "absolute", top: "3vh", left: "5vw" }}>
        <button
          aria-label="ambient"
          className="label"
          style={{ background: "none", border: 0, color: "var(--ink-label)", cursor: "pointer" }}
          onClick={(e) => { e.stopPropagation(); route("ambient"); }}
        >
          ← ambient
        </button>
      </div>
      <button
        aria-label="historial"
        className="label"
        style={{
          position: "absolute", top: "3vh", right: "5vw",
          background: "none", border: 0, color: "var(--ink-label)", cursor: "pointer",
        }}
        onClick={(e) => { e.stopPropagation(); setShowHistory((v) => !v); }}
      >
        {showHistory ? "× cerrar" : "≡ historial"}
      </button>

      {/* Wave is a thin horizontal strip centered vertically — never
          full-bleed, because the canvas amplitude is `h*0.45` and a
          full-viewport canvas would paint chaos over the rest of the UI.
          Mirrors AmbientScreen's 160px strip layout. */}
      <div style={{
        position: "absolute", left: 0, right: 0, top: "50%",
        transform: "translateY(-50%)", height: 160,
        opacity: showHistory ? 0.3 : 1,
        transition: "opacity 0.3s",
        pointerEvents: "none",
      }}>
        <Wave mode={waveMode} />
      </div>

      {showHistory ? (
        <div style={{
          position: "absolute", inset: "10vh 5vw 18vh",
          overflowY: "auto",
          display: "flex", flexDirection: "column", gap: 12,
          maskImage: "linear-gradient(to bottom, transparent 0%, black 8%, black 100%)",
        }}>
          {transcript.map((m) => (
            <div key={m.id} style={{
              color: m.role === "samantha" ? "var(--ink)" : "var(--ink-dim)",
              fontFamily: m.role === "samantha" ? "var(--serif)" : "var(--sans)",
              fontStyle: m.role === "samantha" ? "italic" : "normal",
              fontSize: "var(--text-her-history)",
              alignSelf: m.role === "samantha" ? "flex-start" : "flex-end",
              textAlign: m.role === "samantha" ? "left" : "right",
              maxWidth: "85%",
            }}>
              {m.role === "user" ? "— " : ""}{m.text}
            </div>
          ))}
        </div>
      ) : (
        <div className="her-text" style={{
          position: "absolute", left: 0, right: 0, bottom: "20vh",
          textAlign: "center", fontSize: "var(--text-her-large)",
          padding: "0 6vw",
        }}>
          {lastSamantha?.text ?? ""}
        </div>
      )}

      {/* Mic status — sits below Samantha's last line. Live interim
          shows what the recognizer is currently hearing; errors
          replace it when present. */}
      {!showHistory && (liveCaption || micError) && (
        <div style={{
          position: "absolute", left: 0, right: 0, bottom: "10vh",
          textAlign: "center",
          fontSize: "var(--text-label)",
          fontStyle: "italic",
          letterSpacing: "0.08em",
          color: micError ? "var(--ink-soft)" : "var(--ink-dim)",
          padding: "0 8vw",
          pointerEvents: "none",
        }}>
          {micError ?? `“${liveCaption}”`}
        </div>
      )}

      {showTextInput && !showHistory && (
        <form onSubmit={onTextSubmit} style={{
          position: "absolute", left: "10vw", right: "10vw", bottom: "13vh",
          display: "flex", justifyContent: "center",
        }}>
          <input
            autoFocus
            value={textValue}
            onChange={(e) => { bump(); setTextValue(e.target.value); }}
            placeholder="dile algo…"
            style={{
              width: "100%", background: "transparent", border: 0,
              borderBottom: "1px solid var(--ink-trace)",
              padding: "8px 4px", color: "var(--ink)",
              fontFamily: "var(--serif)", fontStyle: "italic",
              fontSize: "var(--text-input)", outline: "none", textAlign: "center",
            }}
          />
        </form>
      )}

      <button
        className="mic-btn"
        aria-label={conversationActive ? "terminar conversación" : "iniciar conversación"}
        aria-pressed={conversationActive}
        style={{
          position: "absolute", left: "50%", bottom: "5vh", transform: "translateX(-50%)",
          // When the mic is open, hint that with a subtle inset + pulse.
          background: conversationActive ? "var(--ink-soft)" : "var(--mic-active)",
          boxShadow: conversationActive
            ? "0 0 0 6px rgba(255,255,255,0.18)"
            : "none",
          transition: "all 0.25s",
        }}
        onClick={(e) => { e.stopPropagation(); toggleConversation(); }}
      >
        <svg viewBox="0 0 24 24">
          {conversationActive ? (
            // Stop square (clear "tap to hang up")
            <rect x="7" y="7" width="10" height="10" rx="2" />
          ) : (
            <path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3zm5.3-3c0 3-2.54 5.1-5.3 5.1S6.7 14 6.7 11H5c0 3.41 2.72 6.23 6 6.72V21h2v-3.28c3.28-.48 6-3.3 6-6.72h-1.7z" />
          )}
        </svg>
      </button>
    </div>
  );
}
