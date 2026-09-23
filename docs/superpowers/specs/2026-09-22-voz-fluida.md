# Voz fluida — revisión de la 0.21.4 y plan de medición (diseño)

> **Fecha:** 2026-09-22. **Estado:** revisión abierta; sin cambios de
> arquitectura decididos. **Origen:** el propietario cambió el modelo a
> OpenCode Go esperando que las respuestas de voz fueran más fluidas, y no
> lo fueron. Decisión del propietario (2026-09-22): *"replantear la
> arquitectura y revisar con la nueva versión de Hermes qué facilidades
> dan los plugins"*.
>
> **Premisa corregida de entrada:** el modelo **no** era el problema. La
> fluidez se decide en la tubería de voz, y eso es lo que aquí se revisa.

---

## 1. Lo que la 0.21.4 ofrece (y no existía cuando se diseñó la tira)

1. **Streaming TTS por cláusula.** La respuesta se habla frase a frase
   **según se genera**, no al terminar. En escritorio, **un socket de voz
   por respuesta y un solo reloj de audio**, sin huecos entre frases; los
   proveedores con PCM por chunks (el nuestro) son los mejor parados.
   (`tools/tts_streaming.py`, `gateway/streaming_tts_consumer.py`.)
2. **Client-direct.** El cliente sintetiza y por el enlace solo viaja
   texto; si el proveedor es local/plugin, cae al camino relay.
   (`voice.client_direct`, `GET /api/audio/voice-config`.)
3. **Barge-in nativo** (full duplex, suelo de ruido calibrado contra la
   sala en silencio) y **frases de parada por voz**.
4. **Filtro de alucinaciones** de Whisper (26 frases + patrón repetitivo).
5. **gpt-live**: full-duplex con un modelo de voz (nube, **sin tools**,
   delega en Hermes). Otro producto: no local, con coste por minuto.
6. **Registries de STT/TTS para plugins** — lo que ya usa
   `jarvis_voice` (`tools/tts_streaming.register`, `agent.tts_registry`).

## 2. Nuestro estado (lo bueno: ya está cableado)

