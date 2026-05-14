"""Configuración del backend.

Lee de variables de entorno con valores por defecto razonables.
Patrón: nada se hardcodea, todo se puede ajustar sin tocar código.
"""

import os
from dataclasses import dataclass


@dataclass
class Config:
    """Configuración global del backend."""

    # === Servidor HTTP ===
    host: str = "127.0.0.1"           # Solo escucha en localhost (nunca expuesto)
    port: int = 7777                   # Puerto del backend (vLLM usa 8000)

    # === Modo de operación ===
    # "mock"  → respuestas falsas pero plausibles (desarrollo)
    # "real"  → vLLM + Whisper + Piper (producción)
    mode: str = "mock"

    # === Latencia simulada (solo en mode=mock) ===
    # Hacemos que el mock se sienta como el real: con espera y streaming
    mock_min_latency_s: float = 0.4    # Latencia mínima antes de empezar a responder
    mock_max_latency_s: float = 1.8    # Latencia máxima
    mock_streaming_delay_s: float = 0.04  # Pausa entre tokens (simula generación)

    # === LLM (cuando mode=real) ===
    # OpenAI-compatible server. Default points at a local llama-server
    # (llama.cpp). Same URL pattern works for vLLM or LM Studio if you
    # ever swap engines.
    llm_server_url: str = "http://127.0.0.1:8000"
    llm_model: str = "qwen3-8b"  # informational; llama-server typically ignores
    llm_request_timeout_s: float = 60.0
    # Sampling parameters (temperature, top_k, top_p, min_p, presence_penalty,
    # max_tokens) intentionally live on the LLM server side via flags. The
    # backend stays agnostic of the model.

    # === Memoria persistente (ChromaDB) ===
    # Memory works in both mock and real mode. Disable in tests via
    # SAMANTHA_MEMORY_ENABLED=false so chroma's index isn't created
    # under the user's home for every pytest run.
    memory_enabled: bool = True
    memory_persist_dir: str = "~/.samantha/memory"
    memory_top_k: int = 5  # how many past chunks to inject before each LLM call
    memory_short_term_capacity: int = 20  # last N turns kept verbatim in SQLite ring
    memory_embedder_model: str = (
        "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    )

    # === TTS — backend-pluggable ===
    # "vllm_omni" → HTTP to vllm-omni serving Qwen3-TTS Base with voice
    #               cloning. Streaming PCM via OpenAI-compatible
    #               /v1/audio/speech. Best quality, ~40 ms TTFA warm.
    # "piper"     → local Piper synth (no GPU). Fast fallback when the
    #               remote is unreachable. Different sample rate (22050
    #               vs vllm-omni's 24000) but the browser <audio>
    #               element handles either via the WAV header.
    # On vllm_omni failure (network / 5xx / timeout) requests auto-fall
    # back to Piper so the UI stays alive.
    tts_backend: str = "vllm_omni"

    # ── Piper config (local fallback) ──
    # Voice files live outside the repo (~70 MB each). If the model
    # isn't on disk and vllm_omni is also down, /speak degrades to a
    # tone WAV — no hard dependency at runtime.
    # Default: es_ES-sharvard-medium, speaker F (female). The other
    # sharvard speaker is M=0. Single-speaker voices like
    # es_ES-davefx-medium ignore tts_speaker_id (set it to None).
    tts_voices_dir: str = "~/.samantha/voices"
    tts_voice: str = "es_ES-sharvard-medium"
    tts_speaker_id: int | None = 1

    # ── vllm-omni remote config ──
    # URL of the vllm-omni HTTP server. e.g. http://192.168.100.58:8091
    # Leave empty to disable the remote path (forces piper).
    tts_remote_url: str = ""
    tts_remote_timeout_s: float = 60.0  # generous: includes cold-load
    # Model id as seen by the server. With our docker compose this is
    # the in-container mount point of the Qwen3-TTS Base weights.
    tts_remote_model: str = "/models/qwen3-tts-base"
    # Voice clone reference: file URI as resolved INSIDE the vllm-omni
    # container (the /refs mount in tts-server/docker-compose.yml maps
    # to ~/.samantha/voices/ref on the host).
    tts_remote_ref_audio: str = "file:///refs/samantha.wav"
    # Transcript of the ref audio — required by Qwen3-TTS cloning for
    # phoneme alignment. Must match the audio in samantha.wav verbatim.
    # Default matches the Inés Blázquez dubbing-demo clip currently
    # used as ref (conversational scene, not narrative).
    tts_remote_ref_text: str = (
        "tengo que irme ya, la niñera se va a las 5:30, "
        "he prometido a Emma que la ayudaría con su muñeco "
        "de nieve para su proyecto de arte"
    )
    # Language name — Qwen3-TTS expects capitalized "Spanish", not
    # "spanish" (the lowercase form drifts toward the preset speaker's
    # native phonemes — see Qwen3-TTS discussion #230).
    tts_remote_language: str = "Spanish"
    # Style instruction. In voice_clone mode this still shapes prosody
    # and clarity empirically. Adding "ritmo ágil" trims ~5-7% off
    # generation duration without breaking the streaming endpoint
    # (vllm-omni rejects the `speed` param when stream=true).
    tts_remote_instructions: str = (
        "Voz femenina, español nativo de España. "
        "Tono alegre y cercano. Ritmo ágil, conversacional, "
        "sin pausas largas."
    )

    # === Logging ===
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> "Config":
        """Crea config leyendo variables SAMANTHA_*."""
        def _get(key: str, default):
            val = os.environ.get(f"SAMANTHA_{key}")
            if val is None:
                return default
            # Conversión simple por tipo del default
            if isinstance(default, bool):
                return val.lower() in ("1", "true", "yes")
            if isinstance(default, int):
                return int(val)
            if isinstance(default, float):
                return float(val)
            return val

        return cls(
            host=_get("HOST", cls.host),
            port=_get("PORT", cls.port),
            mode=_get("MODE", cls.mode),
            mock_min_latency_s=_get("MOCK_MIN_LATENCY", cls.mock_min_latency_s),
            mock_max_latency_s=_get("MOCK_MAX_LATENCY", cls.mock_max_latency_s),
            mock_streaming_delay_s=_get("MOCK_STREAM_DELAY", cls.mock_streaming_delay_s),
            llm_server_url=_get("LLM_SERVER_URL", cls.llm_server_url),
            llm_model=_get("LLM_MODEL", cls.llm_model),
            llm_request_timeout_s=_get("LLM_REQUEST_TIMEOUT_S", cls.llm_request_timeout_s),
            memory_enabled=_get("MEMORY_ENABLED", cls.memory_enabled),
            memory_persist_dir=_get("MEMORY_PERSIST_DIR", cls.memory_persist_dir),
            memory_top_k=_get("MEMORY_TOP_K", cls.memory_top_k),
            memory_short_term_capacity=_get(
                "MEMORY_SHORT_TERM_CAPACITY", cls.memory_short_term_capacity
            ),
            memory_embedder_model=_get(
                "MEMORY_EMBEDDER_MODEL", cls.memory_embedder_model
            ),
            tts_backend=_get("TTS_BACKEND", cls.tts_backend),
            tts_voices_dir=_get("TTS_VOICES_DIR", cls.tts_voices_dir),
            tts_voice=_get("TTS_VOICE", cls.tts_voice),
            # speaker_id needs a custom path because the helper above
            # can't tell "default int 1" from "user wants 1". `None`
            # = single-speaker model, omit speaker_id from synth.
            tts_speaker_id=(
                int(os.environ["SAMANTHA_TTS_SPEAKER_ID"])
                if os.environ.get("SAMANTHA_TTS_SPEAKER_ID", "").strip()
                else cls.tts_speaker_id
            ),
            tts_remote_url=_get("TTS_REMOTE_URL", cls.tts_remote_url),
            tts_remote_timeout_s=_get(
                "TTS_REMOTE_TIMEOUT_S", cls.tts_remote_timeout_s
            ),
            tts_remote_model=_get("TTS_REMOTE_MODEL", cls.tts_remote_model),
            tts_remote_ref_audio=_get(
                "TTS_REMOTE_REF_AUDIO", cls.tts_remote_ref_audio
            ),
            tts_remote_ref_text=_get(
                "TTS_REMOTE_REF_TEXT", cls.tts_remote_ref_text
            ),
            tts_remote_language=_get(
                "TTS_REMOTE_LANGUAGE", cls.tts_remote_language
            ),
            tts_remote_instructions=_get(
                "TTS_REMOTE_INSTRUCTIONS", cls.tts_remote_instructions
            ),
            log_level=_get("LOG_LEVEL", cls.log_level),
        )


# Singleton accesible desde otros módulos
config = Config.from_env()
