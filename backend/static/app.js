/**
 * Samantha — main app.
 *
 * Screen state machine + event wiring + TTS playback + chat over
 * WebSocket. The browser never touches the microphone (CLAUDE.md
 * §2.8); the mic button sends a `listen` message and the backend
 * supplies the transcription.
 *
 * Phase 3 scope: wire mockup interactions to real backend calls.
 * Phase 5 will swap the mock /transcribe and /speak for real STT/TTS.
 */

import { createOS1Loader } from '/static/os1-loader.js';
import { createSamanthaWave, createAudioViz } from '/static/samantha-wave.js';
import { WSClient } from '/static/ws-client.js';


const QUESTIONS = [
  '¿Cómo te llamo?',
  '¿Cómo estás hoy?',
  '¿Qué te gusta hacer cuando tienes tiempo para ti?',
  'Cuéntame algo que te haya hecho ilusión últimamente. Algo pequeño vale.',
  '¿Y algo que te esté rondando la cabeza estos días?',
  'Una última: conmigo, ¿prefieres que sea más directa o más cuidadosa?',
];

const state = {
  currentQuestion: 0,
  answers: [],
  userName: null,
  micActive: false,
  micContext: null, // 'onboarding' | 'conversation'
};


// ============================================================
// Three.js loaders + Samantha waves
// ============================================================

const loaders = {};
const waves = {};

function initLoaders() {
  document.querySelectorAll('[data-loader]').forEach((el) => {
    const key = el.dataset.loader;
    const startTransformed = el.dataset.startTransformed === 'true';
    loaders[key] = createOS1Loader(el, { startTransformed });
    loaders[key].setVisible(false);
  });
}

function initWaves() {
  document.querySelectorAll('[data-wave]').forEach((el) => {
    const key = el.dataset.wave;
    waves[key] = createSamanthaWave(el);
  });
}

function updateVisuals() {
  const activeScreen = document.querySelector('.screen.active');
  if (!activeScreen) return;
  for (const key in loaders) {
    const el = document.querySelector(`[data-loader="${key}"]`);
    if (el && activeScreen.contains(el)) {
      loaders[key].setVisible(true);
      loaders[key].resize();
    } else {
      loaders[key].setVisible(false);
    }
  }
  for (const key in waves) {
    const el = document.querySelector(`[data-wave="${key}"]`);
    if (el && activeScreen.contains(el)) {
      waves[key].setVisible(true);
      waves[key].resize();
    } else {
      waves[key].setVisible(false);
    }
  }
}


// ============================================================
// Screen routing
// ============================================================

function goto(id) {
  document.querySelectorAll('.screen').forEach((s) => s.classList.remove('active'));
  document.getElementById(id).classList.add('active');
  document.getElementById('state-label').textContent =
    'pantalla: ' + id.replace('screen-', '');
  // Wait one tick so the new container has its layout size
  setTimeout(updateVisuals, 50);
}


// ============================================================
// TTS — calls backend /speak, plays the WAV.
// In mock mode the WAV is a short tone; in Phase 5 it'll be Piper.
// The wave on the active screen flips to 'speaking' while playing.
// ============================================================

let currentTTS = null;

async function speak(text) {
  const activeScreen = document.querySelector('.screen.active');
  const activeWaves = [];
  if (activeScreen) {
    activeScreen.querySelectorAll('[data-wave]').forEach((el) => {
      const w = waves[el.dataset.wave];
      if (w) {
        w.setMode('speaking');
        activeWaves.push(w);
      }
    });
  }

  if (currentTTS) {
    try { currentTTS.pause(); } catch (e) {}
    currentTTS = null;
  }

  try {
    const resp = await fetch('/speak', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, voice: 'default' }),
    });
    if (!resp.ok) throw new Error('speak failed: ' + resp.status);
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const audio = new Audio(url);
    currentTTS = audio;
    await new Promise((resolve) => {
      audio.addEventListener('ended', resolve, { once: true });
      audio.addEventListener('error', resolve, { once: true });
      audio.play().catch(resolve);
    });
    URL.revokeObjectURL(url);
  } catch (e) {
    console.warn('[speak] failed, continuing silently:', e);
  } finally {
    activeWaves.forEach((w) => w.setMode('idle'));
    currentTTS = null;
  }
}


