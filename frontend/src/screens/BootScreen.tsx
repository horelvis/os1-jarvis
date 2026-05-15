import { useEffect, useRef, useState } from "react";
import { OS1Loader, type OS1LoaderHandle } from "../components/OS1Loader";
import { useRoute } from "../core/router";
import { useSamantha } from "../core/store";
import { fetchProfile } from "../net/profile";

// Boot orchestrates two parallel waits: a minimum 2.8s so the OS1
// ribbon has time to morph into its closing ring (~2.2 s for the
// transform at fast speed + a brief breath), and a /profile probe.
// fetchProfile() returns null on 404 (no profile yet → onboarding)
// and throws on any other error. We treat a throw as "backend
// unreachable" and show a retry alert — NOT as "user has no
// profile" — so a transient backend outage can't accidentally
// overwrite an existing profile by re-running onboarding on top of
// it.
export function BootScreen() {
  const route = useRoute();
  const setName = useSamantha((s) => s.setName);
  const loaderRef = useRef<OS1LoaderHandle>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    // Give the ribbon a beat to register, then morph into the OS1 ring.
    // The transform animates over ~2.2 s; minDelay below makes sure
    // we don't navigate away before it lands.
    const morphTimer = setTimeout(
      () => loaderRef.current?.transform(true),
      300,
    );
    const minDelay = new Promise<void>((r) => setTimeout(r, 2800));
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
    return () => {
      cancelled = true;
      clearTimeout(morphTimer);
    };
  }, [route, setName, attempt]);

  if (error) {
    return (
      <div className="screen" style={{ gap: 24 }}>
        <div className="brand">Samantha</div>
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
      <OS1Loader ref={loaderRef} size="large" />
      <div className="brand">Samantha</div>
    </div>
  );
}
