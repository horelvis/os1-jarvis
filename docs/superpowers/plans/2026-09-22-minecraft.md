# JARVIS con cuerpo — Minecraft, fases 0–1 (plan de ejecución)

> **Para quien ejecute:** plan por tareas con casillas (`- [ ]`). El diseño
> está en `docs/superpowers/specs/2026-09-22-minecraft-design.md`; este
> documento no lo repite, lo ejecuta. Leer el diseño antes de empezar.

**Objetivo:** un bot de Minecraft conectado a un servidor local, con el
cuerpo (Mineflayer) en un bridge Node propio y dos tools en Hermes
(`estado_del_mundo`, `ir_a`) que JARVIS pueda invocar por voz.

**Arquitectura:** servidor MC en Docker → bridge Node en
`Hermes/plugins/jarvis_minecraft/bridge/` (systemd propio, HTTP loopback
`:8095`) → plugin Python `jarvis_minecraft` (toolset `mundo`) → gateway
Hermes. El bridge no razona ni llama a ningún modelo: solo ejecuta.

**Tech stack:** Node 22 + `mineflayer` (+ `pathfinder`, `collectblock`),
`node:test`. Python 3.11/3.12 + `loguru` + `urllib` (sin deps nuevas en el
gateway). Docker (`itzg/minecraft-server`, Java 21 dentro de la imagen).
Nada de VRAM.

**Spec:** `docs/superpowers/specs/2026-09-22-minecraft-design.md`.

---

## Restricciones globales

- Identificadores, comentarios y mensajes de commit: **inglés**. Frases
  que se dicen en voz alta y descripciones de tools: **español** (§2.9).
- Nunca `print()` en código de plugin del gateway — `loguru`. El bridge es
  un programa aparte y sí escribe a stderr.
- Nada de `prismarine-viewer` en el sistema que corre (segundo
  navegador/webview, §3). Solo herramienta de desarrollo.
- Nada de `backend/` ni `frontend/` (§3). El trabajo nuevo vive en
  `Hermes/plugins/jarvis_minecraft/`, `systemd/` y `docs/`.
- **No crear directorios de primer nivel.** El compose del servidor vive
  dentro del plugin.
- **El `25565` queda en loopback en las fases 0–1.** Abrirlo a la LAN
  (para que entren a jugar y a verla) es la fase 4 y va con whitelist; el
  chat del juego es la fase 5. Este plan no las toca, pero el compose ya
  está escrito para que abrirlas sea una línea de `.env`.
- **El hilo del gateway no se bloquea nunca desde un hilo del plugin**
  (§12, 2026-08-26). El follower de eventos es un hilo con `urllib`, como
  `jarvis_code/client.py`.
- Las tools se registran con `schema={"description": …, "parameters": …}`
  (el objeto **función**, no los parámetros sueltos): pasar solo los
  parámetros es lo que hizo que el modelo llamara con `{}` (§12).
- `check_fn` en todas las tools: si el bridge no está conectado, no se
  ofrecen.
- **Comandos de test (verificados en esta máquina, 2026-09-22):**
  - Plugins: `cd /home/nexus/git/os1-jarvis && PYTHONNOUSERSITE=1 widget/.venv/bin/python -m pytest Hermes/plugins/jarvis_minecraft/tests -q`
  - Bridge: `cd /home/nexus/git/os1-jarvis/Hermes/plugins/jarvis_minecraft/bridge && npm test`
  - Lint: `cd /home/nexus/git/os1-jarvis && widget/.venv/bin/ruff check Hermes/plugins/jarvis_minecraft && widget/.venv/bin/ruff format --check Hermes/plugins/jarvis_minecraft`
- **Estado del árbol:** hay cambios sin commitear (retirada de
  `jarvis_mascota`, `CLAUDE.md`, `PROGRESS.md`). No se solapan con los
  ficheros de este plan, pero conviene commitearlos antes de empezar para
  no mezclar historias.
- Commit directo en `development`, sin ramas.

## Estructura de ficheros

