import type { WSClientToServer, WSServerToClient } from "../core/types";

type Handler<T extends WSServerToClient["type"]> = (
  msg: Extract<WSServerToClient, { type: T }>,
) => void;

// WebSocket wrapper with auto-reconnect (exponential backoff to 8s).
// The kiosk reloads the page on backend restart, but the WS reconnects
// in place if the backend just drops the connection.
export class WSClient {
  private ws: WebSocket | null = null;
  private handlers = new Map<string, (msg: WSServerToClient) => void>();
  private reconnectDelay = 500;
  private maxReconnectDelay = 8000;
  private shouldReconnect = true;

  constructor(public readonly url: string) {
    this.connect();
  }

  private connect() {
    this.ws = new WebSocket(this.url);
    this.ws.addEventListener("open", () => { this.reconnectDelay = 500; });
    this.ws.addEventListener("message", (ev) => {
      try {
        const msg = JSON.parse(ev.data) as WSServerToClient;
        const h = this.handlers.get(msg.type);
        if (h) h(msg);
      } catch {
        // ignore non-JSON
      }
    });
    this.ws.addEventListener("close", () => {
      if (this.shouldReconnect) {
        setTimeout(() => this.connect(), this.reconnectDelay);
        this.reconnectDelay = Math.min(
          this.maxReconnectDelay,
          this.reconnectDelay * 1.8,
        );
      }
    });
  }

  on<T extends WSServerToClient["type"]>(type: T, handler: Handler<T>): void {
    this.handlers.set(type, handler as (msg: WSServerToClient) => void);
  }

  send(msg: WSClientToServer): boolean {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return false;
    this.ws.send(JSON.stringify(msg));
    return true;
  }

  /** Resolve when the socket is OPEN, or reject after `timeoutMs` if
   *  it never opens. Lets callers tolerate a transient disconnect
   *  (the kiosk had STT running for several seconds, etc.) instead
   *  of immediately failing with ws_not_connected. */
  private async whenOpen(timeoutMs = 3000): Promise<void> {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) return;
    return new Promise((resolve, reject) => {
      const start = Date.now();
      const tick = () => {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
          resolve();
          return;
        }
        if (Date.now() - start >= timeoutMs) {
          reject(new Error("ws_not_connected"));
          return;
        }
        setTimeout(tick, 60);
      };
      tick();
    });
  }

  async chat(
    message: string,
    onToken: (t: string) => void,
    userId = "primary",
  ): Promise<{ reply: string; thinkingMs: number }> {
    await this.whenOpen();
    return new Promise((resolve, reject) => {
      let full = "";
      const restore = () => {
        this.handlers.delete("token");
        this.handlers.delete("done");
        this.handlers.delete("error");
      };
      this.on("token", (m) => { full += m.token; onToken(m.token); });
      this.on("done", (m) => { restore(); resolve({ reply: full, thinkingMs: m.thinking_ms }); });
      this.on("error", (m) => { restore(); reject(new Error(m.error)); });
      if (!this.send({ type: "chat", message, user_id: userId })) {
        restore();
        reject(new Error("ws_not_connected"));
      }
    });
  }

  async listen(): Promise<string> {
    await this.whenOpen();
    return new Promise((resolve, reject) => {
      this.on("transcription", (m) => {
        this.handlers.delete("transcription");
        resolve(m.text);
      });
      if (!this.send({ type: "listen" })) {
        reject(new Error("ws_not_connected"));
      }
    });
  }
}

let _singleton: WSClient | null = null;
export function getWSClient(): WSClient {
  if (!_singleton) {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    _singleton = new WSClient(`${proto}://${location.host}/ws`);
  }
  return _singleton;
}
