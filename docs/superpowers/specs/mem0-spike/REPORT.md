# Mem0 spike — informe

**Date:** 2026-05-12
**Spike duration:** ~1 h (introspección + 2 corridas en vivo)
**Setup:** llama-server (Qwen3-8B-Q8_0) en `http://192.168.100.58:8000` + fastembed local (paraphrase-multilingual-MiniLM-L12-v2 ONNX) + ChromaDB vector store en tmpdirs.

---

## TL;DR

**Mem0 funciona y resuelve cosas reales** — fact extraction automática, history preservation, append-friendly defaults. Pero introduce **~5 s de latencia por turno** y la extracción sale **mayoritariamente en inglés** sin trabajo adicional de prompt engineering. No es un drop-in: requiere customización deliberada para Samantha.

**Recomendación:** **NO migrar a Mem0 en el rediseño v2**. Lo que aporta no compensa el coste para nuestro scope. Implementar el patrón short/long term + facts manualmente sobre ChromaDB (~1 día de trabajo limpio) y reservar Mem0 para v3 cuando la calidad del recall en español sea un problema real.

---

## 1. Setup que funcionó

```python
from mem0 import Memory

memory = Memory.from_config({
    "llm": {
        "provider": "openai",            # llama-server es OpenAI-compat
        "config": {
            "model": "Qwen3-8B-Q8_0.gguf",
            "openai_base_url": "http://192.168.100.58:8000/v1",
            "api_key": "fake-key-llama-server",
            "temperature": 0.2,
        },
    },
    "embedder": {
        "provider": "fastembed",          # local ONNX — llama-server
        "config": {                       # no expone /v1/embeddings
            "model": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        },
    },
    "vector_store": {
        "provider": "chroma",
        "config": {
            "collection_name": "samantha_mem0",
            "path": "/path/to/chroma_dir",
        },
    },
    "history_db_path": "/path/to/history.db",
    "custom_instructions": "(opcional)",
})
```

**Footprint:**
- `mem0ai`: ~20 MB Python deps
- `fastembed`: ~30 MB Python deps + ~80 MB ONNX model (descarga única, cached)
- Total: ~130 MB extra sobre lo que ya tenemos

## 2. Resultados de los tests (corrida estable)

### Test 1 — Fact extraction (`infer=True`, sin custom_instructions)

```
Input messages:
  user: "Tengo un perro labrador llamado Toby."
  assistant: "Anda, qué bonito. ¿Cuántos años tiene?"

Result (5.69 s):
  {"id": "e4a0c6d1-...", "memory": "User has a Labrador dog named Toby", "event": "ADD"}
```

- ✅ Detecta y extrae el hecho correctamente
- ⚠️ **Sale en inglés** aunque la conversación es en español. Default prompt de Mem0 está en inglés.

### Test 2 — Búsqueda

```
Query: "¿qué mascota tiene?"
Result (0.01 s):
  - "User has a Labrador dog named Toby"  (score 1.0)
```

- ✅ Recall multilingual funciona — query en español, hecho en inglés, match perfecto.

### Test 3 — Contradicción (¿Mem0 borra o añade?)

```
Input: "Ya no tengo a Toby, se murió hace una semana."

Result (3.97 s):
  {"id": "fdc644e2-...",
   "memory": "User's Labrador dog Toby died around April 25, 2026, and is no longer with them",
   "event": "ADD"}
```

- ✅ Mem0 añadió un **memory nuevo** en lugar de borrar/actualizar el viejo.
- ✅ Coexisten ahora: "tiene un labrador llamado Toby" + "Toby murió ~25 abril".
- ✅ **Por defecto ya es append-friendly** — alineado con "Samantha nunca olvida" sin necesidad de `custom_instructions`.

### Test 4 — History preservation

```
items = mem.get_all(filters={"user_id": "spike_user"})  # 2 items
for item in items:
    h = mem.history(memory_id=item["id"])
    # → 1 history entry cada uno: event=ADD
```

- ✅ Cada memory mantiene su tabla de versiones en `history.db`.
- ✅ Si Mem0 hiciera UPDATE/DELETE en el futuro, las versiones anteriores quedarían rescatables.

### Test 5 — `infer=False` (append puro)

```
mem.add(messages=[{"role":"user","content":"Mi color favorito es el azul."}],
        infer=False)

Result (0.01 s):
  {"id": "...", "memory": "Mi color favorito es el azul.", "event": "ADD"}
```

- ✅ **500× más rápido** que `infer=True` (5 s vs 10 ms)
- ✅ Guarda texto raw sin tocar LLM — equivalente a nuestro chromadb actual.
- → Perfecto para el **short-term buffer**.

### Test 6 — Phase B con `custom_instructions` append-only

Output con instrucciones forzando español + sólo ADD:

