# PROGRESS.md — Samantha Phase Log

## 2026-08-26 (tarde III) — Vuelve la regla de BarnDoor, y un techo por turno ✅

**Quitada la escalada de las alertas.** Lo que le hacía callarse era
nuestro, no de BarnDoor: la ventana se ensanchaba en re-disparos
consecutivos (180 s → 15 min → 1 h), así que alguien que se quedaba
plantado se mencionaba una vez por hora — y mientras un `(cámara,
etiqueta)` estaba en ese nivel, **cualquier** persona en esa cámara
quedaba silenciada hasta una hora. Fuera, junto con los dos diccionarios
que necesitaba. Queda la regla plana: 180 s por cámara y etiqueta,
persona en horas de silencio saltándosela, y el suelo nocturno de 30 s.

**El coste vuelve con ella, y ahora está escrito en un test en vez de
descubrirse en el salón:** seis horas de alguien parado en la entrada son
**120 menciones**, no ocho. Con la inyección encendida, cada una es un
turno hablado y una llamada al modelo.

**Y `agent.max_turns: 25`.** Hermes es ilimitado por defecto, que es lo
que significaba `api_calls=1/9223372036854775807` en cada línea del log.
Hoy, dos veces, un turno entró en bucle contra una herramienta que esta
plataforma no tiene y corrió hasta que alguien lo vio. Verificado en
vivo: `iteration 1/25` y `api_calls=1/25`.

**Un aviso para la próxima:** `apply-config.sh` fusiona el fichero
versionado sobre el vivo, así que aplicar un ajuste **re-afirma todos los
demás**. Aplicar el arreglo de la hora volvió a encender
`allow_gateway_injection`, apagado desde ayer, porque el fichero
versionado dice `true`. Un override local que importe hay que cambiarlo
en el fichero versionado, no sólo en `.hermes/home/config.yaml`.

## 2026-08-26 (tarde II) — Las herramientas sí estaban; lo que faltaba era el reloj ✅

El usuario: «sigue con los problemas para invocar herramientas de Hermes,
que es el principal motivo de usarlo». La causa resultó ser **una línea
del propio prompt de Hermes**: «Current time, date, timezone → use
terminal (e.g. date)». Esta plataforma no tiene `terminal` —excluida a
propósito— así que le manda a una herramienta que no existe.

De ahí salen los dos misterios del día: el error `'terminal' is not a
deferrable tool` dentro de un bucle sin límite de iteraciones (15.099
tokens, GPU al 93% y 391 W) y, al no encontrar el reloj, **se inventa la
hora**: a las 14:23 pidió un aviso «en seis minutos» y lo programó para
las 17:34. El cron se creaba bien; simplemente quedaba a tres horas.

**Arreglo:** `gateway.message_timestamps.enabled`, que antepone
`[Wed 2026-08-26 14:34:47 CEST]` a cada mensaje. Medido después:
preguntada la hora a las 14:36 responde «casi las dos y media»; pedido a
las 14:36:30 un aviso para dos minutos, queda a las 14:38:30, se dispara,
y la tira lo dice en voz alta a las 14:38:51.

**Dos correcciones a lo que creíamos:**
- El registro de Hermes está en `.hermes/home/logs/agent.log`, no en el
  journal. Mirando sólo el journal se concluye —con seguridad y mal— que
  no se llama a ninguna herramienta; allí se ve que sí: `cronjob`,
  `todo`, `memory`, `ver_en_vivo`.
- «Dice que lo apunta y no lo apunta» era medio falso: la preferencia del
  café **ya estaba** en `memories/USER.md`, puesta por el proveedor de
  memoria y no por una llamada. Mirar el almacén antes de llamarlo
  alucinación.

**Y su memoria estaba envenenada:** `MEMORY.md` seguía diciendo «el
kiosko es solo voz: no hay pantalla… responder con descripción verbal y
ofrecer a vigilar y avisar». Falsa desde que existe la banda, y origen
tanto de las negativas a enseñar cámaras como de las coletillas que el
usuario pidió quitar por la mañana. Corregida. Editar la persona no
alcanza a lo que el agente ha escrito sobre sí mismo.

**Además:** el puente `tool_search` queda apagado para esta plataforma
(ofrecía en su catálogo herramientas que aquí no existen, `terminal`
entre ellas) y el hint deja de insistir en la cámara y pasa a exigir
honestidad — antes, pedirle un aviso creaba el aviso **y** abría una
cámara que nadie pidió; después, sólo el aviso.

**Sigue abierto:** nada acota un run de Hermes
(`api_calls=1/9223372036854775807`); `--n-predict 2048` limita una
generación, no un bucle de ellas.

## 2026-08-26 (tarde) — El calor no eran las cámaras, y un botón para cerrarle ✅

**El usuario preguntó por qué se calienta el PC, y la respuesta cambia un
diagnóstico de ayer.** Medido en ese momento, sin nadie hablándole: GPU a
**67 °C, 93% y 391 W**. `llama-server` llevaba **15.099 tokens generados
en una sola petición**, a 50 tok/s, y seguía — con el vigilante de 90 s
del kiosko habiendo cerrado ese turno minutos antes («dropping a reply
that arrived after the 90s watchdog»). Nadie esperaba esos tokens. Un
`/stop` lo cortó: **67 °C → 54 °C y 391 W → 71 W** al instante.

**Y el mismo patrón está en el diario de ayer: 12.576 tokens en una
generación.** El 2026-08-25 esa carga se atribuyó a las alertas de
cámara y se respondió apagando `allow_gateway_injection`. Con la
inyección apagada ha vuelto a ocurrir, así que la causa era —al menos en
parte— **otra**: turnos que no terminan. El interruptor sigue apagado y
conviene revisar esa decisión con este dato delante.

**Tope puesto donde de verdad corta:** `--n-predict 2048` en
`samantha-llamacpp.service`. Son ~40 s de generación, muy por encima de
cualquier respuesta hablada (una larga no llega a 200 tokens). Acota el
daño; no arregla un modelo que entra en bucle, que es un límite de
iteraciones del lado de Hermes y no está configurado.

**Antes de eso, la misma mañana, «no responde a ninguna pregunta»**, y
eran dos causas silenciosas: un run atascado (todo lo dicho después se
plegaba dentro de él) y que **una sesión nueva se come su primer turno**
con el aviso `📬 No home channel is set`, que la tira descarta —
correctamente— por ser mensaje de sistema. `/stop` y `/sethome` los
resolvieron; los dos están en §5 de CLAUDE.md.

**El tercer interruptor: cerrarle.** Dos pulsaciones en tres segundos —
la primera enciende la cruz—, porque es el único control de la tira que
no se deshace desde la tira. Y sale con `os._exit(0)`: cerrar
«bien» desmonta PortAudio, onnxruntime y CUDA desde el hilo de GTK y
**segfaultea** (`status=11/SEGV`), que con `Restart=on-failure` hacía que
el botón de cerrar lo *reiniciara*. Verificado: `ExecMainStatus=0`,
`NRestarts=0`, ventana desaparecida.

**Y la tira ya se puede pulsar desde un script.** `widget/tools/click.py`
mueve el puntero por XTEST con ctypes, igual que `ewmh.py` llega a
libX11: `xdotool` no está instalado pero `libXtst` sí. Las seis
pulsaciones de esta tarde se probaron así, no se razonaron. CLAUDE.md
llevaba desde agosto diciendo que no se podía enviar un clic a esta
ventana.

## 2026-08-26 — La cámara se mueve de verdad, y JARVIS responde a su nombre ✅

La tarea 13 empezó como una verificación y acabó encontrando que **la
vista en vivo nunca había funcionado**. Con ella cerrada, el usuario
pidió cuatro cosas y las cuatro están hechas.

**El fallo que la verificación existía para encontrar.** La banda se
abría a 900×480, se quedaba vacía y no se cerraba nunca. Tres síntomas y
una causa: `LiveSession.open` capturaba el bucle de eventos con
`asyncio.get_running_loop()`, que es el bucle **del turno**, y ese bucle
deja de correr cuando el turno acaba. Cada paquete que el hilo vigilante
programaba después caía en un bucle muerto, en la única rama de
`_schedule` que no dice nada. El tope de dos minutos tampoco saltaba:
sólo se comprueba con un paquete que llega, y no llegaba ninguno. El
adaptador del kiosko ahora recuerda el bucle de su propio websocket —el
del gateway, que vive entre turnos— y la sesión lo pide.

**Costó una medición y cuatro rondas de instrumentar**, porque entre el
grifo y el píxel no había nada observable. Esas líneas se quedan: `tap
installed`, `first packet`, `streaming`, `first frame landed` y el
`running=` del bucle. Una por vista, ninguna por paquete.

**Y los tests habían normalizado el fallo:** el propio docstring de
`test_live.py` explicaba que «el bucle que `open()` capturó ya está
cerrado» y lo sorteaba metiendo el escenario entero en un `asyncio.run`.
Eso *es* el fallo de producción, escrito como si fuera una manía de los
tests.

**Medido contra la casa, con el arreglo:** ~1,2 s desde el reloj quemado
en la imagen hasta la pantalla; 11,7% de CPU el widget y 38,5% el
gateway; el tope cerrando a los 120,0 s exactos tras 1200 paquetes, y la
tira de vuelta a 900×96 con `_NET_WM_STATE_ABOVE/STICKY/SKIP_*` intactos.
Sin probar: la salida hablada («ya está») y el clic sobre la imagen —
no hay `xdotool` y el micrófono falso no mete dos frases en una sesión.

**Las cuatro peticiones del usuario, en orden:**

