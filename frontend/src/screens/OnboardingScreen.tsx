import { useEffect, useRef, useState } from "react";
import SpeechRecognition, { useSpeechRecognition } from "react-speech-recognition";
import { Wave } from "../components/Wave";
import { useRoute } from "../core/router";
import { useSamantha } from "../core/store";
import { createProfile } from "../net/profile";
import type { ProfileAnswer } from "../core/types";
import type { WaveMode } from "../core/types";

// Translate Web Speech API error codes to short Spanish messages
// the user can act on. Same catalog as ConversationScreen.
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

// Six onboarding prompts. Question 0 is the identity anchor (name).
// Questions 1-5 map 1:1 to the Big Five dimensions (TIPI ordering:
// E / O / C / A / N). Backend promotes each answer to a
// role=fact with kind=big5_{dim} so the personality signal is
// always in the system prompt, not just when recall surfaces it.
const QUESTIONS = [
  // Q0 — identity (required, non-skippable)
  "¿Cómo te llamo?",
  // Q1 — Extraversion: energy from solitude vs. company
  "Cuando se te ha hecho largo el día, ¿te llena más estar a solas, o con gente que te importa?",
  // Q2 — Openness: novelty-seeking vs. familiarity
  "Si tuvieras una tarde libre y nadie te viera, ¿probarías algo nuevo, o volverías a algo conocido?",
  // Q3 — Conscientiousness: planning vs. spontaneity
  "Cuando empiezas algo importante, ¿lo planificas antes, o te lanzas y vas viendo?",
  // Q4 — Agreeableness: voice it vs. swallow it
  "Cuando alguien te molesta, ¿se nota en el momento, o te lo sueles guardar?",
  // Q5 — Neuroticism: emotional reactivity / recovery speed
  "Cuando algo pequeño sale mal por la mañana, ¿se te queda pegado al cuerpo, o pasas pronto a otra cosa?",
];

