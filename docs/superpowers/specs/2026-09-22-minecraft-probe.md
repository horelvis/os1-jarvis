# Minecraft probe — el par de versiones y lo que midió

> **Fecha:** 2026-09-22. **Estado:** cerrado. Sonda desechable; esto es el
> entregable. El plan es `plans/2026-09-22-minecraft.md` (Task 2).

## El par elegido

| | versión |
|---|---|
| Servidor (Paper, Docker) | **1.21.8** |
| `mineflayer` | **4.39.0** |
| `mineflayer-pathfinder` | **2.4.5** |
| `mineflayer-collectblock` | **1.6.0** |

Todas pinneadas con `--save-exact` en
`Hermes/plugins/jarvis_minecraft/bridge/package.json`. El servidor lleva
`VERSION: "1.21.8"` en `server/docker-compose.yml`.

## Lo que se probó, y qué falló

**1.21.1 NO sirve.** Con el servidor en 1.21.1 (el candidato del plan),
el bot llega a `spawn` — posición y hora reales — pero el decoder de
componentes de item revienta:

```
PartialReadError: Read error for undefined : Missing characters in string,
found size is 108271 expected size was 114153
  at Object.ArmorTrimMaterial (…/protodef/…)
```

Es un desajuste entre los datos de protocolo de `minecraft-data` y los
paquetes que Paper 1.21.1 envía: el packet de slot/componente se corta a
medias. La conexión "funciona", así que el síntoma es engañoso — una
parte del mundo queda mal decodificada en silencio.

Mover el cliente a 1.21.8 contra un servidor 1.21.1 **no vale**: el
`versionChecking` de `minecraft-protocol` corta la conexión con

```
Error: This server is version 1.21.1, you are using version 1.21.8,
please specify the correct version in the options.
```

Así que lo que se movió fue el **servidor**, a 1.21.8. Ahí el paquete
decodifica limpio y no hay `PartialReadError`.

Candidata descartada de partida: **1.21.11**, la más nueva que
`minecraft-data` lista, por ser demasiado reciente para el resto del
ecosistema.

## Salida real de la sonda (servidor 1.21.8)

```json
{
  "version": "1.21.8",
  "position": { "x": 41.5, "y": 66, "z": -66.5 },
  "health": 20,
  "food": 20,
  "gameMode": "survival",
  "time": 19699,
  "dimension": "overworld",
  "inventory": [],
  "entities": 1
}
```

`entities: 1` es el propio bot: un mundo recién generado sin nada más
cargado. El inventario está vacío porque el bot acaba de aparecer.

## La trampa que costó una vuelta

**`bot.health` y `bot.food` son `undefined` en el momento del evento
`spawn`.** Llegan un instante después, en el evento `health`. La primera
sonda los leyó en `spawn` y los imprimió como ausentes del JSON — que
parece un fallo de decodificación y no lo es.

Medido en esta misma sesión:

```
spawn:        health: undefined food: undefined   gameMode: survival
health event: health: 20          food: 20
```

**Consecuencia para `state.js` (Task 3):** el snapshot no puede confiar en
que `bot.health` exista. Se lee con `?? 20` (o `null` explícito) para que
un bot recién conectado no meta un `undefined` en el prompt del modelo.

## Nota de seguridad, ya en el compose (fases 0–1)

El servidor escucha en `*:25565` **dentro del contenedor**, pero Docker
solo publica `${MC_BIND_IP:-127.0.0.1}:25565`, así que desde fuera de la
caja solo se llega si `MC_BIND_IP` se pone a la IP de la LAN en `.env`. El
log del servidor avisa en cada arranque de que está en modo offline:

```
**** SERVER IS RUNNING IN OFFLINE/INSECURE MODE!
The server will make no attempt to authenticate usernames.
```

Es lo elegido (fase 0–1, loopback, un solo bot local). Al abrirlo a la
LAN (fase 4) va con whitelist, y el `online-mode` se revisa entonces —
ver el diseño §8 y §11.