1. **Enseñar una cámara es el directo, y en grande.** Pedir la entrada
   llamaba a `mirar` y devolvía una foto de quince segundos. Se cambió la
   frontera entre las dos herramientas y el `platform_hint`. De paso,
   `ver_en_vivo` **reventaba** con el argumento que Hermes pasa de verdad
   —el dict entero como primer parámetro, que `mirar` siempre supo y el
   otro no— y decía en voz alta «la imagen en directo no me llega ahora
   mismo», que suena a cámara rota y no lo era. Y una foto de una sola
   cámara nace ya a 900×480.
2. **Responde a su nombre.** «Jarvis» por defecto, con treinta segundos
   de conversación abierta tras cada respuesta. Dos hallazgos: **Whisper
   no oye «Jarvis»** —«Carbis», «Harvish», «Jervis», «Harvies» en una
   mañana, así que el emparejamiento es por parecido y no por igualdad—
   y **el nombre se tiraba antes de que Whisper lo viera**: el detector
   limpiaba el buffer en cada fotograma por debajo del umbral, así que la
   primera sílaba de un turno no sobrevivía. Ahora guarda medio segundo
   de carrerilla; sin eso la palabra de activación no funciona.
3. **Deja de ofrecerse.** Remataba casi cada respuesta con «¿quiere
   que…?» o «si quiere, puedo…». Una regla nueva en la persona. Después:
   «Ya la tiene delante, señor: la entrada, en directo.» Y nada más.
4. **Dos interruptores en la tira**, sus oídos y su voz. Existen porque
   la alternativa no existe: «deja de escucharme» hay que oírlo para
   obedecerlo, y «cállate» hay que oírlo por encima de su propia voz. El
   del micrófono tira los fotogramas en vez de cerrar el stream (cerrar
   PortAudio desde su propio callback es el segfault de §2.8); el de la
   voz corta lo que esté diciendo en el acto.

**Pendiente:** volver a activar `allow_gateway_injection`, las reglas de
alerta, y probar a mano las dos salidas que faltan del directo.

## 2026-08-25 — La cámara en vivo: doce tareas de trece, y una noche de hallazgos ✅⏸

Se le puede pedir que enseñe una cámara **en movimiento** sobre la tira.
Doce de las trece tareas del plan están cerradas con revisión limpia; la
decimotercera —la verificación contra la casa real— necesita voz humana y
queda pendiente.

**Lo que se construyó**, de abajo arriba: el contrato del canal de la
tira gana `live`, `live_end` y tramas binarias con 4 bytes de epoch; el
adaptador sabe empujar bytes; el vigilante de cámaras ofrece un grifo por
paquete; una sesión posee la vista con su tope de dos minutos; dos
órdenes habladas la abren y la cierran; la tira bifurca por tipo antes de
parsear, decodifica H.264 en su propio hilo y lo pinta cada 40 ms; y sólo
el rectángulo del vídeo recibe clics — el arreglo que §12 aplazó en
agosto, ahora hecho con `XShapeCombineRectangles` por ctypes.

**Los cuatro fallos que la revisión pescó, y ninguno lo habría dicho un
test:**

1. **El grifo no se encendía nunca.** `cameras.py` resolvía el tap una
   vez por conexión RTSP, es decir cada varias horas, así que `set_tap`
   sobre una flota en marcha no hacía nada. La función entera habría
   salido como una banda negra. El test que lo «probaba» pasaba porque el
   falso tenía un generador finito y el vigilante reabría en bucle;
   producción no se acaba nunca.
2. **Pedir la cámara podía congelar el cerebro cinco segundos.**
   `codec_parameters()` abría un contenedor si no había, y `open()` es un
   `av.open()` bloqueante con timeout de 5 s, llamado desde el bucle de
   eventos del gateway.
3. **`stop()` podía cerrar el códec con un `decode()` dentro.** Dos hilos
   sobre el mismo contexto C: caída del proceso del widget, no de la
   vista. Ahora, si el hilo no ha muerto, se suelta el códec sin cerrarlo.
4. **El vídeo iba a 4 fps.** El plan puso la recogida de fotogramas en el
   tick de 250 ms de la banda. Medido después del arreglo, capturando la
   banda a 50 Hz y contando fotogramas distintos: **14 por segundo**,
   frente a ~4.

**Y tres cosas que se aprendieron sobre los ojos**, todas medidas:

- Una persona **sentada** en la entrada da 0.62 / 0.71 / 0.64 en veintisiete
  segundos. Con el listón en 0.7 y una sola mirada, `mirar` decía «vacía»
  dos de cada tres veces mientras el vigilante avisaba. `mirar` ahora
  **vota sobre tres fotogramas** y se queda con el máximo.
- Se descargó y probó `yolov9-s` a 640 contra el `yolov9-t` a 320 que
  corre: sube la media seis centésimas, cuesta diez veces más (97 ms
  contra 10) y **no es uniformemente mejor** — es peor en el fotograma que
  el pequeño acierta. Cinco pasadas del pequeño cuestan la mitad que una
  del grande. El modelo grande queda descargado; la palanca era mirar
  varias veces, no mirar mejor.
- Bajar el listón a 0.45 *además* de votar produjo falsos positivos en una
  hora: dos cambios que se multiplican. Revertido al 0.7 de BarnDoor.

**Fuera del plan, la misma tarde:** llegó un micrófono USB y JARVIS oyó
una voz humana por primera vez; la voz clonada resultó ser la de Samantha
porque el clip por defecto nunca se cambió al de JARVIS; y el suelo
nocturno de 30 s se descubrió disparando un turno completo del LLM cada
medio minuto con alguien en la entrada — la GPU al 95% y 68 °C. Cortada
la inyección, 10% y 46 °C.

**Pendiente:** la tarea 13 (hablarle y comprobar las tres salidas), volver
a activar `allow_gateway_injection`, y las reglas de alerta.

## 2026-08-25 — Y al encender: qué arranca solo y qué espera al login ✅

Cola de la entrada de abajo. Aquellas tres causas quedaron arregladas en
caliente; esto es lo que decide el **próximo** encendido, medido sobre el
arranque de hoy (11:10).

**Lo que pasó de verdad al encender:** el gestor de usuario levantó a las
11:12:44 solo `samantha-hermes` y `samantha-hermes-serve`.
`samantha-llamacpp` aún no estaba `enabled` —su enlace en
`default.target.wants` es de las 12:02—, así que el cerebro arrancó sin
modelo detrás. Y `graphical-session.target` no se activó hasta las
**11:57:50**: 47 minutos de máquina encendida sin sesión gráfica.

**Esa espera no es un fallo, es la forma del producto.** La tira es
mueble de un escritorio (`PartOf=graphical-session.target`), y GDM no
tiene autologin. Hasta que alguien inicia sesión no hay `DISPLAY=:1` en
el que existir. Ofrecido activar el autologin y **descartado por el
usuario**: cualquiera que encienda la máquina entraría al escritorio. Se
queda así, y queda escrito para que no se re-diagnostique cada vez.

**Lo que sí se arregló:** `samantha-llamacpp` tenía el limitador de
arranques por defecto —5 en 10 s— con `RestartSec=5`. Hoy a las 12:00 se
rindió tras **cuatro** intentos y quedó parado; el mismo patrón en un
arranque en frío, con el driver de NVIDIA aún no listo, deja el gateway
en pie y mudo. `StartLimitIntervalSec=0`: reintenta indefinidamente. El
limitador es un guardia contra bucles de fallos instantáneos y este
servicio falla un rato y luego funciona.

**Verificado:** las cuatro unidades `enabled`, linger `yes`,
`systemd-analyze --user verify` limpio, `default.target` arrastrando
llamacpp + hermes + hermes-serve y `graphical-session.target` la tira;
`StartLimitIntervalUSec=0` efectivo tras el `daemon-reload` y sin
tocar el proceso vivo; `:8000`, `:7777` y `:8093` escuchando y el modelo
contestando por `/v1/chat/completions`.

**Changed files:** `systemd/samantha-llamacpp.service`
(`StartLimitIntervalSec=0`, y el `--split-mode row` de la entrada de
abajo, que se había quedado sin commitear).

## 2026-08-25 — Arranca el servidor y JARVIS no está: tres causas, ninguna de código ✅

El síntoma era «el servidor se inicia y no vemos a Jarvis activo». Hermes
y CosyVoice estaban en pie; la tira, no. Tres causas encadenadas, y las
tres son despliegue que nunca se re-aplicó, no lógica rota:

**1. La unidad instalada apuntaba a un worktree borrado.**
`~/.config/systemd/user/samantha-widget.service` seguía siendo la copia
del 23-ago, con `ExecStart` en
`.claude/worktrees/widget-gtk4-spec/widget/.venv/bin/python`. Ese
worktree ya no existe. La versión correcta llevaba en `systemd/` desde el
24-ago sin que nadie ejecutara el `cp` del §5. Y ni ella ni
`samantha-llamacpp` estaban `enabled`: aunque se arreglara el
`ExecStart`, un reinicio volvía a dejar la pantalla vacía.

**2. `samantha-llamacpp.service` no estaba instalado en absoluto**, así
que `:8000` no escuchaba mientras Hermes apunta a `custom:local` →
`http://127.0.0.1:8000/v1`. Con la tira en pantalla, cada turno habría
muerto igual.

**3. `--split-mode row` dejó de ser inofensivo.** Al instalar la unidad,
llama-server se negó a cargar: `device CUDA0 does not support split
buffers`. La flag reparte tensores entre **varias** GPUs y aquí hay una;
el `improvement-sweep` del 04-ago ya la había marcado como no-op que
sobraba, pero la corrección nunca llegó al fichero. En la build de
llama.cpp del 23-ago ha pasado de no-op a error fatal. Medido las dos
veces: con la flag el modelo no carga; sin ella, `/health` responde a los
4 s.

