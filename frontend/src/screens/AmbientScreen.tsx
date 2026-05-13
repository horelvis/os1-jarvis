import { useEffect, useState } from "react";
import { Wave } from "../components/Wave";
import { useRoute } from "../core/router";

const DAYS = ["domingo","lunes","martes","miércoles","jueves","viernes","sábado"];

function contextualPhrase(hour: number): string {
  if (hour < 6)  return "madrugada";
  if (hour < 12) return "buenos días";
  if (hour < 15) return "buena hora";
  if (hour < 20) return "tarde tranquila";
  if (hour < 23) return "ya es de noche";
  return "fin del día";
}

function timeLabel(d: Date): string {
  const h = String(d.getHours()).padStart(2, "0");
  const m = String(d.getMinutes()).padStart(2, "0");
  return `${h}:${m}`;
}

// The "Samantha is here" lock-screen analog. Wave breathes idle,
// time/day in the corners, contextual phrase at the bottom. A tap
// anywhere on the surface drops into a conversation.
export function AmbientScreen() {
  const route = useRoute();
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    const tick = setInterval(() => setNow(new Date()), 60_000);
    return () => clearInterval(tick);
  }, []);

  return (
    <div
      className="screen"
      onClick={() => route("conversation")}
      style={{ cursor: "pointer" }}
    >
      <div style={{ position: "absolute", top: "5vh", left: "6vw" }}>
        <span className="label">{DAYS[now.getDay()]}</span>
      </div>
      <div style={{ position: "absolute", top: "5vh", right: "6vw" }}>
        <span className="label">{timeLabel(now)}</span>
      </div>

      <div style={{
        position: "absolute", left: 0, right: 0, top: "50%",
        transform: "translateY(-50%)", height: 160,
      }}>
        <Wave mode="idle" />
      </div>

      <div className="her-text" style={{
        position: "absolute", bottom: "12vh", left: 0, right: 0,
        textAlign: "center", fontSize: "var(--text-ambient)",
      }}>
        {contextualPhrase(now.getHours())}
      </div>
    </div>
  );
}
