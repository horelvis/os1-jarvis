import { useEffect, useRef, useState } from "react";
import SpeechRecognition, { useSpeechRecognition } from "react-speech-recognition";
import { Wave } from "../components/Wave";
import { useRoute } from "../core/router";
import { useSamantha } from "../core/store";
import { stripEmoji } from "../core/sanitize";
import { useBargeIn } from "../core/useBargeIn";
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
    case "speech_recognition_unavailable":
      return "Tu navegador no soporta reconocimiento de voz.";
    default:
      return `Mic: ${code}`;
  }
}

// Errors from the chat turn (WS / LLM), as Samantha would say them —
// distinct from mic errors, which come from speech recognition.
function chatErrorMessage(code: string): string {
  if (code === "ws_not_connected")
    return "He perdido la conexión con mi cabeza. Dame un momento y repítemelo.";
  if (code.startsWith("llm_error"))
    return "Se me ha ido el hilo. ¿Me lo dices otra vez?";
  return "Algo se me ha cruzado. Inténtalo de nuevo.";
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
  const removeMessage = useSamantha((s) => s.removeMessage);

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
  // AbortController for the in-flight TTS playback. Barge-in (or Esc)
  // aborts the controller, which closes the AudioContext + cancels the
  // streamed fetch, silencing Samantha mid-utterance.
  const speakAbortRef = useRef<AbortController | null>(null);
  // Set when the VAD interrupts Samantha; tells the busy-flip wipe to
  // KEEP the transcript (it's the user's interruption, not echo).
  const bargedInRef = useRef(false);
  const [isSpeaking, setIsSpeaking] = useState(false);

  // VAD-based barge-in: while Samantha is speaking the mic is muted at
  // the speech-recognition layer (to avoid echo), but a separate VAD
  // listens on its own stream and fires when real user voice appears.
  // On trigger we abort speak() and the user-message debounce picks up
  // the next finalTranscript naturally.
  //
  // Kill switch via localStorage so you can disable VAD without
  // touching code while validating audio quality:
  //   localStorage.setItem('sam.bargeIn', '0')   → off (until removed)
  //   localStorage.removeItem('sam.bargeIn')     → back to default on
  const bargeInEnabled =
    typeof window === "undefined"
      ? true
      : localStorage.getItem("sam.bargeIn") !== "0";
  useBargeIn(isSpeaking && bargeInEnabled, () => {
    if (speakAbortRef.current) {
      speakAbortRef.current.abort();
      bargedInRef.current = true;
      // Reopen the mic NOW — waiting for speak() to settle loses the
      // first words of the interruption. startListening on an
      // already-listening manager is a no-op, so the later resume in
      // sendMessage's .then is harmless.
      if (activeRef.current) {
        void SpeechRecognition.startListening({
          continuous: true,
          language: "es-ES",
        });
      }
    }
  });

  const {
    interimTranscript,
    finalTranscript,
    listening,
    resetTranscript,
    browserSupportsSpeechRecognition,
  } = useSpeechRecognition();

  useEffect(() => { activeRef.current = conversationActive; }, [conversationActive]);
  useEffect(() => { busyRef.current = busy; }, [busy]);

  // Tail-echo guard: even though the turn now aborts recognition
  // up-front, results already in flight when the abort lands can
  // still arrive. Anything captured DURING busy is presumed to be
  // Samantha's own voice; when busy flips false we wipe it so the
  // debounce effect can't ship it as a user message — EXCEPT right
  // after a barge-in, where the in-flight transcript is the user's
  // interruption and must survive.
  useEffect(() => {
    if (busy) return;
    if (bargedInRef.current) {
      bargedInRef.current = false;
      return;
    }
    resetTranscript();
  }, [busy, resetTranscript]);

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

  // Unmounting mid-conversation must tear the whole turn down: clear
  // activeRef FIRST so the in-flight sendMessage .then can't restart
  // the (module-singleton) recognizer on another screen, silence any
  // playing TTS, and abort recognition (abort, not stop, so a
  // continuous session can't auto-restart on `onend`).
  useEffect(() => {
    return () => {
      activeRef.current = false;
      speakAbortRef.current?.abort();
      void SpeechRecognition.abortListening();
    };
  }, []);

  // Reflect listening state on the wave when we aren't busy with a
  // backend turn — busy turns take over the wave mode themselves.
  useEffect(() => {
    if (busy) return;
    setWaveMode(listening ? "listening" : "idle");
  }, [listening, busy]);

  useKeys({
    Escape: () => {
      // If Samantha is talking, Esc cuts her off (manual barge-in
      // fallback for when the VAD doesn't fire — e.g. typed input
      // mode, or headphone setup where the mic can't hear).
      if (speakAbortRef.current) {
        speakAbortRef.current.abort();
        return;
      }
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
    setMicError(null);
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

    // ── Full-response TTS ────────────────────────────────────────
    // We collect the LLM tokens into a single string and only call
    // /speak once with the complete reply. The backend streams the
    // PCM, so the user hears Samantha's voice ~0.5 s after the call
    // — but the model decodes the whole utterance with cross-
    // sentence prosodic context, which is what makes the cloned
    // voice sound conversational instead of "reading sentences".
    try {
      let reply = "";
      const result = await getWSClient().chat(trimmed, (token) => {
        reply += token;
        // Live transcript patch for the history view. Strip emojis so
        // the displayed text matches what Samantha will actually say
        // (the TTS path strips them too — see the speak() call below).
        patchMessage(replyId, stripEmoji(reply));
      });
      const cleanReply = stripEmoji(result.reply);
      patchMessage(replyId, cleanReply);

      const full = cleanReply.trim();
      if (full) {
        setWaveMode("speaking");
        const ac = new AbortController();
        speakAbortRef.current = ac;
        setIsSpeaking(true);
        try {
          await speak(full, ac.signal);
        } catch (e) {
          console.warn("speak failed", e);
        } finally {
          setIsSpeaking(false);
          speakAbortRef.current = null;
        }
      }
    } catch (e) {
      console.warn("chat failed", e);
      removeMessage(replyId);
      setMicError(chatErrorMessage(e instanceof Error ? e.message : "unknown"));
    } finally {
      setBusy(false);
      setWaveMode("idle");
    }
  };

  // Surface the listening state and any interim/final transcript so
  // we can see in the browser console whether react-speech-recognition
  // is actually hearing anything.
  useEffect(() => {
    console.info("[conv] listening:", listening,
      "interim:", JSON.stringify(interimTranscript),
      "final:", JSON.stringify(finalTranscript),
      "busy:", busy);
  }, [listening, interimTranscript, finalTranscript, busy]);

  // Debounced commit of the recognizer's final transcript. Web Speech
  // API often emits multiple "final" chunks per utterance (one per
  // pause); waiting TRANSCRIPT_DEBOUNCE_MS after the last update keeps
  // them stitched into one user message.
  useEffect(() => {
    if (!finalTranscript) return;
    if (busy) return;
    const handle = setTimeout(() => {
      const text = finalTranscript.trim();
      console.info("[conv] debounce fired, committing:", JSON.stringify(text));
      // Abort BEFORE resetting: resetTranscript() aborts with
      // pauseAfterDisconnect=false, and in continuous mode the manager
      // auto-restarts on `onend` — the mic would stay open during
      // Samantha's TTS (the echo-loop trap). abortListening() while
      // still listening sets pauseAfterDisconnect=true, so the
      // recognizer stays down until we explicitly resume.
      if (text) void SpeechRecognition.abortListening();
      resetTranscript();
      if (!text) return;
      void sendMessage(text).then(() => {
        console.info("[conv] sendMessage done, conversation still active:",
          activeRef.current);
        if (activeRef.current) {
          // Conversation still active → resume listening.
          SpeechRecognition.startListening({
            continuous: true,
            language: "es-ES",
          });
        }
      }).catch((e) => {
        console.error("[conv] sendMessage rejected:", e);
      });
    }, TRANSCRIPT_DEBOUNCE_MS);
    return () => clearTimeout(handle);
  }, [finalTranscript, busy, resetTranscript]);

  const toggleConversation = () => {
    bump();
    setMicError(null);
    console.info("[conv] toggle clicked. browserSupports:",
      browserSupportsSpeechRecognition,
      "active:", conversationActive);
    if (!browserSupportsSpeechRecognition) {
      setMicError(micErrorMessage("speech_recognition_unavailable"));
      console.warn("[conv] browser does not support speech recognition");
      return;
    }
    if (conversationActive) {
      setConversationActive(false);
      SpeechRecognition.stopListening();
      console.info("[conv] stop listening");
    } else {
      setConversationActive(true);
      try {
        SpeechRecognition.startListening({
          continuous: true,
          language: "es-ES",
        });
        console.info("[conv] start listening (es-ES, continuous)");
      } catch (e) {
        const code = e instanceof Error ? e.message : "unknown";
        setMicError(micErrorMessage(code));
        setConversationActive(false);
        console.error("[conv] startListening threw:", e);
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
