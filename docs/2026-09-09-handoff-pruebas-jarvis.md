# Traspaso: pruebas de conversación y herramientas de Jarvis

## Objetivo inmediato

Comprobar que Jarvis **ejecuta** herramientas desde el recorrido del móvil y
entrega resultados, en vez de afirmar que ha buscado o prometer un resumen.
El usuario prepara otra instancia del agente para colaborar en estas pruebas.

## Acceso y fuentes

- App: `/Users/horelvis/git/ios-jarvis` en el Mac.
- Servidor: `ssh -l nexus 192.168.100.58` (la clave del Mac está autorizada).
- Backend: `/home/nexus/git/os1-jarvis`.
- Leer primero `AGENTS.md` y `CLAUDE.md` del backend.
- Historial técnico: `PROGRESS.md` del backend y los documentos de hoy en `docs/`.
- No compartir tokens, contraseñas, certificados privados ni archivos `.env`.

## Estado comprobado

1. La app ya no usa Apple Speech. Envía PCM por WSS a la caja y recibe
   `transcript(text)` de Whisper local. Móvil y Hermes reciben el mismo texto.
2. Audio y texto se encaminan al teléfono original. Se corrigió `on_pcm`, que
   enviaba voz de turnos móviles directamente al altavoz de la caja.
3. Se corrigió un turno sin terminal causado por clasificar `<laughter>` como
   aviso de sistema y descartar su `done`.
4. La app tiene notas de voz con transcripción desplegable y avatar/icono de
   mayordomo. Última suite iOS: 157 tests correctos.
5. En el backend, `plugins.entries.jarvis.settings.policy.desktop_principal`
   ya valía `orelvis`, pero la fábrica solo pasaba `PlatformConfig.extra`.
   La configuración del plugin nunca llegaba al adaptador y este usaba `casa`.
6. Corregida la fábrica y añadido el parámetro opcional `plugin_settings` al
   adaptador. Los ajustes explícitos de plataforma prevalecen por sección;
   sin configuración el valor seguro sigue siendo `casa`, sin herramientas.
7. Gateway reiniciado a las **13:39:15 CEST**. Log real de arranque:
   `principal=orelvis profile=orelvis toolsets=12`.
8. Suite conjunta actual: **969 tests correctos** (plugin JARVIS + widget).

## Lo que AÚN FALLA / no está demostrado

Una sonda real entró como `orelvis` y pidió ejecutar `session_search` sobre
Alfresco, sin Internet ni modificaciones. El modelo respondió que encontró
cuatro menciones, pero el log registró **una sola llamada al modelo y ninguna
llamada nueva demostrada a esa herramienta**. La frase del modelo no prueba
que haya ejecutado nada.

Turno de la sonda: `e2c9aeed-37eb-4868-941d-54136463b0d1`.
Entrada: **13:45:38 CEST**. Respuesta: **13:46:05 CEST**.
Sesión resuelta: `20260906_224959_de939e5f` en el perfil `orelvis`.
Hubo compresión del historial antes de responder.

**Trampa de verificación encontrada:** al restaurar/comprimir la sesión se
escribieron filas de herramientas históricas con timestamps nuevos en el DB del
perfil. Consultar solo `timestamp >= inicio_de_la_sonda` devuelve búsquedas,
escrituras y otras llamadas antiguas. No son operaciones ejecutadas por esta
sonda. Correlacionar con el turno actual, su nueva fila de usuario, los logs
del agente y los IDs de llamada; no usar ni el contador acumulado `tool_turns`
ni la frase «he podido ejecutarlo» como evidencia.

El perfil `orelvis/config.yaml` sigue declarando `qwen3.8-27b`, aunque el
servidor local sirve Gemma y la configuración raíz declara Gemma. Se observó
que la sonda usó la etiqueta Qwen contra `127.0.0.1:8000`. No se ha cambiado
ese ajuste ni demostrado aún si interviene en las llamadas a herramientas.

## Trabajo recomendado para la instancia de pruebas

1. Revisar qué esquemas de herramientas llegan **realmente** a la llamada del
   modelo en el turno del perfil `orelvis`, no solo los grupos configurados.
2. Contrastar la resolución de perfil y herramientas del Hermes fijado. Su
   `_resolve_enabled_toolsets_for_source` solo acepta una lista no vacía como
   override; el adaptador entrega una tupla. No asumir que el override se aplica.
3. Probar una herramienta local de solo lectura y comprobar la llamada y su
   resultado real. No basta con que la respuesta diga que se ejecutó.
4. Probar petición → resultado → siguiente turno, cancelación y una petición de
   resumen sobre material disponible. Registrar tiempos y terminales.
5. Devolver evidencia y causa propuesta al coordinador antes de modificar
   archivos que este está editando.

## Precauciones operativas concretas

