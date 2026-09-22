import { test } from "node:test";
import assert from "node:assert/strict";
import { snapshot, nearestEntities } from "./state.js";

function fakeBot() {
  return {
    version: "1.21.8",
    health: 20,
    food: 18,
    entity: { position: { x: 142.5, y: 64.0, z: -210.3 } },
    time: { timeOfDay: 14000 },
    game: { dimension: "overworld" },
    inventory: { items: () => [{ name: "cobblestone", count: 64 }] },
    entities: {
      e_12: {
        id: 12,
        name: "zombie",
        type: "hostile",
        position: { x: 150, y: 64, z: -210 },
      },
      e_3: {
        id: 3,
        name: "cow",
        type: "hostile", // hostile type, but far away — dropped by radar
        position: { x: 260, y: 64, z: -210 },
      },
    },
  };
}

test("redondea la posición y cuenta el inventario", () => {
  const s = snapshot(fakeBot());
  // 142.5 rounds to 143 — half away from zero, as Math.round does, and
  // what the model sees is the rounded number.
  assert.deepEqual(s.bot.posicion, { x: 143, y: 64, z: -210 });
  assert.equal(s.inventario[0].bloque, "cobblestone");
  assert.equal(s.inventario[0].cantidad, 64);
  assert.equal(s.bot.es_de_dia, false);
});

test("solo las entidades dentro del radar, las más cercanas primero", () => {
  const near = nearestEntities(fakeBot(), 16, 12);
  assert.deepEqual(
    near.map((e) => e.id),
    ["e_12"],
  );
  assert.equal(near[0].hostil, true);
  // Distance is measured from the ROUNDED position the snapshot reports
  // (143), not from 142.5, so the number in the prompt and the number
  // the model can add up agree.
  assert.equal(near[0].distancia, 7);
});

test("un bot recién conectado no mete undefined: health/food caen a 20", () => {
  // Measured in the probe (2026-09-22): bot.health and bot.food are
  // undefined at `spawn` and arrive in the `health` event a moment
  // later. The snapshot must not leak that into the model's prompt.
  const bot = fakeBot();
  delete bot.health;
  delete bot.food;
  const s = snapshot(bot);
  assert.equal(s.bot.vida, 20);
  assert.equal(s.bot.comida, 20);
});

test("sin bot no hay snapshot, y no revienta", () => {
  const s = snapshot(null);
  assert.equal(s.bot, null);
  assert.deepEqual(s.inventario, []);
  assert.deepEqual(s.entorno.entidades, []);
});

test("la vida fraccionaria se redondea (un zombi pega y deja 10.833…)", () => {
  const bot = fakeBot();
  bot.health = 10.833333015441895;
  assert.equal(snapshot(bot).bot.vida, 11);
});

test("dice si está dentro del agua, no solo cerca", () => {
  const bot = fakeBot();
  bot.entity.isInWater = true;
  assert.equal(snapshot(bot).bot.en_agua, true);
  bot.entity.isInWater = false;
  assert.equal(snapshot(bot).bot.en_agua, false);
});

test("es_de_dia distingue el mediodía de la medianoche", () => {
  const bot = fakeBot();
  bot.time.timeOfDay = 6000;
  assert.equal(snapshot(bot).bot.es_de_dia, true);
  bot.time.timeOfDay = 18000;
  assert.equal(snapshot(bot).bot.es_de_dia, false);
});