// ============================================================
// WebSocket
// ============================================================

const ws = new WSClient(`ws://${location.host}/ws`);


// ============================================================
// Mic — never touches the browser microphone (CLAUDE.md §2.8).
// Clicking the mic asks the backend for a (mock) listen turn.
// ============================================================

function setMicVisual(btnId, active) {
  const btn = document.getElementById(btnId);
  if (!btn) return;
  if (active) btn.classList.add('recording');
  else btn.classList.remove('recording');
}

async function toggleMic() {
  const promptEl = document.getElementById('voice-prompt');
  if (state.micActive) return;
  state.micActive = true;
  state.micContext = 'onboarding';
  setMicVisual('mic-btn', true);
  if (promptEl) promptEl.textContent = 'escuchando...';
  try {
    const text = await ws.listen();
    const input = document.getElementById('answer-input');
    if (input) input.value = text;
  } catch (e) {
    console.warn('listen failed:', e);
  } finally {
    state.micActive = false;
    setMicVisual('mic-btn', false);
    if (promptEl) promptEl.textContent = '';
  }
}

async function toggleConvMic() {
  if (state.micActive) return;
  state.micActive = true;
  state.micContext = 'conversation';
  setMicVisual('conv-mic', true);
  setConvState('listening');
  try {
    const text = await ws.listen();
    const input = document.getElementById('conv-input');
    if (input) input.value = text;
    await sendConvMessage();
  } catch (e) {
    console.warn('listen failed:', e);
    setConvState('idle');
  } finally {
    state.micActive = false;
    setMicVisual('conv-mic', false);
  }
}


// ============================================================
// Boot + Calibration
// ============================================================

function init() {
  goto('screen-boot');
  setTimeout(() => goto('screen-calibration'), 2800);
}

let calViz = null;

async function beginCalibration() {
  const btn = document.getElementById('cal-btn');
  btn.style.display = 'none';

  const setStatus = (txt) => {
    const el = document.getElementById('cal-status');
    el.style.opacity = '0';
    setTimeout(() => { el.textContent = txt; el.style.opacity = '1'; }, 300);
  };
  const setTitle = (txt) => {
    const el = document.getElementById('cal-stage-title');
    el.style.opacity = '0';
    setTimeout(() => {
      el.textContent = txt;
      el.style.transition = 'opacity 0.6s';
      el.style.opacity = '1';
    }, 300);
  };

  const viz = document.getElementById('cal-viz');
  viz.classList.add('show');
  calViz = createAudioViz(viz);

  loaders.calibration.setActive(false);
  setTitle('escuchando el ambiente');
  setStatus('No digas nada, solo un momento...');
  speak('Voy a escuchar el silencio un momento.');
  calViz.setIntensity(0.05);

  setTimeout(() => {
    setTitle('ahora tu voz');
    setStatus('Dime algo. Lo que quieras');
    speak('Ahora dime algo. Lo que quieras.');
    loaders.calibration.setActive(true);
    calViz.setIntensity(0.45);

    setTimeout(() => {
      setStatus('Te oigo bien');
      loaders.calibration.setActive(false);
      calViz.setIntensity(0.15);
      setTimeout(() => {
        if (calViz) calViz.stop();
        viz.classList.remove('show');
        goto('screen-voiceprint');
      }, 1800);
    }, 4000);
  }, 4500);
}


// ============================================================
// Voiceprint
// ============================================================

let vpViz = null;

