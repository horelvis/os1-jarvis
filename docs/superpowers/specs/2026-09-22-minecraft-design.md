# JARVIS con cuerpo — Minecraft (diseño)

> **Fecha:** 2026-09-22. **Estado:** diseño aprobado, sin código.
> **Origen:** `~/Downloads/hermes_minecraft_spec.md` (spec externa, en inglés).
> **Decisiones del propietario (2026-09-22):** servidor Minecraft en
> **Docker** en esta máquina; el bridge Node vive **dentro del plugin**
> (`Hermes/plugins/jarvis_minecraft/`); el cerebro siguen siendo las
> **tools nativas de Hermes** (no un bucle LLM aparte); la primera fase es
> **percepción + movimiento**.
>
> **Ampliación (2026-09-22, misma sesión):** el servidor se abre a la
> **LAN de casa** para que la gente entre y la vea jugar; y JARVIS
> **también oye y habla en el chat del juego**, con identidad por jugador.
> Las dos cosas son fases posteriores, no fase 1 (§10), pero condicionan
> la arquitectura y por eso están escritas aquí.

---

## 1. Qué es y qué no es

Darle a JARVIS un **cuerpo** dentro de Minecraft: un bot (Mineflayer) que
percibe el mundo, se mueve, mina, construye y se defiende, gobernado por
la misma persona y el mismo cerebro que ya hablan por la tira.

**Es:**
- Una **cuarta capacidad** de JARVIS, como las cámaras o el profesor: un
  plugin de Hermes que expone tools y mantiene un estado.
- Una **superficie nueva del mundo**, no de la tira: el bot vive en el
  juego; la tira solo habla de él.
- **Un mundo compartido.** La gente de casa entra a la LAN y juega con
  ella, la mira jugar y la ve desde fuera. La nube no hace falta para eso
  y rompería §1.1.
- **Una segunda boca y una segunda oreja.** Dentro del juego lee el chat y
  responde en él, con identidad por jugador — no solo por la tira (§7).

**No es:**
- **Un segundo cerebro.** La spec original describe un "Agent Bridge" que
  compila un snapshot y **llama al LLM** con `tool_calls`. Eso se
  descarta: Hermes ya es el bucle de tools y quien tiene la persona, la
  memoria y la sesión. Un segundo bucle perdería las tres cosas y
  contradiría §1. El bridge Node es **solo el cuerpo** (Mineflayer) y un
  traductor JSON; no razona, no llama a ningún modelo, no guarda
  conversación.
- **Un narrador de maquinaria.** §1: nunca dice nombres de tools, ni
  "ejecutando 3 de 5", ni el estado del pathfinder. Habla de lo que pasó,
  en pasado y en sus palabras, como con la búsqueda web.
- **Un visor.** `prismarine-viewer` (opcional en la spec) **no entra en el
  sistema que corre**: abriría un segundo navegador/webview, prohibido por
  §3. Queda como herramienta de desarrollo, nunca en la tira.

---

## 2. Arquitectura

```
        Minecraft server (Docker)             mundo virtual
        LAN:25565 (loopback por defecto) ◄── protocolo ──┐
                                                         │
        ┌────────────────────────────────────────────────▼─┐
        │  bridge Node (Mineflayer + pathfinder + collect)  │  cuerpo
        │  systemd --user: jarvis-minecraft-bridge.service  │
        │  estado del mundo · cola de acciones · guardrails │
        │  HTTP loopback 127.0.0.1:8095                     │
        └───────────────────────┬───────────────────────────┘
                     GET /state │ POST /do │ SSE /events
                                ▼
        ┌──────────────────────────────────────────────────┐
        │  plugin jarvis_minecraft (Python)                │  traductor
        │  tools del toolset `mundo` · check_fn · cooldown │
        │  inyección de eventos críticos                   │
        └───────────────────────┬──────────────────────────┘
                                │ tool calls / inject_message
                                ▼
        Hermes gateway :7777 ──► Bonsai 2 27B ──► la tira
```

**Puertos:** `8095` para el bridge. Libres y vecinos: `8093` CosyVoice,
`8094` fue el bus de la mascota retirada, `7777` gateway, `8000` llama,
`9910` bridge de código. Todo en loopback **salvo `25565`**, que es el
único que puede abrirse a la LAN (§8) para que entren a jugar. Nunca
`0.0.0.0`: se ata la IP concreta de la LAN, la misma regla que la página
del móvil (§2.1).

