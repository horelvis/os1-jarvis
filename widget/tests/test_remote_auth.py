"""Who is allowed to open the phone socket.

Behind that socket is an agent holding the `terminal` toolset — CLAUDE.md
§12 (2026-08-26) says plainly "he can run ANY command on this box". Until
this feature the whole of the project's authentication was "only from
this machine"; these two checks are what replaces it.
"""

import stat

import pytest

from samantha_widget.remote_auth import Guard, load_or_create_secret


def test_a_secret_is_created_once_and_reused(tmp_path) -> None:
    path = tmp_path / "remote.token"

    first = load_or_create_secret(path)
    second = load_or_create_secret(path)

    assert first == second
    assert len(first) >= 32


def test_the_secret_file_is_not_readable_by_others(tmp_path) -> None:
    """It is the only thing standing between the wifi and a shell."""
    path = tmp_path / "remote.token"
    load_or_create_secret(path)

    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_the_right_token_passes_and_a_wrong_one_does_not() -> None:
    guard = Guard(secret="s" * 32, origin="https://brain.local:8443")

    assert guard.token_ok("s" * 32) is True
    assert guard.token_ok("x" * 32) is False
    assert guard.token_ok("") is False
    assert guard.token_ok(None) is False


def test_token_comparison_is_constant_time() -> None:
    """A timing oracle on a 32-char secret over a LAN is not theoretical."""
    import inspect

    from samantha_widget import remote_auth

    assert "compare_digest" in inspect.getsource(remote_auth.Guard.token_ok)


@pytest.mark.parametrize(
    "origin",
    [
        "https://brain.local:8443",
        "",  # non-browser clients send none; see the docstring
    ],
)
def test_allowed_origins(origin: str) -> None:
    guard = Guard(secret="s" * 32, origin="https://brain.local:8443")

    assert guard.origin_ok(origin) is True


@pytest.mark.parametrize(
    "origin",
    [
        "https://evil.example",
        "http://brain.local:8443",  # scheme matters
        "https://brain.local:9999",  # port matters
        "https://brain.local.evil.com",  # suffix attack
        "null",
    ],
)
def test_refused_origins(origin: str) -> None:
    guard = Guard(secret="s" * 32, origin="https://brain.local:8443")

    assert guard.origin_ok(origin) is False