**El comando del §5 para comprobarlo estaba mal**, y es la razón de que
esto parezca peor de lo que era: `xwininfo -name "samantha-widget"`
contesta *No window with name … exists!* con la tira dibujada en
pantalla, porque `window.py:36` la titula **«Samantha»**. Corregido en
CLAUDE.md, con el porqué.

**Verificado en vivo:** ventana `0xa00004 "Samantha"` en `900x96+510+984`,
captura con la línea terracota en reposo sobre el escritorio, WebSocket
establecido contra `127.0.0.1:7777`, 22.9 GB de 24.5 en la GPU, y un
turno entero por el socket del kiosko — «Siempre oído, señor.». De
paso quedó medido que el adaptador del kiosko admite **una** conexión:
el probe desplazó a la tira, la tira reconectó y cerró el probe.

**Changed files:** `systemd/samantha-llamacpp.service` (fuera
`--split-mode row`, con el porqué), `CLAUDE.md` (§5, el `xwininfo`).
Sin cambios en el widget ni en los plugins.

## 2026-08-25 — La foto a demanda: se le puede preguntar, y la tira crece ✅

Le dices «enséñame la entrada» y la foto aparece sobre la tira quince
segundos; un clic la pone a tamaño nativo y reinicia el reloj; se va
sola. Es la primera vez que la cámara responde en lugar de solo llamar a
la puerta.

**La decisión que sostiene todo lo demás:** lo que dice el modelo son
**palabras**, y viajan a donde viaje el turno —hoy la tira, y cualquier
plataforma que se configure el día que se configure—. La **imagen** viaja
por un canal aparte, del plugin a la tira,
por el WebSocket de loopback que esos dos procesos ya compartían. Ningún
otro adaptador la ve nunca. El convenio `MEDIA:` de Hermes encajaba y se
descartó justo por lo que es: un convenio **de plataforma**, pensado para
que cualquier adaptador lo pinte. Una propiedad de privacidad sostenida
por convenio no está sostenida.

**Verificado en vivo**, con la casa real y el gateway de siempre: el
fotograma de la cámara —gris, con la marca de hora quemada— encima de la
onda, la tira transparente alrededor. Medido: `900x210` en `510,870` con
la miniatura, `900x480` al hacer clic, y vuelta exacta a `900x96` en
`510,984` tanto por el segundo clic como por el desvanecido, con
`_NET_WM_STATE_ABOVE/STICKY/SKIP_*` intactos todo el rato.

**Changed files:** `Hermes/plugins/samantha_vision/` — `snapshot.py` y
`tool.py` (nuevos), `cameras.py` (`CameraFleet.grab`), `__init__.py` (el
registro del tool y `push_photo`), `plugin.yaml` (pillow), `README.md`,
`tests/`. `Hermes/plugins/samantha_kiosk/` — `protocol.py` (el frame
`photo`), `adapter.py` (`push_photo` y la validación de la ruta),
`__init__.py` (el `platform_hint`), `tests/`.
`Hermes/samantha-config.yaml` (el toolset `camaras`),
`Hermes/setup-runtime.sh` (pillow).
`widget/samantha_widget/` — `photo.py` y `photo_area.py` (nuevos),
`window.py` (la tira crece hacia arriba), `ewmh.py` (`geometry()`),
`geometry.py` (`placement_is_wrong`), `gateway.py` (el frame `photo`, y
un tipo desconocido deja de ser un error), `__main__.py`
(`SAMANTHA_WIDGET_PHOTO`), `README.md`, `tests/`. `CLAUDE.md` (§0, §4,
§9 y dos entradas del §12), la cabecera de estado del diseño de la
instantánea, y esta bitácora.

**Tests:** 140 del widget (eran 110), 130 del plugin de visión (eran 83)
y 45 del kiosko, todos en verde. Ninguno necesita cámara, GPU ni red: la
foto se prueba con un array sintético, el frame con cadenas, y el reloj
del desvanecido se inyecta. Cada tarea aplicó mutaciones y las vio en
rojo contra el test que las guarda; la revisión reprodujo las suyas.

**Notas:**

- **Llama a `mirar` sin argumento, 5 de 5**, aunque el usuario haya
  nombrado la cámara. Es decir: una pregunta sobre una cámara se
  responde con un repaso de todas. Se probó a deletrearlo en la
  descripción del esquema («omitir SOLO si no se ha nombrado ninguna»):
  3 medidas más, sin cambio, y se revirtió. Una edición de prompt que no
  funciona es ruido en el fichero; y a dónde llega el resultado del tool
  es una cuestión de diseño, no de redacción.
- **Nuestra propia frase le regaló la palabra «cámara»**, que el §1 de
  CLAUDE.md le prohíbe decir. Nosotros escribimos `La cámara de {camara}
  no responde.` y él lo repitió: «…y la cámara de fuera no responde». No
  se puede culpar al modelo de repetir una frase que le hemos escrito
  nosotros. Ahora dice `En {camara} no alcanzo a ver ahora mismo.` —el
  mismo molde que las otras dos, que es el único con evidencia detrás.
- **`vision` ya estaba cogido.** Es un toolset **propio de Hermes** y
  lleva `vision_analyze`, análisis de imágenes que esta caja no puede
  servir: el modelo de la tira es Qwen3.8-27B y no mira imágenes.
  Listarlo para llegar a `mirar` le ofrecía además esa otra herramienta,
  que es exactamente lo que `check_fn` existe para evitar, un nivel más
  arriba. El tool vive en un toolset nuestro, `camaras`.
- **Se inventa detalle visual que no puede ver.** «Puerta cerrada, el
  porche vacío», contra un tool que solo había dicho «En la entrada no
  hay nadie». Es de texto y nunca ve el JPEG: todo lo que añada más allá
  de las ocho etiquetas de YOLO es inventado. No se arregla en la capa
  del tool —la frase ya es mínima—; queda en manos de quien decida la
  personalidad.
- **Destroza un nombre pelado:** `fuera` salió como **«Fuora»**, porque
  «En fuera no alcanzo a ver» no es castellano natural y él lo repara.
  Arreglarlo de verdad es dar a cada cámara una forma hablada en la
  config, que es un cambio de esquema y una decisión sobre cómo se
  llaman los sitios de esta casa. Sin hacer, a propósito.
- **Le dijo al usuario que no tenía pantalla mientras se le empujaba la
  foto:** «Sigo sin poder enseñarle nada en una pantalla, señor — aquí
  solo hay voz», y una vez sugirió abrir Hermes Desktop en su lugar. Era
  cierto hasta que la banda existió. El `platform_hint` del kiosko se
  corrigió **en el mismo cambio** que le dio la pantalla; enviar una
  pantalla diciéndole que no la hay es justo el fallo de «la
  documentación describe código que no existe» que este proyecto lleva
  cinco veces cometiendo. Recuérdese el §7: un hint solo alcanza a una
  sesión viva tras `/new` y `/approve`.
- **Los handlers async de un plugin no corren en el bucle del gateway.**
  Hermes los puentea con `_run_async`, que dentro de un bucle en marcha
  ejecuta la corrutina en un **hilo desechable con bucle propio**. La
  decisión (async + `to_thread`) sigue siendo la buena y es barata, pero
  su razón declarada —«bloquear dos segundos el bucle pararía todos los
  turnos de la casa»— era falsa. Se anota porque una regla con la razón
  equivocada la cita después alguien que se cree la razón.
- **La tira crece hacia arriba, y el reintento de colocación funciona
  por el ORDEN EN LA CONEXIÓN X**, no porque GTK haya maquetado en el
  idle. Las dos peticiones bajan por la misma conexión y mutter atiende
  los ConfigureRequest en orden de llegada, así que cuando restringe la
  segunda ya ha aplicado el tamaño de la primera. La primera versión del
  comentario decía «en el idle el tamaño nuevo ya está puesto», que es
  maquetación de GTK —que no es contra lo que mutter restringe, y que el
  idle ni siquiera espera: el frame clock va a prioridad 120 y sujeto al
  reloj, y el idle, a 200, se cuela antes con frecuencia—. El arreglo era correcto y la razón escrita no; así es
  exactamente como el siguiente borra la línea buena.
- **Dos defectos que solo aparecieron ejecutándolo**, los dos ya
  arreglados: al encoger, la tira se quedaba flotando en `y=600` —mutter
  restringe el movimiento contra el tamaño que aún cree que tiene—, y
  una pulsación sobre el aire transparente de la banda ampliaba la foto.
  Ahora hay test de impacto real y se relee la geometría para comprobar
  que el gestor de ventanas obedeció.
- **Lo que sigue sin hacerse, a propósito:** la banda transparente se
  traga los clics del escritorio los segundos que la foto está puesta
  —900x210, o 900x480 ampliada—. El arreglo honesto es
  `XShapeCombineRectangles` a mano (`set_input_region` quiere una
  `cairo.Region`, y Cairo es la trampa sobre la que está construida esta
  máquina), un mecanismo X nuevo en el fichero cuyo EWMH costó días. El
  riesgo del arreglo supera el daño del defecto esta semana.
- **`fuera` está físicamente apagada**, así que «dos cámaras, dos fotos»
  está probado **solo por camino de código**.
- **Sigue sin haber tabla de detecciones ni `revisar`.** «Quién vino
  esta mañana» no tiene respuesta: es el plan 2 del diseño de visión.
  Tampoco hay vídeo en directo: se consideró y se descartó —un
  decodificador más, ancho de banda continuo y una ventana que se queda—.

---

## 2026-08-24 — Repaso de rama: deja de repetirse, y la contraseña sale de la URL ✅

La revisión de la rama entera antes de subirla. Siete arreglos, y dos de
ellos son de los que solo se ven mirando el sistema vivo.

**Lo que se corrigió:**