async function beginVoiceprint() {
  const btn = document.getElementById('vp-btn');
  btn.style.display = 'none';

  const setStatus = (txt) => {
    const el = document.getElementById('vp-status');
    el.style.opacity = '0';
    setTimeout(() => { el.textContent = txt; el.style.opacity = '1'; }, 300);
  };

  document.getElementById('vp-phrase').classList.add('show');
  const viz = document.getElementById('vp-viz');
  viz.classList.add('show');
  vpViz = createAudioViz(viz);
  vpViz.setIntensity(0.05);

  setStatus('Cuando estés, di la frase con calma');
  await speak('Repite la frase cuando estés.');

  document.getElementById('vp-rec').classList.add('show');
  loaders.voiceprint.setActive(true);
  vpViz.setIntensity(0.5);

  setTimeout(() => {
    document.getElementById('vp-rec').classList.remove('show');
    loaders.voiceprint.setActive(false);
    vpViz.setIntensity(0.1);
    setStatus('Te recuerdo');

    setTimeout(() => {
      loaders.voiceprint.transform(true);
      const flash = document.getElementById('flash');
      flash.classList.add('fire');
      setTimeout(() => flash.classList.remove('fire'), 1200);
    }, 800);

    setTimeout(async () => {
      if (vpViz) vpViz.stop();
      goto('screen-greet');
      setTimeout(async () => {
        await speak('Hola. Estoy aquí.');
        document.getElementById('greet-continue').style.opacity = '1';
      }, 1200);
    }, 2800);
  }, 4000);
}


// ============================================================
// Onboarding questions
// ============================================================

function startOnboarding() {
  document.getElementById('greet-continue').style.opacity = '0';
  setTimeout(() => {
    goto('screen-question');
    showQuestion(0);
  }, 600);
}

function showQuestion(idx) {
  state.currentQuestion = idx;
  document.querySelectorAll('#progress .progress-dot').forEach((d, i) => {
    d.className = 'progress-dot';
    if (i < idx) d.classList.add('done');
    if (i === idx) d.classList.add('current');
  });
  const qText = document.getElementById('question-text');
  qText.style.opacity = '0';
  setTimeout(() => {
    qText.textContent = QUESTIONS[idx];
    qText.style.transition = 'opacity 0.8s';
    qText.style.opacity = '1';
    document.getElementById('answer-input').value = '';
    document.getElementById('answer-input').focus();
    setTimeout(() => speak(QUESTIONS[idx]), 400);
  }, 400);
}

function submitAnswer() {
  const val = document.getElementById('answer-input').value.trim();
  if (!val) return;
  state.answers[state.currentQuestion] = val;
  if (state.currentQuestion === 0) state.userName = val.split(' ')[0];
  advance();
}

function skipQuestion() {
  state.answers[state.currentQuestion] = null;
  advance();
}

function advance() {
  if (state.currentQuestion < QUESTIONS.length - 1) {
    showQuestion(state.currentQuestion + 1);
  } else {
    goto('screen-generating');
    simulateAnalysis();
  }
}

function simulateAnalysis() {
  const messages = ['Procesando lo que me has contado', 'Calibrando tono', 'Casi lista'];
  let i = 0;
  const el = document.getElementById('generating-text');
  el.textContent = messages[0];
  loaders.generating.setActive(true);

  const interval = setInterval(() => {
    i++;
    if (i >= messages.length) {
      clearInterval(interval);
      loaders.generating.setActive(false);
      loaders.generating.transform(true);
      setTimeout(showWelcome, 2000);
      return;
    }
    el.style.opacity = '0';
    setTimeout(() => {
      el.textContent = messages[i];
      el.style.opacity = '1';
    }, 400);
  }, 2200);
}

function showWelcome() {
  const name = state.userName || 'tú';
  document.getElementById('welcome-text').innerHTML =
    `Hola, ${escapeHtml(name)}.<br><em style="font-size: 0.85em;">Soy Samantha.</em>`;
  goto('screen-welcome');
  setTimeout(async () => {
    await speak(`Hola, ${name}. Soy Samantha. Encantada de conocerte.`);
    document.getElementById('welcome-continue').style.opacity = '1';
  }, 800);
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}


// ============================================================
// Conversation
// ============================================================

function startConversation() {
  updateTime();
  setInterval(updateTime, 30000);
  const name = state.userName || '';
  setTimeout(async () => {
    const opener = `Bueno... aquí estamos. ${name ? '¿Por dónde quieres empezar, ' + name + '?' : '¿Por dónde quieres empezar?'}`;
    addMessage('samantha', opener);
    await speak(opener);
  }, 600);

  const input = document.getElementById('conv-input');
  input.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') sendConvMessage();
  });
}

