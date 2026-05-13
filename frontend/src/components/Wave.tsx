import { useEffect, useRef } from "react";
import type { WaveMode } from "../core/types";

// Each pulse is a gaussian-windowed cosine that travels horizontally
// from x=0.5 outward. Multiple modes change the emission rate /
// amplitude / propagation speed / lifetime — the formula is identical.

interface Pulse {
  tEmit: number;
  dir: 1 | -1;
  amp0: number;
  sigma: number;
  freq: number;
}

interface ModeParams {
  pulseRatePerSec: number;
  amp0: number;
  sigma: number;
  freq: number;
  speedWidthsPerSec: number;
  lifetimeSec: number;
  strokeOpacity: number;
}

const MODES: Record<WaveMode, ModeParams> = {
  idle:      { pulseRatePerSec: 0.1, amp0: 0.04, sigma: 0.10, freq: 3,  speedWidthsPerSec: 0.15, lifetimeSec: 1.5, strokeOpacity: 0.85 },
  listening: { pulseRatePerSec: 0.5, amp0: 0.30, sigma: 0.20, freq: 7,  speedWidthsPerSec: 0.25, lifetimeSec: 1.5, strokeOpacity: 0.95 },
  thinking:  { pulseRatePerSec: 2.0, amp0: 0.20, sigma: 0.15, freq: 10, speedWidthsPerSec: 0.25, lifetimeSec: 0.8, strokeOpacity: 0.95 },
  speaking:  { pulseRatePerSec: 4.0, amp0: 0.80, sigma: 0.20, freq: 10, speedWidthsPerSec: 0.25, lifetimeSec: 1.2, strokeOpacity: 0.95 },
};

interface WaveProps {
  mode: WaveMode;
  className?: string;
}

export function Wave({ mode, className }: WaveProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const modeRef = useRef<WaveMode>(mode);

  // Refresh the live mode without re-running the animation effect —
  // tearing down requestAnimationFrame on every mode change would drop
  // in-flight pulses mid-flight.
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

    const pulses: Pulse[] = [];
    let lastEmit = performance.now();
    let frameId = 0;
    let running = true;

    const frame = () => {
      if (!running) return;
      const now = performance.now();
      const params = MODES[modeRef.current];

      const interval = 1000 / params.pulseRatePerSec;
      if (now - lastEmit >= interval) {
        for (const dir of [-1, 1] as const) {
          pulses.push({
            tEmit: now,
            dir,
            amp0: params.amp0 * (0.85 + Math.random() * 0.3),
            sigma: params.sigma,
            freq: params.freq,
          });
        }
        lastEmit = now;
      }

      for (let i = pulses.length - 1; i >= 0; i--) {
        const age = (now - pulses[i].tEmit) / 1000;
        if (age > params.lifetimeSec) pulses.splice(i, 1);
      }

      const rect = canvas.getBoundingClientRect();
      const w = rect.width;
      const h = rect.height;
      const baseline = h / 2;
      const maxAmpPx = h * 0.45;

      ctx.clearRect(0, 0, w, h);
      ctx.strokeStyle = `rgba(255,255,255,${params.strokeOpacity})`;
      ctx.lineWidth = 0.6;
      ctx.lineCap = "round";
      ctx.lineJoin = "round";
      ctx.beginPath();

      const samples = Math.max(120, Math.floor(w * 0.6));
      for (let i = 0; i <= samples; i++) {
        const xn = i / samples;
        let y = baseline;
        for (const p of pulses) {
          const age = (now - p.tEmit) / 1000;
          const center = 0.5 + p.dir * age * params.speedWidthsPerSec;
          const ampScale = Math.max(0, 1 - age / params.lifetimeSec);
          const amp = p.amp0 * ampScale * maxAmpPx;
          const dx = xn - center;
          const env = Math.exp(-(dx * dx) / (p.sigma * p.sigma));
          const osc = Math.cos(2 * Math.PI * p.freq * dx);
          y -= amp * env * osc;
        }
        const px = xn * w;
        if (i === 0) ctx.moveTo(px, y);
        else ctx.lineTo(px, y);
      }
      ctx.stroke();

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
      style={{ width: "100%", height: "100%", display: "block" }}
    />
  );
}
