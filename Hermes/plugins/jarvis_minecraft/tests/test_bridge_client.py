"""The client speaks the contract, and survives a bridge that does not."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from Hermes.plugins.jarvis_minecraft import bridge_client
from Hermes.plugins.jarvis_minecraft.bridge_client import LOST, BridgeClient


def _make_bridge(*, state=None, do=None, events=None, status=200):
    """A tiny stand-in for the Node bridge, on a real loopback socket."""

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # keep pytest's output clean
            pass

        def _json(self, payload, code=status):
            body = json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/state":
                self._json(state or {"bot": {"vida": 20}})
            elif self.path == "/events":
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                for event in events or []:
                    self.wfile.write(f"data: {json.dumps(event)}\n\n".encode())
                    self.wfile.flush()
            else:
                self.send_error(404)

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            request = json.loads(self.rfile.read(length) or b"{}")
            self._json(do(request) if do else {"ok": True, "said": "He llegado."})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _url(server):
    host, port = server.server_address
    return f"http://{host}:{port}"


def test_state_devuelve_el_snapshot_y_marca_el_puente_arriba():
    server = _make_bridge(state={"bot": {"vida": 18}})
    try:
        client = BridgeClient(_url(server))
        assert client.up is False
        assert client.state() == {"bot": {"vida": 18}}
        assert client.up is True
    finally:
        server.shutdown()


def test_un_puente_caido_deja_up_en_false_y_state_lanza():
    client = BridgeClient("http://127.0.0.1:1")
    with pytest.raises(Exception):
        client.state()
    assert client.up is False


def test_do_manda_la_accion_y_devuelve_la_respuesta():
    seen = {}

    def do(request):
        seen.update(request)
        return {"ok": True, "said": "He llegado."}

    server = _make_bridge(do=do)
    try:
        client = BridgeClient(_url(server))
        answer = client.do("ir_a", {"x": 1, "y": 2, "z": 3})
        assert answer == {"ok": True, "said": "He llegado."}
        assert seen == {"action": "ir_a", "args": {"x": 1, "y": 2, "z": 3}}
        assert client.up is True
    finally:
        server.shutdown()


def test_una_accion_que_no_llega_es_un_sobre_de_error_no_una_excepcion():
    client = BridgeClient("http://127.0.0.1:1")
    answer = client.do("ir_a", {"x": 1, "y": 2, "z": 3})
    assert answer["ok"] is False
    assert answer["error"] == "sin_puente"


def test_solo_habla_http():
    with pytest.raises(ValueError):
        BridgeClient("file:///etc/passwd")
    with pytest.raises(ValueError):
        list(bridge_client.follow_events("file:///etc/passwd", stop=lambda: True))


def test_follow_events_entrega_los_eventos_y_avisa_del_corte():
    events = [{"event": "chat", "jugador": "Ana"}, {"event": "health", "vida": 4}]
    server = _make_bridge(events=events)
    stopped = {"value": False}
    try:
        gen = bridge_client.follow_events(_url(server), stop=lambda: stopped["value"])
        seen = []
        for payload in gen:
            seen.append(payload)
            if len(seen) >= len(events) + 1:  # events + LOST
                stopped["value"] = True
                break
        assert seen[: len(events)] == events
        assert seen[len(events)] == LOST
    finally:
        server.shutdown()
