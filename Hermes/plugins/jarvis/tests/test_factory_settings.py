"""The registered factory must apply the server's actual admission policy."""

import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest

from Hermes.plugins.jarvis import JarvisAdapter, register
from Hermes.plugins.jarvis.policy import FULL_TOOLSETS


class Context:
    def __init__(self, settings):
        self.settings = settings
        self.platform = None

    def get_config(self, key, default=None):
        return self.settings.get(key, default)

    def register_hook(self, *_args):
        pass

    def register_tool(self, **_kwargs):
        pass

    def register_platform(self, **kwargs):
        self.platform = kwargs


@pytest.mark.parametrize("as_dict", [False, True])
def test_registered_factory_preserves_configured_owner_and_toolsets(
    monkeypatch, as_dict
):
    monkeypatch.delenv("JARVIS_PORT", raising=False)
    seen = []

    async def handle(self, event):
        seen.append((event.source.chat_id, event.source.jarvis_policy))

    monkeypatch.setattr(JarvisAdapter, "handle_message", handle, raising=False)
    settings = {"policy": {"desktop_principal": "orelvis"}, "port": 9999}
    original = deepcopy(settings)
    context = Context(settings)
    register(context)
    extra = {"port": 0}
    config = extra if as_dict else SimpleNamespace(extra=extra)

    async def go():
        adapter = context.platform["adapter_factory"](config)
        assert adapter._configured_port == 0
        # Client-supplied identity is still irrelevant: only the configured
        # server seat determines this legacy compatibility path's authority.
        await adapter._handle_chat("consulta", "primary", "attacker-chosen-chat")
        await adapter.disconnect()

    asyncio.run(go())
    assert seen[0][0] == "orelvis"
    assert seen[0][1].profile == "orelvis"
    assert seen[0][1].toolsets == FULL_TOOLSETS
    assert settings == original
    assert extra == {"port": 0}


def test_absent_settings_keep_the_tool_free_default():
    context = Context({})
    register(context)
    adapter = context.platform["adapter_factory"](SimpleNamespace(extra={}))
    policy = adapter._policy.admit_desktop()
    assert policy.principal == "casa"
    assert policy.toolsets == ()


def test_explicit_platform_policy_overrides_plugin_policy_without_mutation():
    context = Context({"policy": {"desktop_principal": "orelvis"}})
    register(context)
    config = SimpleNamespace(extra={"policy": {"desktop_principal": "casa"}})
    adapter = context.platform["adapter_factory"](config)
    assert adapter._policy.admit_desktop().principal == "casa"
    assert adapter._policy.admit_desktop().toolsets == ()
    assert context.settings["policy"]["desktop_principal"] == "orelvis"


def test_mobile_settings_reach_the_adapter_without_starting_a_listener():
    mobile = {"enabled": False, "roster_path": "/tmp/synthetic-roster.json"}
    context = Context({"mobile": mobile})
    register(context)
    adapter = context.platform["adapter_factory"](SimpleNamespace(extra={}))
    assert adapter._mobile_config == mobile
    assert adapter._mobile_runner is None
