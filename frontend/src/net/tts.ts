// Plays the backend's /speak WAV through an HTMLAudioElement. Phase 5
// swaps the backend to real Piper; the wire format stays audio/wav.
export async function speak(text: string): Promise<void> {
  const res = await fetch("/speak", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, voice: "default" }),
  });
  if (!res.ok) return;
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const audio = new Audio(url);
  await new Promise<void>((resolve) => {
    audio.addEventListener("ended", () => resolve(), { once: true });
    audio.addEventListener("error", () => resolve(), { once: true });
    audio.play().catch(() => resolve());
  });
  URL.revokeObjectURL(url);
}