- El **adaptador implementa el streaming TTS**:
  `supports_streaming_tts`, `begin_streaming_tts`, `write_streaming_tts`,
  `write_streaming_tts_text`, `finish_streaming_tts`, `abort_streaming_tts`.
  Un turno se marca como de voz mandando `audio: "pcm_s16le/24000"` en el
  frame de chat (`MessageType.VOICE` ⇒ *"its delta-to-TTS consumer starts
  speaking at the first clause"*).
- La **tira acepta PCM**: `pcm.start` + frames binarios `JPCM`
  (`widget/jarvis_widget/gateway.py`), y tiene su propio camino de síntesis
  (`speaker.say`) como respaldo.
- `tts.streaming.provider: cosyvoice` y el proveedor
  `CosyVoiceStreamingProvider.stream()` (streaming por cláusula).
- **`voice.auto_tts: false`** mantiene **apagado** el camino delta-to-PCM,
  por un problema antiguo de CosyVoice (una pausa tras el primer bloque).
  La tira entonces espera la respuesta completa y sintetiza por su cuenta.
- **Medido hoy (2026-09-22):** CosyVoice tiene el **primer byte en
  1,1–2,9 s**, no en los ~9 s que dice el comentario de la config. El
  motor de voz **no** es el cuello de botella.
- Desde hoy el modelo es **remoto** (OpenCode Go / glm-5.3), así que el
  **tiempo al primer token** incluye red.

## 3. Hipótesis (a confirmar con la sonda, no a ojo)

- **H1 — espera a la respuesta completa.** Con `auto_tts: false`, ninguna
  habla hasta que el modelo termina: el primer audio paga todo el turno.
- **H2 — cláusulas en serie.** Si cada frase se sintetiza cuando la
  anterior acaba, cada cláusula añade su TTFB como silencio, salvo que se
  prefetche la siguiente mientras suena la actual.
- **H3 — TTFT del modelo remoto.** Puede ser el término dominante ahora
  mismo: glm-5.3 en la nube contra Bonsai en local.

## 4. Plan de medición: cinco marcas

Una sonda marca los cinco tiempos y enseña cuál manda:

```
fin de voz ──► transcripción ──► primer token ──► primer byte TTS ──► primer audio oído
   (VAD)         (Whisper)        (modelo)          (CosyVoice)         (altavoz)
```

- **Fin de voz → transcripción:** del log de la tira (`oído: Xs`,
  `transcripción vacía`).
- **Envío → primer token / `pcm.start` / primer `JPCM`:** sonda por el
  websocket (`widget/tools/`), mandando un frame de voz real
  (`audio: "pcm_s16le/24000"`).
- **Primer `JPCM` → audio oído:** en la tira.

Instrumento: `tools/voz_probe.py` (por escribir) + el log de la tira.

## 4.b Resultado de la primera pasada (2026-09-22)

Sonda construida: `widget/tools/voz_probe.py` (manda un turno de voz real y
marca envío → primer token → `pcm.start` → primer `JPCM` → fin).

**Con `voice.auto_tts: false` (como estaba):**

```
turno 1:  primer_token +13.25s │ pcm_start +13.25s │ primer_pcm +15.93s │ fin +15.97s
turno 2:  primer_token  +4.98s │ pcm_start  +4.98s │ primer_pcm  +7.24s │ fin  +7.27s
```

El primer PCM llegaba **2,3–2,7 s después del último token**: la tira
sintetizaba la respuesta entera al terminar. Primer audio = respuesta
completa del modelo + TTFB de TTS.

**Con `voice.auto_tts: true`:**

```
tool:  primer_token +6.08s │ pcm_start +6.08s │ primer_pcm +6.08s │ fin +7.25s
simple: primer_token +2.31s (sin PCM) / +0.00s (artefacto de la sonda)
```

- **El TTFB de TTS desaparece** (2,3–2,7 s → 0) y **el propietario lo oye
  más fluido**. No reaparece la pausa de CosyVoice que motivó el workaround,
  y no hay doble voz. **Decisión: `auto_tts: true`.**
- **Sigue sin haber solape**: `primer_token == pcm_start == primer_pcm`. La
  respuesta llega **en un solo frame**; los deltas del modelo **no** llegan
  al consumidor de streaming. El término dominante sigue siendo la
  respuesta completa del modelo (2–6 s; 5–13 s con una tool).
- El camino es **inconsistente** con respuestas cortas (sin PCM) y la sonda
  captura un frame temprano que no es la respuesta (`+0.00s`), señal de que
  hay que afinar la instrumentación antes de sacar más conclusiones.


## 5. Rediseño, según lo que salga

- **Si gana H1:** activar el camino de streaming (quitar el workaround
  `auto_tts: false`, mandar `audio` en los turnos de voz) y verificar que
  no se dobla la voz (tira + Hermes).
- **Si gana H2:** pipeline de cláusulas: sintetizar la N+1 mientras suena
  la N, con **un solo reloj de audio**. Es lo que Hermes llama "no
  per-sentence connection gaps".
- **Si gana H3:** volver a local para el turno de voz (Bonsai) o bajar el
  prompt; el modelo remoto se queda para lo que aporta (tools).
- **Transversal:** adoptar las facilidades 3 y 4 (barge-in y filtro de
  alucinaciones) en vez de mantener las nuestras.

## 6. Riesgos y fallos silenciosos

- **Doble voz.** Tira y Hermes sintetizando a la vez: dos voces, o una que
  pisa a la otra. Hay que decidir **un solo dueño** de la síntesis por
  turno y comprobarlo.
- **El workaround tenía motivo.** `auto_tts: false` existe por una pausa de
  CosyVoice tras el primer bloque; reactivar el streaming sin medir puede
  reintroducirla. La sonda de las cinco marcas es justo lo que lo detecta.
- **La tira manda el frame y espera un frame.** Si el camino de streaming
  entrega deltas, hay que comprobar que la tira los pinta/presenta y que el
  filtro de eco recibe el texto hablado completo (el bug del `streaming-tts.patch`).
- **Latencia de red variable.** Una medida de un turno no es la medida;
  hay que repetir y mirar p50/p95.

## 7. Preguntas abiertas

- ¿Quién **habla**: la tira (client-direct) o Hermes (streaming PCM)? Una,
  no las dos.
- ¿Se mantiene CosyVoice, o un TTS más rápido para la primera cláusula y
  CosyVoice después?
- ¿El modelo remoto se queda para voz, o solo para turnos con tools?

**Referencias:** `tools/tts_streaming.py`, `tools/streaming_tts_consumer.py`,
`gateway/streaming_tts_consumer.py`, `website/docs/user-guide/features/voice-mode.md`,
`website/docs/user-guide/features/wake-word.md`,
`Hermes/plugins/jarvis/adapter.py` (streaming TTS),
`Hermes/plugins/jarvis_voice/{provider,tts}.py`,
`widget/jarvis_widget/gateway.py` (`pcm.start`, `JPCM`),
`Hermes/streaming-tts.patch`.
