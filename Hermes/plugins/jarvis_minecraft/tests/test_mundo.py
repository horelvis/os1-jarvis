"""The world tools: schemas the model can obey, and answers that never raise."""

import json

import pytest

from Hermes.plugins.jarvis_minecraft import mundo


class FakeClient:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple] = []

    def state(self):
        if self.fail:
            raise RuntimeError("bridge caído")
        return {"bot": {"vida": 20}, "inventario": [], "entorno": {"entidades": []}}

    def do(self, action, args):
        self.calls.append((action, args))
        if self.fail:
            raise RuntimeError("bridge caído")
        return {"ok": True, "said": "He llegado."}


def test_every_tool_has_a_description_and_a_schema() -> None:
    for name in (mundo.ESTADO, mundo.IR_A, mundo.BUSCAR, mundo.IR_AL_BLOQUE):
        assert mundo.DESCRIPCIONES[name]
        assert mundo.ESQUEMAS[name]["type"] == "object"


def test_block_id_traduce_el_espanol_y_deja_pasar_el_ingles() -> None:
    assert mundo.block_id("agua") == "water"
    assert mundo.block_id("Agua") == "water"
    assert mundo.block_id("madera") == "oak_log"
    assert mundo.block_id("oak_log") == "oak_log"
    assert mundo.block_id("cobblestone") == "cobblestone"


@pytest.mark.asyncio
async def test_buscar_bloque_devuelve_json_con_coordenadas() -> None:
    class Client:
        def do(self, action, args):
            assert action == "buscar_bloque"
            assert args == {"bloque": "water"}
            return {"ok": True, "data": {"x": 5, "y": 63, "z": -2}}

    salida = await mundo.make_handler(Client(), mundo.BUSCAR)({"bloque": "agua"})
    assert json.loads(salida) == {
        "encontrado": True,
        "bloque": "agua",
        "x": 5,
        "y": 63,
        "z": -2,
    }


@pytest.mark.asyncio
async def test_buscar_bloque_sin_resultado_lo_dice_sin_romper() -> None:
    class Client:
        def do(self, action, args):
            return {"ok": False, "error": "no_encontrado", "said": "No veo eso cerca."}

    salida = await mundo.make_handler(Client(), mundo.BUSCAR)({"bloque": "agua"})
    assert json.loads(salida) == {"encontrado": False, "bloque": "agua"}


@pytest.mark.asyncio
async def test_ir_al_bloque_traduce_y_devuelve_la_frase_del_bridge() -> None:
    class Client:
        def do(self, action, args):
            assert action == "ir_al_bloque"
            assert args == {"bloque": "water"}
            return {"ok": True, "said": "He llegado."}

    salida = await mundo.make_handler(Client(), mundo.IR_AL_BLOQUE)({"bloque": "agua"})
    assert salida == "He llegado."


@pytest.mark.asyncio
async def test_sin_nombre_de_bloque_pide_uno() -> None:
    handler = mundo.make_handler(FakeClient(), mundo.BUSCAR)
    assert await handler({}) == mundo.FALTA_BLOQUE
    assert await handler(None) == mundo.FALTA_BLOQUE


def test_ir_a_exige_las_tres_coordenadas_numericas() -> None:
    esquema = mundo.ESQUEMAS[mundo.IR_A]
    assert esquema["required"] == ["x", "y", "z"]
    assert {k: v["type"] for k, v in esquema["properties"].items()} == {
        "x": "number",
        "y": "number",
        "z": "number",
    }


def test_estado_del_mundo_no_tiene_argumentos() -> None:
    assert mundo.ESQUEMAS[mundo.ESTADO]["properties"] == {}
    assert mundo.ESQUEMAS[mundo.ESTADO]["required"] == []


@pytest.mark.asyncio
async def test_estado_devuelve_json_para_el_modelo() -> None:
    handler = mundo.make_handler(FakeClient(), mundo.ESTADO)
    salida = await handler({})
    assert json.loads(salida) == {
        "bot": {"vida": 20},
        "inventario": [],
        "entorno": {"entidades": []},
    }


@pytest.mark.asyncio
async def test_ir_a_pasa_las_coordenadas_y_devuelve_la_frase_del_bridge() -> None:
    client = FakeClient()
    handler = mundo.make_handler(client, mundo.IR_A)
    salida = await handler({"x": 1, "y": 64, "z": -2})
    assert salida == "He llegado."
    assert client.calls == [("ir_a", {"x": 1.0, "y": 64.0, "z": -2.0})]


@pytest.mark.asyncio
async def test_ir_a_sin_coordenadas_pide_las_tres() -> None:
    client = FakeClient()
    handler = mundo.make_handler(client, mundo.IR_A)
    assert await handler({}) == mundo.FALTAN
    assert await handler(None) == mundo.FALTAN
    assert client.calls == []


@pytest.mark.asyncio
async def test_ir_a_desenvuelve_un_dict_anidado_o_una_lista() -> None:
    """The model nests the argument dict — the `ver_en_vivo` lesson."""
    client = FakeClient()
    handler = mundo.make_handler(client, mundo.IR_A)
    assert await handler({"args": {"x": 1, "y": 2, "z": 3}}) == "He llegado."
    assert await handler([{"x": 1, "y": 2, "z": 3}]) == "He llegado."
    assert client.calls == [
        ("ir_a", {"x": 1.0, "y": 2.0, "z": 3.0}),
        ("ir_a", {"x": 1.0, "y": 2.0, "z": 3.0}),
    ]


@pytest.mark.asyncio
async def test_ningun_handler_propaga_una_excepcion() -> None:
    client = FakeClient(fail=True)
    assert await mundo.make_handler(client, mundo.ESTADO)({}) == mundo.NO_ESTADO
    assert (
        await mundo.make_handler(client, mundo.IR_A)({"x": 0, "y": 0, "z": 0})
        == mundo.NO_MUNDO
    )


@pytest.mark.asyncio
async def test_una_respuesta_que_no_es_dict_no_se_dice_como_ok() -> None:
    class Raro:
        def do(self, action, args):
            return "no soy un dict"

    salida = await mundo.make_handler(Raro(), mundo.IR_A)({"x": 0, "y": 0, "z": 0})
    assert salida == mundo.NO_MUNDO


def test_coords_acepta_floats_y_rechaza_lo_que_no_tiene_tres_numeros() -> None:
    assert mundo.coords({"x": 1, "y": 2.5, "z": "-3"}) == (1.0, 2.5, -3.0)
    assert mundo.coords({"x": 1, "y": 2}) is None
    assert mundo.coords({"x": "norte", "y": 2, "z": 3}) is None
    assert mundo.coords("hola") is None
