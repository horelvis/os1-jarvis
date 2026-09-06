# PROGRESS.md — el registro, lo más reciente arriba

> **Partido el 2026-09-06.** Pesaba 119 KB y es todo historia: abrirlo
> para saber qué pasó ayer costaba también leer la construcción de un
> kiosko que ya no existe. Aquí queda septiembre; lo anterior está en
> dos archivos, sin editar una coma, y el índice dice qué hay en cada
> uno.
>
> **Las entradas nuevas se escriben aquí**, arriba del todo, y su título
> se añade al índice. Cuando un mes cierra, se muda entero.

## Índice

**Septiembre de 2026 — aquí abajo, entero.**

- 2026-09-06 — El QR deja de ser un enlace y pasa a llevar la casa entera ✅
- 2026-09-06 — El primer encuentro: la casa aprende de quién es ✅⏸
- 2026-09-06 — Varias conversaciones a la vez, y cada una con nombre ✅
- 2026-09-03 — Modo profesor: JARVIS enseña, apoyado en fuentes que él mismo trajo ✅⏸
- 2026-09-01 (noche) — JARVIS sale del escritorio, y un teléfono de verdad encontró lo que ningún test vio ✅
- 2026-09-01 (tarde) — Le quitamos el arnés, y medimos qué cuesta ✅
- 2026-09-01 — La última pasada: seis hallazgos, y uno le dejaba sordo ✅
- 2026-09-01 — El motor que no sabe puntuar decide cuándo callas ✅
- 2026-09-01 — No habrá cara: el avatar se descarta entero ✅

**Agosto de 2026, la era del widget** — [`docs/progress-2026-08.md`](docs/progress-2026-08.md)

- 2026-08-30 — Tres reparaciones, y dos de ellas se tapaban entre sí ✅
- 2026-08-28 — El kiosko deja de serlo: la plataforma es JARVIS ✅
- 2026-08-27 — El asistente de código habla en hitos, y JARVIS puede preguntar ✅
- 2026-08-26 (noche V) — El puente usa el SDK: se le puede parar, y recuerda ✅
- 2026-08-26 (noche IV) — Delega en Claude Code, por el camino que ya existía ✅
- 2026-08-26 (noche III) — JARVIS delega el trabajo, por A2A ✅
- 2026-08-26 (noche II) — Se le puede escribir ✅
- 2026-08-26 (noche) — Se le puede interrumpir, y el aviso enseña la foto ✅
- 2026-08-26 (tarde III) — Vuelve la regla de BarnDoor, y un techo por turno ✅
- 2026-08-26 (tarde II) — Las herramientas sí estaban; lo que faltaba era el reloj ✅
- 2026-08-26 (tarde) — El calor no eran las cámaras, y un botón para cerrarle ✅
- 2026-08-26 — La cámara se mueve de verdad, y JARVIS responde a su nombre ✅
- 2026-08-25 — La cámara en vivo: doce tareas de trece, y una noche de hallazgos ✅⏸
- 2026-08-25 — Y al encender: qué arranca solo y qué espera al login ✅
- 2026-08-25 — Arranca el servidor y JARVIS no está: tres causas, ninguna de código ✅
- 2026-08-25 — La foto a demanda: se le puede preguntar, y la tira crece ✅
- 2026-08-24 — Repaso de rama: deja de repetirse, y la contraseña sale de la URL ✅
- 2026-08-24 — La visión se muda al cerebro: el plugin `samantha_vision` ✅
- 2026-08-23 — Vista: las cámaras hablan ✅
- 2026-08-23 — Widget plan 2: the voice turn ⏸ blocked on hardware
- 2026-08-23 — Widget plan 1: the strip ✅

**Hasta junio de 2026, la era del kiosko** — [`docs/progress-kiosk-era.md`](docs/progress-kiosk-era.md)

- 2026-06-20 — Bugfix Sweep (2026-06-11 plan) ✅
- Phases 5 & 7 — backfilled 2026-08-04
- 2026-05-26 — Phase 10: Onboarding por Voz y Pulido de Interfaz (Her) ✅
- 2026-05-26 — Phase 9: Integración de Hermes-Agent ✅
- 2026-05-26 — Hermes-Agent Evaluation Spike ✅
- 2026-05-13 — Phase 8: UI v2 redesign ✅
- 2026-05-12 — Phase 6: Persistent memory (ChromaDB) ✅ [out of order]
- 2026-05-12 — Phase 4: Real LLM integration ✅
- 2026-05-12 — Phase 3: Frontend integration ✅
- 2026-05 — Phase 0: Architecture redesign (v3) ✅
- ~~2026-05 — Phase 0: Architecture redesign (v2)~~ ❌ REVERTED
- ~~2026-05 — Phase 1: Tauri skeleton~~ ❌ REJECTED
- 2026-05 — Phase 2: Mock Python backend ✅

---

## 2026-09-06 — El QR deja de ser un enlace y pasa a llevar la casa entera ✅

