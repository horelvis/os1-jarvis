import { useEffect, useRef } from "react";
import type { WaveMode } from "../core/types";

// Voice bars visualizer. 40 vertical capsules arranged along a single
// horizontal centerline. Each bar's height = base envelope (gaussian
// across the bar index, so the middle bars are taller) modulated by
// a per-mode oscillation + a per-bar phase jitter. This is the
// "Siri/Alexa voice" idiom — instantly readable as voice presence.
//
// Mode parameters:
//   amp          peak height fraction of canvas height
//   speed        how fast the oscillation phase advances
//   jitter       per-bar phase chaos (higher = more lively / fragmented)
//   stroke       global alpha of the bar fill
//   envSigma     bell-curve width (smaller = sharper center peak)
//   baseHeight   minimum height fraction so bars never disappear
//
// Voice playback can later drive the bars via Web Audio AnalyserNode —
// the same `mode` prop will keep working, but `speaking` will get
// replaced with a real-amplitude path. For now the deterministic
// patterns read clearly as "thinking" / "speaking" without that wiring.

interface ModeParams {
  amp: number;
  speed: number;
  jitter: number;
  stroke: number;
  envSigma: number;
  baseHeight: number;
}

const MODES: Record<WaveMode, ModeParams> = {
  idle:      { amp: 0.10, speed: 0.6, jitter: 0.25, stroke: 0.55, envSigma: 0.30, baseHeight: 0.05 },
  listening: { amp: 0.35, speed: 1.0, jitter: 0.50, stroke: 0.85, envSigma: 0.40, baseHeight: 0.08 },
  thinking:  { amp: 0.45, speed: 1.4, jitter: 0.55, stroke: 0.90, envSigma: 0.32, baseHeight: 0.08 },
  speaking:  { amp: 0.85, speed: 2.2, jitter: 0.75, stroke: 0.95, envSigma: 0.45, baseHeight: 0.10 },
};

const N_BARS = 40;

// Pre-computed per-bar phase offsets — deterministic but irrational
// step (~0.47 * 2π) so neighbouring bars don't oscillate in lockstep.
const PHASES: number[] = Array.from(
  { length: N_BARS },
  (_, i) => (i * 2.95) % (2 * Math.PI),
);

// Bell envelope across bar index: centre bars taller.
function envelope(i: number, sigma: number): number {
  const x = (i / (N_BARS - 1) - 0.5) * 2; // -1..1
  return Math.exp(-(x * x) / (2 * sigma * sigma));
}

interface WaveProps {
  mode: WaveMode;
  className?: string;
}

export function Wave({ mode, className }: WaveProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const modeRef = useRef<WaveMode>(mode);

  // Update mode without re-running the effect (which would tear down
  // the animation and re-create the canvas).
  useEffect(() => { modeRef.current = mode; }, [mode]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const dpr = Math.min(window.devicePixelRatio, 2);
    const resize = () => {
      const rect = canvas.getBoundingClientRect();
      canvas.width = rect.width * dpr;
      canvas.height = rect.height * dpr;
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.scale(dpr, dpr);
    };
    resize();
    window.addEventListener("resize", resize);

    let frameId = 0;
    let running = true;

    const frame = () => {
      if (!running) return;
      const params = MODES[modeRef.current];
      const t = performance.now() / 1000;

      const rect = canvas.getBoundingClientRect();
      const w = rect.width;
      const h = rect.height;
      const baseline = h / 2;
      const maxAmpPx = h * 0.46;

      // Bars span ~80% of the width, edges leave breathing room.
      const span = w * 0.82;
      const barWidth = Math.max(2, span * 0.012);
      const step = span / N_BARS;
      const startX = (w - span) / 2 + step / 2;

      ctx.clearRect(0, 0, w, h);
      ctx.strokeStyle = `rgba(255,255,255,${params.stroke})`;
      ctx.lineWidth = barWidth;
      ctx.lineCap = "round";

      for (let i = 0; i < N_BARS; i++) {
        const env = envelope(i, params.envSigma);
        const phase = PHASES[i];

        // Slow primary oscillation (0..1 via |sin|).
        const wave = Math.abs(
          Math.sin(t * params.speed * Math.PI + phase),
        );
        // Fast jitter — secondary sine at a different freq + phase
        // so bars don't sync into a single peak.
        const jit =
          params.jitter *
          (0.5 + 0.5 * Math.sin(t * (params.speed * 3.7) + phase * 1.9));

        // Combine: envelope-weighted amp + a non-zero baseline so the
        // bar never collapses to a point (looks alive even at idle).
        const norm =
          params.baseHeight +
          env * params.amp * (0.4 * wave + 0.6 * jit);

        const barHeight = Math.min(1, norm) * maxAmpPx * 2;
        // Account for round caps adding lineWidth/2 at each end.
        const half = Math.max(0, barHeight / 2 - barWidth / 2);
        const x = startX + i * step;

        ctx.beginPath();
        ctx.moveTo(x, baseline - half);
        ctx.lineTo(x, baseline + half);
        ctx.stroke();
      }

      frameId = requestAnimationFrame(frame);
    };
    frameId = requestAnimationFrame(frame);

    return () => {
      running = false;
      cancelAnimationFrame(frameId);
      window.removeEventListener("resize", resize);
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      className={className}
      style={{
        width: "100%",
        height: "100%",
        display: "block",
        pointerEvents: "none",
      }}
    />
  );
}
