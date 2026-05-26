import { useEffect, useRef, useState } from "react";
import SpeechRecognition, { useSpeechRecognition } from "react-speech-recognition";
import { Wave } from "../components/Wave";
import { useRoute } from "../core/router";
import { useSamantha } from "../core/store";
import { createProfile } from "../net/profile";
import { speak } from "../net/tts";
import type { ProfileAnswer } from "../core/types";
import type { WaveMode } from "../core/types";

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

const QUESTIONS = [
  "¿Cómo te llamas?",
  "Cuando se te ha hecho largo el día, ¿te llena más estar a solas, o con gente que te importa?",
  "Si tuvieras una tarde libre y nadie te viera, ¿probarías algo nuevo, o volverías a algo conocido?",
  "Cuando empiezas algo importante, ¿lo planificas antes, o te lanzas y vas viendo?",
  "Cuando alguien te molesta, ¿se nota en el momento, o te lo sueles guardar?",
  "Cuando algo pequeño sale mal por la mañana, ¿se te queda pegado al cuerpo, o pasas pronto a otra cosa?",
];

const VOICE_PROMPTS = [
  "Hola. Estoy aquí. Para empezar a calibrar mi configuración, necesito conocerte un poco. ¿Cómo te llamas?",
  "Dime: cuando se te ha hecho largo el día, ¿te llena más estar a solas, o con gente que te importa?",
  "Si tuvieras una tarde libre y nadie te viera, ¿probarías algo nuevo, o volverías a algo conocido?",
  "Cuando empiezas algo importante, ¿lo planificas antes, o te lanzas y vas viendo?",
  "Cuando alguien te molesta, ¿se nota en el momento, o te lo sueles guardar?",
  "Última pregunta: cuando algo pequeño sale mal por la mañana, ¿se te queda pegado al cuerpo, o pasas pronto a otra cosa?",
];

type OnboardingStep = "welcome" | "speaking" | "listening" | "review" | "done";

