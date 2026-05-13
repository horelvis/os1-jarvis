import { useEffect } from "react";
import { OS1Loader } from "../components/OS1Loader";
import { useRoute } from "../core/router";
import { useSamantha } from "../core/store";
import { fetchProfile } from "../net/profile";

// Boot orchestrates two parallel waits: a minimum 1.5s so the brand
// has time to breathe, and a /profile probe. has_profile decides the
// next screen (ambient) or the onboarding flow.
export function BootScreen() {
  const route = useRoute();
  const setName = useSamantha((s) => s.setName);

  useEffect(() => {
    let cancelled = false;
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
      } catch {
        await minDelay;
        if (!cancelled) route("onboarding");
      }
    };
    load();
    return () => { cancelled = true; };
  }, [route, setName]);

  return (
    <div className="screen" style={{ gap: 32 }}>
      <OS1Loader size="small" />
      <div className="brand">samantha</div>
    </div>
  );
}
