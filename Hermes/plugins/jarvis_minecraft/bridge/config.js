// Everything the bridge reads from the environment, in one place, with a
// default that works on a box where nothing has been set.
//
// The names are JARVIS_MC_* on purpose: the service unit sets none of
// them, so a value that is wrong is a value somebody typed, not one this
// file invented.

function num(name, fallback) {
  const raw = process.env[name];
  if (raw === undefined || raw === "") return fallback;
  const parsed = Number(raw);
  return Number.isFinite(parsed) ? parsed : fallback;
}

// Where the Minecraft server is. Loopback in phases 0-1; a LAN address
// once people are let in, and then never 0.0.0.0 (design §8).
export const HOST = process.env.JARVIS_MC_HOST || "127.0.0.1";
export const PORT = num("JARVIS_MC_PORT", 25565);

// The version mineflayer must speak. Pinned to the server (probe doc,
// 2026-09-22): a mismatch either fails the handshake or, worse, connects
// and decodes packets wrong.
export const VERSION = process.env.JARVIS_MC_VERSION || "1.21.8";

// The bot's name in the world. It is his, not an anonymous user (§7).
export const USERNAME = process.env.JARVIS_MC_USERNAME || "Jarvis";

// Where the bridge listens for the plugin. Loopback, always.
export const BRIDGE_HOST = process.env.JARVIS_MC_BRIDGE_HOST || "127.0.0.1";
export const BRIDGE_PORT = num("JARVIS_MC_BRIDGE_PORT", 8095);

// How far the snapshot looks, and how many entities make it into the
// prompt. A server with a hundred mobs must not dump a hundred entries
// into the model's context (design §4).
export const RADAR = num("JARVIS_MC_RADAR", 16);
export const MAX_ENTITIES = num("JARVIS_MC_MAX_ENTITIES", 12);

// A hanging action is worse than a failed one: the strip goes mute until
// the adapter's 90 s watchdog. This is the deadline every action runs
// under (design §3).
export const ACTION_TIMEOUT_MS = num("JARVIS_MC_ACTION_TIMEOUT", 30000);

// How often a critical event may be emitted. The plugin has its own
// cooldown; this is the body's (design §6).
export const EVENT_COOLDOWN_MS = num("JARVIS_MC_EVENT_COOLDOWN", 30000);

// Reconnect backoff, quick at first and patient after (design §9.1).
export const RECONNECT_MIN_MS = num("JARVIS_MC_RECONNECT_MIN", 1000);
export const RECONNECT_MAX_MS = num("JARVIS_MC_RECONNECT_MAX", 30000);
