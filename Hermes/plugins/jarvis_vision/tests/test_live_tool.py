"""`ver_en_vivo` and `dejar_de_ver`: what he says, and what he never says.

The load-bearing rule is the one the snapshot spec measured: he calls a
camera tool with NO argument 5 times out of 5, even when a camera was
named. `mirar` survives that by surveying all of them. There is no "all"
for a live view, so the handler asks instead of guessing.
"""

import asyncio

from Hermes.plugins.jarvis_vision.live_tool import (
    make_close_handler,
    make_open_handler,
)


class _Session:
    def __init__(self, ok=True) -> None:
        self.ok = ok
        self.camera = None
        self.opened: list[str] = []
        self.closed: list[str] = []

    async def open(self, camera, *, extradata, size):
        self.opened.append(camera)
        if self.ok:
            self.camera = camera
        return self.ok

    async def close(self, reason):
        self.closed.append(reason)
        was, self.camera = self.camera, None
        return was is not None


class _Fleet:
    def __init__(self, params=(b"sps", 704, 480)) -> None:
        self._params = params

    def codec_parameters(self, camera):
        return self._params


def test_a_named_camera_opens_it():
    session = _Session()
    handler = make_open_handler(session, _Fleet(), ["entrada", "fuera"])

    said = asyncio.run(handler(camara="entrada"))

    assert session.opened == ["entrada"]
    assert "entrada" in said.lower()
    assert "/" not in said  # never a path: CosyVoice reads this out loud


def test_no_camera_named_and_only_one_alive_uses_it():
    session = _Session()
    handler = make_open_handler(session, _Fleet(), ["entrada"])

    asyncio.run(handler())

    assert session.opened == ["entrada"]


def test_no_camera_named_and_several_alive_asks_which():
    session = _Session()
    handler = make_open_handler(session, _Fleet(), ["entrada", "fuera"])

    said = asyncio.run(handler())

    assert session.opened == []
    assert "entrada" in said and "fuera" in said


def test_a_camera_that_does_not_exist_is_not_invented():
    session = _Session()
    handler = make_open_handler(session, _Fleet(), ["entrada"])

    said = asyncio.run(handler(camara="garaje"))

    assert session.opened == []
    assert "entrada" in said


def test_a_strip_that_did_not_take_it_is_said_honestly():
    session = _Session(ok=False)
    handler = make_open_handler(session, _Fleet(), ["entrada"])

    said = asyncio.run(handler(camara="entrada"))

    assert said == "Ahora mismo no puedo enseñárselo, señor."
    assert "socket" not in said.lower()
    assert "sesión" not in said.lower()


def test_closing_when_nothing_is_up_is_still_a_sentence():
    session = _Session()
    handler = make_close_handler(session)

    said = asyncio.run(handler())

    assert said == "Estado: no había nada puesto."


def test_no_answer_ever_names_the_machinery():
    session = _Session()
    handler = make_open_handler(session, _Fleet(), ["entrada", "fuera"])
    for said in [asyncio.run(handler()), asyncio.run(handler(camara="entrada"))]:
        low = said.lower()
        for forbidden in ("cámara", "h264", "códec", "socket", "epoch", "sesión"):
            assert forbidden not in low


# ── an argument that is not a name ────────────────────────────────────
#
# Measured on the live gateway, 2026-08-26: asked "enséñame la cámara de
# la entrada", he called this tool with `camara` set to a DICT, and
# `_resolve` met it with `.casefold()`. The handler that documents itself
# as never raising raised, the turn came back as a tool error, and what
# he said out loud was "la imagen en directo no me llega ahora mismo" —
# which sounds like a camera problem and was not one.


def test_a_wrapped_name_is_unwrapped_rather_than_dropped():
    session = _Session()
    handler = make_open_handler(session, _Fleet(), ["entrada", "fuera"])

    said = asyncio.run(handler(camara={"camara": "entrada"}))

    assert session.opened == ["entrada"]
    assert "entrada" in said.lower()


def test_an_argument_with_no_name_in_it_asks_instead_of_raising():
    session = _Session()
    handler = make_open_handler(session, _Fleet(), ["entrada", "fuera"])

    said = asyncio.run(handler(camara={"type": "string"}))

    assert session.opened == []
    assert "entrada" in said and "fuera" in said


def test_a_list_of_one_name_is_a_name():
    session = _Session()
    handler = make_open_handler(session, _Fleet(), ["entrada", "fuera"])

    asyncio.run(handler(camara=["entrada"]))

    assert session.opened == ["entrada"]