```
Hermes/plugins/jarvis_minecraft/
  plugin.yaml              NEW  manifest_version: 2, kind: standalone
  __init__.py              NEW  register(): tools, check_fn, follower
  mundo.py                 NEW  tools: esquemas, frases, handlers (puro)
  bridge_client.py         NEW  HTTP a :8095 + follower SSE (hilo, urllib)
  README.md                NEW  versiones pinneadas, fallos silenciosos
  bridge/
    package.json           NEW  mineflayer + pathfinder + collectblock
    config.js              NEW  env: host, puerto, radar, deadlines
    state.js               NEW  snapshot del mundo (puro)
    state.test.js          NEW
    actions.js             NEW  cola serial, deadline, ir_a
    actions.test.js        NEW
    server.js              NEW  HTTP :8095 (/state, /do, /events)
    server.test.js         NEW
    index.js               NEW  bot + reconexión + wiring
    probe.js               TEMP sonda de versiones (se borra en Task 2)
  server/
    docker-compose.yml     NEW  el servidor MC
  tests/
    __init__.py            NEW
    test_mundo.py          NEW
    test_bridge_client.py  NEW
    test_plugin.py         NEW

systemd/jarvis-minecraft-bridge.service   NEW
docs/superpowers/specs/2026-09-22-minecraft-probe.md  NEW  hallazgos Task 2
```

---

### Task 1: Levantar el servidor de Minecraft

**Files:**
- Create: `Hermes/plugins/jarvis_minecraft/server/docker-compose.yml`

**Interfaces:**
- Produces: un servidor Paper en `127.0.0.1:25565`, `ONLINE_MODE=false`,
  volumen `minecraft-data`. Versión **candidata** `1.21.1` (la sonda de
  Task 2 la confirma o la baja).

- [ ] **Step 1: Escribir el compose**

```yaml
# El servidor de Minecraft de JARVIS. Java 21 viene dentro de la imagen:
# el host solo tiene Java 8 y no se le instala nada.
services:
  minecraft:
    image: itzg/minecraft-server:java21
    container_name: jarvis-minecraft
    environment:
      EULA: "TRUE"
      TYPE: "PAPER"
      VERSION: "1.21.1"
      ONLINE_MODE: "FALSE"      # el bot es local; sin auth de Mojang
      MEMORY: "3G"
      DIFFICULTY: "normal"
      MODE: "survival"
      ENABLE_RCON: "false"
      # La whitelist se enciende cuando el puerto se abre a la LAN (fase 4),
      # con los nombres de casa. Nunca 0.0.0.0 (§2.1).
      # WHITELIST: "Ana,Orelvis"
      # ENFORCE_WHITELIST: "TRUE"
    ports:
      # Loopback por defecto. Para que entren a jugar, MC_BIND_IP=IP_LAN en
      # .env (git-ignored) — nunca 0.0.0.0.
      - "${MC_BIND_IP:-127.0.0.1}:25565:25565"
    volumes:
      - minecraft-data:/data
    restart: unless-stopped

volumes:
  minecraft-data:
```

- [ ] **Step 2: Levantarlo**

Run: `docker compose -f Hermes/plugins/jarvis_minecraft/server/docker-compose.yml up -d`
Expected: `Container jarvis-minecraft  Started`.

- [ ] **Step 3: Esperar a que arranque y verificar**

Run: `docker logs -f jarvis-minecraft` (hasta ver `Done (…)` y
`Starting remote control listener`/`Server started`), luego
`docker compose -f Hermes/plugins/jarvis_minecraft/server/docker-compose.yml ps`
Expected: estado `running (healthy)`.

- [ ] **Step 4: Commit**

```bash
git add Hermes/plugins/jarvis_minecraft/server/docker-compose.yml
git commit -m "feat(minecraft): a local Paper server, loopback only"
```

---

### Task 2: Sonda — el par de versiones MC / mineflayer

La spec no fija versiones y es el fallo más caro de diagnosticar (diseño
§9.3). **Código desechable; el entregable es el doc de hallazgos.**

**Files:**
- Create: `Hermes/plugins/jarvis_minecraft/bridge/package.json`
- Create (temporal, se borra al final): `Hermes/plugins/jarvis_minecraft/bridge/probe.js`
- Create: `docs/superpowers/specs/2026-09-22-minecraft-probe.md`

**Interfaces:**
- Produces: versiones **exactas** de `mineflayer`, `mineflayer-pathfinder`
  y `mineflayer-collectblock` (pinneadas con `--save-exact`), y un
  snapshot real de ejemplo en el doc de hallazgos.

