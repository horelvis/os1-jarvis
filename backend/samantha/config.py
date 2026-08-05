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
    host: str = "127.0.0.1"  # Solo escucha en localhost (nunca expuesto)
    port: int = 7777  # Puerto del backend (vLLM usa 8000)

    # === Modo de operación ===
    # "mock"  → respuestas falsas pero plausibles (desarrollo)
    # "real"  → LLM real (Grok API por defecto / llama-server local)
    #           + CosyVoice 3 TTS (producción)
    mode: str = "mock"

    # === Latencia simulada (solo en mode=mock) ===
    # Hacemos que el mock se sienta como el real: con espera y streaming
    mock_min_latency_s: float = 0.4  # Latencia mínima antes de empezar a responder
    mock_max_latency_s: float = 1.8  # Latencia máxima
    mock_streaming_delay_s: float = 0.04  # Pausa entre tokens (simula generación)

    # === LLM (cuando mode=real) ===
    # OpenAI-compatible server. Default points at X.AI's Grok API after
    # A/B testing showed Qwen3-8B-Q8 (local) produced visibly more
    # verbose / theatrical replies than grok-4-1-fast-non-reasoning for
    # the same evocative system prompt. See CLAUDE.md decision log
    # 2026-05-15 — privacy boundary explicitly relaxed: conversational
    # content now leaves the device when llm_api_key is set.
    #
    # To stay fully local, override at runtime:
    #   SAMANTHA_LLM_SERVER_URL=http://192.168.100.58:8000
    #   SAMANTHA_LLM_MODEL=qwen3-8b
    #   SAMANTHA_LLM_API_KEY=                        # empty
    #
    # Base URL convention: NO `/v1` suffix — real_llm.py appends
    # `/v1/chat/completions`. So `https://api.x.ai`, not
    # `https://api.x.ai/v1`. Same for OpenAI (`https://api.openai.com`).
    llm_server_url: str = "https://api.x.ai"
    llm_model: str = "grok-4-1-fast-non-reasoning"
    # "openai" → standard OpenAI compat endpoint with system prompt packaging (Grok, local llama-server, etc.)
    # "hermes" → local hermes-agent gateway endpoint (passes clean history)
    llm_provider: str = "openai"
    # When non-empty the backend sends `Authorization: Bearer <key>` on
    # each /v1/chat/completions call. Leave empty for local llama-server
    # (no auth). Read from SAMANTHA_LLM_API_KEY; never commit a key.
    llm_api_key: str = ""
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
    memory_embedder_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

    # === TTS — CosyVoice 3 ===
    # CosyVoice 3 (Fun-CosyVoice3-0.5B-2512) on the 4090 at port 8093.
    # Voice cloning via inference_zero_shot with the reference WAV +
    # its transcript. Honors personality v6 inline markers ([laughter],
    # <laughter>palabras</laughter>, [breath], [sigh]).

    # ── CosyVoice 3 server config ──
    # URL of the CosyVoice runtime FastAPI with our overlay
    # (tts-server/cosyvoice/docker-compose.yml). The overlay injects
    # the `<|endofprompt|>` system marker per request, so the client
    # sends plain Spanish.
    #
    # ⚠ 192.168.100.58 is THIS deployment's 4090 box on the LAN.
    # Any other install (CI, laptop, new hardware) MUST override it:
    #   SAMANTHA_TTS_COSYVOICE_URL=http://<your-gpu-host>:8093
    # Kept as the default so the kiosk box needs zero env config.
    tts_cosyvoice_url: str = "http://192.168.100.58:8093"
    tts_cosyvoice_timeout_s: float = 60.0
    # Reference WAV (~8 s of Samantha's voice).
    tts_cosyvoice_ref_wav: str = "~/.samantha/voices/ref/samantha.wav"
    # Literal transcript of the reference WAV. CosyVoice 3 zero-shot
    # needs it to condition the LLM on prosody (cross_lingual sounds
    # robotic because it discards prompt_text). Loaded once at startup.
    tts_cosyvoice_ref_transcript_path: str = "~/.samantha/voices/ref/samantha.txt"

    # === Logging ===
    log_level: str = "INFO"

    def __post_init__(self) -> None:
        normalized = self.mode.strip().lower()
        if normalized not in ("mock", "real"):
            raise ValueError(
                f"SAMANTHA_MODE must be 'mock' or 'real', got {self.mode!r} "
                "— refusing to start with an ambiguous mode (a typo here "
                "would silently serve canned mock replies)."
            )
        self.mode = normalized

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
            llm_provider=_get("LLM_PROVIDER", cls.llm_provider),
            llm_api_key=_get("LLM_API_KEY", cls.llm_api_key),
            llm_request_timeout_s=_get("LLM_REQUEST_TIMEOUT_S", cls.llm_request_timeout_s),
            memory_enabled=_get("MEMORY_ENABLED", cls.memory_enabled),
            memory_persist_dir=_get("MEMORY_PERSIST_DIR", cls.memory_persist_dir),
            memory_top_k=_get("MEMORY_TOP_K", cls.memory_top_k),
            memory_short_term_capacity=_get(
                "MEMORY_SHORT_TERM_CAPACITY", cls.memory_short_term_capacity
            ),
            memory_embedder_model=_get("MEMORY_EMBEDDER_MODEL", cls.memory_embedder_model),
            tts_cosyvoice_url=_get("TTS_COSYVOICE_URL", cls.tts_cosyvoice_url),
            tts_cosyvoice_timeout_s=_get("TTS_COSYVOICE_TIMEOUT_S", cls.tts_cosyvoice_timeout_s),
            tts_cosyvoice_ref_wav=_get("TTS_COSYVOICE_REF_WAV", cls.tts_cosyvoice_ref_wav),
            tts_cosyvoice_ref_transcript_path=_get(
                "TTS_COSYVOICE_REF_TRANSCRIPT_PATH",
                cls.tts_cosyvoice_ref_transcript_path,
            ),
            log_level=_get("LOG_LEVEL", cls.log_level),
        )


# Singleton accesible desde otros módulos
config = Config.from_env()
