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
      // Typing "hasta" in the text input must not toggle history/text
      // panels — only Escape passes through from editable elements.
      const t = e.target;
      const isEditable =
        t instanceof HTMLInputElement ||
        t instanceof HTMLTextAreaElement ||
        (t instanceof HTMLElement && t.isContentEditable);
      if (isEditable && e.key !== "Escape") return;
      const handler = handlersRef.current[e.key];
      if (handler) handler(e);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
}