- **Cuatro sitios afirmaban, como medida, algo falso.** «`inject_message`
  devuelve `False` cuando la tira no ha hablado nunca» no es cierto.
  Leído en la fuente fijada: `False` solo sale de tres sitios —
  `session_key` ausente, permiso denegado, y no haber gateway vivo. La
  sesión inexistente se resuelve **dentro de la corrutina**:
  `_schedule_plugin_message_injection` ya ha devuelto `True`
  (`gateway/run.py:18715`) cuando `_dispatch_…` mira y no encuentra fila
  (`:18729`), y **lo avisa el propio Hermes** desde un done-callback:
  `Plugin message injection was not routed`. Es decir, nuestra línea «no
  hay a quién decírselo» **no podía saltar nunca por el caso para el que
  se escribió**, y el README mandaba a buscar al journal un mensaje que
  no existe. Corregido en `alert.py`, el README, el diseño y CLAUDE.md.
  El calendario de reintentos no se toca: para el caso «aún no está
  arriba» sigue siendo el correcto.
- **No había timeout de socket. Ninguno.** ffmpeg renombró la opción del
  demuxer rtsp de `stimeout` a `timeout`, y una opción desconocida se
  descarta **sin avisar**. Sondeado contra `127.0.0.1:1` con
  `av.logging.DEBUG` (PyAV 18.1.0 / libavformat 62):

      stimeout=5000000 -> Connection to tcp://127.0.0.1:1?timeout=0
      timeout=5000000  -> Connection to tcp://127.0.0.1:1?timeout=5000000

  `timeout=0` es infinito. Una cámara que se muere **a mitad de stream**
  —un switch que se reinicia, un TCP medio abierto— dejaba su hilo
  clavado dentro de `decode()` para siempre: sin excepción, sin log, sin
  backoff y sin reintento. Ciega en silencio hasta reiniciar el gateway.
  `fuera` solo fallaba rápido porque «no route to host» es enrutado, no
  timeout. Ahora se pasan **las dos** opciones: una desconocida se
  ignora, así que vale en las dos direcciones.
- **Dejó de repetirse.** Medido en el gateway vivo: `entrada: alguien` a
  las 15:35, 15:41, 15:53, 16:02 y 16:10 — cinco en 35 minutos, unos 480
  turnos hablados y 480 llamadas al modelo al día, toda la noche
  incluida. Los 180 s paraban el spam de tres segundos y nada paraba el
  de tres minutos. Ahora la ventana **se ensancha** con las repeticiones
  consecutivas: 180 s → 15 min → cada hora, y vuelve al suelo cuando ese
  `(cámara, etiqueta)` lleva una ventana entera sin verse. La primera vez
  nunca se calla, y los 180 s siguen siendo el suelo de BarnDoor. La
  regla nocturna queda **fuera** de la escalada en las dos direcciones:
  ni la ventana ensanchada la silencia, ni sus disparos suben el nivel
  —contarlos la convertiría en su contraria en cuanto amaneciera.
- **Una cámara que conecta y no da vídeo era invisible.** No lanza nada,
  así que el `except` no corría, no se registraba nada a ningún nivel y
  el backoff subía a cinco minutos en silencio. Indistinguible de una
  cámara con la calle vacía delante. Ahora se cuentan los fotogramas por
  intento: cero fotogramas es un WARNING, una vez, con la misma
  disciplina que `unreachable`. Es el modo de fallo #4 del manifiesto.
- **El camino de caja nueva no funcionaba.** `setup-runtime.sh` no
  instalaba `av`, `onnxruntime` ni `numpy` —`uv sync` no los trae; el
  extra `voice` salió de `[all]` a favor del lazy-install, así que en
  esta caja existen solo porque Hermes los instaló para el STT— y el
  bucle de «habilitar» no incluía `samantha-vision`. Y
  `check_requirements()` era **código muerto**: nada en
  `hermes_cli/plugins.py` lo llama, es un convenio de `kind: platform`
  que se pasa como `check_fn` a `register_platform`, y este plugin es
  `standalone`. Borrado, y el README corregido: lo que pasa de verdad en
  una caja sin ellos es una línea, `no detector, no cameras watched`.
- **La contraseña sale de la URL** (petición directa). Vive en `.env` en
  la raíz —ignorado por git, con `.env.example` versionado para que una
  caja nueva sepa qué falta—, `Hermes/run-gateway.sh` lo carga (es el
  único cuello de botella: las dos units que arrancan un proceso de
  Hermes —`samantha-hermes.service` y `samantha-hermes-serve.service`— y
  toda invocación manual pasan por ahí; la del widget no, y no necesita
  credencial) y las URLs dicen `${RTSP_PASSWORD}`. La trampa, que está
  tratada explícitamente: una variable **sin definir** quedaría como el
  texto literal `${RTSP_PASSWORD}`, que se usaría de contraseña y
  acabaría en el journal. `_expand` hace la sustitución él mismo y
  resuelve cada nombre dentro del callback; una variable que falta tira
  esa cámara con un aviso que la nombra —sin conectar y sin registrar la
  URL—. **No** usa `os.path.expandvars`, que expande también un `$NAME`
  pelado: una contraseña puede llevar un `$`, y eso costó un fragmento de
  contraseña en el journal hasta que el patrón se limitó a las llaves.
- **El README versionado deja de ser un mapa a la credencial.** Este
  repo se sube a GitHub y ahí estaban la subred, las dos direcciones, el
  fabricante, la cuenta, la ruta del stream, el fichero con la
  contraseña, la variable dentro de él y el dato de que abre también el
  Frigate de BarnDoor. Todo el campo menos el secreto, más las
  indicaciones para llegar al secreto. Direcciones sustituidas por
  marcadores, aquí y en `samantha-config.yaml` y en esta bitácora; los
  valores reales viven junto a las URLs que describen.

**Menores:** `redact()` en los dos logs de excepción de `alert.py`;
`stop()` itera una copia de la lista de hilos; el diseño decía
`shutdown()` donde la API es `ctx.on_unload(fleet.stop)`; el modo de
fallo #2 del manifiesto decía «no se repite» cuando sí se repite a
DEBUG; `height, width` calculados y borrados en `detect()`; comentarios
de import perezoso que no diferían nada.

**Tests:** 83 del plugin (eran 64) y 110 del widget, todos en verde. Los
nuevos: la cámara que no da fotogramas, la expansión de `${VAR}` y la
variable sin definir, la escalada y su reinicio, `register()` que vuelve
enseguida aunque leer la config bloquee, `_supervise` que se traga una
config que revienta, y dos cámaras con la misma etiqueta dentro de la
ventana. Los dobles de cámara muerta ahora fallan desde `frames()`, que
es donde falla el código real —`CameraStream.__init__` solo guarda la
url—; con la forma antigua ni el timeout ni los cero fotogramas podían
haberse detectado aquí.

**Verificado en vivo** tras reiniciar el gateway: las dos cámaras
vigiladas, la contraseña expandida desde `.env` y redactada en el log.

    samantha-vision: watching 2 camera(s): fuera, entrada
    samantha-vision: fuera unreachable — [Errno 113] No route to host:
      'rtsp://admin:***@…'

**Lo que quedó señalado aquí y se hizo en la re-revisión:** una persona a
las 3 de la mañana disparaba en **cada fotograma muestreado**, no cada
180 s —19.200 frases en una noche de ocho horas, medido—. El usuario
eligió un suelo de 30 s (`NIGHT_FLOOR_SECONDS`), que lo deja en 960. La
regla nocturna de BarnDoor sigue en pie: sigue ganándole a la ventana de
180 s y sigue fuera de la escalada. Silenciar la noche no se diseñó nunca
y sigue sin hacerse: un coche a las 3 se anuncia igual que a mediodía.

---

## 2026-08-24 — La visión se muda al cerebro: el plugin `samantha_vision` ✅

Las cámaras dejan el widget y pasan a vivir dentro del gateway, como
plugin `samantha_vision`. Dos cámaras **con nombre** (`fuera`,
`entrada`), un hilo cada una, las mismas reglas de silencio de siempre
pero con la cámara dentro de la clave del anti-spam. El widget vuelve a
ser la tira: dibuja, escucha y habla.

Sustituye a la entrada del 2026-08-23 («Vista: las cámaras hablan»), que
sigue siendo correcta en todo menos en dónde vive esto.

**Verificado contra la casa real** — una cámara encendida (`entrada`),
la otra apagada (`fuera`), nada simulado:

```
entrada: alguien
← El de la entrada sigue plantado donde está, señor.
```

**Changed files:** `Hermes/plugins/samantha_vision/` entero
(`__init__.py`, `cameras.py`, `alert.py`, `vision.py`, `plugin.yaml`,
`README.md`, `tests/`), `Hermes/samantha-config.yaml`,
`widget/samantha_widget/__main__.py` (se va el hilo de cámara),
`widget/README.md`, `CLAUDE.md` (§0, §2.3, §3, §4, §5, §9, §12),
`docs/superpowers/specs/2026-08-24-samantha-vision-plugin-design.md`
(§3, con lo que midió la sonda), `PROGRESS.md`. Se van
`widget/samantha_widget/vision.py` y `widget/tests/test_vision.py`, que
se mudan con lo demás.

**Tests:** 64 del plugin y 110 del widget, todos en verde. Ninguno
necesita cámara, GPU ni red: lo único que toca el mundo —construir el
detector y abrir un stream— entra como callables que los tests
sustituyen.

**Notas:**