export function OnboardingScreen() {
  const route = useRoute();
  const setName = useSamantha((s) => s.setName);
  const [step, setStep] = useState<OnboardingStep>("welcome");
  const [idx, setIdx] = useState(0);
  const [answers, setAnswers] = useState<(string | null)[]>(Array(6).fill(""));
  const [submitting, setSubmitting] = useState(false);
  const [micError, setMicError] = useState<string | null>(null);
  const [value, setValue] = useState("");
  const inputRef = useRef<HTMLInputElement | null>(null);
  const speakAbortRef = useRef<AbortController | null>(null);

  const {
    interimTranscript,
    finalTranscript,
    listening,
    resetTranscript,
    browserSupportsSpeechRecognition,
  } = useSpeechRecognition();

  // The wave under the question reflects the state of the voice onboarding
  const waveMode: WaveMode =
    step === "speaking"
      ? "speaking"
      : step === "listening"
      ? "listening"
      : step === "done"
      ? "speaking"
      : "idle";

  const startListening = () => {
    setMicError(null);
    resetTranscript();
    setValue("");
    try {
      SpeechRecognition.startListening({ continuous: false, language: "es-ES" });
    } catch (e) {
      const code = e instanceof Error ? e.message : "unknown";
      setMicError(micErrorMessage(code));
      setStep("review");
    }
  };

  const initiateOnboarding = async () => {
    if (!browserSupportsSpeechRecognition) {
      // Degrade gracefully to text-only review loop
      setIdx(0);
      setStep("review");
      return;
    }
    setIdx(0);
    setStep("speaking");
    const ac = new AbortController();
    speakAbortRef.current = ac;
    try {
      await speak(VOICE_PROMPTS[0], ac.signal);
      if (!ac.signal.aborted) {
        setStep("listening");
        startListening();
      }
    } catch (e) {
      console.warn("speak failed", e);
      if (!ac.signal.aborted) {
        setStep("review");
      }
    }
  };

  // Mirror the recognizer's interim transcript into the input so the
  // user sees their words appear as they speak. On a final result we
  // copy the cumulative final into the field.
  useEffect(() => {
    if (step !== "listening") return;
    if (finalTranscript) {
      setValue(finalTranscript.trim());
    } else if (interimTranscript) {
      setValue(interimTranscript);
    }
  }, [interimTranscript, finalTranscript, step]);

  // Transition from listening to review once the user stops talking (natural pause)
  useEffect(() => {
    if (step === "listening" && !listening) {
      setStep("review");
    }
  }, [listening, step]);

  // Stop listening/speaking if the user navigates away mid-capture.
  useEffect(() => {
    return () => {
      SpeechRecognition.stopListening();
      if (speakAbortRef.current) {
        speakAbortRef.current.abort();
      }
    };
  }, []);

  // Force focus on input during review transitions.
  useEffect(() => {
    if (step === "review") {
      inputRef.current?.focus();
    }
  }, [idx, step]);

  const nameRequired = idx === 0;
  const canContinue = value.trim().length > 0;
  const canSkip = !nameRequired;

  const handleRepeat = async () => {
    if (speakAbortRef.current) {
      speakAbortRef.current.abort();
    }
    setStep("speaking");
    const ac = new AbortController();
    speakAbortRef.current = ac;
    try {
      await speak(VOICE_PROMPTS[idx], ac.signal);
      if (!ac.signal.aborted) {
        setStep("listening");
        startListening();
      }
    } catch (e) {
      console.warn("speak failed", e);
      if (!ac.signal.aborted) {
        setStep("review");
      }
    }
  };

  const handleContinue = async () => {
    if (nameRequired && !value.trim()) return;
    const nextAnswers = [...answers];
    nextAnswers[idx] = value.trim() || null;
    setAnswers(nextAnswers);
    setValue("");

    if (speakAbortRef.current) {
      speakAbortRef.current.abort();
      speakAbortRef.current = null;
    }
    SpeechRecognition.stopListening();

    if (idx < QUESTIONS.length - 1) {
      const nextIdx = idx + 1;
      setIdx(nextIdx);
      if (!browserSupportsSpeechRecognition) {
        setStep("review");
      } else {
        setStep("speaking");
        const ac = new AbortController();
        speakAbortRef.current = ac;
        try {
          await speak(VOICE_PROMPTS[nextIdx], ac.signal);
          if (!ac.signal.aborted) {
            setStep("listening");
            startListening();
          }
        } catch (e) {
          console.warn("speak failed", e);
          if (!ac.signal.aborted) {
            setStep("review");
          }
        }
      }
    } else {
      setStep("done");
      if (!browserSupportsSpeechRecognition) {
        await finalize(nextAnswers);
      } else {
        const ac = new AbortController();
        speakAbortRef.current = ac;
        try {
          await speak(
            "Gracias. Un momento mientras calibro mi configuración... Listo, ya estoy aquí.",
            ac.signal
          );
        } catch (e) {
          console.warn("outro speak failed", e);
        }
        if (!ac.signal.aborted) {
          await finalize(nextAnswers);
        }
      }
    }
  };

  const handleSkip = async () => {
    if (nameRequired) return;
    const nextAnswers = [...answers];
    nextAnswers[idx] = null;
    setAnswers(nextAnswers);
    setValue("");

    if (speakAbortRef.current) {
      speakAbortRef.current.abort();
      speakAbortRef.current = null;
    }
    SpeechRecognition.stopListening();

    if (idx < QUESTIONS.length - 1) {
      const nextIdx = idx + 1;
      setIdx(nextIdx);
      if (!browserSupportsSpeechRecognition) {
        setStep("review");
      } else {
        setStep("speaking");
        const ac = new AbortController();
        speakAbortRef.current = ac;
        try {
          await speak(VOICE_PROMPTS[nextIdx], ac.signal);
          if (!ac.signal.aborted) {
            setStep("listening");
            startListening();
          }
        } catch (e) {
          console.warn("speak failed", e);
          if (!ac.signal.aborted) {
            setStep("review");
          }
        }
      }
    } else {
      setStep("done");
      if (!browserSupportsSpeechRecognition) {
        await finalize(nextAnswers);
      } else {
        const ac = new AbortController();
        speakAbortRef.current = ac;
        try {
          await speak(
            "Gracias. Un momento mientras calibro mi configuración... Listo, ya estoy aquí.",
            ac.signal
          );
        } catch (e) {
          console.warn("outro speak failed", e);
        }
        if (!ac.signal.aborted) {
          await finalize(nextAnswers);
        }
      }
    }
  };

  const finalize = async (final: (string | null)[]) => {
    setSubmitting(true);
    const firstAnswer = (final[0] ?? "").trim();
    if (!firstAnswer) {
      setSubmitting(false);
      setIdx(0);
      setStep("review");
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
      setStep("review");
    }
  };

  // 1. Welcome Screen
  if (step === "welcome") {
    return (
      <div className="screen" style={{ gap: "4vh" }}>
        <div style={{ height: 120, display: "flex", alignItems: "center" }}>
          <Wave mode="idle" />
        </div>

        <div className="her-text" style={{
          fontSize: "2.2rem",
          textAlign: "center",
          maxWidth: "600px",
          lineHeight: 1.3,
        }}>
          Instalación del Sistema Operativo OS1
        </div>

        <div style={{
          color: "var(--ink-dim)",
          fontFamily: "var(--sans)",
          fontSize: "0.85rem",
          textAlign: "center",
          maxWidth: "420px",
          lineHeight: 1.6,
          fontWeight: 300,
          letterSpacing: "0.02em",
        }}>
          Este asistente te guiará en la calibración de voz y configuración inicial de tu compañera.
        </div>

        <button
          onClick={initiateOnboarding}
          className="btn-premium"
          style={{ marginTop: "2vh" }}
        >
          Iniciar Calibración
        </button>
      </div>
    );
  }

  // 2. Finalizing Screen
  if (step === "done" || submitting) {
    return (
      <div className="screen" style={{ gap: "4vh" }}>
        <div style={{ height: 120, display: "flex", alignItems: "center" }}>
          <Wave mode="speaking" />
        </div>
        <div className="her-text" style={{
          fontSize: "1.8rem",
          textAlign: "center",
          fontStyle: "italic",
        }}>
          Calibrando configuración...
        </div>
        <div style={{
          color: "var(--ink-dim)",
          fontFamily: "var(--sans)",
          fontSize: "0.75rem",
          letterSpacing: "0.15em",
          textTransform: "uppercase",
        }}>
          un momento por favor
        </div>
      </div>
    );
  }

  // 3. Question Flow (speaking, listening, review)
  return (
    <div className="screen">
      <div style={{ position: "absolute", inset: "5vh 0", height: 100 }}>
        <Wave mode={waveMode} />
      </div>

      <div style={{
        position: "absolute", top: "20vh", left: 0, right: 0,
        display: "flex", justifyContent: "center", gap: 8,
      }}>
        {QUESTIONS.map((_, i) => (
          <span key={i} style={{
            width: 6, height: 6, borderRadius: "50%",
            background: i === idx
              ? "var(--ink)"
              : i < idx ? "var(--ink-soft)" : "var(--ink-trace)",
            transform: i === idx ? "scale(1.4)" : "none",
            transition: "all 0.4s cubic-bezier(0.22, 1, 0.36, 1)",
          }} />
        ))}
      </div>

      <div className="her-text" style={{
        position: "absolute", top: "32vh", left: 0, right: 0,
        textAlign: "center", fontSize: "1.8rem",
        padding: "0 8vw",
        lineHeight: 1.4,
      }}>
        {QUESTIONS[idx]}
      </div>

      <form
        onSubmit={(e) => { e.preventDefault(); handleContinue(); }}
        style={{
          position: "absolute", bottom: "10vh", left: "10vw", right: "10vw",
          display: "flex", flexDirection: "column", alignItems: "center", gap: 20,
        }}
      >
        <input
          ref={inputRef}
          value={value}
          onChange={(e) => { setValue(e.target.value); if (micError) setMicError(null); }}
          placeholder={
            step === "speaking"
              ? "Samantha habla…"
              : step === "listening"
              ? "te escucho…"
              : "escribe tu respuesta si deseas editarla"
          }
          disabled={submitting || step === "speaking"}
          onClick={() => { if (step === "review") inputRef.current?.focus(); }}
          style={{
            width: "100%", background: "transparent", border: 0,
            borderBottom: "1px solid var(--ink-trace)",
            padding: "12px 4px", color: "var(--ink)",
            fontFamily: "var(--serif)", fontStyle: "italic",
            fontSize: "1.25rem", outline: "none", textAlign: "center",
            opacity: step === "speaking" ? 0.3 : 1,
            transition: "opacity 0.3s",
          }}
        />

        {(micError || step === "listening" || step === "speaking") && (
          <div style={{
            color: micError ? "var(--ink-soft)" : "var(--ink-dim)",
            fontSize: "var(--text-label)",
            fontStyle: "italic",
            letterSpacing: "0.08em",
            textAlign: "center",
            minHeight: "1.2em",
          }}>
            {micError ?? (step === "speaking" ? "escuchando a Samantha…" : "escuchando tu voz…")}
          </div>
        )}

        <div style={{ display: "flex", gap: 16, alignItems: "center", marginTop: 8 }}>
          {canSkip && step === "review" && (
            <button
              type="button"
              disabled={submitting}
              onClick={handleSkip}
              className="btn-premium"
              style={{ borderColor: "transparent", color: "var(--ink-faint)" }}
            >
              saltar
            </button>
          )}

          {step === "review" && (
            <button
              type="button"
              className="mic-btn"
              aria-label="volver a grabar"
              disabled={submitting}
              onClick={handleRepeat}
              style={{
                background: "rgba(255, 255, 255, 0.08)",
                border: "1px solid var(--ink-trace)",
                transition: "all 0.2s",
              }}
            >
              <svg viewBox="0 0 24 24" style={{ fill: "var(--ink)" }}>
                <path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3zm5.3-3c0 3-2.54 5.1-5.3 5.1S6.7 14 6.7 11H5c0 3.41 2.72 6.23 6 6.72V21h2v-3.28c3.28-.48 6-3.3 6-6.72h-1.7z" />
              </svg>
            </button>
          )}

          {step === "review" && (
            <button
              type="submit"
              disabled={submitting || (nameRequired && !canContinue)}
              className="btn-premium"
            >
              continuar
            </button>
          )}
        </div>
      </form>
    </div>
  );
}