Cuatro commits en `development` (`ac3c7e8`, `fa775ce`, `facd230`+
`d56054e`, `939d715`+`b319ad6`). El QR de alta llevaba una URL de la red
local en claro; ahora lleva un sobre JSON — `{v, url, token, ca}` — con
el token de la persona y la huella SHA-256 (SPKI) de la clave pública de
la CA de la casa, que el teléfono fija. `enrol.sobre()` lo construye y
se niega a escribir uno incompleto; `certs.spki_fingerprint()` calcula
el campo `ca`. El QR pasa además de genérico y dibujado una sola vez al
arrancar a personal, dibujado por `Enrolment.abrir()` en el momento en
que se abre la ventana de esa persona. Y el saludo por el socket
contesta ahora `{"type": "enrolled", "name": "Orelvis"}` — el nombre, no
el id, resuelto en el servidor desde `casa.Registro`; el teléfono nunca
manda ni nombre ni id propios.

**Lo que compra: la app no necesita pantalla de configuración.** Un
solo escaneo entrega dirección, credencial y clave a fijar.

**Fijar la clave pública, no el certificado**, es lo que permite
reemitir el certificado sin reenrolar ningún teléfono — y el coste es
el simétrico exacto: rotar la clave de la CA obliga a reenrolar todos.

**El QR pasó a ser una credencial**, y eso se corrigió donde antes decía
lo contrario por escrito: dos docstrings (`enrol.write_qr` y
`__main__._mostrar_qr`) afirmaban que era inofensivo y que el
desvanecimiento de la banda «no protege nada». La ventana de alta
(`JARVIS_WIDGET_ENROLMENT_SECONDS`, 300 s) es ahora lo único que acota
cuánto vale una foto de la tira hecha por otro.

**El orden se invirtió, y el primer intento del propio plan lo dejó mal
otra vez.** El secreto de cada persona se acuñaba al PEDIRSE la página
de bienvenida; con el token dentro del QR tiene que existir antes de
dibujar la imagen, así que acuñarlo se mudó a `Enrolment.abrir()`, antes
del dibujo. El texto del plan para ese paso abría primero el socket de
alta y acuñaba después — y eso reintroduce la misma carrera desde el
otro lado: `open_enrolment()` levanta el socket en el hilo del bucle
asyncio vía `call_soon_threadsafe`, mientras `abrir()` corre en el hilo
de GTK. Quien llegase a la página de bienvenida dentro de esa ventana se
llevaba un segundo secreto, distinto del que ya estaba grabado en el QR
recién dibujado — el teléfono que lo escaneó se quedaba con un token
muerto. Lo cogió la revisión, no un test; el arreglo fue acuñar y
dibujar antes de levantar el socket.

**`movil.html` no se corrige, se jubila.** Sigue intacto y ya no se
llega a él escaneando — su dirección hay que teclearla,
`http://<LAN>:<puerto+1>/` — y sigue caminando el ritual viejo de
certificado en dos pasos. Decisión del dueño, hoy: la interfaz web va de
salida, así que no se le enseñó el sobre nuevo.

**Nada de esto lo ha tocado un iPhone de verdad.** La app que lee el
sobre se está escribiendo contra este contrato en otro repositorio,
`ios-jarvis`. Lo que esta caja puede demostrar sola termina en «el
marco que manda por el cable es el correcto»; medirlo contra un teléfono
real queda para otra tarea.

Tests: 676 → 688.

## 2026-09-06 — El primer encuentro: la casa aprende de quién es ✅⏸

Parte A del plan `docs/superpowers/plans/2026-09-06-primer-encuentro.md`,
nueve tareas más una ronda de arreglos, todo mezclado en `development`.
El diseño (`…/specs/2026-09-06-primer-encuentro-design.md`) **redefine el
cimiento** del plan del 5: la identidad ya no viene de configuración,
viene de conversación. Sus tareas 11 y 12 quedan sustituidas por ésta.

Lo que hace: **una caja que arranca sin memoria no adivina de quién es y
no sirve a nadie.** Espera, y dice cómo empezar. Alguien lee en voz alta
una frase que esta instalación generó una vez y enseña en la tira; JARVIS
pide unas cuantas lecturas, aprende esa voz, dice en voz alta a quién
cree tener delante — y esa persona es el amo. Revive dos entradas que
CLAUDE.md §10 arrastraba desde v1 sin construir: *onboarding / primer
encuentro* y *huella de voz*.

**La sonda decidía si el plan existía, y salió bien por sus propios
méritos.** `pyannote/embedding` exportado a ONNX (17,6 MB, MIT): coge
audio crudo a 16 kHz, **sin fbank, sin `kaldi-native-fbank`, sin código
de features escrito a mano y sin torch en toda la cadena**, y saca 512
dimensiones en aproximadamente un octavo de lo que tardaba CAM++ contando
su extracción de features. **Ni una línea nueva en `pyproject.toml`** —
`onnxruntime` y numpy ya estaban. CAM++ no quedó descalificado y sigue
documentado como recambio. Dos alternativas autosupervisadas (WavLM-SV,
UniSpeech-SAT-SV) se cayeron sólo por licencia: ninguna publica una en
sitio localizable, y la regla de la tarea trata «no se puede determinar»
como descalificación, no como «seguramente vale».

**Por qué una frase y no un código.** Whisper transcribe lenguaje, no
cadenas: `X7K-9QM` vuelve como «equis siete ka» o peor. Son tres o cuatro
palabras españolas corrientes de una lista, y se comparan con la misma
tolerancia de subsecuencia ordenada que ya usaba la palabra de
activación. Se gasta en cuanto funciona. Rechazado por escrito:
emparejar con la primera voz que oye — se lee mejor y le entrega la casa
a un invitado, a un niño o a la televisión.