- **La sonda decidió el diseño entero de la alerta, y salió barata.**
  Antes de escribir nada se midió cómo habla un plugin sin que nadie le
  pregunte. Tres hallazgos: **no hay ningún hook posterior al registro**,
  así que `register(ctx)` es la única puerta y tiene que arrancar sus
  propios hilos; la entrega es `ctx.inject_message(texto, role="user",
  session_key=…)` y **solo sabe empujar un mensaje de usuario** —no
  existe forma de ponerle palabras acabadas en la boca, que es justo la
  propiedad que queríamos; y `allow_gateway_injection` es un permiso por
  plugin, apagado por defecto. Eso convierte «se le avisa, no se le hace
  recitar» (CLAUDE.md §1) en una propiedad del mecanismo y no de nuestra
  disciplina. Todo con file:line, ahora en el §3 del diseño; `PROBE.md`
  se borra porque su contenido está allí.
- **El plan traía cuatro errores de detalle que solo aparecen
  compilando.** `ctx.log` no existe (se usa `loguru`); `Detection` tiene
  `confidence`, no `score`; `parse_cameras` tal como estaba escrita
  reventaba con una lista pelada de URLs, es decir, una errata en una
  cámara dejaba a la casa sin ninguna; y el `settings:` del que cuelgan
  las cámaras no estaba.
- **La forma del prompt importaba más que su contenido.** `"en la
  {camera}"` y `"en {camera}"` producen los dos español roto con una
  cámara llamada `fuera` —los nombres son sustantivos pelados, sin
  artículo— y el modelo **no se encoge de hombros: lo repara**
  inventando un sitio que encaje. Medido dos veces en el gateway vivo:
  la cámara que mira a la calle veía a alguien y él informaba de la
  entrada. Un sitio equivocado, no una frase torpe, en una función cuyo
  trabajo entero es decirte quién anda por la casa. La solución fue
  dejar de meter el nombre dentro de una preposición: se le entrega
  etiquetado, `Dónde: fuera. Qué: alguien.`, y él elige la suya.
- **`ctx.get_config("cameras")` lee
  `entries.<id>.settings.cameras`, no la raíz de la entrada.** La forma
  que traía el plan habría dejado el plugin cargado, sin hilos y sin una
  sola queja audible: «no cameras configured» en el journal y él sin
  mencionar a nadie nunca. Es el error que esta configuración invita.
- **`apply-config.sh` fusiona diccionarios en profundidad pero
  reemplaza listas enteras.** Una lista `cameras:` de ejemplo en el
  `samantha-config.yaml` versionado habría pisado las cámaras de verdad
  en la siguiente ejecución. Por eso ahí la forma va **comentada**: un
  comentario no puede machacar nada.
- **PyAV mete la URL RTSP completa, con contraseña, en cada mensaje de
  error.** Llegó al journal en claro una vez antes de que existiera
  `redact()`. Ahora todo lo que se registra pasa por ahí.
- **`inject_message` falla casi siempre al primer intento**, y no es un
  fallo: el inyector se instala solo después de que conecten *todos* los
  adaptadores de plataforma. Se reintenta 1 s, 3 s, 5 s y luego se
  **descarta** la detección. Encolarlas sería peor: le haría recitar
  noticias viejas en cuanto la tira conectase, que es exactamente la
  máquina hablando que prohíbe §1. **Corregido el 2026-08-24:** este
  párrafo decía además que una caja donde la tira no ha hablado nunca
  devuelve `False` para siempre. Es falso — eso vuelve `True` y lo avisa
  Hermes por su cuenta. Ver la entrada de ese día.
- **Las cámaras dentro del cerebro son un riesgo real.** Si un hilo
  tumba el gateway se cae todo, no solo la vista. Cada hilo captura
  cualquier excepción, avisa una vez y reintenta con backoff de 30 s
  hasta un techo de 5 minutos; una cámara apagada es un martes, no un
  error, y nunca cuesta las demás.
- **Falta lo mismo que faltaba ayer: nadie puede preguntarle qué ve.**
  El plugin no registra ninguna herramienta y no recuerda nada. `mirar`,
  `revisar` y la tabla de detecciones son el plan 2.

---

## 2026-08-23 — Vista: las cámaras hablan ✅

El widget mira las cámaras de la casa y, cuando ve algo que merece la
pena, lo dice con sus palabras. Código reutilizado de
[BarnDoor](~/git/barndoor); nada de aquel proyecto viene con él.

**Verificado de extremo a extremo** con un clip real de la cámara
exterior, porque las cámaras están apagadas y hay 1896 grabaciones en
disco:

```
cámara: alguien
← Oye. Hay alguien fuera de casa.
```

**Changed files:** `widget/samantha_widget/{vision,__main__}.py`,
`widget/tests/test_vision.py`, `widget/README.md`,
`docs/superpowers/specs/2026-08-23-samantha-widget-gtk4-design.md` (§5.7).

**Tests:** 126 passed, ruff limpio. Ninguno necesita cámara ni el
modelo de 8 MB.

**Lo que se trajo de BarnDoor, y lo que no:**
- **Sí:** el reparto RTSP de las cámaras y `yolov9-t-320.onnx`.
- **No:** Frigate, MQTT, Telegram, su agente LangGraph. No hay
  acoplamiento entre los dos proyectos.
- **Coste en dependencias: cero.** `onnxruntime` ya estaba por Silero y
  PyAV llegó con faster-whisper.

**Notas:**

- **Ella es avisada, no obligada a recitar.** Una detección no se
  convierte en voz directamente: se convierte en un `chat` por el mismo
  camino que cualquier cosa que diga el usuario, con un prompt que pide
  una frase corta y prohíbe mencionar cámaras o detecciones. "Persona
  detectada en exterior" sería una máquina hablando, y CLAUDE.md §1 dice
  que nunca actúa *usando* sus herramientas. Cuesta una llamada al
  modelo, que sale barata justamente porque el Watcher la hace rara.
- **Detectar es la mitad fácil.** Revisar `agent/rules.py` de BarnDoor
  —sugerencia del usuario— aportó los números que yo habría puesto mal:
  umbral 0.7 (el mío era 0.45, a ojo), anti-spam de 180 s por etiqueta,
  y una persona entre las 23:00 y las 07:00 se salta ese silencio. Solo
  personas: un coche aparcado hablaría toda la noche.
- **Sin el anti-spam la cámara diría "alguien" cada tres segundos**
  mientras alguien esté en la entrada. Eso es exactamente el agente
  visible que §1 prohíbe, además de insoportable.
- El sub-stream, muestreando un fotograma de cada diez. La GPU es de
  Whisper y CosyVoice, que están en el camino crítico de una
  conversación; una cámara no.
- **Falta:** nadie puede preguntarle qué ve. La cámara habla pero no se
  la puede interrogar — eso pide exponer la visión como herramienta de
  Hermes, no como un hilo empujando prompts.
- Las dos cámaras estaban apagadas durante todo este trabajo. Todo lo
  verificado lo está contra grabaciones reales. Sus direcciones viven
  junto a las URLs que describen, en `.hermes/home/config.yaml`, y no
  en un fichero que se sube a GitHub.

---


## 2026-08-23 — Widget plan 2: the voice turn ⏸ blocked on hardware

Everything between the microphone and her voice is built, wired and
running: VAD, transcription, the WebSocket to Hermes, clause-by-clause
synthesis and playback, and the state machine that drives the wave.
**It has never heard anybody**, because this machine has no microphone
plugged in — the input captures digital silence (RMS exactly 0.0000 on
an unmuted source). Task 8 of the plan is the only one left, and it
needs a microphone, not code.

**Design:** `docs/superpowers/specs/2026-08-23-samantha-widget-gtk4-design.md`
**Plan:** `docs/superpowers/plans/2026-08-23-samantha-widget-voice-turn.md`
**Probe:** `docs/superpowers/specs/2026-08-23-widget-gateway-probe.md`

**Changed files:** `widget/samantha_widget/{gateway,vad,stt,speech,audio,
turn,__main__}.py`, `widget/tools/probe_gateway.py`,
`widget/tests/test_{gateway,vad,stt,speech,turn}.py`,
`widget/{pyproject.toml,README.md}`, `systemd/samantha-widget.service`,
`systemd/samantha-hermes.service`, and the probe write-up.

**Tests:** 72 passed in `widget/`, ruff clean.

**Measured, not assumed:**
- CosyVoice synthesises 3.52 s of audio in 1.0 s; Whisper transcribes it
  in 0.23 s and loads in 81 s the first time (~1 s after).
- Whisper sits at ~2.5 GB of VRAM next to CosyVoice (5.3 → 7.8 GB).
- The loop was closed without a microphone by having CosyVoice speak a
  sentence and Whisper transcribe it back.

**Notes — what this cost and what it found:**

- **Samantha's words were being sent to Microsoft.** The agent's own
  `text_to_speech` tool was synthesising through Edge TTS, because
  Hermes' default `tts.provider` is `edge` and the repo's Hermes config
  had no `tts:` section. Found by checking the format of the cache file
  (MP3 = Edge; CosyVoice yields WAV/PCM). Fixed and verified. **The
  config is git-ignored, so this must be redone on the appliance.**
- **The committed `samantha-hermes.service` could not start.** systemd
  runs it from `%h`, so the adapter's relative `frontend/dist` resolved
  to `~/frontend/dist`. Fixed with `WorkingDirectory=`.
- **A second Hermes was running** — the machine's personal one, the old
  remote access to Samantha — holding the profile the repo's pinned
  gateway wanted. Stopped and disabled at the user's request.
- **The gateway narrates itself in English, with emoji**, through
  ordinary token frames, and each carries its own `done` (one turn had
  six). Both would have reached her voice and her wave. Filter added,
  and `done` no longer ends a turn on its own.
- **PortAudio's `callback=` mode segfaults** under GTK: no traceback,
  and it surfaces inside whatever unrelated `import` happens to be
  running, which sent this after concurrent imports for three rounds.
  Reading blocking from our own thread fixes it. `SAMANTHA_WIDGET_NO_MIC`
  exists because isolating the microphone is what found it.