- [ ] **Step 1: Crear el paquete e instalar**

```bash
cd Hermes/plugins/jarvis_minecraft/bridge
npm init -y
npm pkg set name=jarvis-minecraft-bridge private=true type=module
npm install --save-exact mineflayer mineflayer-pathfinder mineflayer-collectblock
```

- [ ] **Step 2: Escribir la sonda**

```js
// probe.js — desechable. Conecta, imprime estado y sale.
import mineflayer from "mineflayer";

const bot = mineflayer.createBot({
  host: "127.0.0.1",
  port: 25565,
  username: "Jarvis",
  auth: "offline",
  version: process.env.MC_VERSION || "1.21.1",
});

bot.once("spawn", () => {
  console.log(JSON.stringify({
    version: bot.version,
    position: bot.entity.position,
    health: bot.health,
    food: bot.food,
    time: bot.time.timeOfDay,
    inventory: bot.inventory.items().map((i) => ({ name: i.name, count: i.count })),
    entities: Object.keys(bot.entities).length,
  }, null, 2));
  bot.quit();
});
bot.on("error", (e) => { console.error("ERROR", e.message); process.exit(1); });
bot.on("kicked", (r) => { console.error("KICKED", r); process.exit(1); });
```

- [ ] **Step 3: Ejecutarla**

Run: `node probe.js`
Expected: un JSON con `version`, `position`, `health: 20`.
Si el handshake falla o `version` no coincide: bajar `VERSION` en el
compose al **par más nuevo que mineflayer soporte**, recrear el contenedor
y repetir. Anotar el par elegido.

- [ ] **Step 4: Escribir los hallazgos y borrar la sonda**

`docs/superpowers/specs/2026-09-22-minecraft-probe.md`: par de versiones
final, salida real de la sonda, y cualquier sorpresa (p. ej. Paper
reportando una cadena de versión que mineflayer no adivina — de ahí
`version:` explícito). Borrar `probe.js`.

- [ ] **Step 5: Commit**

```bash
git add Hermes/plugins/jarvis_minecraft/bridge/package.json \
        Hermes/plugins/jarvis_minecraft/bridge/package-lock.json \
        docs/superpowers/specs/2026-09-22-minecraft-probe.md
git commit -m "feat(minecraft): pin the server/mineflayer version pair"
```

---

### Task 3: `state.js` — el snapshot del mundo

**Files:**
- Create: `Hermes/plugins/jarvis_minecraft/bridge/config.js`
- Create: `Hermes/plugins/jarvis_minecraft/bridge/state.js`
- Create: `Hermes/plugins/jarvis_minecraft/bridge/state.test.js`

**Interfaces:**
- `config.js` exporta `HOST`, `PORT`, `RADAR` (16), `MAX_ENTITIES` (12),
  `ACTION_TIMEOUT_MS` (30000), `EVENT_COOLDOWN_MS` (30000), todos desde
  `process.env.JARVIS_MC_*` con esos defaults.
- `snapshot(bot, { radar = RADAR, maxEntities = MAX_ENTITIES } = {}) ->
  object` — el JSON del diseño §4. Solo lee campos del bot; sin red.
- `nearestEntities(bot, radar, maxEntities) -> array`.

- [ ] **Step 1: Escribir el test primero (con un bot falso)**

```js
import { test } from "node:test";
import assert from "node:assert/strict";
import { snapshot, nearestEntities } from "./state.js";

function fakeBot() {
  return {
    version: "1.21.1",
    health: 20, food: 18,
    entity: { position: { x: 142.5, y: 64.0, z: -210.3 } },
    time: { timeOfDay: 14000 },
    dimension: "overworld",
    inventory: { items: () => [{ name: "cobblestone", count: 64 }] },
    entities: {
      e_12: { id: 12, name: "zombie", type: "hostile",
              position: { x: 150, y: 64, z: -210 } },
      e_3:  { id: 3, name: "cow", type: "animal",
              position: { x: 160, y: 64, z: -210 } },
    },
  };
}

test("redondea la posición y cuenta el inventario", () => {
  const s = snapshot(fakeBot());
  assert.deepEqual(s.bot.posicion, { x: 142, y: 64, z: -210 });
  assert.equal(s.inventario[0].bloque, "cobblestone");
  assert.equal(s.bot.es_de_dia, false);
});

test("solo las entidades dentro del radar, las más cercanas primero", () => {
  const near = nearestEntities(fakeBot(), 16, 12);
  assert.deepEqual(near.map((e) => e.id), ["e_12"]);
  assert.equal(near[0].hostil, true);
});
```

