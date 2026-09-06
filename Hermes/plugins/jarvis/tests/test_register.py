"""register() must land the authorization env vars under the NEW name.

Written after a review finding (2026-08-28): `_env()`'s legacy fallback for
`JARVIS_ALLOWED_USERS` / `JARVIS_ALLOW_ALL_USERS` never reaches
`authz_mixin.py`, which reads `os.environ[allowed_users_env]` /
`os.environ[allow_all_env]` by the literal new name through a bare
`os.getenv` of its own — it does not call `_env()`. So a box that still
carries `JARVIS_KIOSK_ALLOWED_USERS` and nothing under the new name went
unauthorized silently the moment the platform was renamed, and nothing here
caught it: every existing test drove `_configured_port`, never `register()`.
These tests exercise the process environment `register()` actually leaves
behind, the same thing `authz_mixin.py` reads.
"""

import os

import pytest

pytest.importorskip("aiohttp")

from Hermes.plugins.jarvis import register


class _StubCtx:
    """Just enough of the plugin registration context to call register()."""

    def __init__(self):
        self.hooks = {}

    def register_hook(self, name, fn):
        self.hooks[name] = fn

    def register_platform(self, **kwargs):
        self.kwargs = kwargs


def test_the_old_allowed_users_name_is_ignored(monkeypatch):
    """The clean cut of 2026-09-03: the old name stops working.

    It used to land under the new one. Now it does not, and what the
    user gets instead is the default — which is the safe direction: an
    allowlist that falls back to `primary` stops him answering a
    stranger, where inheriting a stale value would keep one authorised
    after the operator believed they had changed it.
    """
    monkeypatch.delenv("JARVIS_ALLOWED_USERS", raising=False)
    monkeypatch.setenv("SAMANTHA_KIOSK_ALLOWED_USERS", "custom_user")

    register(_StubCtx())

    assert os.environ["JARVIS_ALLOWED_USERS"] == "primary"


def test_with_neither_name_set_the_default_lands_under_the_new_name(monkeypatch):
    monkeypatch.delenv("JARVIS_ALLOWED_USERS", raising=False)
    monkeypatch.delenv("SAMANTHA_KIOSK_ALLOWED_USERS", raising=False)

    register(_StubCtx())

    assert os.environ["JARVIS_ALLOWED_USERS"] == "primary"


def test_the_new_name_set_explicitly_is_what_is_used(monkeypatch):
    monkeypatch.setenv("JARVIS_ALLOWED_USERS", "explicit_user")
    monkeypatch.setenv("SAMANTHA_KIOSK_ALLOWED_USERS", "legacy_user")

    register(_StubCtx())

    assert os.environ["JARVIS_ALLOWED_USERS"] == "explicit_user"


def test_the_old_allow_all_name_is_ignored(monkeypatch):
    """Also the clean cut, and this one matters more than its twin.

    `ALLOW_ALL` opens the socket to everybody. An old name that still
    worked would be a door somebody opened once and cannot see any
    more; ignored, the worst case is that he answers nobody.
    """
    monkeypatch.delenv("JARVIS_ALLOW_ALL_USERS", raising=False)
    monkeypatch.setenv("SAMANTHA_KIOSK_ALLOW_ALL_USERS", "true")

    register(_StubCtx())

    assert "JARVIS_ALLOW_ALL_USERS" not in os.environ


def test_with_neither_allow_all_name_set_it_stays_absent(monkeypatch):
    # The failure mode this guards against is worse than "unauthorized":
    # inventing "" or "false" would make ALLOW_ALL look CONFIGURED (and
    # falsy) rather than not configured at all — a different, and in
    # authz_mixin's own terms wrong, code path.
    monkeypatch.delenv("JARVIS_ALLOW_ALL_USERS", raising=False)
    monkeypatch.delenv("SAMANTHA_KIOSK_ALLOW_ALL_USERS", raising=False)

    register(_StubCtx())

    assert "JARVIS_ALLOW_ALL_USERS" not in os.environ


def test_register_platform_is_still_called_with_the_new_env_names(monkeypatch):
    # register() must go on to declare the NEW names to Hermes, not the
    # legacy ones — that part of Task 2 was already correct, kept here so
    # a regression in the fallback logic above can't silently break it too.
    monkeypatch.delenv("JARVIS_ALLOWED_USERS", raising=False)
    monkeypatch.delenv("SAMANTHA_KIOSK_ALLOWED_USERS", raising=False)
    monkeypatch.delenv("JARVIS_ALLOW_ALL_USERS", raising=False)
    monkeypatch.delenv("SAMANTHA_KIOSK_ALLOW_ALL_USERS", raising=False)

    ctx = _StubCtx()
    register(ctx)

    assert ctx.kwargs["allowed_users_env"] == "JARVIS_ALLOWED_USERS"
    assert ctx.kwargs["allow_all_env"] == "JARVIS_ALLOW_ALL_USERS"


# ── the wave's WORKING state, driven from the tool hooks ──────────────


def test_register_wires_both_tool_hooks():
    ctx = _StubCtx()

    register(ctx)

    assert set(ctx.hooks) == {"pre_tool_call", "post_tool_call"}


def test_two_tools_at_once_announce_once_and_clear_once(monkeypatch):
    """Not a hypothetical. One real turn dispatched `web_search` and
    `web_extract` ONE MILLISECOND apart (measured 2026-09-06), so a flag
    would switch the wave off when the first finished, with the second
    still running. The count is what makes the wave mean anything."""
    import Hermes.plugins.jarvis as plugin

    anuncios = []

    class _Adaptador:
        def push_working_threadsafe(self, on):
            anuncios.append(on)

    monkeypatch.setattr(plugin, "adaptadores_vivos", lambda: [_Adaptador()])
    ctx = _StubCtx()
    register(ctx)
    pre, post = ctx.hooks["pre_tool_call"], ctx.hooks["post_tool_call"]

    pre(tool_name="web_search")
    pre(tool_name="web_extract")
    assert anuncios == [True], "the second tool must not re-announce"

    post(tool_name="web_extract")
    assert anuncios == [True], "one tool finishing is not the turn finishing"

    post(tool_name="web_search")
    assert anuncios == [True, False]


def test_a_stray_post_cannot_drive_the_count_negative(monkeypatch):
    """A `post` with no `pre` behind it is reachable — `model_tools` has
    a `skip_pre_tool_call_hook` argument. Without the floor, the count
    would go to -1 and the next real tool would leave the wave still."""
    import Hermes.plugins.jarvis as plugin

    anuncios = []

    class _Adaptador:
        def push_working_threadsafe(self, on):
            anuncios.append(on)

    monkeypatch.setattr(plugin, "adaptadores_vivos", lambda: [_Adaptador()])
    ctx = _StubCtx()
    register(ctx)

    ctx.hooks["post_tool_call"](tool_name="huerfano")
    ctx.hooks["pre_tool_call"](tool_name="de verdad")

    assert anuncios == [True]


def test_an_adapter_that_raises_cannot_take_the_tool_call_with_it(monkeypatch):
    """These run INSIDE somebody's tool call. A hook that raised would
    surface as that tool failing, for a frame about a wave."""
    import Hermes.plugins.jarvis as plugin

    class _Roto:
        def push_working_threadsafe(self, on):
            raise RuntimeError("el socket se fue")

    monkeypatch.setattr(plugin, "adaptadores_vivos", lambda: [_Roto()])
    ctx = _StubCtx()
    register(ctx)

    ctx.hooks["pre_tool_call"](tool_name="lo que sea")
    ctx.hooks["post_tool_call"](tool_name="lo que sea")
