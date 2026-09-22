// One action at a time, each with a deadline.
//
// Two properties, and both are the point:
//
//   * SERIAL. Mineflayer and the pathfinder cannot do two things at once,
//     and order matters — walk there, then place a block. Two actions in
//     flight produce a body that twitches between goals.
//
//   * DEADLINED. A hanging action is worse than a failing one: the strip
//     goes mute until the adapter's 90 s watchdog and the user hears
//     nothing. Every action runs under a timeout and a timeout is an
//     ordinary answer, not an exception.
//
// Nothing here rejects. `run` always resolves to {ok, said, error?,
// state?} — the plugin turns that into a sentence, and a tool that
// throws would cost the whole turn instead of one action.

import { ACTION_TIMEOUT_MS } from "./config.js";

// What he says when an action ends. Kept here so the handler in the
// plugin and the raw HTTP answer agree, and so a test can assert on it
// without importing the plugin.
export const SAID = {
  llegado: "He llegado.",
  sin_camino: "No encuentro por dónde ir.",
  tardanza: "Me he quedado a medias.",
  fallo: "No he podido hacerlo.",
};

export function deadline(promise, ms, reason) {
  let timer;
  const timeout = new Promise((_resolve, reject) => {
    timer = setTimeout(() => reject(new Error(reason)), ms);
    // Do not hold the Node process open for a pending deadline.
    if (typeof timer.unref === "function") timer.unref();
  });
  return Promise.race([promise, timeout]).finally(() => clearTimeout(timer));
}

// The actions in phase 1. `ir_a` is the only body action; `decir` is
// here already because §3's contract has it and a stub that writes to
// chat is trivial next to the pathfinder.
//
// `goals` is a PARAMETER, not `bot.pathfinder.goals`. mineflayer-pathfinder
// exports `goals` from the package; it is not a property of the bot's
// pathfinder, and reaching for it there throws — which the queue then
// reports as "no encuentro por dónde ir", a wrong sentence for a coding
// mistake. `index.js` injects the real one; tests inject a fake.
export function ir_a(bot, { x, y, z }, goals) {
  if (!bot?.pathfinder) throw new Error("no_pathfinder");
  if (!goals) throw new Error("no_goals");
  const goal = new goals.GoalBlock(Math.floor(x), Math.floor(y), Math.floor(z));
  return bot.pathfinder.goto(goal);
}

export function decir(bot, { texto }) {
  if (!bot?.chat) throw new Error("no_chat");
  bot.chat(String(texto));
}

export function makeHandlers(bot, goals) {
  return {
    ir_a: (args) => ir_a(bot, args, goals),
    decir: (args) => decir(bot, args),
  };
}

// Which failure becomes which sentence. A path the pathfinder cannot
// find is not an error, it is a fact about the world, and it gets its own
// words so the model can tell "impossible place" from "the body broke".
//
// The internal-error names are checked FIRST: `no_goals` contains "Goal"
// and would otherwise be read as a pathfinding failure — a coding mistake
// wearing the sentence for an impossible place.
function saidFor(error) {
  const message = String(error?.message ?? error);
  if (message === "timeout") return { error: "tardanza", said: SAID.tardanza };
  if (/^no_(pathfinder|goals|chat)$/.test(message)) {
    return { error: "fallo", said: SAID.fallo };
  }
  if (/No path|no_path|unreachable|Goal/i.test(message)) {
    return { error: "sin_camino", said: SAID.sin_camino };
  }
  return { error: "fallo", said: SAID.fallo };
}

export class ActionQueue {
  constructor({ handlers, timeoutMs = ACTION_TIMEOUT_MS, snapshot = null } = {}) {
    this.handlers = handlers || {};
    this.timeoutMs = timeoutMs;
    this.snapshot = snapshot; // optional: attaches the new state to an ok
    // The chain of promises that enforces seriality. Each action appends
    // to the tail; the next one waits for this one to settle, success or
    // failure.
    this.tail = Promise.resolve();
  }

  run(name, args = {}) {
    const result = this.tail.then(() => this.#execute(name, args));
    // Keep the chain alive even if #execute were ever to throw — it does
    // not, but a broken chain would silently stop every later action.
    this.tail = result.then(
      () => undefined,
      () => undefined,
    );
    return result;
  }

  async #execute(name, args) {
    const handler = this.handlers[name];
    if (!handler) return { ok: false, error: "desconocida", said: SAID.fallo };

    try {
      await deadline(
        Promise.resolve().then(() => handler(args)),
        this.timeoutMs,
        "timeout",
      );
    } catch (error) {
      return { ok: false, ...saidFor(error) };
    }

    const answer = { ok: true, said: SAID.llegado };
    if (this.snapshot) {
      try {
        answer.state = this.snapshot();
      } catch {
        // A snapshot is a convenience on the answer, never a reason to
        // turn a success into a failure.
      }
    }
    return answer;
  }
}
