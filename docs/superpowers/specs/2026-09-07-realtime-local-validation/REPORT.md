# OS1 Jarvis: revisión y conversación en tiempo real local

7 de septiembre de 2026. Repositorio revisado: este checkout de `os1-jarvis`.

## Hallazgos prioritarios

### P1. Una respuesta del móvil puede terminar en los altavoces de la habitación

Cuando el teléfono se desconecta, [remote.py:1017](../../../../widget/jarvis_widget/remote.py) libera su reserva de turno. Si después llega la respuesta, [destino_de:658](../../../../widget/jarvis_widget/__main__.py) vuelve a buscar el dispositivo por persona y obtiene `None`. [Speaker:479](../../../../widget/jarvis_widget/speech.py) interpreta ese valor como salida por los altavoces locales.

La reproducción con las funciones originales confirma el cambio de destino tras liberar la reserva. No se reprodujo una conversación privada real. Es deuda reconocida en el código, no un fallo recién introducido. Otra conexión de la misma persona también puede convertirse en destinataria de la respuesta pendiente.

**Corrección necesaria:** fijar dispositivo y turno al aceptar la entrada. Una desconexión debe cancelar o retener la respuesta para su destinatario original, nunca convertirla en una respuesta pública.

### P1. Identificar personas todavía no separa su memoria ni sus permisos

[personas.py:15](../../../../widget/jarvis_widget/personas.py) reconoce esta limitación. Ni la configuración versionada ni las claves examinadas en la configuración local activa contienen `profile_routes` o `multiplex_profiles`. El [conjunto de herramientas de Jarvis](../../../../Hermes/jarvis-config.yaml) incluye memoria, búsqueda de sesiones, terminal y archivos.

Los identificadores separan conversaciones, pero no configuran perfiles Hermes con memoria y permisos distintos. No se leyeron recuerdos personales ni se intentó acceder a datos de otra persona para demostrarlo.

**Corrección necesaria:** aplicar rutas, perfiles y permisos efectivos antes de considerar privado el uso multiusuario. El motor de turnos no sustituye esa configuración.

### P2. Una pulsación repetida puede abrir dos preguntas del mismo teléfono

[RemoteDesk.claim:563](../../../../widget/jarvis_widget/remote.py) rechaza otro dispositivo de la misma persona, pero permite que el mismo dispositivo vuelva a reclamar mientras se está respondiendo. Una prueba sintética confirma que se despachan dos entradas sin cerrar explícitamente la primera.

Esto importa porque [Adapter._open_turn:807](../../../../Hermes/plugins/jarvis/adapter.py) sustituye el registro anterior por conversación, y [send:481](../../../../Hermes/plugins/jarvis/adapter.py) descarta `reply_to` y `metadata` antes de buscar por `chat_id`. Falta correlación de extremo a extremo para distinguir una respuesta antigua de una nueva. No se ejecutó un escenario completo contra Hermes en vivo.

**Corrección necesaria:** rechazar la nueva entrada como ocupada o cancelar explícitamente el turno anterior. En ambos casos, cada pregunta necesita su propio identificador.

### P2. Algunas grabaciones terminan sin avisar al teléfono

La salida por [transcripción vacía](../../../../widget/jarvis_widget/__main__.py), la de [eco completo](../../../../widget/jarvis_widget/__main__.py) y la de [bienvenida inicial atendida](../../../../widget/jarvis_widget/__main__.py) liberan el turno sin pasar por el aviso de finalización del altavoz. La reproducción confirma que [settle_turn](../../../../widget/jarvis_widget/__main__.py) libera la reserva sin llamar a `done()`.

El [contrato del teléfono](../../../../widget/jarvis_widget/remote.py) indica que ese aviso rearma el micrófono. Por tanto, el cliente puede seguir esperando aunque el servidor ya haya liberado el turno. El código de la app iOS no está incluido en esta revisión: se ha comprobado el servidor y su contrato documentado, no el comportamiento real de la app.

**Corrección necesaria:** todos los caminos deben cerrar el turno con un estado terminal silencioso y dirigido al dispositivo original. En una respuesta con audio, el cierre debe ir después de los fragmentos que correspondan.

## Otros límites encontrados

- **Dos pruebas del puente están desajustadas con el nombre actual.** [test_projects.py:40](../../../../Hermes/bridges/code-a2a/tests/test_projects.py) y la prueba siguiente esperan que nombres históricos con `samantha` resuelvan `os1-jarvis`. Está confirmado el fallo de esas pruebas; queda por decidir si se conservan alias antiguos o se actualizan las expectativas. No es evidencia de que resolver el nombre actual falle.
- **El filtro de eco es compartido.** [dispatch](../../../../widget/jarvis_widget/__main__.py) filtra también entradas de móviles contra el texto recordado por el filtro global. Puede eliminar repeticiones legítimas entre destinos. Es un riesgo identificado por lectura, no una reproducción acústica realizada en esta revisión.
- **La documentación ha quedado desfasada.** El README describe componentes retirados y afirma que falta una prueba de micrófono que el registro posterior da por realizada. Los comentarios también conservan supuestos de una sola persona. Esto hace más difícil distinguir garantías actuales de decisiones históricas.

## Valoración de las técnicas

La cadena local existente es una base razonable: Silero detecta actividad, Vosk ayuda a decidir el final del habla y el eco, Whisper transcribe, Hermes coordina las herramientas y el modelo local, y CosyVoice produce la voz. Las máquinas de estado separadas de la interfaz, el TTS secuencial por cláusulas y capturar el destino al encolar audio son decisiones útiles. La captura del destino necesita ocurrir antes, al admitir el turno, para cerrar el primer hallazgo.