- [ ] **Step 2: Ejecutar y ver fallar**

Run: `cd Hermes/plugins/jarvis_minecraft/bridge && npm test`
Expected: FAIL — `state.js` no existe.

- [ ] **Step 3: Implementar `config.js` y `state.js`**

`es_de_dia`: `timeOfDay < 13000 || timeOfDay > 23000` (aprox.; el umbral
no es crítico). `hostil`: `type === "hostile"`. Distancia redondeada.

- [ ] **Step 4: Ejecutar y ver pasar**

Run: `npm test`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add Hermes/plugins/jarvis_minecraft/bridge/config.js \
        Hermes/plugins/jarvis_minecraft/bridge/state.js \
        Hermes/plugins/jarvis_minecraft/bridge/state.test.js
git commit -m "feat(minecraft): a pure world snapshot, bounded and testable"
```

---

### Task 4: `actions.js` — cola serial, deadline y `ir_a`

**Files:**
- Create: `Hermes/plugins/jarvis_minecraft/bridge/actions.js`
- Create: `Hermes/plugins/jarvis_minecraft/bridge/actions.test.js`

**Interfaces:**
- `deadline(promise, ms, reason) -> Promise` — rechaza con `Error(reason)`
  si tarda más.
- `class ActionQueue { constructor({ handlers, timeoutMs }); run(name, args)
  -> Promise<{ ok, said, error?, state? }> }` — **serializa**: una acción a
  la vez, FIFO. Nunca rechaza; convierte el error en `{ok:false, said}`.
- `ir_a(bot, { x, y, z }) -> Promise<void>` usando
  `bot.pathfinder.goto(new goals.GoalBlock(x, y, z))`.
- `SAID` — mapa de frases: `llegado`, `sin_camino`, `tardanza`.

- [ ] **Step 1: Escribir el test (cola y deadline, con un bot falso)**

Probar: (a) dos `run` no se solapan (orden de entrada/salida), (b) un
handler que tarda más que `timeoutMs` devuelve `ok:false` con
`error:"tardanza"`, (c) un handler que lanza devuelve `ok:false` sin
romper la cola. `ir_a` se prueba con un `pathfinder.goto` falso que
resuelve y otro que rechaza.

- [ ] **Step 2: Ejecutar y ver fallar** — `npm test`.

- [ ] **Step 3: Implementar `actions.js`.**

`deadline` con un `setTimeout` que limpia al resolverse. La cola encadena
promesas (`this.tail = this.tail.then(...)`) y captura todo.

- [ ] **Step 4: Ejecutar y ver pasar** — `npm test`.

- [ ] **Step 5: Commit**

```bash
git add Hermes/plugins/jarvis_minecraft/bridge/actions.js \
        Hermes/plugins/jarvis_minecraft/bridge/actions.test.js
git commit -m "feat(minecraft): a serial action queue with a deadline"
```

---

### Task 5: `server.js` + `index.js` — el bridge en pie

**Files:**
- Create: `Hermes/plugins/jarvis_minecraft/bridge/server.js`
- Create: `Hermes/plugins/jarvis_minecraft/bridge/server.test.js`
- Create: `Hermes/plugins/jarvis_minecraft/bridge/index.js`

**Interfaces:**
- `createServer({ getState, doAction, subscribe, events }) ->
  http.Server`. Rutas:
  - `GET /state` → `200 application/json` con `getState()`.
  - `POST /do` → cuerpo `{action, args}`; `200` con
    `await doAction(action, args)`; `400` si falta `action`.
  - `GET /events` → `text/event-stream`; cada evento como
    `data: {json}\n\n`; al conectar envía un comentario `: ok` de
    keepalive.
- `index.js`: crea el bot, `bot.once("spawn")` → `queue` + `createServer`
  escuchando en `HOST:PORT`; `bot.on("end"/"error")` → reconexión con
  back-off (1 s → 30 s), un WARNING la primera vez y DEBUG después
  (diseño §9.1).

- [ ] **Step 1: Escribir el test del servidor**

Levantar en puerto `0`, leer el `address().port`, y con `fetch`:
`GET /state` devuelve el objeto; `POST /do` devuelve `{ok:true}`; una
suscripción SSE recibe un `data:` publicado. Cerrar el servidor al final.

- [ ] **Step 2: Ejecutar y ver fallar** — `npm test`.

- [ ] **Step 3: Implementar `server.js` e `index.js`.**

- [ ] **Step 4: Prueba manual contra el servidor real**

Run: `node index.js` en una terminal; en otra:
`curl -s http://127.0.0.1:8095/state | head` y
`curl -s -X POST http://127.0.0.1:8095/do -d '{"action":"ir_a","args":{"x":0,"y":64,"z":0}}' -H 'content-type: application/json'`
Expected: un snapshot real; y el bot moviéndose (ver `docker logs` o
repetir `/state` y ver la posición cambiar).