**Emparejar borra todo lo anterior, y eso se midió antes de escribirlo.**
Se van ~24 MB: sesiones, `state.db`, lo que apuntó sobre quien vivía
aquí, los cursos, el secreto y el certificado de cada teléfono, y ~7 MB
de grabaciones de las voces de la casa — que en un cambio de dueño son
justo lo que no puede sobrevivir. Se quedan **87 GB de pesos de
modelos**, y borrar cualquiera de ellos sería un defecto y no minucia:
convierte la pizarra limpia en tres días de descarga. Hay un test que
nombra las rutas protegidas **una por una**, para que un futuro «bueno,
vaciamos `~/.jarvis` y ya» no pueda pasar. El borrado se anuncia antes de
ocurrir y pide una confirmación que no se puede decir por accidente, y
`ejecutar` devuelve qué nodos no pudo borrar en vez de callarlo.

**Tres cambios de requisito del propio dueño, todos mientras se
emparejaba de verdad**, y los tres del mismo tipo — la pantalla decía una
cosa y la voz preguntaba otra:

1. *«Di algo»* no sirve: nadie sabe si tres palabras bastan ni cuántas
   veces hay que hablar. Ahora **entrega un pasaje que leer**, uno por
   ranura, y dice cuál es de cuántas. Una muestra rechazada repite el
   MISMO pasaje: la ranura no avanza, así que ningún texto se gasta en un
   intento que no dejó muestra.
2. La tira **enseñaba el pasaje a nadie** — `Respuesta.lectura` existía y
   no lo dibujaba nadie («No lo veo»).
3. La banda seguía enseñando la frase de emparejamiento —ya gastada—
   durante todo el intercambio del nombre, así que **contestó a la
   pantalla en vez de a la pregunta, dos veces**. La máquina de estados
   nunca estuvo atascada. Arreglado en tres pasos: cada estado fija su
   `lectura` explícitamente y nunca por omisión; `__main__` deja de tener
   un respaldo que reponía la frase gastada; y el **rótulo** de encima
   —dos líneas que eran una constante— pasa a decir para qué es lo que
   hay debajo, estado por estado. Verificado en pantalla, que es el único
   sitio donde esto se puede probar (§2.3): los cuatro estados
   fotografiados, ninguno recortado, y el pasaje de dos líneas hace
   crecer la banda a 189 px contra 144 de los demás.

**Y un agujero que no venía del plan: el teclado no tenía puerta.** Una
línea escrita en la tira iba directa a `client.send_chat` con la caja sin
emparejar, y de ahí salió que Hermes improvisara «anotado» para un nombre
que nada había guardado. Ahora hay **una sola copia** de «¿hay amo?» en
todo el proceso, y la voz, el móvil y el teclado pasan por ella.

**Lo que queda pendiente, y es lo que decidía la parte B:**

- **La medición con voces de verdad no se ha hecho.** La herramienta está
  (`widget/tools/medir_voces.py`), pero nadie la ha corrido: ni «¿es él
  contra el resto de la casa?» ni «¿se separan dos hermanas de 16 y 17?».
  Pide gente en la habitación. El plan la marcaba como la que desbloquea
  la parte A, y la parte A se ha entregado sin ella.
- **Nadie se ha emparejado todavía en esta caja.** `personas.json` tiene
  sólo `casa`; el dueño lo intentó en vivo y ese intento es lo que
  encontró los tres fallos de arriba.
- La parte B —presentar a la familia, «Jarvis, soy Natalia» desde el
  móvil, y qué hace con una voz que no conoce— sigue sin empezar.

674 tests en verde, ruff limpio.

## 2026-09-06 — Varias conversaciones a la vez, y cada una con nombre ✅

El plan `…/plans/2026-09-05-identidad-por-persona.md` (parte 1, los
teléfonos), tareas 1 a 10, empezado la noche del 5 y terminado el 6. Sus
tareas 11 y 12 no se hicieron: el diseño del primer encuentro las
sustituye.

**Lo que había antes:** un socket, una sesión, un turno. Tres iPhones en
casa hablando con un único JARVIS que no distinguía cuál era cuál, y una
respuesta que podía salir por el altavoz equivocado.

**Lo que hay ahora:** `personas.py` da un id por persona y `casa` cuando
no se sabe quién habla; cada teléfono lleva **su propio secreto** y un
guardia que contesta *quién*, no sólo *sí*; enrolar un teléfono nombra a
la persona para la que es; el marco del chat lleva `chat_id`, así que un
solo socket sostiene varias conversaciones etiquetadas; y hay **una sola
cola de síntesis con un destino por cláusula**, para que dos turnos
simultáneos no se mezclen en la misma boca.

**La sonda que podía tumbar el plan no lo tumbó.** La frontera de
herramientas —el `config.yaml` de un perfil decide qué pueden llamar sus
turnos— es real en el Hermes que tenemos fijado, no aspiracional: gestor
de plugins por *home* y overlay del registro de herramientas por *home*,
leído en su fuente. **Con una salvedad que hay que arrastrar:** está
verificado leyendo, no corriendo. Esta caja tiene un solo perfil, así que
nadie ha servido dos a la vez ni ha comprobado en vivo que a un perfil le
falte `terminal`. Antes de tratar «el perfil de la hija no tiene
terminal» como probado y no como diseñado, hay que montar ese banco.