**Por qué el bridge es un servicio aparte y no lo lanza el plugin.** El
bot tiene que seguir conectado al servidor aunque el gateway se reinicie,
y una sesión de Minecraft no se reconecta sola. Mismo razonamiento que
`jarvis-code-a2a.service`: unidad propia, `After=network.target`,
`Restart=on-failure`. El plugin lo busca; no lo posee.

**Por qué Node y no Python.** La spec pide Mineflayer y no hay equivalente
maduro en Python (`pyCraft` no tiene pathfinding ni collectblock). Node 22
y npm 10 ya están en la máquina. El coste es un runtime más en el
proyecto; se paga dentro del directorio del plugin, sin tocar la raíz.

### El contrato es un contrato de cuerpo, no un contrato de Minecraft

Decisión del propietario (2026-09-22): el interés del proyecto es
incorporar **más juegos**, así que lo reutilizable no es Minecraft, es el
**contrato** de §3 — `/state`, `/do`, `/events` — que define qué es tener
un cuerpo: percibir, actuar y avisar. Minecraft es **el primer
adaptador**; lo específico del juego vive en `state.js` y `actions.js`, y
lo genérico (`server.js`, el plugin, la forma de las tools) se hereda.

Los siguientes candidatos son los juegos que **sí tienen API de bot**,
que son pocos: **Luanti/Minetest** (código abierto, protocolo y mods
programables), **Factorio** (API de mods, *headless*), **OpenRA**,
**ViZDoom** para investigación. Los juegos cerrados y competitivos
(**Fortnite** y compañía) **no tienen API de bots**: llevan
anti-cheat, automatizarlos infringe el EULA y arriesga baneo, y la única
ruta sería *computer-use* — ver la pantalla y mover ratón y teclado como
un humano —, que es frágil y sensible a ToS. Queda **fuera de alcance**,
y decirlo forma parte del diseño.

---

## 3. El contrato bridge ↔ plugin

HTTP JSON en loopback, sin autenticación (loopback), sin estado de sesión
entre llamadas. Tres endpoints, y la disciplina de fallo del proyecto.

### `GET /state` → snapshot

Devuelve el estado del mundo en el esquema de §4. Barato (lo compila el
bridge en cada tick), sin efectos secundarios.

### `POST /do` → una acción

```json
{ "action": "ir_a", "args": { "x": 142, "y": 64, "z": -210 } }
```

Respuesta **cuando la acción termina**, no cuando empieza:

```json
{ "ok": true, "said": "He llegado.", "state": { /* snapshot */ } }
{ "ok": false, "error": "sin_camino", "said": "No encuentro por dónde ir." }
```

`decir` es la única acción que no mueve el cuerpo: escribe en el chat del
juego (la segunda boca de §7).

```json
{ "action": "decir", "args": { "texto": "Voy para allá." } }
```

El bridge **serializa**: una sola acción a la vez, en cola. Mineflayer y
el pathfinder no hacen dos cosas a la vez, y el orden importa. Cada acción
tiene un **deadline** (`JARVIS_MC_ACTION_TIMEOUT`, por defecto 30 s) tras
el cual se aborta y se responde `ok:false` — un `move_to` que cuelga es
peor que uno que falla, porque la tira se queda muda.

### `GET /events` → SSE

El firehose de lo que el mundo hace sin que nadie pregunte: vida baja,
ataque recibido, muerte, llegada, inventario lleno — y **el chat de los
jugadores** (`{"event":"chat","jugador":"Ana","texto":"…"}`), que es la
segunda oreja de §7. El plugin lo sigue en un **hilo propio con
`urllib`**, exactamente como `jarvis_code/client.py` sigue el firehose de
`:9910` — nunca en el loop del gateway (§12, 2026-08-26, la lección de la
cámara en vivo). Cada evento crítico se inyecta a la sesión con
`ctx.inject_message()`; el chat sigue el camino de plataforma descrito en
§7.

---

## 4. Percepción: el snapshot del mundo

El esquema de la spec, recortado a lo que el modelo necesita y acotado
para no inflar el prompt. Los números redondeados: al modelo no le importa
`142.5` frente a `142`, y los decimales son tokens.

