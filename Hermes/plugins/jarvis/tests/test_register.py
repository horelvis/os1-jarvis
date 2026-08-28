"""register() must land the authorization env vars under the NEW name.

Written after a review finding (2026-08-28): `_env()`'s legacy fallback for
`JARVIS_ALLOWED_USERS` / `JARVIS_ALLOW_ALL_USERS` never reaches
`authz_mixin.py`, which reads `os.environ[allowed_users_env]` /
`os.environ[allow_all_env]` by the literal new name through a bare
`os.getenv` of its own — it does not call `_env()`. So a box that still
carries `SAMANTHA_KIOSK_ALLOWED_USERS` and nothing under the new name went
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

    def register_platform(self, **kwargs):
        self.kwargs = kwargs


def test_legacy_allowed_users_lands_under_the_new_name(monkeypatch):
    monkeypatch.delenv("JARVIS_ALLOWED_USERS", raising=False)
    monkeypatch.setenv("SAMANTHA_KIOSK_ALLOWED_USERS", "custom_user")

    register(_StubCtx())

    assert os.environ["JARVIS_ALLOWED_USERS"] == "custom_user"


def test_with_neither_name_set_the_default_lands_under_the_new_name(monkeypatch):
    monkeypatch.delenv("JARVIS_ALLOWED_USERS", raising=False)
    monkeypatch.delenv("SAMANTHA_KIOSK_ALLOWED_USERS", raising=False)

    register(_StubCtx())

    assert os.environ["JARVIS_ALLOWED_USERS"] == "primary"


def test_the_new_name_set_explicitly_wins_over_the_legacy_one(monkeypatch):
    monkeypatch.setenv("JARVIS_ALLOWED_USERS", "explicit_user")
    monkeypatch.setenv("SAMANTHA_KIOSK_ALLOWED_USERS", "legacy_user")

    register(_StubCtx())

    assert os.environ["JARVIS_ALLOWED_USERS"] == "explicit_user"


def test_legacy_allow_all_lands_under_the_new_name(monkeypatch):
    monkeypatch.delenv("JARVIS_ALLOW_ALL_USERS", raising=False)
    monkeypatch.setenv("SAMANTHA_KIOSK_ALLOW_ALL_USERS", "true")

    register(_StubCtx())

    assert os.environ["JARVIS_ALLOW_ALL_USERS"] == "true"


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
