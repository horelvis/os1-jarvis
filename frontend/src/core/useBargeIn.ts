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

  // Lazy-create the MicVAD instance once. The .new() returns a promise
  // and may take ~300 ms (downloading the ONNX model + spawning the
  // audio worklet); we live with that on the very first activation.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const vad = await MicVAD.new({
        onSpeechStart: () => {
          cbRef.current();
        },
        // Default model + threshold work well enough for v1. Tune if
        // false positives become a problem (positiveSpeechThreshold,
        // negativeSpeechThreshold, redemptionFrames, etc.).
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
      vad.start();
    } else {
      vad.pause();
    }
  }, [active]);
}