Hay que distinguir tres cosas: transportar eventos por una conexión persistente, recibir texto progresivo del modelo y recibir audio por fragmentos. Jarvis ya tiene la primera y la tercera. El [adapter:528](../../../../Hermes/plugins/jarvis/adapter.py) entrega el texto completo de una respuesta; dividirlo después en cláusulas no convierte la generación del LLM en streaming.

La integración principal concentra muchas decisiones en `__main__.py`. Conviene extraer el ciclo de vida del turno cuando se integre el mecanismo local, con pruebas de sus conexiones a los componentes reales. Las pruebas de helpers son útiles, pero no bastan para validar todo el recorrido del micrófono al teléfono.

## Prototipo local entregado

- [Motor de turnos](motor_turnos_local.py)
- [Pruebas del motor](test_motor_turnos_local.py)
- [Reproducciones con funciones originales de Jarvis](test_jarvis_contracts.py)

Este es el prototipo revisado. Los archivos anteriores `local_realtime.py` y `test_local_realtime.py` son borradores y no son la versión recomendada.

El motor utiliza biblioteca estándar y no realiza ninguna llamada a OpenAI ni a otros servicios de inferencia. Comprueba:

- Sesión, persona, turno y destino identificados por separado.
- Apertura serializada por sesión y rechazo de aperturas después de desconectar.
- Texto y audio conservados en orden bajo saturación, con espera de los productores.
- Cancelación que rechaza nuevas publicaciones del turno y puede retirar explícitamente su audio pendiente, sin retirar el de otra persona.
- Solicitud de cancelación de una tarea lenta antes de esperar espacio en la cola.
- Un único evento terminal por turno ante llamadas concurrentes.
- Recuperación explícita de terminales cuya publicación se interrumpió.

**No está integrado en Jarvis y no es un motor neuronal de voz a voz.** No transcribe, no sintetiza, no ejecuta herramientas ni mide latencia. La recuperación de terminales requiere que el integrador invoque el mecanismo de recuperación; no implica entrega garantizada a través de una red o de un reinicio.

También quedan fuera la persistencia, limpieza de sesiones antiguas, límites en bytes, supervisión completa de múltiples herramientas y confirmaciones de reproducción en el cliente. La cola limita el número de eventos, no el tamaño de cada fragmento. Un único consumidor lento puede retrasar otros destinos: la integración deberá decidir si separa sus colas.

Cancelar una tarea asíncrona solicita su cancelación cooperativa. No revierte acciones ya ejecutadas, ni garantiza detener por sí sola un hilo, un proceso externo o una operación de GPU.

## Verificación

| Conjunto | Resultado |
| --- | --- |
| Widget original | 721 pruebas pasan |
| Plugins y pruebas Hermes del proyecto | 556 pruebas pasan |
| Puente de código | 110 pasan; 2 fallan por las expectativas del nombre histórico |
| Motor local nuevo | 13 pruebas pasan |
| Reproducciones con helpers originales | 3 pruebas pasan |

Se repitió la ejecución conjunta de las 16 pruebas nuevas después de revisar el prototipo y pasó. Los 24 fallos del primer intento del widget correspondían a sockets bloqueados por el entorno: con permiso para los sockets locales, la suite completa pasó. No se cuentan como fallos de Jarvis.

Para ejecutar las nuevas pruebas:

```bash
cd docs/superpowers/specs/2026-09-07-realtime-local-validation
env PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 \
  ../../../../widget/.venv/bin/python -B \
  -m unittest -v test_motor_turnos_local.py test_jarvis_contracts.py
```

Las tres reproducciones usan funciones originales con dispositivos simulados. No ejecutan el flujo completo de `dispatch`, ni prueban la app iOS o el audio real. Tampoco se ha medido latencia, calidad de reconocimiento o consumo GPU. El repositorio original continúa limpio; no se han modificado ni reiniciado los servicios domésticos.

## Integración completamente local

1. Vincular cada entrada a su turno y dispositivo original; resolver todos los caminos de finalización y desconexión. Añadir pruebas del recorrido completo con motores simulados.
2. Propagar el identificador de turno por widget, protocolo, adapter, respuesta y cola de voz. Mantener la conversación como identidad distinta del turno. El cliente iOS necesitará una actualización coordinada del contrato.
3. Aplicar perfiles y permisos efectivos por persona, incluyendo una política explícita para la identidad compartida de la casa.
4. Conservar Silero, Vosk, Whisper, Hermes/llama.cpp y CosyVoice. Añadir streaming de texto solo a través de una integración comprobada con Hermes. Cancelar de forma explícita la generación y los trabajos que todavía puedan detenerse.
5. Registrar cuánto audio se generó, envió y reprodujo. Ajustar el contexto tras una interrupción para que el modelo no suponga que el usuario escuchó una respuesta entera.
6. Medir tiempo hasta el primer audio, respuesta a interrupciones, pausas entre fragmentos, varios usuarios simultáneos y memoria GPU. Elegir ajustes con esas medidas y con el presupuesto de la RTX 4090; no cargar modelos adicionales sin comprobarlo.

Se puede construir una experiencia similar en sus mecanismos de conversación sin una API remota. La equivalencia en naturalidad o rapidez sigue siendo una hipótesis que hay que medir con los motores locales.
