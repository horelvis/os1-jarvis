import { useEffect, useRef } from "react";

type KeyHandlers = Record<string, (e: KeyboardEvent) => void>;

// Global keyboard hook. Screens declare which keys they care about
// (Enter to submit onboarding, Escape to leave conversation, etc.)
// without touching DOM focus.
export function useKeys(handlers: KeyHandlers): void {
  const handlersRef = useRef(handlers);
  handlersRef.current = handlers;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const handler = handlersRef.current[e.key];
      if (handler) handler(e);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
}