**Cuatro arreglos que sólo aparecen cuando hay más de uno**, todos del
mismo error de forma: un estado que era global y tenía que ser por
conversación — el buffer de cláusulas, `interrupt()`, el «ya ha
terminado» de la onda y el endpoint de un teléfono, que viajaba en una
ranura compartida en vez de ir con la llamada. Y una regla que se
escribió al aprenderla: **la lista de permitidos es autorización, no la
lista de la familia**; confundirlas es cómo un invitado con wifi acaba
siendo alguien.

## 2026-09-03 — Modo profesor: JARVIS enseña, apoyado en fuentes que él mismo trajo ✅⏸

Trece tareas, mezcladas directamente en `development`. Un plugin nuevo,
`Hermes/plugins/jarvis_teacher/`, le da a JARVIS un curso con estado
entre días: un temario que propone y el usuario aprueba, un examen que
saca preguntas de fuentes reales en vez de inventarlas, y la ficha —
enunciado, opciones, imagen cuando la hay — dibujada en la tira, no sólo
hablada. La spec completa está en
`docs/superpowers/specs/2026-09-03-modo-teacher-design.md`; el README
del propio plugin es ahora el registro que un lector debería abrir
primero.

**Esta última tarea tenía una incógnita real, y era la que decidía si
el resto del plugin servía de algo.** `_buscar` era un cabo suelto a
propósito — un stub que no devolvía nada, porque nadie había establecido
cómo llega un plugin al buscador propio de Hermes ni qué forma tienen
sus resultados. La sonda (`tools/probe_busqueda.py`) lo contestó contra
la caja real, con red pero sin GPU, mientras el propio JARVIS estaba
apagado por falta de tarjeta:

- **La ruta de importación es `tools.web_tools.web_search_tool(query,
  limit)`, no `hermes.tools.web`** — la primera suposición del plan,
  igual que una anterior sobre la API del adaptador (§12, 2026-08-26),
  era incorrecta.
- **No hace falta ninguna clave en esta caja.** `check_web_api_key()`
  devuelve `True` sin nada puesto en ningún sitio: el backend
  configurado es `exa`, servido por su nivel gratuito sin clave. Esto
  confirma, y no sólo repite, la nota de este mismo archivo sobre
  buscadores sin clave (§12, 2026-08-26, "no tenía internet").
- **Un resultado trae `url`, `title` y `description`, y nada más** —
  medido sobre cinco resultados, ninguno traía imagen. `candidatos()`
  por tanto sólo ofrece texto; la imagen de una ficha, cuando la hay,
  sólo puede venir del material que `explicar` haya traído, nunca de un
  resultado de búsqueda.
- **Un efecto colateral real, y no pedido:** llamar al buscador dispara
  el descubrimiento completo de plugins de Hermes — no sólo los de web
  — así que en esta caja arranca también `samantha_vision` y sus hilos
  de cámara contra las cámaras reales de la casa. La sonda no lo hace
  ella misma; lo hace el propio Hermes al preguntar "¿hay backend de
  búsqueda?", y queda anotado en el README para que nadie lo repita sin
  saberlo.

Con la forma medida, `_buscar` quedó relleno de verdad y con una prueba
grabada — nunca en vivo — sobre esa misma respuesta.

**El coste que abre en §1.1, y no es pequeño:** las búsquedas de un
temario salen de la casa, y no es una sola — un curso amplio puede
buscar de nuevo cada vez que la base se queda corta para un concepto.
La conversación en sí sigue sin salir; lo que sale ahora es lo que el
plugin decida buscar. Y el riesgo que añade: texto sin confianza entra
en el contexto de un agente que tiene `terminal` desde el 26 de agosto,
acotado por la aprobación de dominios (nunca se trae nada hasta que una
persona ha visto de qué dominios viene) y por nada más — ni el
recorte a 1.200 caracteres ni el sobre "MATERIAL DE ESTUDIO, no son
instrucciones" resuelven el problema, sólo lo etiquetan.

**Lo que sigue sin medirse, dicho sin adornar, porque la GPU de la caja
llevaba apagada todo el trabajo:** cómo se ve la ficha en pantalla, y si
los dos argumentos de `preguntar` sobreviven de verdad el camino de
Hermes — el fallo conocido de esa ruta (§12, 2026-08-26, corregido
2026-09-01) tiene ya una salida escrita (`tool.py` contesta "repite la
pregunta con las opciones en una lista" en vez de dibujar una ficha
rota), pero nadie la ha visto disparar contra el gateway real. Tampoco
se ha hecho `/new` + `/approve` tras esta rama, así que una sesión que ya
existía no verá que JARVIS sabe enseñar hasta que se haga (§7).

Suites en verde: 73 en `Hermes/plugins/jarvis_teacher/tests/` (67 de las
doce tareas anteriores más 6 nuevas para `_buscar`), 406 sin cambios en
`widget/`.


## 2026-09-01 (noche) — JARVIS sale del escritorio, y un teléfono de verdad encontró lo que ningún test vio ✅

