import { useState } from "react";
import { Wave } from "../components/Wave";
import { useRoute } from "../core/router";
import { useSamantha } from "../core/store";
import { createProfile } from "../net/profile";
import type { ProfileAnswer } from "../core/types";

const QUESTIONS = [
  "¿Cómo te llamo?",
  "¿Cómo estás hoy?",
  "¿Qué te gusta hacer cuando tienes tiempo para ti?",
  "Cuéntame algo que te haya hecho ilusión últimamente. Algo pequeño vale.",
  "¿Y algo que te esté rondando la cabeza estos días?",
  "Una última: conmigo, ¿prefieres que sea más directa o más cuidadosa?",
];

// First-encounter flow. Six prompts one at a time. Empty / skipped
// answers land as null and the backend keeps the question text in
// the chunk anyway so Samantha can refer back to "you didn't answer
// the third one" later if she wants.
export function OnboardingScreen() {
  const route = useRoute();
  const setName = useSamantha((s) => s.setName);
  const [idx, setIdx] = useState(0);
  const [answers, setAnswers] = useState<(string | null)[]>(Array(6).fill(""));
  const [submitting, setSubmitting] = useState(false);
  const [value, setValue] = useState("");

  const submitCurrent = (skip: boolean) => {
    const next = [...answers];
    next[idx] = skip ? null : value.trim() || null;
    setAnswers(next);
    setValue("");
    if (idx < QUESTIONS.length - 1) setIdx(idx + 1);
    else finalize(next);
  };

  const finalize = async (final: (string | null)[]) => {
    setSubmitting(true);
    const firstAnswer = final[0];
    const name =
      firstAnswer && firstAnswer.trim().length > 0
        ? firstAnswer.trim().split(/\s+/)[0]
        : "tú";
    const payload: ProfileAnswer[] = QUESTIONS.map((q, i) => ({
      q,
      a: final[i] ?? null,
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
    <div className="screen" style={{ position: "relative" }}>
      <div style={{ position: "absolute", inset: "5vh 0", height: 100 }}>
        <Wave mode="listening" />
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
          autoFocus
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="escribe y pulsa enter"
          disabled={submitting}
          style={{
            width: "100%", background: "transparent", border: 0,
            borderBottom: "1px solid var(--ink-trace)",
            padding: "10px 4px", color: "var(--ink)",
            fontFamily: "var(--serif)", fontStyle: "italic",
            fontSize: "1.2rem", outline: "none", textAlign: "center",
          }}
        />
        <div style={{ display: "flex", gap: 16 }}>
          <button
            type="button"
            disabled={submitting}
            onClick={() => submitCurrent(true)}
            className="label"
            style={{
              background: "none", border: 0,
              color: "var(--ink-faint)", cursor: "pointer",
            }}
          >
            saltar
          </button>
          <button
            type="submit"
            disabled={submitting}
            className="label"
            style={{
              background: "rgba(255,255,255,0.08)",
              border: "1px solid var(--ink-trace)",
              padding: "10px 24px", borderRadius: 999,
              color: "var(--ink)", cursor: "pointer",
            }}
          >
            continuar
          </button>
        </div>
      </form>
    </div>
  );
}
