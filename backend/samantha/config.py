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
    vllm_url: str = "http://127.0.0.1:8000"
    llm_model: str = "Qwen/Qwen3.5-9B-Instruct"  # Candidato actual; ajustable
    llm_max_tokens: int = 512
    llm_temperature: float = 0.7

    # === Memoria (cuando mode=real) ===
    chroma_persist_dir: str = "~/.samantha/memory"

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
            vllm_url=_get("VLLM_URL", cls.vllm_url),
            llm_model=_get("LLM_MODEL", cls.llm_model),
            llm_max_tokens=_get("LLM_MAX_TOKENS", cls.llm_max_tokens),
            llm_temperature=_get("LLM_TEMPERATURE", cls.llm_temperature),
            chroma_persist_dir=_get("CHROMA_DIR", cls.chroma_persist_dir),
            log_level=_get("LOG_LEVEL", cls.log_level),
        )


# Singleton accesible desde otros módulos
config = Config.from_env()
