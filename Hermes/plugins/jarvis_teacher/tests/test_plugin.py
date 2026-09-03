"""Registration declares tools and touches nothing else.

`register(ctx)` is a plugin's whole lifecycle on the way in — there is
no later hook (§12, 2026-08-24) — so anything that reads a file, opens
a socket or builds a database here turns a missing dependency into a
plugin that never loads.
"""

from Hermes.plugins import jarvis_teacher


class FakeCtx:
    def __init__(self) -> None:
        self.tools: list[dict] = []
        self.unloads: list = []

    def register_tool(self, **kw) -> None:
        self.tools.append(kw)

    def on_unload(self, fn) -> None:
        self.unloads.append(fn)

    def get_config(self, key, default=None):
        return default


def test_registration_declares_the_seven_tools() -> None:
    ctx = FakeCtx()
    jarvis_teacher.register(ctx)
    nombres = {t["name"] for t in ctx.tools}
    assert nombres == {
        "ensename",
        "planificar",
        "aprobar",
        "explicar",
        "preguntar",
        "responder",
        "terminar",
    }


def test_every_tool_is_in_the_clases_toolset() -> None:
    ctx = FakeCtx()
    jarvis_teacher.register(ctx)
    assert {t["toolset"] for t in ctx.tools} == {"clases"}


def test_no_tool_declares_more_than_two_arguments() -> None:
    """§12 (2026-08-26): arguments are what the Hermes path loses."""
    ctx = FakeCtx()
    jarvis_teacher.register(ctx)
    for tool in ctx.tools:
        propiedades = tool["schema"].get("properties", {})
        assert len(propiedades) <= 2, tool["name"]


def test_registration_writes_nothing_to_disk(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("JARVIS_TEACHER_HOME", str(tmp_path))
    jarvis_teacher.register(FakeCtx())
    assert not list(tmp_path.iterdir())
