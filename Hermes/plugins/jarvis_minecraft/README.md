# jarvis-minecraft

Le da a JARVIS un cuerpo en Minecraft. Un bot (Mineflayer) que ve el
mundo y se mueve por él, gobernado por el toolset `mundo`. El bot no
piensa: no llama a ningún modelo, no guarda conversación, no decide nada.
Es cuerpo y traductor.

Diseño completo: `docs/superpowers/specs/2026-09-22-minecraft-design.md`.
Plan de las fases 0–1: `docs/superpowers/plans/2026-09-22-minecraft.md`.
La sonda que fijó las versiones: `docs/superpowers/specs/2026-09-22-minecraft-probe.md`.

## Qué hay, y dónde

```
server/docker-compose.yml   el servidor Paper, en Docker (127.0.0.1:25565)
bridge/                     el cuerpo, en Node
  index.js                  conecta el bot, reconecta, monta el HTTP
  state.js                  el snapshot del mundo (puro)
  actions.js                cola serial, deadline, ir_a / decir
  server.js                 HTTP loopback :8095  (/state, /do, /events)
  config.js                 JARVIS_MC_*, con defaults que funcionan
mundo.py                    las tools que ve el modelo (esquemas, frases)
bridge_client.py            el lado Python: HTTP + seguidor de eventos
__init__.py                 register(): declara tools, inyecta eventos
```

## El par de versiones, y por qué importa

| | versión |
|---|---|
| Servidor (Paper) | **1.21.8** |
| mineflayer | **4.39.0** |
| mineflayer-pathfinder | **2.4.5** |
| mineflayer-collectblock | **1.6.0** |

Pinneadas con `--save-exact`. **No subas una sola.** Con el servidor en
1.21.1 y el mismo mineflayer, la conexión llega a `spawn` y luego el
decoder de componentes de item revienta (`PartialReadError` en
`ArmorTrimMaterial`): medio mundo mal decodificado y un síntoma que
parece otra cosa. La historia está en el doc de la sonda.

## Arrancar

```bash
# 1. El servidor (una vez; queda con restart: unless-stopped)
docker compose -f Hermes/plugins/jarvis_minecraft/server/docker-compose.yml up -d
docker logs -f jarvis-minecraft     # hasta "Done (…)! For help, type help"

# 2. El bridge
cp systemd/jarvis-minecraft-bridge.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now jarvis-minecraft-bridge.service
journalctl --user -u jarvis-minecraft-bridge.service -f   # "the bot is in the world"

# 3. Comprobar
curl -s http://127.0.0.1:8095/state | head -c 200
```

Node viene de **nvm** en esta caja, no de `/usr/bin/node`. La unidad usa
la ruta resuelta (`readlink -f "$(which node)"`) y **cambia cuando cambie
la versión de nvm**: una unidad apuntando a una versión que ya no está
falla con «No such file or directory» mientras todo lo demás parece sano.

## Mirar y jugar

El servidor escucha en loopback por defecto. Para que la gente de casa
entre a jugar y a verla jugar, `MC_BIND_IP` en el `.env` de la raíz
(git-ignored):

```
MC_BIND_IP=192.168.0.20
```

**Nunca `0.0.0.0`**, y en cuanto se abre, whitelist obligatoria (está
comentada en el compose). Verla no necesita nada nuevo: se entra al mundo
desde un cliente normal y se la mira en tercera persona o como
espectador. `prismarine-viewer` no se usa: sería un segundo navegador
(CLAUDE.md §3). El chat del juego — que él oiga y hable ahí — es la fase
5 y necesitará una plataforma de Hermes, no una tool (diseño §7).

## Variables del bridge (`bridge/config.js`)

Todas con default que funciona en una caja sin nada configurado:
`JARVIS_MC_HOST`, `JARVIS_MC_PORT`, `JARVIS_MC_VERSION`,
`JARVIS_MC_USERNAME`, `JARVIS_MC_BRIDGE_HOST/PORT`, `JARVIS_MC_RADAR`,
`JARVIS_MC_MAX_ENTITIES`, `JARVIS_MC_ACTION_TIMEOUT`,
`JARVIS_MC_EVENT_COOLDOWN`, `JARVIS_MC_RECONNECT_MIN/MAX`.

## Config de Hermes

- `plugins.enabled` debe incluir `jarvis-minecraft` o no carga. La
  entrada `entries.jarvis-minecraft.enabled` **no** es un gate de carga.
- `allow_gateway_injection: true` es lo que deja que un evento crítico
  (fase 3) llegue a la conversación. Sin él, `inject_message()` devuelve
  `False` y el cuerpo se muere en silencio.
- `platform_toolsets.jarvis` debe incluir `mundo`, o el toolset existe
  pero la tira no lo ve.
- La URL del bridge se lee con `ctx.get_config("bridge", …)`
  (`plugins.entries.jarvis-minecraft.settings.bridge`). El default es
  `http://127.0.0.1:8095`.

## Tests

```bash
# Bridge (Node)
cd Hermes/plugins/jarvis_minecraft/bridge && npm test

# Plugin (Python)
cd /home/nexus/git/os1-jarvis && PYTHONNOUSERSITE=1 widget/.venv/bin/python -m pytest \
  Hermes/plugins/jarvis_minecraft/tests -q
```
