"""Registration declares tools, and an event becomes a prompt — nothing else."""

import pytest

from Hermes.plugins import jarvis_minecraft
from Hermes.plugins.jarvis_minecraft import mundo
from Hermes.plugins.jarvis_minecraft.bridge_client import LOST


class FakeCtx:
    def __init__(self) -> None:
        self.tools: list[dict] = []
        self.unloads: list = []
        self.messages: list[tuple] = []
        self.accept = True

    def register_tool(self, **kw) -> None:
        self.tools.append(kw)

    def on_unload(self, fn) -> None:
        self.unloads.append(fn)

    def get_config(self, key, default=None):
        return default

    def inject_message(self, prompt, role="user", session_key=None) -> bool:
        self.messages.append((prompt, role, session_key))
        return self.accept


class FakeClient:
    def __init__(self, *, up: bool = False) -> None:
        self.up = up

    def state(self):
        return {"bot": {"vida": 20}}


@pytest.fixture(autouse=True)
def _reset_cooldown():
    jarvis_minecraft._last_event["at"] = 0.0


def test_wire_declara_las_tools_en_el_toolset_mundo() -> None:
    ctx = FakeCtx()
    nombres = jarvis_minecraft._wire(ctx, FakeClient())
    esperadas = [mundo.ESTADO, mundo.IR_A, mundo.BUSCAR, mundo.IR_AL_BLOQUE]
    assert nombres == esperadas
    assert {t["name"] for t in ctx.tools} == set(esperadas)
    assert {t["toolset"] for t in ctx.tools} == {"mundo"}


def test_el_schema_es_el_objeto_funcion_no_solo_los_parametros() -> None:
    """§12: passing only `parameters` is what made the model call with `{}`."""
    ctx = FakeCtx()
    jarvis_minecraft._wire(ctx, FakeClient())
    for tool in ctx.tools:
        schema = tool["schema"]
        assert schema["description"] == mundo.DESCRIPCIONES[tool["name"]]
        assert schema["parameters"] == mundo.ESQUEMAS[tool["name"]]


def test_check_fn_sigue_al_puente() -> None:
    ctx = FakeCtx()
    client = FakeClient(up=False)
    jarvis_minecraft._wire(ctx, client)
    checks = [t["check_fn"] for t in ctx.tools]
    assert all(check() is False for check in checks)
    client.up = True
    assert all(check() is True for check in checks)


def test_wire_no_arranca_hilos_ni_toca_la_red() -> None:
    """Registration must be pure: nothing here opens a socket."""
    ctx = FakeCtx()
    jarvis_minecraft._wire(ctx, FakeClient())
    assert ctx.unloads == []


def test_un_evento_critico_se_inyecta_una_vez_por_ventana() -> None:
    ctx = FakeCtx()
    evento = {"event": "died"}
    assert jarvis_minecraft._inject(ctx, evento, now=lambda: 100.0) is True
    assert jarvis_minecraft._inject(ctx, evento, now=lambda: 110.0) is False
    assert jarvis_minecraft._inject(ctx, evento, now=lambda: 200.0) is True
    assert len(ctx.messages) == 2


def test_el_chat_y_perder_el_puente_no_inyectan() -> None:
    ctx = FakeCtx()
    assert jarvis_minecraft._inject(ctx, {"event": "chat", "texto": "hola"}) is False
    assert jarvis_minecraft._inject(ctx, LOST) is False
    assert ctx.messages == []


def test_el_prompt_no_nombra_maquinaria() -> None:
    ctx = FakeCtx()
    jarvis_minecraft._inject(ctx, {"event": "emergency"}, now=lambda: 100.0)
    prompt, role, session_key = ctx.messages[0]
    assert role == "user"
    assert session_key == jarvis_minecraft.JARVIS_SESSION_KEY
    assert "peligro" in prompt
    # Tool identifiers never appear. The words for the things he must NOT
    # say do appear, in the prohibition itself — the same shape
    # jarvis_vision/alert.py uses.
    for identificador in ("ir_a", "estado_del_mundo", "tool_call", "{}"):
        assert identificador not in prompt
    assert "No digas" in prompt


def test_un_gateway_que_rechaza_no_rompe_ni_queda_aceptado() -> None:
    ctx = FakeCtx()
    ctx.accept = False
    ctx.messages.clear()
    assert jarvis_minecraft._inject(ctx, {"event": "died"}, now=lambda: 100.0) is False
