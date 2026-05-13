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
    setWaveMode("listening");
    try {
      const text = await listen();
      await sendMessage(text);
    } catch {
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
    <div className="screen" style={{ position: "relative" }} onClick={bump}>
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

      <div style={{
        position: "absolute", inset: 0,
        opacity: showHistory ? 0.3 : 1,
        transition: "opacity 0.3s",
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