function updateTime() {
  const d = new Date();
  const h = d.getHours().toString().padStart(2, '0');
  const m = d.getMinutes().toString().padStart(2, '0');
  document.getElementById('time-now').textContent = `${h}:${m}`;
}

function addMessage(who, text) {
  const t = document.getElementById('transcript');
  const div = document.createElement('div');
  div.className = 'msg msg-' + who;
  div.textContent = text;
  t.appendChild(div);
  t.scrollTop = t.scrollHeight;
  return div;
}

function setConvState(s) {
  const labels = { idle: 'disponible', listening: 'escuchando', thinking: 'pensando', speaking: 'hablando' };
  document.getElementById('conv-state').textContent = labels[s] || s;
  if (waves.conv) waves.conv.setMode(s);
}

async function sendConvMessage() {
  const input = document.getElementById('conv-input');
  const val = input.value.trim();
  if (!val) return;
  addMessage('user', val);
  input.value = '';
  setConvState('thinking');

  const bubble = addMessage('samantha', '');
  let started = false;

  try {
    const { reply } = await ws.chat(val, (token) => {
      if (!started) {
        started = true;
        setConvState('speaking');
      }
      bubble.textContent += token;
      const t = document.getElementById('transcript');
      t.scrollTop = t.scrollHeight;
    });
    await speak(reply);
  } catch (e) {
    console.warn('chat failed:', e);
    bubble.textContent = 'Algo no ha ido bien. Vuelve a intentarlo en un momento.';
  } finally {
    setConvState('idle');
  }
}


// ============================================================
// Debug helpers (visible in dev, hidden in kiosk)
// ============================================================

function restart() {
  state.currentQuestion = 0;
  state.answers = [];
  state.userName = null;
  document.getElementById('transcript').innerHTML = '';

  const calBtn = document.getElementById('cal-btn');
  if (calBtn) { calBtn.style.display = ''; calBtn.textContent = 'empezar'; }
  document.getElementById('cal-status').textContent = 'Pulsa para empezar';
  document.getElementById('cal-stage-title').textContent = 'déjame escucharte';
  document.getElementById('cal-viz').classList.remove('show');
  if (calViz) { calViz.stop(); calViz = null; }

  const vpBtn = document.getElementById('vp-btn');
  if (vpBtn) { vpBtn.style.display = ''; vpBtn.textContent = 'grabar mi voz'; }
  document.getElementById('vp-status').textContent = 'Di la frase con tu voz natural';
  document.getElementById('vp-rec').classList.remove('show');
  document.getElementById('vp-phrase').classList.remove('show');
  document.getElementById('vp-viz').classList.remove('show');
  if (vpViz) { vpViz.stop(); vpViz = null; }

  for (const key in loaders) {
    loaders[key].reset();
    loaders[key].setActive(false);
  }
  for (const key in waves) waves[key].setMode('idle');
  init();
}

function skipToConv() {
  state.userName = state.userName || 'amigo';
  document.getElementById('transcript').innerHTML = '';
  goto('screen-conversation');
  startConversation();
}


// ============================================================
// Boot — wire it all up
// ============================================================

initLoaders();
initWaves();

// Expose handlers used by inline onclick= in index.html
window.beginCalibration = beginCalibration;
window.beginVoiceprint = beginVoiceprint;
window.startOnboarding = startOnboarding;
window.submitAnswer = submitAnswer;
window.skipQuestion = skipQuestion;
window.toggleMic = toggleMic;
window.toggleConvMic = toggleConvMic;
window.startConversation = startConversation;
window.restart = restart;
window.skipToConv = skipToConv;
window.goto = goto;

document.getElementById('answer-input').addEventListener('keypress', (e) => {
  if (e.key === 'Enter') submitAnswer();
});

window.addEventListener('resize', () => {
  for (const key in loaders) loaders[key].resize();
  for (const key in waves) waves[key].resize();
});

init();
