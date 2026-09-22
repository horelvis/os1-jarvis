// The body. Connect to Minecraft, keep a queue of actions, and answer the
// plugin over loopback.
//
// It does NOT think. No model is called from here, no conversation is
// kept, and nothing here decides what the bot should do. It connects, it
// reports, it obeys, and — in a later phase — it protects itself when
// health drops. That is the whole job.
//
// One process, one bot, owned by systemd (design §9.5). A second bridge
// would make the server kick the first and both would look sane.

import mineflayer from "mineflayer";
import pathfinderPkg from "mineflayer-pathfinder";
import collectblockPkg from "mineflayer-collectblock";
import { ActionQueue, makeHandlers } from "./actions.js";
import {
  BRIDGE_HOST,
  BRIDGE_PORT,
  HOST,
  PORT,
  RECONNECT_MAX_MS,
  RECONNECT_MIN_MS,
  USERNAME,
  VERSION,
} from "./config.js";
import { createBridgeServer } from "./server.js";
import { snapshot } from "./state.js";

// These two packages are CommonJS with `__esModule`, so a default import
// arrives as `undefined` and the loadPlugin function hides behind a named
// export: `pathfinder` (a function named `inject`) on
// mineflayer-pathfinder, and `plugin` on mineflayer-collectblock. Passing
// the wrong thing is `AssertionError: plugin needs to be a function` at
// startup, before the bot ever connects.
const { Movements, goals, pathfinder } = pathfinderPkg;
const { plugin: collectblock } = collectblockPkg;

let bot = null;
let queue = null;
let server = null;
let backoff = RECONNECT_MIN_MS;
let everConnected = false;

function startServer() {
  server = createBridgeServer({
    getState: () => (bot ? snapshot(bot) : snapshot(null)),
    doAction: (action, args) => {
      if (!queue) {
        return Promise.resolve({
          ok: false,
          error: "sin_cuerpo",
          said: "Ahora mismo no estoy en el mundo.",
        });
      }
      return queue.run(action, args);
    },
  });
  server.listen(BRIDGE_PORT, BRIDGE_HOST, () => {
    console.log(
      `jarvis-minecraft-bridge: listening on http://${BRIDGE_HOST}:${BRIDGE_PORT}`,
    );
  });
}

function connect() {
  bot = mineflayer.createBot({
    host: HOST,
    port: PORT,
    username: USERNAME,
    auth: "offline",
    version: VERSION,
  });

  bot.loadPlugin(pathfinder);
  bot.loadPlugin(collectblock);

  bot.once("spawn", () => {
    // Movements and the handler table are built once per connection: a
    // reconnect makes a new bot and the old pathfinder is gone with it.
    bot.pathfinder.setMovements(new Movements(bot));
    queue = new ActionQueue({
      handlers: makeHandlers(bot, goals),
      snapshot: () => snapshot(bot),
    });
    if (everConnected) {
      console.log("jarvis-minecraft-bridge: the bot is back");
    } else {
      console.log("jarvis-minecraft-bridge: the bot is in the world");
      everConnected = true;
    }
    backoff = RECONNECT_MIN_MS;
  });

  bot.on("kicked", (reason) => {
    console.log(`jarvis-minecraft-bridge: kicked — ${JSON.stringify(reason)}`);
  });

  bot.on("error", (error) => {
    console.log(`jarvis-minecraft-bridge: error — ${error?.message ?? error}`);
  });

  bot.on("end", (reason) => {
    queue = null;
    bot = null;
    // The server may simply not be up yet. One line the first time, then
    // debug-level silence until it comes back — a warning every second at
    // three in the morning is the failure this is written against
    // (design §9.1).
    console.log(`jarvis-minecraft-bridge: disconnected (${reason || "end"})`);
    setTimeout(connect, backoff);
    backoff = Math.min(backoff * 2, RECONNECT_MAX_MS);
  });
}

startServer();
connect();