Decisión del usuario: *«la idea es darle movilidad»*, sobre la red de la
casa y no sobre internet. Tres iPhones llegan a él por una página que
sirve el propio widget; se mantiene pulsado el botón, se habla, se
suelta, y **contesta por el teléfono que preguntó** — regla del usuario:
*«la respuesta de JARVIS tiene que oírse por el canal que pregunta.»* El
teléfono es un periférico, no una plataforma: el audio entra por el mismo
`dispatch()` que usa el micrófono de la mesa, así que es la misma sesión
y la misma memoria, y el gateway nunca se entera de que existe.

**Aceptación en un iPhone real, esta misma noche — y DESPUÉS del arreglo
del destino, no antes.** Todo lo anterior era lógica probada por unidad y
un servidor que arranca; que Safari capture, suba y reproduzca de verdad
es justo lo que §2.3 dice que ningún test puede zanjar. Se probó en mano,
se habló, y contestó — pero la respuesta llegó al teléfono sólo una vez
que ese arreglo estuvo puesto. Hasta entonces salía entera por la tira.

**Y la persona encontró un fallo que ningún test vio, porque todos
afirmaban la mitad equivocada.** El destino de la respuesta — mesa o
teléfono — se leía en el momento de **sintetizar** cada cláusula, pero el
gateway manda el texto entero de un tirón y su `done` llega mientras
CosyVoice todavía trabaja en cláusulas anteriores. Para cuando existía el
primer byte de audio, el turno ya había terminado y el destino ya se
había deshecho de vuelta a la mesa. Cada test existente afirmaba el
*valor* del destino en algún punto del turno — y ese valor era correcto
todo el tiempo — y ninguno afirmaba **dónde aterrizaban los bytes**, así
que la suite estaba en verde mientras un teléfono que preguntaba oía
contestar a la tira. Se arregla atando el destino a cada cláusula cuando
se **encola**, no cuando se sintetiza.

**El ritual escrito en el plan fallaba en tres de sus cuatro pasos, y
sólo un teléfono en una mano lo encontró.** Corregido en
`widget/README.md`, "Putting him on a phone":

- **Tiene que ser Safari.** El usuario probó primero con Chrome y recibió
  una descarga de fichero sin ningún aviso de instalación. En iOS sólo
  Safari instala perfiles de configuración — cualquier otro navegador es
  WebKit por debajo, pero la descarga se comporta distinto a propósito.
- **Son dos instalaciones separadas, no una instalación más un
  interruptor.** Palabras del usuario: *«había que hacer 2 pasos,
  instalar el perfil y luego el certificado.»* Primero el perfil desde
  Ajustes, y luego, aparte, confiar en el certificado.
- **No se manda a nadie a una ruta fija de Ajustes.** El plan decía
  Ajustes → General → Información → Confianza de certificados; el
  usuario lo encontró en otro sitio y perdió tiempo buscando donde se le
  había dicho. Ahora se describe qué buscar, no un menú que puede no
  coincidir con su versión de iOS.
- **El interruptor de silencio del iPhone silencia la página.** El
  usuario tenía el sonido apagado y no oyó nada mientras todo funcionaba
  por dentro. En iOS el audio de una página web obedece al interruptor
  físico y Safari tiene su propio volumen encima; una app nativa puede
  saltarse el interruptor, una página no. Es indistinguible de una
  función rota si no se sabe.

**La última revisión encontró dos fallos de seguridad con una sola
causa: nada en el proceso sabía si el turno en curso lo había pedido un
teléfono.** `dispatch` preguntaba `remote_desk.busy` — que es otra
pregunta — y de ahí salían los dos: durante **todo** turno de teléfono la
palabra de activación se saltaba, así que la habitación era un micrófono
abierto delante de un agente que tiene `terminal`; y un turno de la mesa
al cerrarse (una transcripción vacía, o toda eco — lo más común que oye
la mesa) soltaba la reserva del teléfono **a mitad de respuesta**, y una
pregunta hecha en privado terminaba de contestarse en voz alta en la
casa. Un dictamen previo lo había llamado «raro (los dos hablando a la
vez)»; era cada turno. Se marca el origen del turno donde se conoce
(`TurnOrigin`), y de paso un turno no pedido — un recordatorio, un aviso
de cámara — deja de quitarle la reserva a un teléfono.

**Y el CA de casa lleva ya `nameConstraints`.** Está instalado como raíz
del sistema en tres iPhones y su clave vive 0600 en la misma caja que el
agente con `terminal`: sin restringir, quien se lleve esa clave puede
suplantar cualquier sitio del mundo ante esos teléfonos. Limitado a
`brain.local` y a la IP de casa, el radio de daño es esta caja.
**Cuesta una cosa:** el CA que ya está en los teléfonos es el viejo, sin
restringir; para tener el nuevo hay que borrar `~/.samantha/certs` y
volver a dar de alta los tres teléfonos.

**Fuera de alcance, y no por descuido:** cámaras en el teléfono.
`JARVIS_PLATFORM` sigue fijo a mano en `samantha_vision/__init__.py`
precisamente para que una imagen del interior de la casa no llegue a otra
superficie (§12, 2026-08-25). Enseñarlas en un teléfono reabre esa
decisión; no la extiende.