- [ ] **Step 5: Commit**

```bash
git add Hermes/plugins/jarvis_minecraft/bridge/server.js \
        Hermes/plugins/jarvis_minecraft/bridge/server.test.js \
        Hermes/plugins/jarvis_minecraft/bridge/index.js
git commit -m "feat(minecraft): the bridge speaks HTTP on loopback"
```

---

### Task 6: La unidad systemd

**Files:**
- Create: `systemd/jarvis-minecraft-bridge.service`

**Interfaces:**
- Produces: un único dueño del bot (diseño §9.5). Nada más lo lanza.

- [ ] **Step 1: Escribir la unidad**

```ini
[Unit]
Description=JARVIS Minecraft bridge (Mineflayer) — the body
# No PartOf=graphical-session: no tiene nada que ver con la tira y debe
# estar vivo aunque nadie haya iniciado sesión.
After=network.target docker.service

[Service]
Type=simple
ExecStart=/usr/bin/node %h/git/os1-jarvis/Hermes/plugins/jarvis_minecraft/bridge/index.js
WorkingDirectory=%h/git/os1-jarvis/Hermes/plugins/jarvis_minecraft/bridge
Environment=NODE_ENV=production
Restart=on-failure
RestartSec=5
TimeoutStopSec=30

[Install]
WantedBy=default.target
```

- [ ] **Step 2: Instalarla y arrancarla**

```bash
cp systemd/jarvis-minecraft-bridge.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now jarvis-minecraft-bridge.service
systemctl --user status jarvis-minecraft-bridge.service --no-pager
```

Expected: `active (running)`; `curl -s http://127.0.0.1:8095/state`
responde.

- [ ] **Step 3: Commit**

```bash
git add systemd/jarvis-minecraft-bridge.service
git commit -m "feat(minecraft): the bridge as its own user unit"
```

---

### Task 7: `mundo.py` — esquemas y frases (puro)

**Files:**
- Create: `Hermes/plugins/jarvis_minecraft/mundo.py`
- Create: `Hermes/plugins/jarvis_minecraft/tests/__init__.py`
- Create: `Hermes/plugins/jarvis_minecraft/tests/test_mundo.py`

**Interfaces:**
- `TOOLSET = "mundo"`.
- `ESTADO = "estado_del_mundo"`, `IR_A = "ir_a"` (fase 1).
- `DESCRIPCIONES: dict[str, str]` y `ESQUEMAS: dict[str, dict]` — el
  objeto **función** se compone en `__init__.py`.
- `make_handler(client, name) -> async (args) -> str`; nunca lanza;
  devuelve la frase `said` del bridge o un fallback en español.

- [ ] **Step 1: Escribir el test**

Comprobar: cada nombre tiene descripción y esquema; `ir_a` exige
`x`,`y`,`z` numéricos; el handler con un `client` falso devuelve su
`said`; con un `client` que lanza devuelve el fallback y no propaga.

- [ ] **Step 2: Ejecutar y ver fallar**

Run: `cd /home/nexus/git/os1-jarvis && PYTHONNOUSERSITE=1 widget/.venv/bin/python -m pytest Hermes/plugins/jarvis_minecraft/tests -q`
Expected: FAIL — no existe `mundo.py`.

- [ ] **Step 3: Implementar `mundo.py`.**