- **`--system-site-packages` also exposes `~/.local/lib`**, and numpy /
  anyio / websockets were being loaded from there at mismatched
  versions. `PYTHONNOUSERSITE=1` plus `pip install --ignore-installed`.
  `pip list --local` is the only honest view of what the venv holds.
- **Clauses were being synthesised concurrently** and their PCM chunks
  interleaved in the player. They are strictly sequential now.
- **Hermes still answers as "Hermes, tu asistente"** and offers `/help`
  to a person with no keyboard. Plan 3's problem, and the likeliest
  reason the widget fails to convince.

---


## 2026-08-23 — Widget plan 1: the strip ✅

A borderless, transparent, always-on-top bar along the bottom edge of the
screen, with Samantha's wave animating through four states, running as a
systemd user service. First step of replacing the Chromium kiosk with a
native GTK4 desktop widget (decision taken 2026-08-22, written up today).

**Design:** `docs/superpowers/specs/2026-08-23-samantha-widget-gtk4-design.md`
**Plan:** `docs/superpowers/plans/2026-08-23-samantha-widget-strip.md`

**Changed files:**
- `widget/` (new top-level directory, approved by the user 2026-08-23):
  `pyproject.toml`, `README.md`, `samantha_widget/{__init__,__main__,theme,
  geometry,ewmh,window,wave_model,wave}.py`, `tools/render_wave.py`,
  `tests/{test_imports,test_ewmh,test_geometry,test_wave_model}.py`
- `systemd/samantha-widget.service` (new)
- `docs/superpowers/specs/2026-08-23-samantha-widget-gtk4-design.md` (new,
  §4 revised during execution)
- `docs/superpowers/plans/2026-08-23-samantha-widget-strip.md` (new, tasks 1,
  6 and 7 annotated with what actually happened)
- `docs/superpowers/plans/2026-08-23-samantha-widget-voice-turn.md` (new,
  plan 2 — not started)

**Tests:** 20 passed in `widget/`, ruff clean. `backend/`, `frontend/`,
`Hermes/` and `tts-server/` untouched — verified by diff, not by assertion.

**Notes — what the plan got wrong, which is most of what was learned:**

- **Cairo does not work on this machine.** PyGObject needs `gi._gi_cairo`
  from the system package `python3-gi-cairo` to hand a `cairo.Context` to a
  draw function. `python3-cairo` IS installed, which makes it misleading:
  the failure is a `TypeError` raised inside the draw callback, where GTK
  swallows it — the strip appears, never draws, and logs nothing. Replaced
  with `Gsk.PathBuilder` + `Gtk.Snapshot.append_stroke` (GTK 4.14), which
  needs no extra package and composites on the GPU. Spec §4 revised.
- **`--system-site-packages` makes pip treat system packages as satisfying
  a requirement**, so `pip install pytest` was a silent no-op and the venv
  was using the system's runner. `--ignore-installed` pins it locally.
- **systemd needs the package installed, not just present.** Every start
  died with `No module named samantha_widget` while running it by hand from
  `widget/` worked — the current directory was covering for it.
  `pip install -e .` is now in the plan and the README.
- **E402 is off in ruff's default set**, so the `# noqa: E402` that
  PyGObject's require_version-before-import pattern demands was itself
  flagged as unused (RUF100). Enabled explicitly.
- **Verification kept lying.** `xdotool` is not installed, so states cannot
  be photographed by sending a keystroke — hence `SAMANTHA_WIDGET_STATE`.
  Then the screen locked mid-run and every screenshot silently captured the
  lock screen instead of the strip: a plausible image of the wrong thing.
  `tools/render_wave.py` renders each state offscreen, immune to that.
- **Shape changed twice during the run, at the user's request:** from a
  floating 1100 px terracotta card to a full-width bar, then to a
  transparent background with the terracotta moved into the line itself.
  `theme.STRIP_MAX_WIDTH` and `theme.BACKGROUND` are the two knobs back.
- **GNOME places it at x=66, width 1854, not 0/1920.** The Ubuntu dock
  reserves those pixels from normal windows. Taking them needs
  `_NET_WM_WINDOW_TYPE_DOCK`, which also gives up keyboard focus; the user
  chose to leave it.