```
Memory 1: "User tiene un perro labrador llamado Toby"   (mezcla EN/ES)
Memory 2: "User's Labrador Toby passed away around April 25, 2026..."
```

- 🟡 Las instrucciones afectan ligeramente el español pero NO consiguen output puro en español. La estructura del prompt interno de Mem0 manda más que las instrucciones extra.
- ✅ Sigue siendo append-only (event=ADD en ambos).

## 3. Lo bueno

1. **Funciona con llama.cpp + ChromaDB existentes.** No necesitamos cambiar runtime ni storage.
2. **fastembed elimina la dependencia de embeddings vía llama-server.** Local, ONNX, ~10ms por embedding, multilingual.
3. **Append-friendly por defecto** — no encontré ningún caso donde Mem0 quisiera borrar/actualizar. Aunque la docu dice que puede, en práctica para nuestros tests no lo hizo.
4. **History tracking** preserva versiones incluso si Mem0 decide UPDATE.
5. **`infer=False` es un escape válido** para short-term buffer.
6. **API estable y bien tipada** en v2.0.2 (Pydantic configs).

## 4. Lo malo

1. **Latencia: 4-6 s por turno con `infer=True`.** En conversación normal eso es un retraso percibido. Mitigaciones posibles:
   - Hacer la extracción **asíncrono** después de responder al usuario.
   - Usar `infer=False` para el grueso, y `infer=True` sólo periódicamente (cada N turnos, batched).
2. **Language drift hacia inglés.** El prompt interno de Mem0 está en inglés, así que extrae en inglés por defecto. Customizable con `custom_instructions` pero no del todo. Para Samantha (español puro) habría que pasar `prompt=...` custom a cada `add()` o monkey-patch del template interno.
3. **Dep size:** +130 MB sobre lo que tenemos hoy. No es enorme pero tampoco trivial para un appliance.
4. **Doble LLM** — fact extraction usa el mismo llama-server que la conversación. Cada turno hace 2 round-trips: uno para generar la respuesta de Samantha, otro para extraer hechos. Bloquea recursos.
5. **Comportamiento no determinista de "será UPDATE o ADD?"** depende del LLM y de la similitud semántica con memorias existentes. Difícil garantizar 100% append.
6. **Conocimiento Mem0-específico** para mantener: configs, prompts, semántica de events. Más superficie que cuidar.

## 5. ¿Qué resuelve Mem0 que no podemos resolver fácilmente nosotros?

- **Fact extraction automática.** Único feature realmente diferencial. Sin Mem0, los turnos se guardan literal y Samantha tiene que inferir hechos por similitud — funciona OK pero no es lo mismo que tener "el usuario tiene un perro Toby" como hecho estructurado retrieval-friendly.

Todo lo demás (vector store, history, append-only, multilingual embeddings) lo podemos hacer con ChromaDB directo.

## 6. Recomendación

**No migrar a Mem0 en el rediseño v2.** Razones:

- La latencia de 5 s/turno es significativa y la solución (async extraction) añade complejidad que no compensa para v2.
- Language drift requeriría trabajo adicional de prompt engineering.
- El feature realmente útil (fact extraction) podemos diferirlo a v3 cuando tengamos uso real y veamos si lo necesitamos.
- En el spec del rediseño ya tenemos un modelo append-only sobre ChromaDB con `role: "fact"` que cubre los casos críticos (nombre, onboarded_at, futuras preferencias estructuradas).

**Plan para v2 (sin Mem0):**

1. **Capa short-term** — tabla SQLite nueva con ring buffer de los últimos 20 mensajes. Lectura instantánea, va al prompt verbatim.
2. **Capa long-term** — ChromaDB que ya tenemos. Recall por similitud. Sigue siendo append-only por código (no usamos `forget`).
3. **Embedder** — swap del default ONNX MiniLM inglés por `paraphrase-multilingual-MiniLM-L12-v2` vía fastembed o sentence-transformers. Mejor recall en español.
4. **Facts** — chunks `role: "fact"` con metadata estructurada (ya en el spec §9).

Tiempo estimado: 1 día. Ganamos lo principal (short/long term + español) sin pagar el coste de Mem0.

**Reabrir Mem0 más adelante si:**
- Necesitamos fact extraction automática real (Samantha empieza a olvidar contexto entre conversaciones).
- El recall por similitud se queda corto en producción.
- Aparecen nuevas versiones de Mem0 con mejores controles para append-only y multilingual.

## 7. Limpieza del spike

```bash
# Eliminar deps que solo añadimos para evaluar
cd backend && .venv/bin/pip uninstall -y mem0ai
# fastembed se queda — lo necesitamos como embedder de la solución casera

# Eliminar tmpdirs (ya hechos por tempfile)
rm -rf /var/folders/*/T/samantha-mem0-spike-*

# El script queda para referencia futura
ls docs/superpowers/specs/mem0-spike/
```

---

End of spike report.
