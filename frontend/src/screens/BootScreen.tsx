import { useEffect, useState } from "react";
import { OS1Loader } from "../components/OS1Loader";
import { useRoute } from "../core/router";
import { useSamantha } from "../core/store";
import { fetchProfile } from "../net/profile";

// Boot orchestrates two parallel waits: a minimum 1.5s so the brand
// has time to breathe, and a /profile probe. fetchProfile() returns
// null on 404 (no profile yet → onboarding) and throws on any other
// error. We treat a throw as "backend unreachable" and show a retry
// alert — NOT as "user has no profile" — so a transient backend
// outage can't accidentally overwrite an existing profile by
// re-running onboarding on top of it.
export function BootScreen() {
  const route = useRoute();
  const setName = useSamantha((s) => s.setName);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    const minDelay = new Promise<void>((r) => setTimeout(r, 1500));
    const load = async () => {
      try {
        const profile = await fetchProfile();
        await minDelay;
        if (cancelled) return;
        if (profile) {
          setName(profile.name);
          route("ambient");
        } else {
          route("onboarding");
        }
      } catch (e) {
        await minDelay;
        if (cancelled) return;
        setError(e instanceof Error ? e.message : "no consigo hablar con el backend");
      }
    };
    load();
    return () => { cancelled = true; };
  }, [route, setName, attempt]);

  if (error) {
    return (
      <div className="screen" style={{ gap: 24 }}>
        <div className="brand">samantha</div>
        <div
          style={{
            opacity: 0.7,
            maxWidth: 380,
            textAlign: "center",
            lineHeight: 1.5,
          }}
        >
          No oigo al backend. ({error})
        </div>
        <button
          onClick={() => setAttempt((a) => a + 1)}
          style={{
            background: "transparent",
            border: "1px solid currentColor",
            color: "inherit",
            padding: "10px 24px",
            borderRadius: 999,
            font: "inherit",
            cursor: "pointer",
            opacity: 0.8,
          }}
        >
          Reintentar
        </button>
      </div>
    );
  }

  return (
    <div className="screen" style={{ gap: 32 }}>
      <OS1Loader size="small" />
      <div className="brand">samantha</div>
    </div>
  );
}