`estado_del_mundo` sin argumentos, devuelve `json.dumps(state,
ensure_ascii=False)` (no se dice en voz alta; el modelo lo parafrasea).
`ir_a` con `x/y/z` `number`. Frases de fallback en español.

- [ ] **Step 4: Ejecutar y ver pasar** — pytest.

- [ ] **Step 5: Commit**

```bash
git add Hermes/plugins/jarvis_minecraft/mundo.py Hermes/plugins/jarvis_minecraft/tests
git commit -m "feat(minecraft): the world tools, schemas and Spanish sentences"
```

---

### Task 8: `bridge_client.py` — HTTP y follower SSE

**Files:**
- Create: `Hermes/plugins/jarvis_minecraft/bridge_client.py`
- Create: `Hermes/plugins/jarvis_minecraft/tests/test_bridge_client.py`

**Interfaces:**
- `class BridgeClient:`
  - `state(timeout=5.0) -> dict` (lanza en fallo; el handler captura).
  - `do(action, args, timeout=35.0) -> dict` (timeout > deadline del
    bridge).
  - `up -> bool` — última llamada con éxito; lo usa `check_fn`.
- `follow_events(url, stop) -> Iterator[dict]` — generador que reconecta
  con back-off y **nunca propaga la excepción**, con `LOST` entre
  conexiones; calcado de `jarvis_code/client.py`.

- [ ] **Step 1: Escribir el test** con un `http.server` local en puerto `0`
  que sirva `/state`, `/do` y un `/events` que emita dos `data:` y cierre.
  Probar: `state`/`do` devuelven el JSON; `follow_events` rinde los dos
  eventos y luego `LOST` sin lanzar.

- [ ] **Step 2: Ejecutar y ver fallar** — pytest.

- [ ] **Step 3: Implementar `bridge_client.py`** con `urllib.request`
  (bloqueante, como `jarvis_code/client.py`; el hilo es nuestro).

- [ ] **Step 4: Ejecutar y ver pasar** — pytest.

- [ ] **Step 5: Commit**

```bash
git add Hermes/plugins/jarvis_minecraft/bridge_client.py \
        Hermes/plugins/jarvis_minecraft/tests/test_bridge_client.py
git commit -m "feat(minecraft): the plugin's HTTP client and event follower"
```

---

### Task 9: Cablear el plugin — registro, config y runtime

**Files:**
- Create: `Hermes/plugins/jarvis_minecraft/plugin.yaml`
- Create: `Hermes/plugins/jarvis_minecraft/__init__.py`
- Create: `Hermes/plugins/jarvis_minecraft/tests/test_plugin.py`
- Create: `Hermes/plugins/jarvis_minecraft/README.md`
- Modify: `Hermes/jarvis-config.yaml`
- Modify: `Hermes/setup-runtime.sh`

**Interfaces:**
- `register(ctx)`: lee la URL con `ctx.get_config("bridge", "http://127.0.0.1:8095")`,
  construye el `BridgeClient`, registra `estado_del_mundo` e `ir_a` con
  `check_fn=lambda: client.up`, arranca el hilo del follower.
- Follower: por cada evento crítico (`emergency`, `died`, `attacked`),
  `ctx.inject_message(prompt, role="user", session_key=JARVIS_SESSION_KEY)`
  con el patrón de `jarvis_vision/alert.py` (plantilla de prompt, no una
  frase; reintentos 1/3/5 s). Cooldown por evento.

- [ ] **Step 1: Escribir `plugin.yaml`**

`manifest_version: 2`, `api_version: 1`, `name: jarvis-minecraft`,
`kind: standalone`, con el bloque de modos de fallo silenciosos (diseño
§9) y `python_dependencies: ["loguru>=0.7,<1"]`.

- [ ] **Step 2: Escribir el test del plugin** con un `ctx` falso (como
  `jarvis_teacher/tests/test_plugin.py`): comprobar que registra dos tools
  en el toolset `mundo`, que `check_fn` es False con el bridge caído y
  True cuando `client.up`, y que un evento crítico llama a
  `inject_message` una sola vez por ventana de cooldown.

- [ ] **Step 3: Ejecutar y ver fallar** — pytest.

- [ ] **Step 4: Implementar `__init__.py`.** `register()` puro (nada de
  red); el hilo del follower y el sondeo de salud arrancan fuera del
  camino de registro, como `jarvis_vision`.

