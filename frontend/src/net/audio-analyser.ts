// Singleton bridge between the TTS player (net/tts.ts) and the Wave
// visualizer (components/Wave.tsx). The player publishes its
// AnalyserNode while audio is active; the visualizer samples it
// inside its requestAnimationFrame loop.
//
// No React state involved on purpose — the visualizer pulls fresh
// FFT data 60×/s and the publisher just flips a module-level slot.
// Going through a store would mean a re-render per frame.

// Web Audio's getByteFrequencyData wants `Uint8Array<ArrayBuffer>`
// specifically (not the default `ArrayBufferLike`), so allocate the
// underlying buffer explicitly to keep TS strict happy.
type ByteBuf = Uint8Array<ArrayBuffer>;

let activeAnalyser: AnalyserNode | null = null;
let freqScratch: ByteBuf | null = null;

function makeScratch(n: number): ByteBuf {
  return new Uint8Array(new ArrayBuffer(n)) as ByteBuf;
}

export function setActiveAnalyser(a: AnalyserNode | null): void {
  activeAnalyser = a;
  freqScratch = a ? makeScratch(a.frequencyBinCount) : null;
}

// Returns frequency-domain magnitudes for the latest audio frame
// (Uint8, 0..255), or null if no audio is currently playing. The
// caller MUST NOT retain the array — it's a shared scratch buffer
// reused on every call.
export function sampleFrequencyData(): Uint8Array | null {
  if (!activeAnalyser || !freqScratch) return null;
  activeAnalyser.getByteFrequencyData(freqScratch);
  return freqScratch;
}
