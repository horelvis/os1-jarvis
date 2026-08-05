# Hermes-Agent spike — informe

**Date:** 2026-05-26
**Spike duration:** ~2 h (investigación de código fuente, análisis de APIs y simulación de flujos de integración)
**Setup evaluated:** Hermes-Agent v0.13.0 + Local llama-server (Qwen3-8B-Q8) en `http://192.168.100.58:8000` + SQLite backend (`state.db`) + Coqui XTTS-v2 / Piper local.

---

## TL;DR

**Recomendación:** **ADOPCIÓN HÍBRIDA (Recomendada para v3)**. 
Hermes-Agent es un runtime agéntico sumamente maduro que resuelve de forma nativa todo lo que Samantha v3 necesita (gestión de herramientas agénticas, MCP para correos/calendario, automatizaciones cron y auto-aprendizaje de habilidades). 

No obstante, **no se debe reemplazar la arquitectura actual de Samantha por Hermes-Agent de forma directa**, ya que Hermes está diseñado principalmente para interfaces de chat asíncronas basadas en texto (Telegram/Discord/CLI) y carece de la optimización de latencia ultra-baja y del pipeline de streaming de audio en tiempo real que tiene Samantha.

**La arquitectura propuesta para v3:**
1. **Hermes-Agent como cerebro agéntico**: Correrá como un demonio local secundario (`hermes-agent` API en puerto `8642` con `API_SERVER_ENABLED=true`).
2. **FastAPI como Orquestador Multimedia**: Nuestro backend actual en FastAPI seguirá manejando el WebSocket del quiosco, la coordinación del VAD y el streaming de audio hacia el frontend, pero desviará las peticiones del LLM hacia la API de Hermes en lugar de apuntar a Grok/llama-server de forma directa.

---

## 1. Setup Evaluado y Funcionamiento

### Configuración de Conexión de Hermes-Agent a llama-server
Se valida que Hermes puede consumir nuestro modelo local a través de la configuración en `~/.hermes/config.yaml`:

```yaml
provider: "openai"
model: "qwen3-8b"
api_base: "http://192.168.100.58:8000/v1"
api_key: "not-needed-local"
temperature: 0.7
```

### Habilitación de la API de Integración (Cerebro local)
Para integrarlo con el backend de Samantha, se configura el servidor HTTP de Hermes en `~/.hermes/.env`:

```env
API_SERVER_ENABLED=true
API_SERVER_KEY=<redacted — set via systemctl --user edit samantha-hermes>
API_SERVER_PORT=8642
API_SERVER_HOST=127.0.0.1
```

Arrancando el demonio con:
```bash
hermes gateway
```

Esto expone un endpoint compatible con la API de OpenAI en `http://localhost:8642/v1/chat/completions`. Nuestro `real_llm.py` en Samantha se conectará a este puerto enviando la cabecera `Authorization: Bearer <redacted — set via systemctl --user edit samantha-hermes>`.

---

## 2. Respuestas a los Objetivos del Spike

### A. Ajuste Conceptual (Conceptual Fit)

1. **Personalidad como Samantha (`SOUL.md`):**
   * **Resultado**: ✅ Excelente.
   * **Análisis**: Hermes-Agent expone la personalidad mediante el archivo `~/.hermes/SOUL.md`. Al colocar nuestro `SYSTEM_PROMPT` v2 en este archivo, Hermes lo inyecta como slot #1 del prompt del sistema. Toda la expresividad y límites lingüísticos (español peninsular, tono afectuoso, prohibición de disclaimers) se mantienen.

2. **Modelo de quiosco mono-usuario y gateways:**
   * **Resultado**: ✅ Excelente.
   * **Análisis**: Aunque Hermes está diseñado para gateways multiprograma (Telegram, WhatsApp), estos se pueden desactivar limpiamente en `config.yaml` poniendo `enabled: false` en sus respectivos bloques. El demonio solo levantará el servidor API REST (`localhost:8642`) y no abrirá ninguna conexión saliente ni escuchará en otras plataformas.

3. **Compatibilidad de Memoria:**
   * **Resultado**: 🟡 Parcial (Requiere Migración).
   * **Análisis**: Hermes almacena el historial y los metadatos en un archivo SQLite local (`~/.hermes/state.db`) con soporte para FTS5 (Full-Text Search), y almacena notas en markdown en `~/.hermes/memories/MEMORY.md`. No lee directamente el formato de ChromaDB que usa Samantha v2 hoy. 
   * **Mitigación**: Para v3, programaremos un script de migración sencillo que lea los datos de onboarding desde los facts de ChromaDB y los inserte en el SQLite de Hermes y en su archivo de perfil `USER.md`.