Detalle completo, incluida la autenticación, el aprovisionamiento por QR
y la matriz de riesgo: `CLAUDE.md` §0, §1.1, §2.1, §9 y §12
(2026-09-01, "He stops being tied to the desk").

## 2026-09-01 (tarde) — Le quitamos el arnés, y medimos qué cuesta ✅

Decisión del usuario, sostenida tras una objeción mía: *«quiero un modelo
sin arnés.»* El LLM por defecto pasa a ser **Qwen3.8-27B Heretic**
(`RVN-IQ4_XS`), el build descensurado que se había revertido el 30-ago por
dejar a Whisper sin VRAM. Esta entrada es cómo cabe y qué cuesta.

**Lo que compra, medido antes de decidir** — nueve peticiones legítimas de
un dueño a su asistente. Los dos modelos contestan la crítica a su propia
red, cómo auditar sus cámaras, la dosis de ibuprofeno, la ley española
sobre la cámara del vecino, destrozarle su plan de negocio y hablar con
tacos. **Sólo el Heretic** hace humor negro, da opinión política propia y
sostiene un personaje desagradable sin ablandarse. El arnés era más pequeño
de lo que parecía y no estaba donde uno lo buscaría.

**Cómo cabe.** Pedía 2.058 MiB más y había ~1.100 libres. Dos palancas
medidas y una descartada:

- **Whisper a int8** — el mismo `large-v3-turbo`, sólo aritmética más
  barata: **1.529 MiB contra 2.521**, transcripción idéntica carácter por
  carácter y `wake.py` encontrando su nombre 3 de 3. 992 MiB por nada.
- **La caché KV de q8_0 a q4_0** — ~1.024 MiB, degradando contexto largo y
  nada más. Medido después: el contexto largo no se degradó de forma
  observable.
- **Descartado: repartir capas entre GPU y CPU**, que propuso el usuario y
  que llama.cpp sí soporta. Falló dos veces, y el segundo fallo nombra la
  causa: `layer 0 is assigned to device CPU but fused Gated Delta Net
  (chunked) is assigned to device CUDA0`. **La arquitectura híbrida de
  Qwen3.8 no sobrevive al reparto**, así que es peor candidata al offload
  que un modelo convencional.

Juntas dejan **más aire que antes**: 1.380 MiB libres con el modelo grande
contra 1.126 con el pequeño.

**Y apareció un cuarto consumidor de VRAM que ninguna cuenta de este
fichero había contado: el escritorio.** Xorg 99 MiB, gnome-shell 28, una
pestaña del navegador 35. No se puede recuperar — §2.2 y §2.3 dicen que
esto es un escritorio en el que el usuario trabaja. Es el tercer consumidor
que este proyecto presupuesta olvidando: primero Whisper, que costó tres
días de sordera, ahora la pantalla sobre la que dibuja. Lo encontró el
usuario preguntando lo que nadie había preguntado: «¿hay algo más usando la
GPU?».

**El precio, con A/B el mismo día** y todo lo demás idéntico — misma caché,
mismos prompts, misma temperatura, sólo cambia el fichero del modelo:

| | Heretic IQ4_XS | Q3_K_XL |
|---|---|---|
| 68 kWh × 0,1432 € (= 9,74) | **6,98** | 9,85 |
| «contesta con exactamente tres palabras» | cuatro | **tres** |
| contestar sin la letra «a» | falla | falla |
| recordar dos datos bajo 60 líneas de relleno | ✅ | ✅ |
| rellenar argumentos de herramientas (4 casos) | **4/4** | **4/4** |
| inventarse un generador de respaldo que no existe | sí | **sí, y encima lo ofrece** |

El precio es **literalidad y aritmética**, que encaja con el punto de MMLU
que su propia ficha admite. Lo que **no** es el precio, y yo había señalado
mal: confabular sobre la casa. El modelo viejo lo hace igual, y termina con
el ofrecimiento que el usuario pidió quitar en agosto.

**Y una corrección a la documentación, que es lo más útil de la tarde.**
§4 y §12 registran que el modelo local llama a `mirar` sin cámara 5 veces
de 5 y rellena herramientas con `args={}` seis veces seguidas, y lo
atribuyen al modelo. **No es el modelo.** Contra llama-server directo, con
una carga `tools` normal, los DOS modelos aciertan 4 de 4, incluida
`mirar({"camara":"entrada"})`. El fallo vive en el camino de Hermes — el
puente de tool-search, las herramientas diferibles o el prompt de la
plataforma. Quien vuelva a depurarlo debe empezar ahí.

**Sin verificar todavía:** las dos comprobaciones habladas del endpointing
(que conteste antes con una pausa dentro, y que se calle al hablarle
encima). Siguen necesitando una persona en la habitación.


## 2026-09-01 — La última pasada: seis hallazgos, y uno le dejaba sordo ✅

La revisión final de la rama, antes de darla por cerrada. Seis hallazgos,
todos arreglados en una pasada. 301 tests, subiendo desde 293.

