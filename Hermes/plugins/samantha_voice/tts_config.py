"""The five settings tts.py needs, read from the environment.

Extracted from backend/samantha/config.py when backend/ was retired
(plan 3, 2026-08-24). The names of the environment variables are
unchanged — SAMANTHA_TTS_COSYVOICE_* — because they are set on the
kiosk box, in systemd units and in Hermes' config, and renaming them
would break a running system to gain nothing.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class TTSConfig:
    # CosyVoice 3 (Fun-CosyVoice3-0.5B-2512) with our server overlay.
    # Loopback since 2026-08-22: GPU and container are on this machine.
    # Split them again (CI, a laptop driving a remote GPU) with
    # SAMANTHA_TTS_COSYVOICE_URL=http://<your-gpu-host>:8093
    url: str = "http://127.0.0.1:8093"
    # Per-read timeout, not a whole-body cap: a healthy stream never
    # trips it, a wedged server fails loudly instead of hanging.
    timeout_s: float = 60.0
    # ~7 s of his voice, and the literal transcript of it. Zero-shot
    # needs both: cross_lingual discards prompt_text and sounds robotic.
    #
    # This said `samantha.wav` until 2026-08-25, and that is why he spoke
    # in Samantha's voice for two days after becoming JARVIS. The clip
    # beside it — `jarvis.wav`, recorded 2026-08-23 the day the persona
    # changed — was only ever reachable by exporting
    # SAMANTHA_TTS_COSYVOICE_REF_WAV by hand, and nothing on this box
    # exported it: not the unit, not run-gateway.sh, not .env. A voice
    # that depends on somebody remembering an environment variable is
    # not the voice he has; the default is.
    ref_wav: str = "~/.samantha/voices/ref/jarvis.wav"
    ref_transcript_path: str = "~/.samantha/voices/ref/jarvis.txt"
    # Character given to the VOICE, not to the words: a system prompt
    # before <|endofprompt|> that conditions delivery. Empty keeps the
    # server's own "You are a helpful assistant."
    voice_prompt: str = ""

    @classmethod
    def from_env(cls) -> TTSConfig:
        def _get(key: str, default):
            val = os.environ.get(f"SAMANTHA_TTS_COSYVOICE_{key}")
            if val is None:
                return default
            if isinstance(default, float):
                return float(val)
            return val

        return cls(
            url=_get("URL", cls.url),
            timeout_s=_get("TIMEOUT_S", cls.timeout_s),
            ref_wav=_get("REF_WAV", cls.ref_wav),
            ref_transcript_path=_get("REF_TRANSCRIPT_PATH", cls.ref_transcript_path),
            voice_prompt=_get("VOICE_PROMPT", cls.voice_prompt),
        )


config = TTSConfig.from_env()