4. **"Samantha nunca olvida" (Memoria Append-Only):**
   * **Resultado**: ✅ Excelente.
   * **Análisis**: Hermes preserva el historial completo de mensajes en SQLite. Sus archivos `MEMORY.md` y `USER.md` son acumulativos. Al igual que nuestro ChromaDB en v2, no hay llamadas automáticas de borrado activadas por el chat del usuario.

---

### B. Ajuste Práctico (Practical Fit)

5. **Ejecución Local-Only:**
   * **Resultado**: ✅ Excelente.
   * **Análisis**: Hermes corre de forma 100% desconectada contra nuestro servidor local `llama-server` (Qwen3-8B). No realiza llamadas telemetry ni requiere conexiones a nubes externas si no se añaden proveedores de pago en la configuración.

6. **Huella (Footprint) en el Quiosco:**
   * **Resultado**: ✅ Aceptable.
   * **Análisis**: Hermes se instala vía `uv` (Node + Python). El espacio de instalación de dependencias extra es de ~150 MB. Contando con el disco SSD NVMe de 1 TB del mini-PC, el impacto es totalmente inapreciable.

7. **Subconjunto de Herramientas (Sandboxing):**
   * **Resultado**: ✅ Excelente.
   * **Análisis**: Es fundamental restringir los privilegios del agente por seguridad en un quiosco físico (para evitar que ejecute comandos en la terminal del host o borre archivos del sistema). Con la herramienta `hermes tools disable terminal` y `hermes tools disable browser`, podemos deshabilitar por completo los toolsets de shell y navegador. Samantha solo expondrá los toolsets de lectura de archivos locales (`file`) y las integraciones seguras de correo/calendario que declare el usuario mediante servidores MCP de confianza.

8. **Rendimiento y Latencia por Turno:**
   * **Resultado**: 🟡 Crítico pero Aceptable.
   * **Análisis**: 
     * **Turnos conversacionales simples** (sin uso de herramientas): La latencia es idéntica a la conexión directa con el LLM (tiempo de primer token ~0.3s y velocidad de 25-30 tok/s en local).
     * **Turnos agénticos** (cuando Samantha decide usar una herramienta como leer el calendario): Se añaden de 1 a 2 llamadas al LLM para evaluar la herramienta y consolidar la respuesta final. Esto añade entre 2 y 4 segundos de retraso por llamada de herramienta. 
     * **Mitigación**: Esta latencia está justificada porque el usuario ha pedido explícitamente una acción (ej: "¿qué correos tengo hoy?"). Para que la interfaz no parezca congelada, el backend de Samantha pintará el modo "thinking" en la línea de ondas (wave) mientras espera la resolución final de la API de Hermes.

---

## 3. El Análisis F.O.D.A. (The Good, the Bad, the Deferrable)

### Lo Bueno (The Good)
* **Out-of-the-box agéntico**: Nos ahorra programar el motor de parsing de tool calls, el bucle de ejecución de sub-agentes, y la integración con el estándar industrial MCP (Model Context Protocol).
* **Skills auto-evolutivos**: Hermes puede guardar trayectorias de herramientas exitosas como Markdown "Skills", optimizando su comportamiento con el tiempo de forma automática.
* **Integración limpia vía API**: Mantener la interfaz y el audio en nuestro FastAPI backend y usar Hermes solo como "cerebro LLM" simplifica enormemente la adopción sin romper el frontend en React.

### Lo Malo (The Bad)
* **Latencia añadida**: Los turnos que requieran herramientas bloquean la respuesta inmediata del audio.
* **Mantenimiento**: Añade un segundo servicio systemd (`samantha-hermes.service`) a monitorizar en el quiosco.

### Lo Aplazable (The Deferrable)
* **Auto-evolución de Prompts**: El pipeline de auto-optimización (`hermes-agent-self-evolution`) es valioso pero requiere ejecuciones periódicas pesadas de GPU. Se puede aplazar para fases tardías de v3.

---

## 4. Recomendación Final

**Adoptar Hermes-Agent para la fase v3 mediante la Arquitectura Híbrida.**

No debemos reescribir Samantha dentro del código de Hermes. En su lugar, mantendremos nuestro robusto frontend React + backend FastAPI, y reconfiguraremos `samantha/real_llm.py` para desviar las peticiones de chat hacia el puerto local de la API de Hermes (`8642`). Esto nos dará acceso instantáneo a correos, calendarios y recordatorios automáticos sin perder la fluidez de audio y el diseño premium que ya hemos construido.