```json
{
  "bot": {
    "vida": 20,
    "comida": 18,
    "posicion": { "x": 142, "y": 64, "z": -210 },
    "dormido": false,
    "hora": 14000,
    "es_de_dia": false,
    "dimension": "overworld"
  },
  "inventario": [
    { "bloque": "cobblestone", "cantidad": 64 },
    { "bloque": "iron_pickaxe", "cantidad": 1 }
  ],
  "entorno": {
    "entidades": [
      { "tipo": "zombie", "id": "e_12", "distancia": 8, "hostil": true }
    ],
    "bajo_los_pies": "grass_block",
    "miran": ["zombie"]
  }
}
```

- `entorno.entidades` acotado a un radio (`JARVIS_MC_RADAR`, por defecto
  16) y a los N más cercanos (12). Un servidor con cien mobs no puede
  volcar cien entradas al prompt.
- `bajo_los_pies` cubre `target_block_underfoot` de la spec.
- **Sin imágenes.** El modelo es texto; el mundo se cuenta con texto, y
  nada de lo que devuelve una tool se lee en voz alta (§5).

---

## 5. Las tools

Toolset propio, **`mundo`**, con nombres en español como `mirar` y
`ensename` (los nombres no se dicen; la convención del repo manda). Mapa
1:1 con la spec:

| spec (inglés) | tool JARVIS | toolset |
|---|---|---|
| — (percepción) | `estado_del_mundo` | `mundo` |
| `move_to_coordinates` | `ir_a` | `mundo` |
| `collect_resources` | `minar` | `mundo` |
| `place_block` | `colocar` | `mundo` |
| `defend_or_attack` | `atacar` | `mundo` |

Igual que en `jarvis_teacher` y `jarvis_vision`, `schema` es el **objeto
función** de OpenAI (`{"description": …, "parameters": …}`), no los
parámetros sueltos: pasar solo `parameters` es lo que hizo que el modelo
llamara `mirar` con `{}` cinco veces de cinco (§4, §12).

- **`estado_del_mundo`** — sin argumentos. Devuelve el snapshot de §4
  **como texto JSON** para que el modelo razone. No lo dice en voz alta;
  lo parafrasea.
- **`ir_a(x, y, z)`** — pathfinding. La tool devuelve una frase corta
  ("He llegado." / "No encuentro por dónde ir.") y el estado nuevo.
- **`minar(bloque, cantidad=1)`** — busca en el radio, mina, recoge.
- **`colocar(bloque, x, y, z, cara=[x,y,z]?)`** — `cara` opcional; el
  bridge la deduce del bloque sólido adyacente si falta.
- **`atacar(objetivo)`** — `objetivo` es el `id` del snapshot
  (`"e_12"`), no el tipo: dos zombis son dos zombis.

**`check_fn`** en todas: si el bridge no está conectado al servidor, la
tool no se le ofrece al modelo. Ofrecer una tool que no puede funcionar es
exactamente lo que `check_fn` existe para evitar (§12, Ruling 11).

---

## 6. Guardrails (traducidos a esta arquitectura)

La spec define tres. Dos se implementan tal cual; el tercero cambia de
sitio porque el bucle de LLM ya no está en el bridge.

1. **Modo emergencia — en el bridge, sin LLM.** Si `vida < 6`, el bridge
   **aborta la acción en curso** (incluida una que él pidió), come si
   lleva comida, y ejecuta una rutina de retirada: retrocede al último
   punto seguro conocido y se encierra. Luego emite `emergency` por SSE.
   No espera aprobación de nadie porque a vida 6 no hay tiempo. Es la
   única parte del sistema que actúa sola, y su radio está acotado: comer
   y esconderse, nada más.
2. **Rate limiting — reencuadrado.** No hay "1 llamada al LLM cada 2 s"
   porque el bridge no llama al LLM. El equivalente es que **el bridge
   emite como máximo un evento crítico por ventana**
   (`JARVIS_MC_EVENT_COOLDOWN`, por defecto 30 s) y **el plugin inyecta
   como máximo un mensaje por ventana**. El bucle de tools ya lo acota
   `agent.max_turns: 10` (§jarvis-config.yaml).
3. **Comprobación física de bloques — en el bridge.** Antes de
   `colocar`, verifica que el destino está vacío y que hay una cara
   sólida adyacente para anclar. Si no, `ok:false` con una frase, sin
   colocar a medias.

---

## 7. Cómo se le pide (voz y persona)

