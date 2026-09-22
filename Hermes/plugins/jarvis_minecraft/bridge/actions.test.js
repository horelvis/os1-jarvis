import { test } from "node:test";
import assert from "node:assert/strict";
import {
  ActionQueue,
  buscar_bloque,
  deadline,
  ir_a,
  ir_al_bloque,
  SAID,
} from "./actions.js";

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

test("las acciones no se solapan y guardan el orden", async () => {
  const order = [];
  const queue = new ActionQueue({
    handlers: {
      lenta: async () => {
        order.push("inicio-lenta");
        await sleep(40);
        order.push("fin-lenta");
      },
      rapida: async () => {
        order.push("rapida");
      },
    },
    timeoutMs: 1000,
  });

  const first = queue.run("lenta");
  const second = queue.run("rapida");
  await Promise.all([first, second]);

  assert.deepEqual(order, ["inicio-lenta", "fin-lenta", "rapida"]);
});

test("una acción que tarda más que el deadline devuelve tardanza, no cuelga", async () => {
  const queue = new ActionQueue({
    handlers: { lenta: () => sleep(200) },
    timeoutMs: 30,
  });
  const answer = await queue.run("lenta");
  assert.equal(answer.ok, false);
  assert.equal(answer.error, "tardanza");
  assert.equal(answer.said, SAID.tardanza);
});

test("un handler que lanza no rompe la cola", async () => {
  const queue = new ActionQueue({
    handlers: {
      rompe: () => {
        throw new Error("boom");
      },
      sigue: async () => "bien",
    },
    timeoutMs: 1000,
  });
  const broken = await queue.run("rompe");
  assert.equal(broken.ok, false);
  assert.equal(broken.error, "fallo");

  const ok = await queue.run("sigue");
  assert.equal(ok.ok, true);
  assert.equal(ok.said, SAID.llegado);
});

test("un path imposible se cuenta como sin_camino", async () => {
  const queue = new ActionQueue({
    handlers: {
      ir_a: () => {
        throw new Error("No path to the goal!");
      },
    },
    timeoutMs: 1000,
  });
  const answer = await queue.run("ir_a", { x: 0, y: 0, z: 0 });
  assert.equal(answer.error, "sin_camino");
  assert.equal(answer.said, SAID.sin_camino);
});

test("una acción desconocida es un fallo, no un lanzamiento", async () => {
  const queue = new ActionQueue({ handlers: {}, timeoutMs: 100 });
  const answer = await queue.run("volar");
  assert.equal(answer.ok, false);
  assert.equal(answer.error, "desconocida");
});

test("cada acción tiene su propia frase de éxito", async () => {
  const queue = new ActionQueue({
    handlers: { ir_a: async () => {}, decir: async () => {} },
    timeoutMs: 100,
  });
  assert.equal((await queue.run("ir_a")).said, SAID.llegado);
  assert.equal((await queue.run("decir")).said, SAID.dicho);
});

test("el snapshot se adjunta al éxito y nunca lo estropea", async () => {
  const good = new ActionQueue({
    handlers: { noop: async () => {} },
    timeoutMs: 100,
    snapshot: () => ({ bot: { vida: 20 } }),
  });
  const withState = await good.run("noop");
  assert.deepEqual(withState.state, { bot: { vida: 20 } });

  const bad = new ActionQueue({
    handlers: { noop: async () => {} },
    timeoutMs: 100,
    snapshot: () => {
      throw new Error("no bot");
    },
  });
  const withoutState = await bad.run("noop");
  assert.equal(withoutState.ok, true);
  assert.equal(withoutState.state, undefined);
});

test("deadline resuelve si la promesa llega a tiempo", async () => {
  const value = await deadline(Promise.resolve("ya"), 1000, "timeout");
  assert.equal(value, "ya");
});

