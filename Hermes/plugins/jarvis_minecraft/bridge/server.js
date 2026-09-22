// The three endpoints the plugin talks to, on loopback. Nothing else.
//
//   GET  /state   the snapshot (design §4)
//   POST /do      run one action, answer when it is DONE (design §3)
//   GET  /events  server-sent events: what the world does unprompted
//
// No authentication: it binds 127.0.0.1 and the only client is the
// gateway on the same box. No session state between calls either — every
// request carries everything it needs.
//
// This module owns no bot. It is handed `getState`, `doAction`,
// `subscribe` and `events`, which is what lets it be tested with fakes
// and no Minecraft server in the room.

import { createServer as createHttpServer } from "node:http";

const MAX_BODY = 64 * 1024; // an action is coordinates, not a file

// How often an idle /events stream says something. Without it the
// plugin's urllib read times out after 60 s and the follower reports
// "se ha cortado el puente" every minute on an idle world — measured
// 2026-09-22. A comment line is valid SSE and ignored by any reader.
const KEEPALIVE_MS = 15_000;

function sendJson(res, status, payload) {
  const body = JSON.stringify(payload);
  res.writeHead(status, {
    "content-type": "application/json; charset=utf-8",
    "content-length": Buffer.byteLength(body),
  });
  res.end(body);
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    let size = 0;
    const chunks = [];
    req.on("data", (chunk) => {
      size += chunk.length;
      if (size > MAX_BODY) {
        reject(new Error("body too large"));
        req.destroy();
        return;
      }
      chunks.push(chunk);
    });
    req.on("end", () => resolve(Buffer.concat(chunks).toString("utf8")));
    req.on("error", reject);
  });
}

export function createBridgeServer({
  getState,
  doAction,
  subscribe = () => () => {},
  events = null,
  keepAliveMs = KEEPALIVE_MS,
} = {}) {
  const clients = new Set();
  const pings = new Map();

  // One fan-out point. `events` is an optional emitter-like ({ on }) the
  // bot side owns; subscribe() is the seam tests use instead.
  if (events?.on) {
    events.on("event", (payload) => broadcast(payload));
  }

  function broadcast(payload) {
    const line = `data: ${JSON.stringify(payload)}\n\n`;
    for (const res of clients) {
      try {
        res.write(line);
      } catch {
        drop(res);
      }
    }
  }

  function drop(res) {
    clients.delete(res);
    const ping = pings.get(res);
    if (ping) {
      clearInterval(ping);
      pings.delete(res);
    }
  }

  const server = createHttpServer(async (req, res) => {
    const url = new URL(req.url, "http://127.0.0.1");
    try {
      if (req.method === "GET" && url.pathname === "/state") {
        sendJson(res, 200, getState());
        return;
      }

      if (req.method === "POST" && url.pathname === "/do") {
        let payload;
        try {
          payload = JSON.parse((await readBody(req)) || "{}");
        } catch {
          sendJson(res, 400, { ok: false, error: "json", said: "No te he entendido." });
          return;
        }
        if (!payload?.action) {
          sendJson(res, 400, { ok: false, error: "accion", said: "No te he entendido." });
          return;
        }
        const answer = await doAction(payload.action, payload.args || {});
        sendJson(res, 200, answer);
        return;
      }

      if (req.method === "GET" && url.pathname === "/events") {
        res.writeHead(200, {
          "content-type": "text/event-stream",
          "cache-control": "no-cache",
          connection: "keep-alive",
        });
        // A comment line is a valid, ignored keepalive for EventSource
        // and for the plugin's own reader. It also tells the reader the
        // stream is live before the first real event.
        res.write(": ok\n\n");
        clients.add(res);
        if (keepAliveMs > 0) {
          const ping = setInterval(() => {
            try {
              res.write(": ping\n\n");
            } catch {
              drop(res);
            }
          }, keepAliveMs);
          if (typeof ping.unref === "function") ping.unref();
          pings.set(res, ping);
        }
        const unsubscribe = subscribe((payload) => broadcast(payload));
        req.on("close", () => {
          drop(res);
          try {
            unsubscribe();
          } catch {
            // A cleanup that raises must not take the server with it.
          }
        });
        return;
      }

      sendJson(res, 404, { ok: false, error: "no_route" });
    } catch (error) {
      // Last line of defence: an unhandled throw here would kill the
      // request with no body and look like the bridge is down.
      sendJson(res, 500, { ok: false, error: "interno", said: String(error?.message ?? error) });
    }
  });

  // Exposed so a test can publish without a bot.
  server.broadcast = broadcast;
  return server;
}
