import { test } from "node:test";
import assert from "node:assert/strict";
import { createBridgeServer } from "./server.js";

function listen(server) {
  return new Promise((resolve) => {
    server.listen(0, "127.0.0.1", () => resolve(server.address().port));
  });
}

test("GET /state devuelve el snapshot", async () => {
  const server = createBridgeServer({
    getState: () => ({ bot: { vida: 20 }, inventario: [] }),
    doAction: async () => ({ ok: true }),
  });
  const port = await listen(server);
  try {
    const res = await fetch(`http://127.0.0.1:${port}/state`);
    assert.equal(res.status, 200);
    assert.equal(res.headers.get("content-type"), "application/json; charset=utf-8");
    const body = await res.json();
    assert.equal(body.bot.vida, 20);
  } finally {
    server.close();
  }
});

test("POST /do ejecuta y responde cuando la acción termina", async () => {
  const seen = [];
  const server = createBridgeServer({
    getState: () => ({}),
    doAction: async (action, args) => {
      seen.push([action, args]);
      return { ok: true, said: "He llegado." };
    },
  });
  const port = await listen(server);
  try {
    const res = await fetch(`http://127.0.0.1:${port}/do`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ action: "ir_a", args: { x: 1, y: 2, z: 3 } }),
    });
    assert.equal(res.status, 200);
    const body = await res.json();
    assert.equal(body.said, "He llegado.");
    assert.deepEqual(seen, [["ir_a", { x: 1, y: 2, z: 3 }]]);
  } finally {
    server.close();
  }
});

test("POST /do sin action es 400, no un lanzamiento", async () => {
  const server = createBridgeServer({
    getState: () => ({}),
    doAction: async () => ({ ok: true }),
  });
  const port = await listen(server);
  try {
    const res = await fetch(`http://127.0.0.1:${port}/do`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ args: { x: 1 } }),
    });
    assert.equal(res.status, 400);
    const body = await res.json();
    assert.equal(body.ok, false);
  } finally {
    server.close();
  }
});

test("POST /do con json roto es 400", async () => {
  const server = createBridgeServer({ getState: () => ({}), doAction: async () => ({}) });
  const port = await listen(server);
  try {
    const res = await fetch(`http://127.0.0.1:${port}/do`, {
      method: "POST",
      body: "{not json",
    });
    assert.equal(res.status, 400);
  } finally {
    server.close();
  }
});

test("GET /events entrega lo que se publica, tras un keepalive", async () => {
  const server = createBridgeServer({ getState: () => ({}), doAction: async () => ({}) });
  const port = await listen(server);
  const controller = new AbortController();
  try {
    const res = await fetch(`http://127.0.0.1:${port}/events`, {
      signal: controller.signal,
    });
    assert.equal(res.status, 200);
    assert.equal(res.headers.get("content-type"), "text/event-stream");

    const reader = res.body.getReader();
    const decoder = new TextDecoder();

    const first = decoder.decode((await reader.read()).value);
    assert.equal(first, ": ok\n\n");

    server.broadcast({ event: "chat", jugador: "Ana", texto: "hola" });
    const second = decoder.decode((await reader.read()).value);
    assert.equal(second, 'data: {"event":"chat","jugador":"Ana","texto":"hola"}\n\n');
  } finally {
    controller.abort();
    server.close();
  }
});

test("una petición a una ruta que no existe es 404", async () => {
  const server = createBridgeServer({ getState: () => ({}), doAction: async () => ({}) });
  const port = await listen(server);
  try {
    const res = await fetch(`http://127.0.0.1:${port}/nope`);
    assert.equal(res.status, 404);
  } finally {
    server.close();
  }
});

test("GET /events manda keepalives en un stream inactivo", async () => {
  // Without this the plugin's blocking read times out after 60 s and the
  // follower reports a cut every minute on a world where nothing happens.
  const server = createBridgeServer({
    getState: () => ({}),
    doAction: async () => ({}),
    keepAliveMs: 20,
  });
  const port = await listen(server);
  const controller = new AbortController();
  try {
    const res = await fetch(`http://127.0.0.1:${port}/events`, {
      signal: controller.signal,
    });
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let seen = "";
    const deadline = Date.now() + 2000;
    while (!seen.includes(": ping") && Date.now() < deadline) {
      const { value, done } = await reader.read();
      if (done) break;
      seen += decoder.decode(value);
    }
    assert.match(seen, /: ping/);
  } finally {
    controller.abort();
    server.close();
  }
});