Se le pide **hablando**, como todo lo demás: *"Jarvis, ve a por madera"*,
*"¿dónde estás?"*, *"hazte una casita aquí"*. El modelo decide la tool.

- **Percepción bajo demanda, no en cada turno.** La spec pide un snapshot
  por turno; eso metería ~300 tokens en *toda* conversación, incluidas las
  que no tienen nada que ver con Minecraft, y ensuciaría la persona. En su
  lugar: `estado_del_mundo` cuando hace falta, y **eventos críticos
  inyectados** cuando el mundo cambia solo (le atacan, muere, se hace de
  noche con vida baja).
- **Los eventos necesitan permiso.** `allow_gateway_injection: true` en la
  entrada del plugin, o `ctx.inject_message()` devuelve `False` y el bot
  se muere en silencio mientras todo lo demás parece sano — el fallo de
  `jarvis-vision` y `jarvis-code`, ya medido dos veces (§jarvis-config.yaml).
- **Qué dice y qué no.** Dice que ha ido, qué encontró y qué le pasó, en
  pasado. No dice el nombre de la tool, ni las coordenadas que usó, ni
  cuántos bloques minó. Si un encargo no se puede cumplir sin narrar la
  maquinaria, lo declina en sus palabras.
- **Una identidad en el juego.** El bot es "Jarvis", no un usuario
  anónimo. El servidor es de la casa; que el nombre sea el suyo es lo
  coherente con §1.

### Dentro del juego: la segunda boca (fase posterior)

Decisión del propietario (2026-09-22): con gente en el mundo, JARVIS
**lee el chat y responde en él**, no solo por la tira. Eso es más que una
tool, y hay que decirlo con precisión:

- **Es una plataforma de Hermes, no una tool.** El sitio donde nace un
  turno determina dónde viaja su respuesta (decisión ya tomada en
  `plans/2026-09-08-hermes-authority-migration.md`: el destino es
  inmutable, se fija al admitir el turno). Un turno que llega por el chat
  del juego se responde **en el chat del juego**; uno que llega por la
  tira se responde **por la tira**. La tira es una plataforma (`jarvis`);
  el juego sería otra (`minecraft`). El adapter de esa plataforma entrega
  llamando a la acción `decir` del bridge.
- **Identidad por jugador.** El nombre del jugador en el mundo es el
  `chat_id` de esa plataforma, y se resuelve a un perfil/sesión de Hermes
  reutilizando lo que ya existe para el móvil (`multiplex_profiles`,
  `profile_routes`, y el hilo de *identidad por persona* del 2026-09-05).
  Que Ana hable en el juego no puede responderle con la memoria de orelvis.
- **Oye todo, contesta cuando le hablan.** Igual que en la tira decide
  `wake.py` (§2.8), aquí contestar a cada línea del chat sería insufrible:
  solo responde si le nombran, o si ya está en conversación con ese
  jugador. La regla exacta se decide en esa fase.
- **Sin eco.** No puede contestarse a sí mismo ni a otros bots; el bridge
  marca el origen y el plugin descarta lo propio.
- **La persona no cambia.** Sigue sin narrar maquinaria, aquí igual que
  en la voz. En el juego escribe texto; por la tira sigue hablando.

**Lo primero que mide esa fase** es si un plugin `kind: standalone` puede
registrar una plataforma o si eso es cosa de un plugin `kind: platform`
(§jarvis-config.yaml, `jarvis`). Según la respuesta, el chat vive en
`jarvis_minecraft` o en un plugin hermano; no se asume.

---

## 8. Infraestructura

### Servidor (Docker, en esta máquina)

- Imagen `itzg/minecraft-server`, `TYPE=PAPER`, **versión pinneada**.
  Java 21 viene dentro de la imagen: **no se instala Java en el host**
  (hoy solo hay Java 8, que no sirve para un MC moderno).
- **El puerto se ata a una IP concreta, nunca a `0.0.0.0`** (misma regla
  que la página del móvil, §2.1). Por defecto `127.0.0.1:25565`; para que
  la gente entre, `${MC_BIND_IP}:25565` con la IP de la LAN, que vive en
  `.env` (git-ignored) como el `RTSP_PASSWORD`. El compose lee
  `MC_BIND_IP` con loopback como valor por defecto, así que abrirlo es
  una línea y no un descuido.
