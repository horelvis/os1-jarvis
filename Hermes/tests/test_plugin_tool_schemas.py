"""Every tool our plugins register must match Hermes' schema contract.

The contract is not documented anywhere; it is this line of
`.hermes/src/tools/registry.py` (`get_definitions`):

    schema_with_name = {**entry.schema, "name": entry.name}
    result.append({"type": "function", "function": schema_with_name})

So `schema` IS the OpenAI *function* object — `{"description": …,
"parameters": {…}}` — and not the parameters object. Every built-in tool
declares it that way.

All four of our plugins declared the parameters object directly, for
months. The model was therefore shown a function with no `parameters`
key and no description at all, and calling it with `{}` was the only
thing it could do. That is the whole of the "`args={}` through the
Hermes path" defect: `mirar` called with no camera five times out of
five (§12, 2026-08-26), `ensename` opening no course (2026-09-03), and
a correction in §12 that blamed "the Hermes path" without finding this.

This test exists so that the next tool cannot repeat it.
"""

from __future__ import annotations

import importlib
from typing import Any

import pytest

PLUGINS = ["jarvis_teacher", "jarvis_vision", "jarvis_voice", "jarvis_code", "jarvis"]


class _Ctx:
    """Enough plugin context to reach every `register_tool` call."""

    def __init__(self) -> None:
        self.tools: list[dict[str, Any]] = []

    def register_tool(self, **kw: Any) -> None:
        self.tools.append(kw)

    def register_platform(self, **kw: Any) -> None:
        pass

    def on_unload(self, fn: Any) -> None:
        pass

    def get_config(self, key: str, default: Any = None) -> Any:
        return default

    def __getattr__(self, name: str):  # any hook a plugin may reach for
        return lambda *a, **k: None


def _registered(plugin: str) -> list[dict[str, Any]]:
    module = importlib.import_module(f"Hermes.plugins.{plugin}")
    ctx = _Ctx()
    module.register(ctx)
    return ctx.tools


@pytest.mark.parametrize("plugin", PLUGINS)
def test_every_tool_declares_parameters_where_hermes_looks(plugin: str) -> None:
    for tool in _registered(plugin):
        schema = tool["schema"]
        name = tool["name"]
        assert "parameters" in schema, (
            f"{plugin}.{name}: the schema has no `parameters`, so the model "
            f"is shown a tool that takes no arguments and calls it with {{}}"
        )
        params = schema["parameters"]
        assert params.get("type") == "object", f"{plugin}.{name}"
        assert isinstance(params.get("properties"), dict), f"{plugin}.{name}"


@pytest.mark.parametrize("plugin", PLUGINS)
def test_no_tool_leaves_its_parameters_at_the_function_level(plugin: str) -> None:
    """The exact shape of the bug: `properties` where `parameters` belongs."""
    for tool in _registered(plugin):
        schema, name = tool["schema"], tool["name"]
        assert "properties" not in schema, (
            f"{plugin}.{name}: `properties` sits at the function level, which "
            f"is where the parameters object was passed instead of wrapping it"
        )


@pytest.mark.parametrize("plugin", PLUGINS)
def test_the_model_is_told_what_each_tool_does(plugin: str) -> None:
    """`register_tool(description=…)` never reaches the model.

    `get_definitions` spreads the schema and adds only `name`, so a
    description that lives outside the schema is shown to the plugin
    listing and to nobody else.
    """
    for tool in _registered(plugin):
        schema, name = tool["schema"], tool["name"]
        assert schema.get("description", "").strip(), (
            f"{plugin}.{name}: no description inside the schema, so the model "
            f"sees a bare name"
        )