- Hay trabajo sin commit en ambos repositorios. No hacer reset, checkout de
  archivos, commits masivos ni sobrescribir cambios ajenos.
- No abrir otra conexión a `ws://127.0.0.1:7777/ws` mientras el widget esté
  conectado: sustituye su socket. Coordinar una pausa del widget y restaurarlo
  con `trap`/`finally` si hace falta una sonda sobre ese puerto.
- Las sondas no deben añadir credenciales ni reenrolar teléfonos.
- Mantener captura, transcripción y modelo locales. La sonda de herramientas
  debe ser de lectura local; no ejecutar búsquedas web o escrituras por accidente.
- No conceder herramientas a `casa` ni tomar un `chat_id` del cliente como
  prueba de identidad. El arreglo de fábrica aplica configuración existente.
- No presentar una prueba sintética, una fila histórica reimportada o un texto
  del modelo como confirmación de que el usuario recibió un resultado real.

## Comandos de consulta

```bash
ssh -l nexus 192.168.100.58
```

En el servidor:

```bash
journalctl --user -u jarvis-widget.service -u jarvis-hermes.service --since '10 minutes ago' --no-pager
```

Logs adicionales:

- `.hermes/home/logs/gateway.log`
- `.hermes/home/logs/agent.log`
- `.hermes/home/profiles/orelvis/logs/agent.log`

Usar SQLite en modo solo lectura si se inspecciona historial. Informar nombres
de herramientas, IDs, conteos y errores; evitar copiar conversaciones completas.

## Coordinación entre instancias (pendiente de confirmación)

El documento de este servidor puede servir de punto de encuentro por SSH.
Todavía no hay confirmación de contacto con la instancia del Mac ni una ventana
de pruebas acordada. No interpretar este reparto propuesto como trabajo ya hecho.

- **OpenCode backend (Linux):** revisar resolución de perfil, tipo del override
  de toolsets y esquemas enviados al modelo; correlacionar llamadas y resultados
  del turno actual. No editar el repositorio iOS.
- **OpenCode iOS (Mac), propuesto:** conducir el recorrido desde la app y recoger
  transcripción, identificador de turno si está disponible, eventos terminales,
  texto recibido y reproducción de audio. No modificar backend durante la prueba.
- **Antes de comenzar:** la instancia del Mac añade una confirmación al final
  de este documento con archivos que está editando, revisión/build de la app,
  recorrido usado (legacy o admisión móvil Hermes) y ventana propuesta en UTC.
  Cada instancia añade entradas nuevas; no reescribe las de la otra.
- **Servicios:** no reiniciar gateway/widget, cambiar modelo/configuración,
  borrar sesiones ni abrir sondas en `:7777/ws` durante la ventana sin acuerdo
  explícito. Mantener intactos los cambios sin commit existentes.

### Secuencia propuesta

1. Acordar una única petición local de solo lectura y comprobar previamente
   que las herramientas efectivas no permiten operaciones fuera del alcance
   de la sonda. Una instrucción en el prompt no es una restricción de permisos.
2. Enviar la petición desde iOS y correlacionar su entrada con la llamada real
   a la herramienta y su resultado en backend, sin contar historial reimportado.
3. Confirmar en iOS recepción de resultado, terminal y audio en el teléfono
   original; después enviar un turno de seguimiento.
4. Probar cancelación y un nuevo turno por separado, registrando cualquier
   evento tardío. Probar después el resumen de material local disponible.

### Registro por prueba

```text
Instancia / build o revisión:
Archivos en edición:
Inicio y fin (UTC):
Recorrido / identificador de prueba:
Turno / sesión / nueva fila de usuario (si disponibles):
Perfil resuelto / herramientas efectivas:
Herramienta / tool_call_id / resultado o error (sin contenido privado):
Eventos terminales y tiempos observados en iOS:
Texto y audio recibidos en el teléfono original: sí / no / no comprobado
Resultado: verificado / fallido / no demostrado
Siguiente acción propuesta y responsable:
```

### 2026-09-09T11:51:48Z | Linux -> iOS | COORD-001

El usuario confirma este archivo como canal compartido. Usar la copia del
servidor por SSH, no una copia independiente del Mac. Añadir mensajes al final
con fecha UTC, emisor e identificador de referencia; releer antes de editar.

**Backend disponible para coordinar; pruebas conjuntas aún no iniciadas.**
En esta instancia solo estoy editando este documento. He leído `CLAUDE.md`,
el handoff y el estado del worktree; no he cambiado código, configuración ni
servicios, ni he abierto una conexión al gateway. Los cambios previos del
repositorio pertenecen a trabajo anterior y no se consideran míos.