- **Whitelist obligatoria en cuanto se abre a la LAN.** El modelo de
  amenaza del proyecto ya es "quien esté en el wifi, invitados incluidos"
  (§1.1): el puerto es alcanzable por cualquiera en la red, y la
  whitelist es la única puerta. `ONLINE_MODE=false` + whitelist es lo
  pragmático para un juego de casa; `true` da identidad real por cuenta
  Microsoft, pero entonces **el bot también necesita cuenta**
  (`auth: "microsoft"`) y cada persona la suya. Se empieza por
  `false` + whitelist y se revisa si la identidad por jugador (la del
  chat, §7) lo pide.
- `restart: unless-stopped`, `-Xmx` acotado (2–4 GB). El mundo en un
  volumen nombrado, fuera de git.
- El `docker-compose.yml` vive **dentro del directorio del plugin**
  (`Hermes/plugins/jarvis_minecraft/server/`), no en un directorio de
  primer nivel nuevo. `tts-server/` ya es la excepción histórica; no se
  crea otra.
- **Verla jugar no necesita nada nuevo.** Se entra al mundo desde un
  cliente de Minecraft normal y se la mira en tercera persona o como
  espectador. `prismarine-viewer` seguiría fuera: es un segundo
  navegador/webview (§3).

### Bridge (Node, dentro del plugin)

```
Hermes/plugins/jarvis_minecraft/
├── plugin.yaml            manifest_version: 2, kind: standalone
├── __init__.py            register(): tools + check_fn + inyección
├── mundo.py               tools, esquemas, frases (puro, testeable)
├── bridge_client.py       HTTP a :8095 + follower SSE (hilo, urllib)
├── bridge/                el cuerpo, Node
│   ├── package.json       mineflayer, mineflayer-pathfinder,
│   │                        mineflayer-collectblock
│   ├── index.js           arranque, conexión, reconexión
│   ├── state.js           snapshot, puro y testeable
│   ├── actions.js         cola serial, deadlines, guardrails
│   └── server.js          HTTP loopback :8095 (state/do/events)
├── server/                docker-compose.yml del servidor MC
├── README.md              versiones pinneadas, fallos silenciosos
└── tests/                 espejo de los tests Python de los otros plugins
```

### Arranque

- `systemd/jarvis-minecraft-bridge.service` — `ExecStart=node …/bridge/index.js`,
  `Restart=on-failure`, `After=network.target`. No depende del display ni
  de la sesión gráfica.
- `Hermes/setup-runtime.sh`: añadir `jarvis_minecraft` a los bucles de
  symlink y `plugins enable`, y un paso `npm ci --prefix
  …/jarvis_minecraft/bridge`. Las `python_dependencies` del manifest se
  **declaran pero Hermes no las instala** (solo avisa); para Node no hay
  ni eso, así que el `npm ci` es explícito o el bridge no arranca.
- `jarvis-config.yaml`: `plugins.enabled` += `jarvis-minecraft`;
  `platform_toolsets.jarvis` += `mundo`; entrada con
  `allow_tool_override: false` y `allow_gateway_injection: true`.

### Presupuesto

| | RAM | VRAM |
|---|---|---|
| servidor MC (Docker) | ~2–4 GB | 0 |
| bridge Node | ~150–250 MB | 0 |
| plugin (en el gateway) | ~0 | 0 |

**VRAM: cero.** No compite con llama-server, CosyVoice ni Whisper, y el
presupuesto de §0 queda intacto. RAM libre hoy: 54 GB. Este es el primer
subsistema del proyecto que no toca la GPU, y conviene que siga siéndolo:
nada de `prismarine-viewer` en producción.

---

## 9. Modos de fallo silenciosos (el apartado que importa)

Como en `jarvis_vision`, cada fallo tiene que tener nombre y síntoma.

1. **El servidor no está levantado.** El bridge no conecta: un WARNING la
   primera vez, luego DEBUG, con back-off (nunca un warning por intento a
   las tres de la mañana). Las tools quedan con `check_fn=False`.
2. **El bridge no está corriendo.** El plugin no responde a `/state`; un
   WARNING, luego DEBUG. Se ve en `systemctl --user status
   jarvis-minecraft-bridge`.
3. **Versión de Minecraft incompatible.** Mineflayer y el servidor hablan
   protocolos distintos: el handshake falla o el bot entra y no ve nada.
   Es el fallo más caro de diagnosticar; por eso la **fase 0 fija el par
   versión-MC / versión-mineflayer con una sonda** antes de escribir nada
   más, y las dos quedan pinneadas en `package.json` y en el compose.
