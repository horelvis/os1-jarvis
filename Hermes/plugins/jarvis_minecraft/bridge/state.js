// The world, as the model needs to see it: the design's §4 snapshot.
//
// Pure. It reads fields off a bot and returns a plain object — no
// network, no timers, no bot API calls that could throw on a connection
// that is not ready. That is what lets the whole thing be tested with a
// fake bot and no Minecraft server in the room.
//
// Two rules shape every number here:
//   * rounded, because 142.5 and 142 are the same place and the decimal
//     is a token;
//   * bounded, because a busy server must not dump a hundred entities
//     into a 64K window.

import { MAX_ENTITIES, RADAR } from "./config.js";

// A Minecraft day runs 0..23999. These are the eyebrows of dawn and
// dusk; the exact minute does not matter, only that the model can tell
// "it is about to get dark" from "it is noon".
const DAWN = 23000;
const DUSK = 13000;

function round(value) {
  return Number.isFinite(value) ? Math.round(value) : null;
}

function positionOf(entity) {
  const p = entity?.position;
  if (!p) return { x: null, y: null, z: null };
  return { x: round(p.x), y: round(p.y), z: round(p.z) };
}

function isDay(timeOfDay) {
  if (!Number.isFinite(timeOfDay)) return null;
  return timeOfDay < DUSK || timeOfDay > DAWN;
}

function distanceTo(botPos, entityPos) {
  const dx = (entityPos.x ?? 0) - (botPos.x ?? 0);
  const dy = (entityPos.y ?? 0) - (botPos.y ?? 0);
  const dz = (entityPos.z ?? 0) - (botPos.z ?? 0);
  return Math.sqrt(dx * dx + dy * dy + dz * dz);
}

// The hostile flag. mineflayer sets `type: "hostile"` for mobs that
// attack; the radar cares about those first, but a cow at eight blocks
// is still worth mentioning, so this never filters — it only labels.
function isHostile(entity) {
  return entity?.type === "hostile";
}

export function nearestEntities(bot, radar = RADAR, maxEntities = MAX_ENTITIES) {
  if (!bot?.entities || !bot?.entity?.position) return [];

  const origin = positionOf(bot.entity);
  const nearby = [];
  for (const entity of Object.values(bot.entities)) {
    // The bot itself sits in `bot.entities`, id and all. It is not a
    // thing in the surroundings.
    if (entity === bot.entity) continue;
    const position = positionOf(entity);
    const distance = distanceTo(origin, position);
    if (distance > radar) continue;
    nearby.push({
      tipo: entity.name || entity.type || "desconocido",
      id: `e_${entity.id}`,
      distancia: Math.round(distance),
      hostil: isHostile(entity),
    });
  }
  nearby.sort((a, b) => a.distancia - b.distancia);
  return nearby.slice(0, maxEntities);
}

function blockUnderfoot(bot) {
  // Best-effort and deliberately shallow: a missing label is fine while
  // the alternative is losing the whole snapshot to it.
  //
  // `bot.blockAt` wants a real Vec3, not a `{x, y, z}` literal — a plain
  // object returns null, which reads exactly like an unloaded chunk. It
  // is what made a working world look empty while diagnosing this on
  // 2026-09-22.
  try {
    const below = bot.entity.position.offset(0, -1, 0);
    const block = bot.blockAt(below);
    return block?.name || null;
  } catch {
    return null;
  }
}

export function snapshot(bot, { radar = RADAR, maxEntities = MAX_ENTITIES } = {}) {
  if (!bot?.entity?.position) {
    return {
      bot: null,
      inventario: [],
      entorno: { entidades: [], bajo_los_pies: null },
    };
  }

  const entities = nearestEntities(bot, radar, maxEntities);
  const timeOfDay = bot.time?.timeOfDay;

  return {
    bot: {
      // `?? 20` and not `bot.health`: at spawn these are undefined and
      // the `health` event has not fired yet (probe, 2026-09-22).
      //
      // Rounded: Minecraft health is fractional (fall damage, poison),
      // and `10.833333015441895` in the prompt is both ugly and a token
      // sink for a distinction the model never uses.
      vida: round(bot.health) ?? 20,
      comida: round(bot.food) ?? 20,
      posicion: positionOf(bot.entity),
      dormido: bot.isSleeping ?? false,
      hora: Number.isFinite(timeOfDay) ? timeOfDay : null,
      es_de_dia: isDay(timeOfDay),
      dimension: bot.game?.dimension ?? null,
      // Whether the bot is IN water or lava, not just standing near it.
      // Without this the model cannot verify a request like "entra al
      // agua": `ir_a` only says it arrived at coordinates, and a model
      // that cannot check the result invents one — measured 2026-09-22,
      // when it claimed to be waist-deep while the snapshot said
      // `grass_block`.
      en_agua: bot.entity?.isInWater ?? false,
      en_lava: bot.entity?.isInLava ?? false,
    },
    inventario: inventory(bot),
    entorno: {
      entidades: entities,
      bajo_los_pies: blockUnderfoot(bot),
      miran: entities.filter((e) => e.hostil).map((e) => e.tipo),
    },
  };
}

function inventory(bot) {
  try {
    return bot.inventory.items().map((item) => ({
      bloque: item.name,
      cantidad: item.count,
    }));
  } catch {
    return [];
  }
}