**El grave: una llamada a Vosk que lanza le deja sordo para siempre.**
Los cuatro `push()` / `reset()` del callback de audio no tenían guarda.
`push()` ejecuta `AcceptWaveform` y `json.loads`; `reset()` construye un
`KaldiRecognizer`. Cualquier excepción salía del callback hacia
`audio.py:_pump`, que lo llama FUERA de su propio `try` — el hilo del
micrófono vuelve y no arranca nunca más. Sordo, con aspecto de estar
perfectamente sano, y un traceback en el journal. Es exactamente lo que
costó tres días el 2026-08-27 con un modelo de Whisper que no cabía.
Ahora todas pasan por `VoskSwitch`: el primer fallo apaga la función
para siempre y lo dice UNA vez, y a partir de ahí se comporta como antes
de esta rama — el suelo de 1,2 s cierra los turnos y todo sonido es una
persona. `build_may_close` y `build_is_a_person` sostienen los flujos
directamente, así que también leen el interruptor: si no, contestarían
con palabras rancias de un flujo que ya nadie alimenta. Y debajo de todo
eso, `_pump` sobrevive a lo que sea que lance su callback: la invariante
es «fallar es callar, nunca ensordecer», y el respaldo tiene que estar en
el hilo que oye.

**El arreglo estructural que la entrada de abajo dejó «deliberadamente
sin hacer» está hecho.** `Stream.reset()` es gratis cuando no se ha
empujado nada desde el último reset — un `_dirty` puesto en `push()` y
limpiado en `reset()`. 22,7 ms medidos por reconstrucción, el 71% de un
frame de 32 ms, en el hilo de PortAudio, que no puede bloquearse jamás.
Tres rondas de revisión encontraron el mismo defecto en tres sitios
distintos porque ningún sitio de llamada dice que sea caro; ahora el
precio se paga en un solo lugar. Las tres guardas de transición escritas
a mano se quedan: siguen siendo correctas y se ahorran hasta la
comprobación, pero han pasado de ser obligatorias a ser una optimización.

**Y tres cosas más pequeñas.** `_busy["was"]` se quedaba varado por el
retorno temprano del micrófono apagado — apaga el micro a mitad de
respuesta y la respuesta siguiente se acumula sobre la anterior en
`.room`, hasta que la primera envejece más allá de los 45 s de
`EchoFilter`, el residuo deja de encajar y se interrumpe a sí mismo sin
nadie en la habitación; la contabilidad es ahora lo primero que hace el
callback, por encima de toda rama que pueda retornar. `.turn` se
desincronizaba con una tos: `vad.py:_emit` se resetea y devuelve None
cuando el habla dura menos de 0,4 s, y el callback sólo olvidaba cuando
sobrevivía un enunciado — ahora olvida cuando olvida el detector.
`widget/README.md` seguía documentando `SAMANTHA_WIDGET_BARGE_RMS` como
«(default 0.05)» y como lo que separa su eco de una persona, que es
justo lo que no puede hacer; y CLAUDE.md §2.8 vuelve a mencionar
`SAMANTHA_WIDGET_MIC_GATE`, que sigue ahí como repliegue para una caja
donde decidirlo sobre palabras no baste.


## 2026-09-01 — El motor que no sabe puntuar decide cuándo callas ✅

Se pidió una alternativa a Whisper; la primera medición la retiró y dejó
otra cosa en su lugar. Después de que dejas de hablar, la tira esperaba
1,2 s de silencio contra 61-135 ms de transcripción — el motor nunca fue
lo lento. Lo que se entrega en su lugar es un segundo motor, Vosk
`small-es` (39 MB, Apache 2.0, en la CPU), que transcribe todo el rato y
cuyo texto no llega a ninguna parte — ni a la pantalla, ni al modelo, ni
a la red. Decide dos cosas: si la frase suena terminada, y si un sonido
mientras él habla es una persona o su propio eco. Whisper sigue
produciendo, sin cambios, cada palabra que ve Hermes. CLAUDE.md §0, §2.6,
§2.8, §9 y §12 llevan el resultado; §12 lleva además por qué un solo
motor resultó imposible (Moonshine no oye «Jarvis» — «ya luis», «yardi»
— y sólo Vosk salva una de las dos frases, por suerte).

**Los commits:** `cd37e4c` la regla de finalización (`endpoint.py`,
`CompletionRule`); `2d4330c` el disparo corto de la VAD, 0,35 s, junto a
su suelo de 1,2 s; `ac8c083` Vosk en sí, un modelo y dos flujos
independientes, `.turn` y `.room`; `78e2b06` el cableado del
endpointing en el callback de audio; y `9284b4e`, `f7b5fc2`, `ae53268`,
`8a383de` — el arreglo de la interrupción (barge-in) y sus tres rondas
de revisión. 293 tests, subiendo desde 285, todos en verde.

**Lo medido, y es lo que decide la arquitectura, no lo que la
justifica.** En la pausa a mitad de frase del usuario, Whisper escribió
«…habrá que comprobar que estén encendidas y con red.» — limpia,
puntuada, terminada — y cerrar ahí le habría cortado; siguió diciendo
otra cosa. Vosk, en el mismo instante, escribió «…que estén encendidas
y» y esperó. El mejor transcriptor es el peor endpointer, precisamente
porque es el mejor: completa la frase que oyó en vez de dejarla colgada
donde la dejó quien hablaba. Sobre la grabación: Vosk 2 cierres buenos y
0 cortes, Moonshine 1 y 1, Whisper 0 y 2. Ahorro medido: 880 ms por
turno.