- **Two things not verified.** That it survives a workspace switch (would
  have moved the user's desktop while they were working), and the service
  running from the canonical path — the installed unit currently points at
  the worktree, because `widget/` does not exist on `development` yet.
- **The kiosk was never installed on this machine.**
  `systemctl --user is-enabled samantha-ui.service` returns `not-found`, so
  the "leave the fallback intact" constraint had nothing to preserve here.
  Nothing was removed regardless.

---

## 2026-06-20 — Bugfix Sweep (2026-06-11 plan) ✅

23-task sweep fixing the daily-conversation path, backend robustness, frontend robustness, and deploy issues found in a full-project review.

**Fase 1 — Conversation core:**
- Task 1: Stop duplicating current user message in LLM context (collect → persist ordering).
- Task 2: Abort recognition before transcript reset so mic stays muted during TTS.
- Task 3: Abort TTS and recognizer on unmount; clear activeRef first.
- Task 4: Restart mic immediately on barge-in; keep interruption transcript via bargedInRef.
- Task 5: Drop empty reply bubble on chat failure; honest Samantha-voiced error copy.

**Fase 2 — Backend robustness:**
- Task 7: Generic exception handler returns JSONResponse(500) instead of re-raising.
- Task 8: Memory init and per-turn memory work moved off the event loop (asyncio.to_thread); ShortTermBuffer gains a threading.Lock.
- Task 9: WS loop survives malformed messages, binary frames, and mid-stream disconnects; MAX_WS_MESSAGE_CHARS cap.
- Task 10: SAMANTHA_MODE validated and normalized at startup; unknown values raise ValueError.
- Task 11: TTS read timeout applied to synthesis streams (wedged server no longer hangs /speak).
- Task 12: Hermes path gets facts + semantic recall injected into system prompt.

**Fase 3 — Frontend robustness:**
- Task 13: Global keyboard shortcuts ignored while typing in editable elements.
- Task 14: Serialize chat turns — concurrent sends clobbered WS handlers.
- Task 15: Surface microphone permission errors via isMicrophoneAvailable effect.
- Task 16: Kill switch skips VAD init (no mic stream, no CDN fetches) when barge-in disabled.
- Task 17: Dispose Three.js geometries and materials on OS1Loader unmount.
- Task 18: Strip debug logging, fix emoji residue (ZWJ + combining keycap), move @types dep.

**Fase 4 — Deploy & TTS server:**
- Task 19: Add missing samantha-backend.service and samantha-ui.service systemd units.
- Task 20: Move hermes API key out of committed unit file (rotate on kiosk box).
- Task 21: CosyVoice server — clip audio before int16 cast; pin upstream clone.
- Task 22: is_available() exhaustive dispatch; unified default fallback; purge stale docs across tts.py/config.py/api.py/memory.py/schemas.py.

**Changed files:** `backend/samantha/api.py`, `backend/samantha/config.py`, `backend/samantha/memory.py`, `backend/samantha/real_llm.py`, `backend/samantha/schemas.py`, `backend/samantha/short_term.py`, `backend/samantha/tts.py`, `backend/tests/test_api.py`, `backend/tests/test_short_term.py`, `backend/tests/test_tts.py`, `frontend/src/screens/ConversationScreen.tsx`, `frontend/src/core/useKeys.ts`, `frontend/src/core/useBargeIn.ts`, `frontend/src/core/store.ts`, `frontend/src/core/sanitize.ts`, `frontend/src/components/OS1Loader.tsx`, `frontend/package.json`, `tts-server/cosyvoice/server.py`, `tts-server/cosyvoice/Dockerfile`, `systemd/samantha-backend.service`, `systemd/samantha-ui.service`, `systemd/samantha-hermes.service`

**Tests:** 75 passed, 1 pre-existing failure (test_synth_produces_riff_wave — piper not installed on dev machine). Frontend: tsc clean, pnpm build succeeds.

**Notes:**
- The piper test failure is not new — `piper` module is not installed in the dev venv. On the kiosk box with piper installed it passes.
- Task 6 (Fase 1 smoke test) is manual — verify in the real kiosk environment.

---

## Phases 5 & 7 — backfilled 2026-08-04

- **Phase 5 — STT + TTS + audio ✅:** STT moved to the browser Web Speech API (`es-ES`, decision 2026-05-13); TTS server-side via `/speak`, iterated Piper → XTTS-v2 → CosyVoice 3 only (commit `2f7d6cf`).
- **Phase 7 — Kiosk deployment ✅:** systemd user units (`samantha-backend.service`, `samantha-ui.service`, `samantha-hermes.service`) + auto-login → openbox → Chromium `--kiosk`; llama-server runs manually on the 4090 box, never via systemd on the kiosk.

CLAUDE.md §4 marks both ✅ but no PROGRESS entry was recorded at the time.

---

> **For Claude Code:** Append to this file after completing each phase
> from CLAUDE.md §4. Newest entries at the top. Format:
>
> ```
> ## YYYY-MM-DD — Phase N: Title ✅
> Brief summary (2-3 lines).
> **Changed files:** list
> **Tests:** pass/fail count
> **Notes:** any caveats, follow-ups, or surprises
> ```

## 2026-05-26 — Phase 10: Onboarding por Voz y Pulido de Interfaz (Her) ✅

Rediseño interactivo del onboarding a un flujo conversacional por voz. Samantha lee por voz las preguntas y el micrófono se abre automáticamente al finalizar su locución. Se pulieron botones y espaciados siguiendo la estética minimalista y orgánica de la película *Her*.

**Changed files:**
- [OnboardingScreen.tsx](file:///Volumes/Macintosh%20SSD%20-%20Daten/Users/horelvis/git/os1-samantha/frontend/src/screens/OnboardingScreen.tsx) (modificado)
- [components.css](file:///Volumes/Macintosh%20SSD%20-%20Daten/Users/horelvis/git/os1-samantha/frontend/src/styles/components.css) (modificado)

**Tests:** tsc --noEmit exitoso; 65 tests en pytest aprobados.

**Notes:** Se implementó degradación elegante a modo texto en caso de que el navegador no tenga soporte para SpeechRecognition o permisos bloqueados de micrófono.

---

## 2026-05-26 — Phase 9: Integración de Hermes-Agent ✅

Integración híbrida de NousResearch `hermes-agent` como cerebro agéntico secundario compatible con la API de OpenAI. Se estructuró el envío limpio del historial de conversación y se propagó el `user_id` para garantizar la continuidad de sesión y memoria del agente local.

**Changed files:**
- [config.py](file:///Volumes/Macintosh%20SSD%20-%20Daten/Users/horelvis/git/os1-samantha/backend/samantha/config.py) (modificado)
- [real_llm.py](file:///Volumes/Macintosh%20SSD%20-%20Daten/Users/horelvis/git/os1-samantha/backend/samantha/real_llm.py) (modificado)
- [api.py](file:///Volumes/Macintosh%20SSD%20-%20Daten/Users/horelvis/git/os1-samantha/backend/samantha/api.py) (modificado)
- [samantha-hermes.service](file:///Volumes/Macintosh%20SSD%20-%20Daten/Users/horelvis/git/os1-samantha/systemd/samantha-hermes.service) (nuevo)
- [test_api.py](file:///Volumes/Macintosh%20SSD%20-%20Daten/Users/horelvis/git/os1-samantha/backend/tests/test_api.py) (modificado)

**Tests:** 65 passed, 0 failed

**Notes:** La omisión de `/no_think` permite al agente de Hermes utilizar el bloque de razonamiento de Qwen para invocar herramientas, y la inyección de `X-Hermes-Session-Id` mapea correctamente el almacenamiento SQLite de Hermes.

---

## 2026-05-26 — Hermes-Agent Evaluation Spike ✅

Evaluación e informe de viabilidad técnica de NousResearch Hermes-Agent para sustentar las capacidades agénticas de Samantha v3. Se concluye con una recomendación de adopción híbrida, empleando Hermes como cerebro REST API local de herramientas y memoria mientras se conserva el backend actual en FastAPI para la gestión de audio en tiempo real y el frontend en React.

**Changed files:**
- [REPORT.md](file:///Volumes/Macintosh%20SSD%20-%20Daten/Users/horelvis/git/os1-samantha/docs/superpowers/specs/hermes-agent-spike/REPORT.md) (nuevo)

**Tests:** N/A (fase investigativa/documental)

**Notes:** La integración híbrida vía API OpenAI-compatible mantiene intacto nuestro frontend y simplifica de sobremanera la incorporación de MCP (correo/calendario).

---

## 2026-05-13 — Phase 8: UI v2 redesign ✅

Full redesign per `docs/superpowers/specs/2026-05-12-ui-redesign-design.md`
and `docs/superpowers/plans/2026-05-12-ui-redesign-v2.md`.

- **Frontend:** vanilla-JS in `backend/static/` deleted. New `frontend/`
  with React 18 + Vite 5 + TypeScript 5.5 strict. 4 screens (Boot,
  Onboarding, Ambient, Conversation immersive + history toggle). Design
  tokens system in `frontend/src/styles/tokens.css`. State managed by
  Zustand. Three.js OS1Loader ported to a `forwardRef` component with
  imperative handle.
- **Wave:** rewritten as a traveling wave packet — pulses propagate from
  the center outward with gaussian envelope and per-mode parameters
  (idle / listening / thinking / speaking) per spec §6. Stroke 0.6 px.
- **Memory:** extended with short-term (SQLite ring buffer, last 20
  turns, capacity-configurable), long-term (ChromaDB + fastembed
  multilingual ONNX embedder `paraphrase-multilingual-MiniLM-L12-v2`),
  and facts (`role: "fact"` chunks). `Memory.set_fact`, `get_fact`,
  `all_facts` added. `recall()` excludes short-term entries AND
  `role: "fact"` chunks.
- **Persistence:** no `profile.json`. `profile.py` thin facade over
  Memory. `/profile` endpoints (GET / POST / DELETE) routed through
  facts. `/ping` includes `has_profile: bool`.
- **Prompt assembly:** `real_llm._build_payload` accepts `facts`,
  `recall`, `short_term` kwargs (keyword-only). System prompt assembled
  per spec §9.6:
  `SYSTEM_PROMPT + # Lo que sabes de ella + # Lo que recuerdas + # Conversación reciente + user-turn`.
- **Backend serves frontend/dist:** `STATIC_DIR` removed,
  `FRONTEND_DIST = ../../frontend/dist`, `/assets` mount guarded on
  `dist/assets/` existing so backend-only test runs keep working.
- **CLAUDE.md updated:** §2.4 (frontend lives separately), §2.7 (3-layer
  memory architecture), §2.10 new (frontend stack), §3 (no-framework /
  no-build-step rules removed), §5 (npm commands + vite dev workflow),
  §7 (npm install && npm run build before systemd), §12 (two decision
  log entries: frontend pivot + memory redesign).

**Changed files (this redesign):**
- Backend new: `samantha/short_term.py`, `samantha/profile.py`,
  `tests/test_short_term.py`, `tests/test_profile.py`.
- Backend modified: `samantha/memory.py` (fastembed + short-term + facts),
  `samantha/real_llm.py` (three-layer prompt), `samantha/api.py`
  (/profile endpoints, _collect_facts, frontend/dist serving),
  `samantha/schemas.py` (ProfileAnswer / ProfileCreateRequest /
  ProfileResponse, PingResponse.has_profile),
  `samantha/config.py` (memory_short_term_capacity, memory_embedder_model),
  `pyproject.toml` (fastembed → main deps).
- Frontend new: 17 files under `frontend/`: package.json, tsconfig*,
  vite.config.ts, index.html, .gitignore, plus 12 `src/**` files
  (App.tsx, main.tsx, types.ts, store.ts, router.ts, useKeys.ts,
  profile.ts, tts.ts, wsClient.ts, mic.ts, Wave.tsx, OS1Loader.tsx,
  BootScreen.tsx, AmbientScreen.tsx, ConversationScreen.tsx,
  OnboardingScreen.tsx, tokens.css, base.css, components.css).
- Deleted: `backend/static/{index.html, style.css, app.js,
  samantha-wave.js, os1-loader.js, ws-client.js}`.

**Tests:** backend pytest 50 / 50 green. Frontend `npm run typecheck`
clean, `npm run build` succeeds (608KB bundle, Three.js dominant).
End-to-end smoke (mock mode): Boot → Onboarding → /profile POST →
Ambient → tap → Conversation → WS chat token stream works.

**Out of scope (deferred):**
- Samantha proactiva (initiative engine) → v3
- Agentic Samantha (emails, calendar, tools) → v3, scoped at
  `docs/superpowers/specs/2026-05-12-hermes-agent-spike-scope.md`
- Real STT (faster-whisper) + real TTS (Piper) → Phase 5 of v1 phase plan
- Memory browser UI → future

---

## 2026-05-12 — Phase 6: Persistent memory (ChromaDB) ✅ [out of order]

Done out of spec order (Phase 5 STT/TTS deferred) because the user
wanted to develop memory in parallel with their llama.cpp install.

Persistent semantic memory over user messages + Samantha replies, backed
by ChromaDB (SQLite + HNSW) at `~/.samantha/memory/`. Default embedder is
ChromaDB's ONNX MiniLM (will swap to multilingual sentence-transformers
once we see retrieval quality on real Spanish conversation).

Each turn now: (1) remember user msg → (2) recall top-k similar past
chunks → (3) inject into system prompt as "# Lo que recuerdas de esta
persona" → (4) stream reply → (5) remember reply. Both `/chat` and
`/ws chat` follow the same path.

**Design directive (user, mid-implementation):** *"Samantha nunca debe
olvidar nada."* The originally planned "olvida X" intent-detection
feature was REMOVED. `Memory.forget()` and `Memory.clear()` are kept
as admin/test tools but never triggered by user input. The system
prompt (v2) instructs Samantha to decline forget requests in character.

**Changed files:**
- `CLAUDE.md` §2.7 rewritten (sentence-transformers swap-path, no
  Ollama dep, never-forgets principle); §4 Phase 6 deliverables updated.
- `backend/samantha/memory.py` (new — Memory class: remember/recall/all/
  forget/clear/stats; MemoryChunk dataclass; chromadb lazy import).
- `backend/samantha/personality.py` (v1 → v2: added "no olvidas" clause
  + refusal example, `SYSTEM_PROMPT_VERSION = "v2-2026-05-12"`).
- `backend/samantha/real_llm.py` (`stream_reply()` / `generate_reply()`
  / `_build_payload()` accept `memories` kwarg; `_format_memories()`
  renders the system-prompt addendum).
- `backend/samantha/api.py` (`get_memory()` lazy singleton; `/chat` and
  `/ws chat` wire remember/recall/inject/remember).
- `backend/samantha/config.py` (`memory_enabled`, `memory_persist_dir`
  renamed from `chroma_persist_dir`, `memory_top_k`).
- `backend/pyproject.toml` (chromadb to main deps; sentence-transformers
  moved to [real] extras as upgrade path).
- `backend/tests/conftest.py` (new — sets `SAMANTHA_MEMORY_ENABLED=false`
  for the integration suite so chroma files don't land in the developer
  home; dedicated Memory tests use `tmp_path`).
- `backend/tests/test_api.py` (added 9 tests: remember+recall, user_id
  isolation, admin forget, persistence across reopens, empty store,
  clear, role validation, no-forget-intent-exposed, memory injection
  into system prompt).
- `docs/02-system-prompt-iterations.md` (v2 section added, marked as
  active; v1 kept for reference).

**Tests:** 29 / 29 passing.

**Notes:**
- First test run downloads ChromaDB's ONNX MiniLM (~80 MB). Subsequent
  runs use the cached model.
- Embedder is English-leaning. Spanish retrieval works (multilingual
  signal in pretraining) but is not optimal. Swap to
  `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` when
  real conversation data shows recall misses.
- Memory is enabled by default in production (mock and real modes both
  use it). To disable for local debugging: `SAMANTHA_MEMORY_ENABLED=false`.
- The `Memory.forget()` admin tool is unreachable from any HTTP/WS
  surface today. If we ever expose a "factory reset" or "new owner"
  flow, it'll be a separate admin endpoint that requires explicit
  intent, not a chat command.

---

## 2026-05-12 — Phase 4: Real LLM integration ✅

Wired Samantha to a real local LLM via an OpenAI-compatible HTTP API.
Chose **llama.cpp (`llama-server`)** as the runtime instead of vLLM —
single-user single-stream workload doesn't benefit from vLLM's batching
engine, and llama.cpp runs natively on Mac (Metal) AND Linux (CUDA),
unblocking Mac-side development. See decision log §12 in CLAUDE.md.

The `real_llm` client uses `httpx.AsyncClient.stream()` to consume
OpenAI-style SSE deltas and yields token chunks as they arrive. The
WebSocket `/ws` and non-streaming `/chat` both dispatch on `config.mode`
via a unified `_stream_tokens()` async generator, so the on-wire protocol
is identical regardless of backend. If the LLM server is down, the
fallback reply is in Samantha's voice — the UI never sees a raw error.

`personality.SYSTEM_PROMPT` is embedded as a module constant (canonical
source-of-truth lives in `docs/02-system-prompt-iterations.md`, v1).

**Changed files:**
- `CLAUDE.md` updated (§2.5 vLLM→llama.cpp, §3 systemd filename,
  §4 Phase 4 deliverables, §5 commands, §12 decision log entry)
- `docs/02-system-prompt-iterations.md` (new — canonical prompt v1)
- `backend/samantha/personality.py` (new — embedded prompt + version)
- `backend/samantha/real_llm.py` (new — OpenAI-compat streaming client)
- `backend/samantha/config.py` (renamed `vllm_url` → `llm_server_url`,
  added `llm_request_timeout_s`, env var `SAMANTHA_LLM_SERVER_URL`)
- `backend/samantha/api.py` (unified `_stream_tokens()` dispatch by mode;
  `/chat` and `/ws` now branch on `config.mode` cleanly)
- `backend/pyproject.toml` (httpx moved to main deps; vllm removed from
  `[real]` extras since llama.cpp is a separate binary)
- `systemd/samantha-llamacpp.service` (new — runs `llama-server` with
  the model on :8000, restarts on failure, GPU offload via NGL=99)
- `backend/tests/test_api.py` (added 3 tests: SSE parsing, HTTP-error
  fallback, system-prompt presence + version)

**Tests:** 20 / 20 passing (`pytest tests/ -v`).

**Notes:**
- Run real mode locally:
  ```bash
  # 1. Install llama.cpp (brew install llama.cpp on Mac;
  #    apt/build-from-source on Linux).
  # 2. Download a GGUF model, e.g.:
  #    huggingface-cli download Qwen/Qwen3.5-9B-Instruct-GGUF \
  #      qwen3.5-9b-instruct-q4_k_m.gguf \
  #      --local-dir ~/.samantha/models
  # 3. Start llama-server:
  llama-server --model ~/.samantha/models/qwen3.5-9b-instruct-q4_k_m.gguf \
               --host 127.0.0.1 --port 8000 --jinja
  # 4. Start the backend in real mode:
  SAMANTHA_MODE=real python -m samantha.api
  ```
- The system prompt is v1 and untested against the actual model. Iterate
  by editing `docs/02-system-prompt-iterations.md` → sync to
  `personality.py`. Open questions are listed at the bottom of v1.
- The `llm_model` field in config is informational — llama-server runs
  whichever GGUF it was started with. The field becomes meaningful if
  you ever swap to vLLM (which uses it to select among loaded models).
- `httpx.AsyncClient` is created lazily on first call so the event loop
  owns it. `real_llm.aclose()` exists for clean shutdown but isn't wired
  into FastAPI's lifespan yet (no harm; the OS reclaims sockets on exit).

---

## 2026-05-12 — Phase 3: Frontend integration ✅

Migrated the `samantha_mockup_v7.html` mockup into modular files
under `backend/static/` and wired every interaction to the real
backend. FastAPI now serves both the SPA and the API on `:7777`.
The browser never touches the microphone (CLAUDE.md §2.8): the mic
button triggers a `listen` message over the new `/ws` WebSocket; the
backend returns a fake transcription (Phase 5 will swap in real STT).
Replaced `speechSynthesis` with fetch + `<audio>` playback of `/speak`.
Removed the obsolete `/chat/stream` SSE endpoint; streaming now flows
through `/ws` (token / done events).

**Changed files:**
- `backend/static/index.html` (rewritten — was the Tauri skeleton)
- `backend/static/style.css` (new — full extraction)
- `backend/static/app.js` (new — screen state machine + event wiring)
- `backend/static/samantha-wave.js` (new — wave + audio-viz factories)
- `backend/static/os1-loader.js` (new — Three.js ribbon)
- `backend/static/ws-client.js` (new — WebSocket client with reconnect)
- `backend/samantha/api.py` (refactored — StaticFiles, GET /, /ws, no SSE/CORS)
- `backend/tests/test_api.py` (added 7 tests: index, static assets, /ws)

**Tests:** 17 / 17 passing (`pytest tests/ -v`).

**Notes:**
- CORS middleware for Tauri origins removed (same-origin now).
- `/chat` (non-streaming) kept for tests; the UI uses `/ws`.
- TTS still plays the 0.4s tone WAV (Phase 5 swaps Piper in). Onboarding
  timings stay natural because they're driven by independent setTimeouts,
  not by audio `ended` events.
- Three.js loaded via importmap from `cdn.jsdelivr.net` (CLAUDE.md §6),
  fonts via Google Fonts. Both authorized; vendoring is a future concern.
- WS auto-reconnects with backoff so the kiosk recovers from backend restarts.
- Frontend never calls `getUserMedia` / `speechSynthesis` / `webkitSpeechRecognition`
  — all routed through the backend per CLAUDE.md §2.8.

---

## 2026-05 — Phase 0: Architecture redesign (v3) ✅

Final architecture settled on Ubuntu Server 24.04 LTS + Chromium kiosk
mode + Python-only backend serving frontend on `localhost:7777`.
Eliminated all snap/Ubuntu Frame complexity from the v2 plan. The
Python backend serves both the static HTML/CSS/JS and the API on a
single port. Browser communication via fetch + WebSocket.

**Changed files:**
- `CLAUDE.md` updated to v3 (sections §2.2, §2.3, §2.8, §3, §4, §5,
  §6, §8, §9, §10, §11, §12 updated)
- `PROGRESS.md` updated (this file)
- Project structure unchanged from v2 (still no `src-tauri/`,
  no `snap/`)

**Tests:** N/A (architectural change, no new code)

**Notes:**
- This is the THIRD architecture iteration. v1 was Tauri + Rust
  (rejected). v2 was Ubuntu Frame + WPE WebKit + snap (rejected).
- The principle behind v3: "familiar tools first, exotic only when
  justified." Chromium kiosk is the most widely-deployed Linux kiosk
  solution.
- Hardware decision unchanged: Minisforum AtomMan G7 Ti SE
- LLM, STT, TTS, memory decisions unchanged

---

## ~~2026-05 — Phase 0: Architecture redesign (v2)~~ ❌ REVERTED

Briefly settled on Ubuntu Frame + WPE WebKit + snap. Reverted before
implementation due to snapcraft complexity and WPE WebKit API concerns.

---

## ~~2026-05 — Phase 1: Tauri skeleton~~ ❌ REJECTED

Originally built in v1 of the architecture. Replaced by web-based
kiosk approach. Code removed.

**Why rejected:** Tauri adds a Rust + WebKit2GTK layer that's
unnecessary when the backend can serve the frontend directly to a
browser in kiosk mode.

---

## 2026-05 — Phase 2: Mock Python backend ✅

FastAPI server with 5 endpoints (ping, chat, chat/stream, transcribe,
speak). Pattern-matched responses in `mock_llm.py` covering 14
keyword-based categories plus 10 fallback replies. All responses follow
the Samantha personality guidelines (no disclaimers, concise, warm).

**Changed files:**
- `backend/pyproject.toml` (new)
- `backend/samantha/__init__.py` (new)
- `backend/samantha/config.py` (new)
- `backend/samantha/schemas.py` (new)
- `backend/samantha/mock_llm.py` (new)
- `backend/samantha/api.py` (new)
- `backend/tests/test_api.py` (new)
- `backend/README.md` (new)

**Tests:** 10 / 10 passing.

**Notes:**
- Predates Phase 0 redesigns; needs minor updates in Phase 3:
  - Add `StaticFiles` mount for `/static/*`
  - Add `GET /` route returning `index.html`
  - Add WebSocket endpoint `/ws` for streaming
  - Remove `/chat/stream` SSE (replaced by WebSocket in Phase 3)
- Simulated latency (0.4–1.8s) intentional to match real LLM speeds
- `/transcribe` returns hardcoded fake transcriptions for mock mode
- `/speak` returns a synthesized tone WAV (placeholder for Piper output)

---