**Para OpenCode en el Mac:** responder aquí a `COORD-001` con build/revisión de
iOS, recorrido activo, archivos que estás editando y ventana de pruebas propuesta
en UTC. Confirmar si puedes conducir la app real o necesitas intervención del
usuario. No iniciar todavía una sonda ni reiniciar servicios: primero acordamos
la petición local de lectura y su alcance efectivo.

No hay acuse de recibo de iOS en el momento de publicar este mensaje. La siguiente
acción de coordinación es su respuesta; no se presupone entrega ni lectura.

### 2026-09-09T16:44:55Z | Backend | T_6fa63a9a9bd0

El canal pasó a Collab, sala `s_19328386`, con ACK real de Mac e incorporación
`T_16e83da45945` completada. Este documento conserva evidencia, no sustituye
la sala. La tarea de diagnóstico está reclamada por backend y sigue abierta.

**Incidente revalidado:** perfil `orelvis/state.db`, sesión
`20260906_224959_de939e5f`, usuario 285 seguido únicamente de asistente 286
(`stop`, 150 caracteres, cero tool_calls/resultados nuevos). `agent.log:6889-6892`
registra una llamada principal y envío tras 27,5 s; no prueba recepción. La
correlación se apoya en sesión, intervalo y petición, no en un UUID encontrado
en el DB. IDs de herramientas reimportados se contrastaron con el DB raíz.

**Corrección preparada, no desplegada:**

- `Hermes/plugins/jarvis/adapter.py`: lista nueva en `toolsets_for_source`.
- `Hermes/plugins/jarvis/tests/test_policy.py`: contrato y prueba de importación
  real de adaptador/core, incluido `casa` sin herramientas.
- Resolver genérico en `.hermes/src/gateway/run.py`: `[]` no hereda permisos,
  override explícito no incorpora plugins/MCP adicionales. Pruebas en
  `.hermes/src/tests/gateway/test_webhook_route_toolsets.py`.
- `Hermes/source-toolsets.patch` y `Hermes/setup-runtime.sh`: persistencia
  reproducible sobre el pin, aplicación idempotente y negativa ante conflictos.
- Verificación: 974 tests plugin/widget, 18 resolver Hermes; los 18 también
  pasan sobre el pin limpio con parche. Sin reinicios ni cambios de perfil.

**Sondas locales de componentes, NO prueba móvil:** cuatro peticiones con
esquema efectivo limitado a `session_search` devolvieron tool_calls. La etiqueta
Qwen no impide por sí sola llamar a herramientas. No se capturó el payload
histórico exacto posterior a compresión; la causa de aquella decisión del modelo
sigue sin aislarse. Helper local: `/tmp/opencode/orelvis_tool_probe.py`.

Después se ejecutó `session_search` original con DB explícito de solo lectura:
una sesión, 3434 caracteres, `total_changes=0`, 0,005 s. Hash del resultado y
del contenido realmente enviado a Gemma:
`ca6a20a7b2057bb881ce4fbdc40196fb212fb2fd399d564efd895d5138a28d18`.
Gemma devolvió `stop`, 339 caracteres, 1,209 s. ID de respuesta:
`chatcmpl-at8iIooov8Q37MAolLSF7kmLcJZWwXQK`. El ID de herramienta
`helper_seed_session_search_1` fue generado por el helper: no es evidencia de
llamada autónoma del modelo. Dos intentos previos fallaron en la inyección de DB
del helper; no se cuentan como ejecuciones correctas.

**Bloqueo:** el mensaje a Mac solicitando ventana de reinicio/prueba no pudo
enviarse: conexión rechazada en `192.168.100.129:9920`. Estado Collab
`reconnecting`. No se reinició el gateway ni se abrió otro socket en `:7777`.
Reintentar la sala existente, acordar ventana y verificar el ciclo completo
desde iOS, con herramientas efectivamente acotadas antes de inferencia; después
seguimiento y cancelación. No marcar la tarea completada con estas sondas.

### 2026-09-09T18:21:12Z | Backend | Ventana P1 abierta

Mac confirmó iPhone conectado y ninguna prueba activa; el usuario pidió iniciar.
Gateway reiniciado a las 18:21:10 UTC, PID 2000766; widget reconectado a las
18:21:12 UTC, sin reiniciarlo ni abrir sockets alternativos. Arreglo de resolver
cargado. `LISTO P1` enviado por Collab; pendiente recepción real de Mac y petición.

**Configuración temporal activa que hay que restaurar al cerrar la ventana:**
`.hermes/home/profiles/orelvis/config.yaml`, `agent.disabled_toolsets`, contenía
solo `[tts]`. Para P1 se añadieron `memory`, `cronjob`, `todo`, `clarify`,
`camaras`, `web`, `a2a`, `codigo`, `terminal`, `clases`, `file`. No modificar
otras secciones al restaurar. Resolver real y generación de esquemas verificados
en proceso aislado: exactamente `[session_search]`. No cambia el modelo.

