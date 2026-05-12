/**
 * Samantha Wave — the horizontal line that *is* Samantha.
 *
 * One line crossing the screen, composed from three sines at
 * different frequencies for an organic feel. Lerps smoothly
 * between four modes:
 *   - idle:      near-still, micro-undulation (breathing)
 *   - listening: medium amplitude, natural rhythm
 *   - thinking:  small but faster, "considering"
 *   - speaking:  wide and organic
 *
 * Canvas 2D, no dependencies. The mockup's audio reactivity
 * was decorative; per CLAUDE.md §2.8 the real audio data never
 * comes from the browser, so this stays as a state-driven motif.
 */

export function createSamanthaWave(canvas) {
  const ctx = canvas.getContext('2d');
  let mode = 'idle';
  let running = true;
  let visible = true;
  let lastTime = performance.now();

  // Per-mode targets:
  //   amp        — overall vertical scale of spikes
  //   burstRate  — new spikes per second
  //   life       — how long each spike lives (seconds)
  //   spread     — sigma of the Gaussian that places spikes around the
  //                center (small = tight cluster, large = wider). Spikes
  //                near the edges are also attenuated by `centerWindow`
  //                in draw(), so the cluster fades smoothly to flat.
  const modes = {
    idle:      { amp: 0.05, burstRate: 0.5,  life: 1.2,  spread: 0.05 },
    listening: { amp: 0.40, burstRate: 6.0,  life: 0.7,  spread: 0.16 },
    thinking:  { amp: 0.22, burstRate: 16.0, life: 0.35, spread: 0.13 },
    speaking:  { amp: 1.00, burstRate: 26.0, life: 0.55, spread: 0.20 },
  };
  let curAmp = modes.idle.amp;
  let curBurst = modes.idle.burstRate;
  let curLife = modes.idle.life;
  let curSpread = modes.idle.spread;

  // Active spikes — each is a thin, signed peak that grows in,
  // sits, then fades. Drawn as a sum of narrow Gaussians along the
  // polyline so the resulting line crosses the baseline cleanly
  // between peaks (like a real audio waveform).
  /** @type {{x:number, sign:number, height:number, age:number, life:number}[]} */
  const spikes = [];
  let nextBurstIn = 0;
  let lastSign = 1;

  function resize() {
    const dpr = Math.min(window.devicePixelRatio, 2);
    const rect = canvas.getBoundingClientRect();
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.scale(dpr, dpr);
  }
  resize();
  window.addEventListener('resize', resize);

  function addSpike() {
    // Gaussian distribution centered on x=0.5 (Box–Muller). Sigma is
    // small so spikes cluster tightly in the middle; the rare outlier
    // is then further softened by the centerWindow envelope at draw time.
    const r = Math.sqrt(-2 * Math.log(Math.max(1e-6, Math.random())));
    const theta = 2 * Math.PI * Math.random();
    const z = r * Math.cos(theta);
    const xPos = Math.min(0.98, Math.max(0.02, 0.5 + z * curSpread));

    // Mostly alternate signs (so the polyline crosses zero between
    // peaks), but allow occasional same-sign for variation.
    const sign = Math.random() < 0.78 ? -lastSign : lastSign;
    lastSign = sign;

    // Heights skewed toward small with occasional big ones — like
    // syllable stress in real speech.
    const heightRoll = Math.random();
    const height = 0.18 + heightRoll * heightRoll * 0.82;

    spikes.push({
      x: xPos,
      sign,
      height,
      age: 0,
      life: curLife * (0.6 + Math.random() * 0.8),
    });
  }

  function spikeEnvelope(age, life) {
    // Fast attack (0..12% of life), then a smooth decay.
    const t = age / life;
    if (t < 0.12) return t / 0.12;
    const k = (t - 0.12) / 0.88;
    return Math.max(0, 1 - k * k);
  }

  function step(dt) {
    const target_p = modes[mode] || modes.idle;
    const lerp = 1 - Math.pow(0.001, dt);
    curAmp += (target_p.amp - curAmp) * lerp;
    curBurst += (target_p.burstRate - curBurst) * lerp;
    curLife += (target_p.life - curLife) * lerp;
    curSpread += (target_p.spread - curSpread) * lerp;

    nextBurstIn -= dt;
    let safety = 0;
    while (nextBurstIn <= 0 && safety++ < 16) {
      addSpike();
      nextBurstIn += 1 / Math.max(0.1, curBurst);
    }

    for (let i = spikes.length - 1; i >= 0; i--) {
      spikes[i].age += dt;
      if (spikes[i].age >= spikes[i].life) spikes.splice(i, 1);
    }
  }

  function draw() {
    if (!running) return;
    const now = performance.now();
    const dt = Math.min(0.05, (now - lastTime) / 1000);
    lastTime = now;

    if (visible) {
      step(dt);

      const rect = canvas.getBoundingClientRect();
      const w = rect.width;
      const h = rect.height;
      const cy = h / 2;
      const maxAmp = h * 0.48;
      // Spike width in pixels (sigma of its Gaussian footprint).
      // Smaller = sharper / more peaked.
      const sigma = 2.6;
      const twoSigma2 = 2 * sigma * sigma;

      ctx.clearRect(0, 0, w, h);
      ctx.lineWidth = 1.8;
      ctx.strokeStyle = 'rgba(255, 255, 255, 0.94)';
      ctx.lineCap = 'round';
      ctx.lineJoin = 'round';
      ctx.beginPath();

      // Pre-compute spike positions in pixels + their current envelope
      // so the inner loop doesn't redo it per sample. The spatial
      // `centerWindow` factor makes peaks taller in the center and
      // softer toward the edges — so the cluster fades to flat baseline
      // even if a spike drifts wide.
      const N = spikes.length;
      const px = new Float32Array(N);
      const wt = new Float32Array(N);
      for (let i = 0; i < N; i++) {
        const sp = spikes[i];
        px[i] = sp.x * w;
        const d = (sp.x - 0.5) * 2; // [-1, 1] normalized distance from center
        // Smooth Gaussian-ish window: 1 at center, 0 at edges, knee around |d|≈0.7
        const centerWindow = Math.exp(-d * d * 4.5);
        wt[i] = sp.sign * sp.height * spikeEnvelope(sp.age, sp.life) * centerWindow;
      }

      const step_px = 0.75;
      for (let x = 0; x <= w; x += step_px) {
        let yOff = 0;
        for (let i = 0; i < N; i++) {
          const dx = x - px[i];
          // Skip far-away spikes for perf (well past 3σ).
          if (dx > 12 || dx < -12) continue;
          yOff += wt[i] * Math.exp(-(dx * dx) / twoSigma2);
        }
        const y = cy - yOff * maxAmp * curAmp;
        if (x === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();
    }

    requestAnimationFrame(draw);
  }
  draw();

  return {
    setMode(m) { mode = m; },
    setVisible(v) { visible = v; },
    resize,
    destroy() { running = false; },
  };
}


/**
 * Decorative audio visualizer used during calibration / voiceprint
 * screens. Accepts a synthetic intensity (0..1) since the real mic
 * data never reaches the browser (CLAUDE.md §2.8).
 */
export function createAudioViz(canvas) {
  const ctx = canvas.getContext('2d');
  let running = true;
  let phase = 0;
  let simIntensity = 0.1;
  let targetIntensity = 0.1;

  function draw() {
    if (!running) return;
    const w = canvas.width;
    const h = canvas.height;
    ctx.clearRect(0, 0, w, h);

    simIntensity += (targetIntensity - simIntensity) * 0.08;
    const noise = (Math.sin(phase * 0.7) * 0.3 + Math.sin(phase * 2.3) * 0.15) * 0.05;
    const vol = Math.max(0, simIntensity + noise);

    const amp = 4 + vol * h * 0.6;
    const cy = h / 2;

    ctx.lineWidth = 2.5;
    ctx.strokeStyle = `rgba(255, 255, 255, ${0.4 + vol * 1.5})`;
    ctx.lineCap = 'round';
    ctx.beginPath();
    for (let x = 0; x < w; x += 2) {
      const t = (x / w) * Math.PI * 4 + phase;
      const y = cy + Math.sin(t) * amp * (0.5 + 0.5 * Math.sin((x / w) * Math.PI));
      if (x === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();

    phase += 0.04 + vol * 0.3;
    requestAnimationFrame(draw);
  }
  draw();

  return {
    stop() { running = false; },
    setIntensity(v) { targetIntensity = v; },
  };
}