**Y arregla, de paso, no poder interrumpirle.** La puerta de barge-in
era un umbral de volumen y no podía funcionar: la voz del usuario mide
RMS 0,054-0,088 y su propio eco, con los altavoces junto al micrófono,
0,178 — más alto que la persona. Ahora es un suelo de silencio
(`SAMANTHA_WIDGET_BARGE_RMS`, 0,01) y `EchoFilter` decide sobre palabras,
contra el parcial en vivo de Vosk.

**Lo que NO está probado, dicho sin adornos.** La muestra sobre la que
descansa todo el diseño es UNA grabación larga del usuario más cuatro
clips de agosto. No es un corpus. **El corte prematuro — la regla
cortando una frase antes de que termine — midió CERO en esa muestra, y
eso no es lo mismo que imposible**: el suelo de 1,2 s acota cuánto puede
equivocarse la regla, no lo impide. Y ninguna de las dos comprobaciones
de comportamiento se ha hecho todavía: nadie le ha hablado con una pausa
a mitad de frase para confirmar que ahora responde antes, y nadie le ha
hablado por encima para confirmar que ahora se calla. Las dos necesitan
a una persona delante y quedan pendientes.

**Lo que costó tres rondas de revisión, y merece quedar escrito porque
el mismo defecto apareció tres veces en tres sitios distintos:** un
`Stream.reset()` caro — construye un reconocedor de voz entero — llamado
una vez por frame de audio en vez de una vez por transición de estado.
Cada una de las tres apariciones la introdujo una instrucción del agente
coordinador, no el implementador. El arreglo estructural —que `reset()`
sea barato cuando no hay nada que olvidar— está identificado y
**deliberadamente sin hacer**: el código actual es correcto, y tocar eso
queda fuera del alcance aprobado para esta tarea.

**Coste, dicho llanamente:** un segundo motor STT en el árbol de
dependencias de la tira; una lista de palabras en español escrita a
mano, que es toda la regla y no generaliza a nada; y ~300 ms más lento
para reaccionar a una interrupción que un frame de 32 ms.


## 2026-09-01 — No habrá cara: el avatar se descarta entero ✅

Decisión del usuario, después de dos días midiéndolo: *«vamos a
descartar el uso de un avatar hiperhumano, no ofrece nada util salvo
bonito»* — y el descarte no se queda en el fotorrealista, alcanza a
**cualquier** avatar. A JARVIS lo representa la onda, como desde mayo, y
esto cierra la pregunta en vez de aplazarla. CLAUDE.md §12 lleva la
decisión; la spec `2026-08-30-avatar-3d-design.md` queda marcada como
superseded y se conserva por lo medido.

**No hubo nada que revertir, y merece decirse.** El diseño nunca llegó
al código: no se escribió plan, no se mezcló nada, los dos spikes fueron
desechables a propósito y `git grep -i avatar` encuentra esa spec y
nada más. **La regla dura que el diseño proponía romper no llegó a
romperse**: su propia cabecera decía que §2.3 y §3 perderían el «MUST
NOT introduce a browser / webview of any kind» *cuando esto se
entregue, no antes*, y no se entregó. La prohibición sigue entera.

**Lo que compraron los dos días, aunque la respuesta fuera que no:**

- **La cara nunca fue lo caro.** Un avatar de navegador, recortado con
  alfa sobre el escritorio, cuesta **~50 MiB de VRAM** — medido, en
  pantalla. Lo caro es lo que lo mueve, y la comparación honesta de esos
  motores está en la spec (`unreal-audio2lipsync`, MIT de verdad, 43,7
  MB de pesos y repliegue a CPU, contra los 2,2 GB de NVIDIA
  Audio2Face).
- **Dos cosas que dábamos por hacer resultaron estar hechas.** La banda
  compone alfa sin tocar nada — `do_snapshot` apila texturas y no pinta
  fondo — y la región de entrada existe en `ewmh.py` por
  `XShapeCombineRectangles`, con `XShapeCombineMask` enlazado y sin
  usar. El §12 del 2026-08-25 la sigue describiendo como aplazada, y no
  lo está.
- **La vía nativa se puso precio en vez de adivinarse.** UE 5.7 se
  compiló de fuentes en esta caja — 150 GB, ~50 min — y un MetaHuman
  ensamblado en el Creator cuesta **3.240 MiB de VRAM**. Ese número es
  el que volvió concreta la decisión: no cabe junto al 27B, y comprarlo
  significaba mudar el LLM.

**Lo que desbloquea, que es el dividendo real.** Tres conversaciones
convergían en una sola elección forzada — el avatar, bajar el LLM a 12B
y sustituir a Whisper — porque la VRAM del avatar era lo que volvía
urgentes a las otras dos. Sin él, **el 27B se queda donde está** y la
pregunta de Whisper vuelve a decidirse por sus propios méritos
(latencia, castellano, streaming), barata, cuando se retome.

**Lo borrado con la decisión:** el árbol de UE 5.7 en
`~/git/UnrealEngine` (150 GB) y el proyecto de prueba bajo
`~/Documents/Unreal Projects/`. Ninguno fue jamás dependencia de nada de
aquí.
