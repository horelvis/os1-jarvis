// Plays the backend's /speak response.
//
// The happy path is raw int16 PCM at 24 kHz mono streamed over
// chunked transfer encoding (Content-Type: audio/pcm). We decode it
// chunk by chunk via Web Audio API, scheduling each AudioBuffer
// back-to-back so audio starts ~0.5 s after the POST and continues
// seamlessly while the backend keeps streaming from vllm-omni.
//
// The fallback path is a complete WAV (audio/wav) returned by the
// tone synthesizer when no real TTS backend is reachable. We play it
// via HTMLAudioElement so the UI never hangs on a degraded backend.

export async function speak(text: string): Promise<void> {
  const res = await fetch("/speak", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, voice: "default" }),
  });
  if (!res.ok || !res.body) return;

  const contentType = res.headers.get("Content-Type") ?? "";

  // Fallback (tone WAV). Old-style blob playback.
  if (contentType.startsWith("audio/wav")) {
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const audio = new Audio(url);
    await new Promise<void>((resolve) => {
      audio.addEventListener("ended", () => resolve(), { once: true });
      audio.addEventListener("error", () => resolve(), { once: true });
      audio.play().catch(() => resolve());
    });
    URL.revokeObjectURL(url);
    return;
  }

  // Streaming PCM path.
  const sampleRate = parseInt(
    res.headers.get("X-TTS-Sample-Rate") ?? "24000",
    10,
  );

  const audioCtx = new AudioContext({ sampleRate });
  // Browsers gate AudioContext on a user gesture; speak() is called
  // from a button/keypress handler so resume should always succeed.
  if (audioCtx.state === "suspended") await audioCtx.resume();

  let scheduledEnd = audioCtx.currentTime;
  let lastSource: AudioBufferSourceNode | null = null;
  const reader = res.body.getReader();
  // Hold one trailing byte across chunks if the chunk boundary lands
  // mid-int16-sample. Rare but possible with HTTP chunked transfer.
  let leftover: Uint8Array | null = null;

  // Read-decode-schedule loop. Each iteration appends one AudioBuffer
  // to the playback queue at scheduledEnd; subsequent chunks land
  // immediately after with no gap.
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    let bytes: Uint8Array;
    if (leftover && leftover.length > 0) {
      bytes = new Uint8Array(leftover.length + value.length);
      bytes.set(leftover, 0);
      bytes.set(value, leftover.length);
      leftover = null;
    } else {
      bytes = value;
    }

    const evenLength = bytes.length - (bytes.length % 2);
    if (evenLength < bytes.length) {
      leftover = bytes.slice(evenLength);
    }
    if (evenLength === 0) continue;

    // Copy into a fresh buffer so the Int16Array view is aligned and
    // independent of the network chunk's lifetime.
    const aligned = bytes.slice(0, evenLength);
    const int16 = new Int16Array(
      aligned.buffer,
      aligned.byteOffset,
      evenLength / 2,
    );

    const float32 = new Float32Array(int16.length);
    for (let i = 0; i < int16.length; i++) {
      float32[i] = int16[i] / 32768;
    }

    const buffer = audioCtx.createBuffer(1, float32.length, sampleRate);
    buffer.copyToChannel(float32, 0);
    const source = audioCtx.createBufferSource();
    source.buffer = buffer;
    source.connect(audioCtx.destination);
    const startAt = Math.max(audioCtx.currentTime, scheduledEnd);
    source.start(startAt);
    scheduledEnd = startAt + buffer.duration;
    lastSource = source;
  }

  // Wait for the scheduled playback to actually finish so the
  // caller's `await speak(...)` reflects real playback completion.
  // setTimeout against the accumulated scheduledEnd is more reliable
  // than the "ended" event of the last source: the listener is
  // registered after `source.start()` and can race with a very short
  // final chunk that ends before the handler is attached.
  const remainingS = Math.max(0, scheduledEnd - audioCtx.currentTime);
  if (remainingS > 0) {
    await new Promise<void>((resolve) =>
      // Small +100 ms tail so the OS audio buffer fully drains before
      // the caller restarts the mic (mic-feedback guard).
      setTimeout(resolve, remainingS * 1000 + 100),
    );
  }
  // Keep lastSource referenced until close so it isn't GC'd mid-play.
  void lastSource;
  await audioCtx.close();
}
