import { useEffect, useRef } from "react";
import { MicVAD } from "@ricky0123/vad-web";

// Hook that listens for the user's voice while `active` is true and
// fires `onSpeechStart` when speech is detected. Used to interrupt
// Samantha's TTS mid-utterance ("barge-in").
//
// Implementation notes:
//
// - Uses Silero VAD compiled to wasm via @ricky0123/vad-web. Far more
//   reliable than watching `interimTranscript` from react-speech-
//   recognition, because the speech recognizer's mic gets polluted by
//   the speakers' audio even with browser echo-cancellation.
//
// - The library bundles a worklet + ONNX model + WASM runtime; by
//   default they load from a CDN. That's fine for dev; for the kiosk
//   deployment we should vendor them under /public/ later.
//
// - We don't start a fresh MicVAD on every speak() call — that costs
//   ~300 ms of cold-start each time. We keep one instance for the
//   component lifetime and toggle .start()/.pause() on `active`.
//
// - The hook destroys the VAD on unmount so the mic stream is released.

export function useBargeIn(
  active: boolean,
  onSpeechStart: () => void,
): void {
  const vadRef = useRef<MicVAD | null>(null);
  const cbRef = useRef(onSpeechStart);
  cbRef.current = onSpeechStart;

  // Suppress VAD events for a short window after `active` flips true.
  // Without this the very start of Samantha's audio bleeds through
  // browser AEC into the mic and Silero fires `onSpeechStart` on her
  // own voice → she cuts herself off after the first word. 600 ms
  // is enough for the audio buffer to settle.
  const warmupUntilRef = useRef(0);

  // Lazy-create the MicVAD instance once. The .new() returns a promise
  // and may take ~300 ms (downloading the ONNX model + spawning the
  // audio worklet); we live with that on the very first activation.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const vad = await MicVAD.new({
        // vad-web 0.0.30 changed defaults to expect assets locally
        // (`./silero_vad_legacy.onnx`), which 404s on our Vite dev
        // server. Point both asset paths at jsDelivr until we vendor
        // them under /public/ for the kiosk build.
        baseAssetPath:
          "https://cdn.jsdelivr.net/npm/@ricky0123/vad-web@0.0.30/dist/",
        onnxWASMBasePath:
          "https://cdn.jsdelivr.net/npm/onnxruntime-web@1.26.0/dist/",
        // Conservative thresholds: with the laptop's built-in mic and
        // speakers the browser's AEC isn't enough — Samantha's own
        // voice leaks back enough for Silero defaults to fire.
        // Raising the positive threshold to 0.85 and demanding 300 ms
        // of sustained speech filters echo while still triggering on
        // real user voice within a third of a second.
        positiveSpeechThreshold: 0.85,
        negativeSpeechThreshold: 0.6,
        minSpeechMs: 300,
        onSpeechStart: () => {
          if (Date.now() < warmupUntilRef.current) return;
          cbRef.current();
        },
      });
      if (cancelled) {
        vad.destroy();
        return;
      }
      vadRef.current = vad;
    })().catch((e) => {
      console.warn("useBargeIn: VAD init failed", e);
    });

    return () => {
      cancelled = true;
      vadRef.current?.destroy();
      vadRef.current = null;
    };
  }, []);

  // Toggle start/pause on `active`. If the VAD instance isn't ready
  // yet (cold-start race) we just no-op; the first speak() may miss
  // barge-in until the worklet loads.
  useEffect(() => {
    const vad = vadRef.current;
    if (!vad) return;
    if (active) {
      warmupUntilRef.current = Date.now() + 600;
      vad.start();
    } else {
      vad.pause();
    }
  }, [active]);
}
