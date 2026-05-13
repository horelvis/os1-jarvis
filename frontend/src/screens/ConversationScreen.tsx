import { useEffect, useRef, useState } from "react";
import { Wave } from "../components/Wave";
import { useRoute } from "../core/router";
import { useSamantha } from "../core/store";
import { useKeys } from "../core/useKeys";
import { listen } from "../net/mic";
import { speak } from "../net/tts";
import { getWSClient } from "../net/wsClient";
import type { WaveMode } from "../core/types";

const IDLE_TIMEOUT_MS = 5 * 60 * 1000;

// Same catalog as OnboardingScreen — duplicated to keep screens
// independent; if a third surface needs it, lift to core/i18n.
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

// Three input modes share the same surface:
//   - mic (default): tap → backend captures → STT → send
//   - text (T-key): typing fallback for noisy rooms / kiosk testing
//   - history (H-key): scrollable transcript over a dimmed wave
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
  const [liveTranscript, setLiveTranscript] = useState("");
  const lastActivityRef = useRef<number>(Date.now());

  const bump = () => { lastActivityRef.current = Date.now(); };

  useEffect(() => {
    const tick = setInterval(() => {
      if (Date.now() - lastActivityRef.current > IDLE_TIMEOUT_MS) {
        route("ambient");
      }
    }, 30_000);
    return () => clearInterval(tick);
  }, [route]);

  useKeys({
    Escape: () => {
      if (showTextInput) setShowTextInput(false);
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
    setWaveMode("thinking");

    const replyId = crypto.randomUUID();
    appendMessage({ id: replyId, role: "samantha", text: "", timestamp: Date.now() });

    try {
      let started = false;
      let acc = "";
      const result = await getWSClient().chat(trimmed, (token) => {
        if (!started) { started = true; setWaveMode("speaking"); }
        acc += token;
        patchMessage(replyId, acc);
      });
      patchMessage(replyId, result.reply);
      await speak(result.reply);
    } catch (e) {
      console.warn("chat failed", e);
    } finally {
      setWaveMode("idle");
    }
  };

  const onMicClick = async () => {
    bump();
    setMicError(null);
    setWaveMode("listening");
    try {
      const text = await listen({
        onInterim: (partial) => setLiveTranscript(partial),
      });
      setLiveTranscript("");
      await sendMessage(text);
    } catch (e) {
      const code = e instanceof Error ? e.message : "unknown";
      setMicError(micErrorMessage(code));
      setLiveTranscript("");
      setWaveMode("idle");
    }
  };

  const onTextSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const v = textValue;
    setTextValue("");
    setShowTextInput(false);
    sendMessage(v);
  };

  const lastSamantha = [...transcript].reverse().find((m) => m.role === "samantha");

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

      {/* Mic status — sits below Samantha's last line. Shown only when
          the user is actively dictating or a mic error occurred. */}
      {!showHistory && (liveTranscript || micError) && (
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
          {micError ?? `“${liveTranscript}”`}
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
        aria-label="microphone"
        style={{ position: "absolute", left: "50%", bottom: "5vh", transform: "translateX(-50%)" }}
        onClick={(e) => { e.stopPropagation(); onMicClick(); }}
      >
        <svg viewBox="0 0 24 24">
          <path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3zm5.3-3c0 3-2.54 5.1-5.3 5.1S6.7 14 6.7 11H5c0 3.41 2.72 6.23 6 6.72V21h2v-3.28c3.28-.48 6-3.3 6-6.72h-1.7z" />
        </svg>
      </button>
    </div>
  );
}
