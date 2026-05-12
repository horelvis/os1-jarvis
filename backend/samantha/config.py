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
            log_level=_get("LOG_LEVEL", cls.log_level),
        )


# Singleton accesible desde otros módulos
config = Config.from_env()
