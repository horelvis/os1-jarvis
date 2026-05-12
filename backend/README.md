# Samantha Backend — Fase 2 (Mock)

Servidor FastAPI que finge ser Samantha sin tener modelos LLM cargados.
El frontend Tauri se conectará aquí vía HTTP en `localhost:7777`.

Cuando llegue el hardware real, sustituiremos la lógica mock por
llamadas reales a vLLM, Whisper y Piper — el contrato HTTP no cambia.

## Estructura

```
backend/
├── pyproject.toml          # Dependencias Python
├── samantha/
│   ├── __init__.py
│   ├── api.py              # FastAPI app + endpoints
│   ├── config.py           # Config desde env vars
│   ├── schemas.py          # Modelos Pydantic (contrato HTTP)
│   └── mock_llm.py         # Cerebro mock con pattern matching
└── tests/
    └── test_api.py         # 10 tests de integración
```

## Instalación

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Ejecutar el servidor

```bash
python -m samantha.api
```

O directamente con uvicorn:

```bash
uvicorn samantha.api:app --host 127.0.0.1 --port 7777
```

Salida esperada:

```
INFO  Samantha backend starting on 127.0.0.1:7777 (mode=mock)
INFO  Started server process [...]
INFO  Application startup complete.
INFO  Uvicorn running on http://127.0.0.1:7777
```

## Probar manualmente

```bash
# Ping
curl http://127.0.0.1:7777/ping

# Chat
curl -X POST http://127.0.0.1:7777/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "hola", "user_id": "test"}'

# Chat con streaming (Server-Sent Events)
curl -N -X POST http://127.0.0.1:7777/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"message": "cuéntame algo", "user_id": "test"}'
```

## Ejecutar tests

```bash
pytest tests/ -v
```

Los 10 tests cubren: ping, chat, transcribe, speak, validación de input,
pattern matching del mock, y que las respuestas son variadas.

## Endpoints

| Método | Endpoint | Función |
|---|---|---|
| GET  | `/ping` | Health check |
| POST | `/chat` | Mensaje → respuesta |
| POST | `/chat/stream` | Mensaje → respuesta token a token (SSE) |
| POST | `/transcribe` | Audio (multipart) → texto |
| POST | `/speak` | Texto → audio WAV |

## Variables de entorno

| Variable | Default | Función |
|---|---|---|
| `SAMANTHA_HOST` | `127.0.0.1` | Solo localhost (nunca expuesto) |
| `SAMANTHA_PORT` | `7777` | Puerto del backend |
| `SAMANTHA_MODE` | `mock` | `mock` o `real` |
| `SAMANTHA_MOCK_MIN_LATENCY` | `0.4` | Latencia mínima simulada (segundos) |
| `SAMANTHA_MOCK_MAX_LATENCY` | `1.8` | Latencia máxima simulada |
| `SAMANTHA_MOCK_STREAM_DELAY` | `0.04` | Pausa entre tokens en streaming |
| `SAMANTHA_LOG_LEVEL` | `INFO` | DEBUG, INFO, WARNING, ERROR |

## Cómo funciona el mock

El mock NO usa IA. Funciona con pattern matching simple:

1. Recibe el mensaje del usuario
2. Lo normaliza (minúsculas, sin acentos)
3. Busca patrones cuyas keywords aparezcan en el mensaje
4. Elige el patrón de mayor prioridad
5. Devuelve una respuesta aleatoria del pool de ese patrón

Los patrones están definidos en `samantha/mock_llm.py`. Hay 14 categorías:
saludos, estado anímico (+/-), preguntas sobre Samantha, trabajo, amor,
memoria, despedidas, gracias, etc. Cada una tiene 3-4 respuestas
posibles para que haya variedad.

Si ninguna keyword matchea, fallback a respuestas genéricas
("Cuéntame más", "¿Y eso por qué?", etc.) que sirven en cualquier contexto.

## Próximos pasos

Cuando este backend esté integrado con Tauri (Fase 3) y validado, las
siguientes fases serán:

- **Fase 4** — Sustituir `mock_llm.py` por cliente real de vLLM
- **Fase 5** — Sustituir `/transcribe` mock por faster-whisper
- **Fase 6** — Sustituir `/speak` mock por Piper
- **Fase 7** — Añadir memoria con ChromaDB

El **contrato HTTP no cambia** en ninguna de esas fases — solo cambia
la implementación detrás.