- [ ] **Step 5: Escribir `README.md`** — par de versiones, puertos,
  variables `JARVIS_MC_*`, cómo levantar el servidor y el bridge, y los
  siete fallos silenciosos.

- [ ] **Step 6: Modificar `jarvis-config.yaml`**

  - `plugins.enabled` += `jarvis-minecraft`
  - `plugins.entries.jarvis-minecraft`: `allow_tool_override: false`,
    `allow_gateway_injection: true` (con el comentario de por qué, como
    visión y código).
  - `platform_toolsets.jarvis` += `mundo`.

- [ ] **Step 7: Modificar `setup-runtime.sh`**

  - Añadir `jarvis_minecraft` a los dos bucles (symlink y `plugins
    enable`).
  - Añadir un paso `npm ci --prefix "$REPO_ROOT/Hermes/plugins/jarvis_minecraft/bridge"`
    (Hermes no instala deps de plugin; para Node no hay ni declaración).

- [ ] **Step 8: Ejecutar toda la suite y el lint**

Run: `PYTHONNOUSERSITE=1 widget/.venv/bin/python -m pytest Hermes/plugins/jarvis_minecraft/tests -q`
y `widget/.venv/bin/ruff check Hermes/plugins/jarvis_minecraft && widget/.venv/bin/ruff format --check Hermes/plugins/jarvis_minecraft`
Expected: PASS y limpio.

- [ ] **Step 9: Commit**

```bash
git add Hermes/plugins/jarvis_minecraft Hermes/jarvis-config.yaml Hermes/setup-runtime.sh
git commit -m "feat(minecraft): register the world toolset in the gateway"
```

---

### Task 10: Prueba de voz de extremo a extremo (necesita una persona)

**Files:**
- Modify: `PROGRESS.md` (la entrada del día)

- [ ] **Step 1: Aplicar la config y reiniciar el gateway**

```bash
Hermes/apply-config.sh
systemctl --user restart jarvis-hermes.service
journalctl --user -u jarvis-hermes.service -f   # buscar "jarvis-minecraft: registered"
```

- [ ] **Step 2: Comprobar que las tools están vivas**

Que `curl -s http://127.0.0.1:8095/state` responda, y en el journal
`jarvis-minecraft: registered 2 tools (toolset mundo)`.

- [ ] **Step 3: Hablarle a la tira**

1. *"Jarvis, ¿dónde estás?"* → llama `estado_del_mundo` y contesta en sus
   palabras, sin coordenadas crudas ni nombres de tools.
2. *"Ve a las coordenadas 0, 64, 0"* → llama `ir_a`, el bot se mueve, y
   él dice que ha llegado.
3. *"Ve a un sitio imposible"* (p. ej. dentro de piedra) → `ir_a`
   devuelve `sin_camino` y él lo dice sin inventar.

- [ ] **Step 4: Medir y anotar**

Tiempo de extremo a extremo de cada orden, y confirmar que no hay
regresión en la conversación normal (un turno sin Minecraft no debe
mencionarlo). Escribir el resultado en `PROGRESS.md`.

- [ ] **Step 5: Commit**

```bash
git add PROGRESS.md
git commit -m "docs(progress): the Minecraft body, phase 1"
```

---

## Criterio de cierre de la fase 1

- El servidor y el bridge arrancan solos (`docker compose` +
  `jarvis-minecraft-bridge.service`) tras un reinicio de la máquina.
- JARVIS responde por voz a "¿dónde estás?" y ejecuta "ve a X" sin narrar
  la maquinaria.
- Un bridge caído o un servidor caído dejan las tools fuera de la lista
  (`check_fn`) y una línea en el journal, sin romper la conversación.
- `pytest` del plugin y `npm test` del bridge en verde; ruff limpio.
- **VRAM sin cambios** (el diseño §8 lo exige y es el presupuesto que
  manda).

## Fuera de alcance (fases 2–6)

`minar`, `colocar`, `atacar`, modo emergencia, inyección de eventos
críticos; abrir el servidor a la LAN para que la gente entre a jugar y a
verla; el chat del juego con identidad por jugador; y un segundo juego
sobre el mismo contrato de cuerpo. Ver el diseño §10.