test("ir_a llama al pathfinder con el goal y los enteros de la posición", async () => {
  const calls = [];
  const bot = {
    pathfinder: {
      goto: async (goal) => {
        calls.push(goal);
      },
    },
  };
  const goals = {
    GoalBlock: class {
      constructor(x, y, z) {
        this.x = x;
        this.y = y;
        this.z = z;
      }
    },
  };
  await ir_a(bot, { x: 142.9, y: 64.2, z: -210.7 }, goals);
  assert.equal(calls.length, 1);
  // Floor, not round: a block coordinate is the block you are inside,
  // and -210.7 is inside -211.
  assert.deepEqual(
    { x: calls[0].x, y: calls[0].y, z: calls[0].z },
    { x: 142, y: 64, z: -211 },
  );
});

test("sin goals inyectados ir_a falla claro, no con sin_camino", async () => {
  const bot = { pathfinder: { goto: async () => {} } };
  assert.throws(() => ir_a(bot, { x: 1, y: 2, z: 3 }), /no_goals/);

  const queue = new ActionQueue({
    handlers: { ir_a: (args) => ir_a(bot, args) },
    timeoutMs: 200,
  });
  const answer = await queue.run("ir_a", { x: 1, y: 2, z: 3 });
  assert.equal(answer.error, "fallo");
});

test("buscar_bloque devuelve las coordenadas redondeadas del agua más cercana", async () => {
  const bot = {
    registry: { blocksByName: { water: { id: 34 } } },
    findBlock: ({ matching }) => {
      assert.equal(matching, 34);
      return { position: { x: 12.6, y: 62.1, z: -8.4 } };
    },
  };
  assert.deepEqual(buscar_bloque(bot, { bloque: "water" }), {
    x: 13,
    y: 62,
    z: -8,
  });
});

test("buscar_bloque no encuentra nada y no revienta", async () => {
  const bot = {
    registry: { blocksByName: { water: { id: 34 } } },
    findBlock: () => null,
  };
  assert.equal(buscar_bloque(bot, { bloque: "water" }), null);
  assert.throws(() => buscar_bloque(bot, { bloque: "chorizo" }), /bloque_desconocido/);
});

test("ir_al_bloque usa GoalNear, no GoalBlock: el agua es un fluido", async () => {
  const calls = [];
  const bot = {
    registry: { blocksByName: { water: { id: 34 } } },
    findBlock: () => ({ position: { x: 5, y: 63, z: 5 } }),
    pathfinder: {
      goto: async (goal) => {
        calls.push(goal);
      },
    },
  };
  const goals = {
    GoalNear: class {
      constructor(x, y, z, range) {
        Object.assign(this, { x, y, z, range });
      }
    },
  };
  await ir_al_bloque(bot, { bloque: "water" }, goals);
  assert.equal(calls.length, 1);
  assert.deepEqual(
    { x: calls[0].x, y: calls[0].y, z: calls[0].z, range: calls[0].range },
    { x: 5, y: 63, z: 5, range: 1 },
  );
});

test("no_encontrado tiene su propia frase, no es un fallo", async () => {
  const bot = {
    registry: { blocksByName: { water: { id: 34 } } },
    findBlock: () => null,
    pathfinder: { goto: async () => {} },
  };
  const goals = { GoalNear: class {} };
  const queue = new ActionQueue({
    handlers: { ir_al_bloque: (args) => ir_al_bloque(bot, args, goals) },
    timeoutMs: 200,
  });
  const answer = await queue.run("ir_al_bloque", { bloque: "water" });
  assert.equal(answer.ok, false);
  assert.equal(answer.error, "no_encontrado");
  assert.equal(answer.said, SAID.no_encontrado);
});

test("los datos del handler llegan al modelo en answer.data", async () => {
  const queue = new ActionQueue({
    handlers: { buscar_bloque: () => ({ x: 1, y: 2, z: 3 }) },
    timeoutMs: 200,
  });
  const answer = await queue.run("buscar_bloque", { bloque: "water" });
  assert.deepEqual(answer.data, { x: 1, y: 2, z: 3 });
});
