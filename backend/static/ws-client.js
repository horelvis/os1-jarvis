/**
 * WebSocket client for /ws.
 *
 * Protocol (JSON messages both ways):
 *
 *   Client → Server:
 *     { "type": "chat",   "message": "..." , "user_id": "primary" }
 *     { "type": "listen"  }                  // mic placeholder, Phase 5 will add audio
 *
 *   Server → Client:
 *     { "type": "token",         "token": "..." }            // streamed during chat
 *     { "type": "done",          "thinking_ms": 1234 }       // chat finished
 *     { "type": "transcription", "text": "..." }             // listen result
 *     { "type": "error",         "error": "..." }
 *
 * The client auto-reconnects with backoff so the kiosk recovers if
 * the backend restarts.
 */

export class WSClient {
  constructor(url) {
    this.url = url;
    this.ws = null;
    this.handlers = new Map();
    this.openHandlers = [];
    this.closeHandlers = [];
    this.reconnectDelay = 500;
    this.maxReconnectDelay = 8000;
    this.shouldReconnect = true;
    this.connect();
  }

  connect() {
    this.ws = new WebSocket(this.url);

    this.ws.addEventListener('open', () => {
      console.log('[ws] connected');
      this.reconnectDelay = 500;
      this.openHandlers.forEach((fn) => fn());
    });

    this.ws.addEventListener('message', (ev) => {
      let msg;
      try {
        msg = JSON.parse(ev.data);
      } catch (e) {
        console.error('[ws] non-JSON message:', ev.data);
        return;
      }
      const handler = this.handlers.get(msg.type);
      if (handler) handler(msg);
      else console.warn('[ws] unhandled type:', msg.type, msg);
    });

    this.ws.addEventListener('close', () => {
      console.warn('[ws] closed');
      this.closeHandlers.forEach((fn) => fn());
      if (this.shouldReconnect) {
        setTimeout(() => this.connect(), this.reconnectDelay);
        this.reconnectDelay = Math.min(this.maxReconnectDelay, this.reconnectDelay * 1.8);
      }
    });

    this.ws.addEventListener('error', (e) => {
      console.error('[ws] error', e);
    });
  }

  on(type, handler) {
    this.handlers.set(type, handler);
  }

  onOpen(fn) {
    this.openHandlers.push(fn);
    if (this.ws && this.ws.readyState === WebSocket.OPEN) fn();
  }

  onClose(fn) {
    this.closeHandlers.push(fn);
  }

  send(obj) {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      console.warn('[ws] send while closed, dropping:', obj);
      return false;
    }
    this.ws.send(JSON.stringify(obj));
    return true;
  }

  /**
   * Send a chat message and collect the streamed tokens via onToken.
   * Resolves with the full reply once a {type:"done"} is received.
   */
  chat(message, onToken, userId = 'primary') {
    return new Promise((resolve, reject) => {
      let full = '';
      const tokenStash = this.handlers.get('token');
      const doneStash = this.handlers.get('done');
      const errorStash = this.handlers.get('error');
      const restore = () => {
        if (tokenStash) this.handlers.set('token', tokenStash); else this.handlers.delete('token');
        if (doneStash) this.handlers.set('done', doneStash); else this.handlers.delete('done');
        if (errorStash) this.handlers.set('error', errorStash); else this.handlers.delete('error');
      };
      this.handlers.set('token', (msg) => { full += msg.token; onToken(msg.token); });
      this.handlers.set('done', (msg) => {
        restore();
        resolve({ reply: full, thinkingMs: msg.thinking_ms });
      });
      this.handlers.set('error', (msg) => {
        restore();
        reject(new Error(msg.error || 'ws chat error'));
      });

      if (!this.send({ type: 'chat', message, user_id: userId })) {
        restore();
        reject(new Error('websocket not connected'));
      }
    });
  }

  /**
   * Trigger a "listen" turn. The backend (mock) returns a fake
   * transcription; Phase 5 will swap in real STT.
   */
  listen() {
    return new Promise((resolve, reject) => {
      const stash = this.handlers.get('transcription');
      this.handlers.set('transcription', (msg) => {
        if (stash) this.handlers.set('transcription', stash);
        else this.handlers.delete('transcription');
        resolve(msg.text);
      });
      if (!this.send({ type: 'listen' })) {
        reject(new Error('websocket not connected'));
      }
    });
  }

  close() {
    this.shouldReconnect = false;
    if (this.ws) this.ws.close();
  }
}
