import asyncio
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from Hermes.plugins.jarvis.adapter import JarvisAdapter
from Hermes.plugins.jarvis.policy import FULL_TOOLSETS, PolicyError, PolicyResolver


def _policy():
    return {
        "local_provider": {
            "provider": "custom:local",
            "model": "qwen3.8-27b",
            "base_url": "http://127.0.0.1:8000/v1",
        }
    }


def test_only_approved_principals_have_a_policy():
    resolver = PolicyResolver(_policy())
    assert resolver.admit_mobile("orelvis").toolsets == FULL_TOOLSETS
    casa = resolver.admit_mobile("casa")
    assert casa.toolsets == ()
    assert not {"terminal", "file", "camaras"}.intersection(casa.toolsets)
    try:
        resolver.admit_mobile("marta")
    except PolicyError:
        pass
    else:
        raise AssertionError("an unapproved persona must not be admitted")


def test_desktop_chat_id_cannot_select_orelvis_policy(monkeypatch):
    seen = []

    async def record(self, event):
        seen.append(event.source.jarvis_policy)

    monkeypatch.setattr(JarvisAdapter, "handle_message", record, raising=False)

    async def go():
        adapter = JarvisAdapter({"policy": _policy()})
        await adapter._handle_chat("hola", "primary", "orelvis")
        turn = adapter._active_turns["casa"]
        assert turn.policy == seen[0]
        await adapter.disconnect()

    asyncio.run(go())
    assert seen[0].principal == "casa"
    assert seen[0].toolsets == ()


def test_mobile_policy_mutation_rejects_later_admission():
    policy = _policy()
    resolver = PolicyResolver(policy)
    first = resolver.admit_mobile("orelvis")
    policy["local_provider"]["model"] = "other"
    assert first.toolsets == FULL_TOOLSETS
    try:
        resolver.admit_mobile("orelvis")
    except PolicyError:
        pass
    else:
        raise AssertionError("changed policy must reject a new mobile turn")


def test_mobile_admission_rejects_a_nonlocal_provider():
    policy = _policy()
    policy["local_provider"]["base_url"] = "https://api.example/v1"
    resolver = PolicyResolver(policy)
    try:
        resolver.admit_mobile("casa")
    except PolicyError:
        pass
    else:
        raise AssertionError("a mobile turn must not fall back to a remote provider")


@pytest.mark.parametrize("principal", ["casa", "orelvis"])
def test_toolsets_override_is_a_fresh_list(principal):
    policy = PolicyResolver(_policy()).admit_mobile(principal)
    source = SimpleNamespace(jarvis_policy=policy)
    adapter = object.__new__(JarvisAdapter)
    override = adapter.toolsets_for_source(source)
    assert isinstance(override, list)
    assert override == list(policy.toolsets)
    override.append("unapproved")
    assert adapter.toolsets_for_source(source) == list(policy.toolsets)


@pytest.mark.parametrize(
    "source", [SimpleNamespace(), SimpleNamespace(jarvis_policy={})]
)
def test_missing_or_invalid_snapshot_has_no_override(source):
    assert object.__new__(JarvisAdapter).toolsets_for_source(source) is None


def test_policy_override_reaches_real_hermes_resolver(tmp_path):
    # A fresh interpreter avoids the plugin suite's fallback adapter shim.
    root = Path(__file__).resolve().parents[4]
    runtime = root / ".hermes" / "src"
    python = runtime / ".venv" / "bin" / "python"
    if not python.is_file():
        pytest.skip("real Hermes runtime is not installed")
    result = subprocess.run(
        [
            str(python),
            "-c",
            """
from types import SimpleNamespace
from gateway.platforms.base import BasePlatformAdapter
from gateway.run import GatewayRunner
from hermes_cli.tools_config import _get_platform_tools
from Hermes.plugins.jarvis.adapter import JarvisAdapter
from Hermes.plugins.jarvis.policy import PolicyResolver

assert issubclass(JarvisAdapter, BasePlatformAdapter)
adapter = object.__new__(JarvisAdapter)
runner = object.__new__(GatewayRunner)
runner._adapter_for_source = lambda source: adapter
resolver = PolicyResolver({})
cfg = {
    "platform_toolsets": {"jarvis": ["terminal", "file"]},
    "mcp_servers": {"unrelated_mcp": {"command": "never-executed"}},
    "agent": {"disabled_toolsets": ["terminal"]},
}
for principal in ("casa", "orelvis"):
    policy = resolver.admit_desktop() if principal == "casa" else PolicyResolver(
        {"desktop_principal": "orelvis"}
    ).admit_desktop()
    source = SimpleNamespace(jarvis_policy=policy)
    override = adapter.toolsets_for_source(source)
    assert isinstance(override, list)
    assert override == list(policy.toolsets)
    actual = runner._resolve_enabled_toolsets_for_source(cfg, source, "jarvis")
    if principal == "casa":
        assert actual == [], actual
    else:
        assert "file" in actual, actual
        assert "terminal" not in actual, actual
        assert set(actual) <= set(policy.toolsets), actual
    assert "unrelated_mcp" not in actual
source = SimpleNamespace()
assert adapter.toolsets_for_source(source) is None
assert runner._resolve_enabled_toolsets_for_source(cfg, source, "jarvis") == sorted(
    _get_platform_tools(cfg, "jarvis")
)
""",
        ],
        cwd=tmp_path,
        env={
            "PATH": os.defpath,
            "HOME": str(tmp_path),
            "HERMES_HOME": str(tmp_path),
            "PYTHONPATH": os.pathsep.join((str(runtime), str(root))),
            "PYTHONNOUSERSITE": "1",
        },
        capture_output=True,
        check=False,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