Petición acordada: «Busca en nuestras conversaciones locales sobre Alfresco y
resume ahora lo encontrado. No uses Internet ni modifiques nada».
Referencia previa al ensayo: última fila de mensajes del perfil 286, histórica.
Helper de metadatos sin contenido: `/tmp/opencode/current_turn_evidence.py`.
La restricción temporal no debe confundirse con el estado normal del perfil.

### 2026-09-09T18:28:15Z | Backend + Mac | P1 recibida, búsqueda no demostrada

Mac recibió LISTO y trasladó confirmación física global del usuario: «todo ok»
respecto a respuesta/texto/audio/cierre. Sin captura cruda de frames ni turn_id.
La transcripción del widget a las 18:27:56 UTC fue una pregunta sobre información
de una propuesta Alfresco, no la petición explícita de búsqueda/resumen acordada.

DB de solo lectura: nueva fila de usuario 571, asistente 572, 361 caracteres,
`finish_reason=stop`, cero llamadas/resultados de herramientas posteriores al
usuario. `agent.log:7415-7418`: una llamada principal, respuesta lista en 18,5 s
y envío registrado. Hubo tres compresiones; las herramientas reimportadas antes
de la fila 571 no cuentan. El widget redujo solo la voz a 251 caracteres.

Conclusión: entrega física global reportada, ejecución de búsqueda no verificada
y recepción del frame `done` no capturada. Cierres móviles 1006 posteriores no
demuestran por sí solos fallo de ese turno. Comunicado a Mac por Collab; se pide
repetir la frase exacta antes del seguimiento. Restricción temporal sigue activa.

### 2026-09-09T18:40:05Z | Backend | Búsqueda real desde móvil confirmada

Nueva conexión móvil autenticada `orelvis` a las 18:39:25 UTC, voz/transcripción
a las 18:39:39 UTC con petición de búsqueda local Alfresco. No contiene el
marcador «Prueba dos» propuesto después. Gateway registra la misma petición y
cache key `agent:orelvis:jarvis:dm:orelvis`; persistencia en
`.hermes/home/profiles/orelvis/state.db`, sesión `20260906_224959_de939e5f`.
Se contrastó también el DB raíz, sin nuevo turno. La restricción temporal
está aplicada al perfil que procesó esta petición.

Secuencia nueva, comprobada en SQLite de solo lectura:

- Usuario 857, 130 caracteres.
- Asistente 858 llama `session_search`, ID `7KDKu48wVlZcFUFsIr84VYTUC5upTfvN`.
- Resultado 859 con el mismo ID: 10261 caracteres, `success=true`,
  `mode=discover`, `count=1`.
- Asistente 860: 642 caracteres, `finish_reason=stop`.

`agent.log:7453-7458` confirma dos llamadas al modelo, ejecución de búsqueda
en 0,02 s, respuesta lista tras 26,3 s y envío. Tres compresiones previas
explican gran parte de la latencia; las llamadas reimportadas anteriores a 857
no cuentan. El widget registró reducción de la voz de 642 a 261 caracteres.

Esto sí demuestra llamada nueva, resultado real y respuesta posterior en el
recorrido móvil. Pendiente confirmar recepción física de ESTE resumen con Mac;
no trasladar el «todo ok» del turno anterior. Sin captura del frame `done` ni
identificador de transporte. Evidencia enviada por Collab; no repetir búsqueda
innecesariamente. Seguimiento/cancelación y restauración del perfil pendientes.

### 2026-09-09T18:44:06Z | Backend | Ventana cerrada, fallo TTS localizado

Mac comunica transcripción visible pero reproducción gris/deshabilitada; usuario
pide depurar en simulador. Pruebas físicas pausadas, sin conectar aún simulador.
Journal del gateway a las 18:40:05.967 UTC registra fallo de CosyVoice local en
`_send_desktop_pcm` para turno `3f3e2ff0-9ccc-41df-9dda-da6f8c5c4f6b`:
`peer closed connection without sending complete message body (incomplete chunked read)`.
Coincide temporalmente con la respuesta de búsqueda de 642 caracteres. No hay
contadores PCM ni captura de terminal; no afirmar que el audio llegó al móvil.

Restaurado `agent.disabled_toolsets: [tts]` en el perfil `orelvis`, retirando
solo las once exclusiones temporales. Gateway reiniciado a las 18:44:04 UTC
(PID 2068509); widget reconectado a las 18:44:06 UTC. Ya no está activa la
restricción de prueba. El arreglo de resolver sigue desplegado. Pendiente
investigar cierre del stream CosyVoice y nueva ventana de audio/seguimiento/
cancelación. Evidencia comunicada por Collab; tarea no completada.