4. **Una acción cuelga.** El deadline la aborta y devuelve `ok:false`; sin
   él, la tira se queda muda hasta el watchdog de 90 s.
5. **Dos bridges, un bot.** Un segundo proceso intentando la misma
   identidad hace que el servidor patee al primero, y los dos parecen
   cuerdos. La unidad systemd es el único dueño del bot; nada más lo
   lanza.
6. **Inyección denegada.** Sin `allow_gateway_injection`, los eventos
   críticos se pierden en silencio (medido en visión y en código). Queda
   escrito en `jarvis-config.yaml` para que no vuelva a costar una tarde.
7. **La rutina de emergencia falla.** Aunque la retirada no llegue a
   término, el evento `emergency` **se emite igual**: JARVIS tiene que
   poder decir que está en apuros aunque no se haya salvado.

---

## 10. Fases

Solo las fases 0 y 1 tienen plan de ejecución
(`plans/2026-09-22-minecraft.md`). Las demás son dirección, no compromiso.

1. **Fase 0 — sonda.** Servidor Docker arriba, `mineflayer` conecta,
   `GET /state` devuelve un snapshot real. Fija el par de versiones.
   Criterio de cierre: un JSON con la posición del bot, leído desde
   `curl`.
2. **Fase 1 — cuerpo y dos tools.** Bridge completo (cola, deadline,
   reconexión), unidad systemd, plugin con `estado_del_mundo` e `ir_a`,
   toolset `mundo` habilitado. Prueba de voz: *"¿dónde estás?"* y *"ve a
   tal sitio"*. ← **alcance aprobado para empezar**
3. **Fase 2 — minar y construir.** `minar` (collectblock) y `colocar`
   (comprobación física), con inventario en el snapshot.
4. **Fase 3 — combate y supervivencia.** `atacar`, modo emergencia,
   inyección de eventos críticos, cooldown.
5. **Fase 4 — el mundo compartido.** Abrir el `25565` a la LAN
   (`MC_BIND_IP` en `.env`), whitelist, y que la gente entre a jugar y a
   verla. No añade código de agente; añade infraestructura y una decisión
   de seguridad.
6. **Fase 5 — la segunda boca.** La plataforma `minecraft`: leer el chat
   del juego, responder en él, identidad por jugador (§7). Empieza
   midiendo si un plugin `kind: standalone` puede registrar una
   plataforma.
7. **Fase 6 — otro juego.** Probar que el contrato de cuerpo generaliza:
   un segundo adaptador (Luanti o Factorio) detrás del mismo `/state`,
   `/do`, `/events`. Candidatos y descartes en §2.
8. **Fase 7 — autónomo (fuera de alcance hoy).** Rutinas de construcción
   guiadas, encargos largos sin supervisión.

---

## 11. Preguntas abiertas

- **Versión de Minecraft.** Se fija en la fase 0; candidata `1.21.x` con
  el mineflayer que la soporte. No se inventa aquí.
- **Semilla y modo de juego.** ¿Supervivencia desde cero, o un mundo
  creativo preparado para construir? Cambia qué tiene sentido que le
  pidamos.
- **El bot en el chat del juego.** Decidido que sí (§7); queda abierto
  **cuándo contesta**: ¿solo si le nombran, o también si ya está en
  conversación con ese jugador?
- **`online-mode`.** ¿Whitelist por nombre (simple, pero un nombre se
  puede falsificar) o cuentas Microsoft reales (identidad de verdad, más
  fricción y una cuenta para el bot)?
- **Coordenadas frente a nombres.** ¿Solo `ir_a(x,y,z)`, o también "ve a
  casa" con puntos con nombre guardados? Los nombres son más naturales
  para hablar; necesitan un registro de sitios.
- **Qué pasa si él muere.** ¿Respawn silencioso y sigue, o lo cuenta?
  §1 dice que cuenta lo que le pasa.

**Referencias:** `~/Downloads/hermes_minecraft_spec.md` (spec de origen);
`Hermes/plugins/jarvis_vision/` (plugin, check_fn, inyección, modos de
fallo); `Hermes/plugins/jarvis_code/client.py` (follower SSE en hilo);
`systemd/jarvis-code-a2a.service` (servicio hermano); `CLAUDE.md` §0
(presupuesto), §1 (persona), §3 (estructura), §12 (decisiones).