// First-encounter flow. Six prompts one at a time. The mic is
// single-shot per question (continuous: false) — the user reviews
// what landed in the input before clicking "continuar", so an STT
// misfire doesn't lock the pairing onto a wrong name.
export function OnboardingScreen() {
  const route = useRoute();
  const setName = useSamantha((s) => s.setName);
  const [idx, setIdx] = useState(0);
  const [answers, setAnswers] = useState<(string | null)[]>(Array(6).fill(""));
  const [submitting, setSubmitting] = useState(false);
  const [micError, setMicError] = useState<string | null>(null);
  const [value, setValue] = useState("");
  const inputRef = useRef<HTMLInputElement | null>(null);

  const {
    interimTranscript,
    finalTranscript,
    listening,
    resetTranscript,
    browserSupportsSpeechRecognition,
  } = useSpeechRecognition();

  // The wave under the question reflects what the user is doing right
  // now: idle while reading, listening when the mic is active.
  const waveMode: WaveMode = listening ? "listening" : "idle";

  const onMicClick = () => {
    if (listening || submitting) return;
    setMicError(null);
    if (!browserSupportsSpeechRecognition) {
      setMicError(micErrorMessage("speech_recognition_unavailable"));
      return;
    }
    resetTranscript();
    setValue("");
    try {
      // Single-shot: continuous=false so the recognizer stops on the
      // first natural pause. The user reviews + edits before pressing
      // "continuar".
      SpeechRecognition.startListening({ continuous: false, language: "es-ES" });
    } catch (e) {
      const code = e instanceof Error ? e.message : "unknown";
      setMicError(micErrorMessage(code));
    }
  };

  // Mirror the recognizer's interim transcript into the input so the
  // user sees their words appear as they speak. On a final result we
  // copy the cumulative final into the field and stop.
  useEffect(() => {
    if (!listening) return;
    if (finalTranscript) {
      setValue(finalTranscript.trim());
    } else if (interimTranscript) {
      setValue(interimTranscript);
    }
  }, [interimTranscript, finalTranscript, listening]);

  // When listening ends, focus the input so the user can edit / press
  // Enter without clicking. resetTranscript so the next question
  // starts clean.
  useEffect(() => {
    if (!listening && finalTranscript) {
      inputRef.current?.focus();
      resetTranscript();
    }
  }, [listening, finalTranscript, resetTranscript]);

  // Stop listening if the user navigates away mid-capture.
  useEffect(() => {
    return () => { SpeechRecognition.stopListening(); };
  }, []);

  // Force focus on every question transition. autoFocus only fires on
  // first mount; idx changes don't remount the input.
  useEffect(() => {
    inputRef.current?.focus();
  }, [idx]);

  // Question 0 is the name. Per the pairing-must-finalize directive,
  // it cannot be skipped and the form blocks "continuar" until the
  // user has typed something. Questions 1-5 can be skipped (null).
  const nameRequired = idx === 0;
  const canContinue = value.trim().length > 0;
  const canSkip = !nameRequired;

  const submitCurrent = (skip: boolean) => {
    if (skip && nameRequired) return;          // safety net
    if (!skip && !canContinue) return;         // safety net
    const next = [...answers];
    next[idx] = skip ? null : value.trim();
    setAnswers(next);
    setValue("");
    SpeechRecognition.stopListening();
    if (idx < QUESTIONS.length - 1) setIdx(idx + 1);
    else void finalize(next);
  };

  const finalize = async (final: (string | null)[]) => {
    setSubmitting(true);
    const firstAnswer = (final[0] ?? "").trim();
    if (!firstAnswer) {
      setSubmitting(false);
      setIdx(0);
      return;
    }
    const name = firstAnswer.split(/\s+/)[0];
    const payload: ProfileAnswer[] = QUESTIONS.map((q, i) => ({
      q,
      a: final[i],
    }));
    try {
      const profile = await createProfile(name, payload);
      setName(profile.name);
      route("ambient");
    } catch (e) {
      console.error("createProfile failed", e);
      setSubmitting(false);
    }
  };

  return (
    <div className="screen">
      <div style={{ position: "absolute", inset: "5vh 0", height: 100 }}>
        <Wave mode={waveMode} />
      </div>

      <div style={{
        position: "absolute", top: "20vh", left: 0, right: 0,
        display: "flex", justifyContent: "center", gap: 6,
      }}>
        {QUESTIONS.map((_, i) => (
          <span key={i} style={{
            width: 6, height: 6, borderRadius: "50%",
            background: i === idx
              ? "var(--ink)"
              : i < idx ? "var(--ink-soft)" : "var(--ink-trace)",
            transform: i === idx ? "scale(1.5)" : "none",
            transition: "all 0.4s",
          }} />
        ))}
      </div>

      <div className="her-text" style={{
        position: "absolute", top: "32vh", left: 0, right: 0,
        textAlign: "center", fontSize: "var(--text-display)",
        padding: "0 8vw",
      }}>
        {QUESTIONS[idx]}
      </div>

      <form
        onSubmit={(e) => { e.preventDefault(); submitCurrent(false); }}
        style={{
          position: "absolute", bottom: "10vh", left: "10vw", right: "10vw",
          display: "flex", flexDirection: "column", alignItems: "center", gap: 16,
        }}
      >
        <input
          ref={inputRef}
          autoFocus
          value={value}
          onChange={(e) => { setValue(e.target.value); if (micError) setMicError(null); }}
          placeholder={listening ? "te escucho…" : "escribe y pulsa enter"}
          disabled={submitting}
          onClick={() => inputRef.current?.focus()}
          style={{
            width: "100%", background: "transparent", border: 0,
            borderBottom: "1px solid var(--ink-soft)",
            padding: "10px 4px", color: "var(--ink)",
            fontFamily: "var(--serif)", fontStyle: "italic",
            fontSize: "1.2rem", outline: "none", textAlign: "center",
          }}
        />
        {(micError || listening) && (
          <div style={{
            color: micError ? "var(--ink-soft)" : "var(--ink-dim)",
            fontSize: "var(--text-label)",
            fontStyle: "italic",
            letterSpacing: "0.1em",
            textAlign: "center",
            minHeight: "1.2em",
          }}>
            {micError ?? "escuchando…"}
          </div>
        )}
        <div style={{ display: "flex", gap: 16, alignItems: "center" }}>
          {canSkip && (
            <button
              type="button"
              disabled={submitting || listening}
              onClick={() => submitCurrent(true)}
              className="label"
              style={{
                background: "none", border: 0,
                color: "var(--ink-faint)", cursor: "pointer",
              }}
            >
              saltar
            </button>
          )}
          {/* Mic populates the input live (via the hook's interim
              transcript) — doesn't auto-submit. Lets the user
              correct an STT mistake before committing the pairing
              (especially critical for Q0, the name). */}
          <button
            type="button"
            className="mic-btn"
            aria-label="responder con la voz"
            aria-pressed={listening}
            disabled={submitting}
            onClick={onMicClick}
            style={{
              opacity: listening ? 0.6 : 1,
              transition: "opacity 0.2s",
            }}
          >
            <svg viewBox="0 0 24 24">
              <path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3zm5.3-3c0 3-2.54 5.1-5.3 5.1S6.7 14 6.7 11H5c0 3.41 2.72 6.23 6 6.72V21h2v-3.28c3.28-.48 6-3.3 6-6.72h-1.7z" />
            </svg>
          </button>
          <button
            type="submit"
            disabled={submitting || listening || !canContinue}
            className="label"
            style={{
              background: canContinue
                ? "rgba(255,255,255,0.08)"
                : "rgba(255,255,255,0.02)",
              border: "1px solid var(--ink-trace)",
              padding: "10px 24px", borderRadius: 999,
              color: canContinue ? "var(--ink)" : "var(--ink-faint)",
              cursor: canContinue ? "pointer" : "not-allowed",
              opacity: canContinue ? 1 : 0.5,
              transition: "all 0.2s",
            }}
          >
            continuar
          </button>
        </div>
      </form>
    </div>
  );
}
