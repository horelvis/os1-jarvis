"""Who is allowed to open the phone socket.

Behind that socket is an agent holding the `terminal` toolset — CLAUDE.md
§12 (2026-08-26) says plainly "he can run ANY command on this box". Until
this feature the whole of the project's authentication was "only from
this machine"; these two checks are what replaces it.
"""

import json
import stat

import pytest

from jarvis_widget.personas import CASA
from jarvis_widget.remote_auth import (
    Guard,
    load_or_create_roster,
    load_or_create_secret,
)


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


def test_the_roster_is_made_once_and_reused(tmp_path):
    ruta = tmp_path / "personas.json"
    primero = load_or_create_roster(ruta)
    assert primero == {CASA: primero[CASA]}
    assert load_or_create_roster(ruta) == primero


def test_the_roster_file_is_not_world_readable(tmp_path):
    ruta = tmp_path / "personas.json"
    load_or_create_roster(ruta)
    assert oct(ruta.stat().st_mode)[-3:] == "600"


def test_the_roster_adopts_an_existing_single_secret(tmp_path, monkeypatch):
    """Three iPhones in this house are enrolled against the OLD single
    secret file today. A roster that ignores it and mints a fresh
    `casa` secret would silently lock all three out on the very upgrade
    that is supposed to be invisible to them, so the first roster ever
    written adopts whatever `remote.token` already holds instead of
    minting its own."""
    old = tmp_path / "remote.token"
    old.write_text("ya-enrolado-en-tres-iphones")
    monkeypatch.setenv("JARVIS_WIDGET_REMOTE_TOKEN", str(old))

    ruta = tmp_path / "personas.json"
    roster = load_or_create_roster(ruta)

    assert roster == {CASA: "ya-enrolado-en-tres-iphones"}


def test_a_secret_names_its_person(tmp_path):
    # Names ASCII, not "papá": `personas.normalizar` (task 2) is ASCII
    # only and would fold an accented id to `CASA`, which is a different
    # thing being tested (see `test_the_roster_re_normalises_names_on_read`).
    ruta = tmp_path / "personas.json"
    ruta.write_text(json.dumps({"papa": "aaa", "marta": "bbb"}))
    ruta.chmod(0o600)
    guard = Guard(load_or_create_roster(ruta), "https://brain.local:8443")
    assert guard.persona_for("bbb") == "marta"
    assert guard.persona_for("aaa") == "papa"


def test_an_unknown_secret_is_nobody_and_not_casa(tmp_path):
    # `casa` is where an UNATTRIBUTED turn goes. An unknown secret is a
    # failed authentication, which is a different thing: the socket is
    # refused, not downgraded.
    guard = Guard({"papa": "aaa"}, "https://brain.local:8443")
    assert guard.persona_for("zzz") is None
    assert guard.persona_for(None) is None
    assert guard.persona_for("") is None


def test_the_roster_re_normalises_names_on_read(tmp_path):
    """The file is edited by hand. An accented or otherwise invalid id
    does not survive `normalizar` and falls back to `CASA` rather than
    reaching a session key or a profile name unchecked."""
    ruta = tmp_path / "personas.json"
    ruta.write_text(json.dumps({"papá": "aaa"}))
    ruta.chmod(0o600)
    assert load_or_create_roster(ruta) == {CASA: "aaa"}


def test_token_ok_still_means_what_it_meant():
    guard = Guard({"papa": "aaa"}, "https://brain.local:8443")
    assert guard.token_ok("aaa")
    assert not guard.token_ok("zzz")


def test_token_comparison_is_constant_time() -> None:
    """A timing oracle on a 32-char secret over a LAN is not theoretical."""
    import inspect

    from jarvis_widget import remote_auth

    assert "compare_digest" in inspect.getsource(remote_auth.Guard.persona_for)


@pytest.mark.parametrize(
    "origin",
    [
        "https://brain.local:8443",
        "",  # non-browser clients send none; see the docstring
    ],
)
def test_allowed_origins(origin: str) -> None:
    guard = Guard({"casa": "s" * 32}, "https://brain.local:8443")

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
    guard = Guard({"casa": "s" * 32}, "https://brain.local:8443")

    assert guard.origin_ok(origin) is False


def test_both_ways_in_are_accepted() -> None:
    """mDNS is the nice path and it is not guaranteed on a house
    network, so the LAN address is the design's own fallback. A browser
    sends the origin it was loaded from and `origin_ok` compares whole,
    so a Guard bound to the name alone refused every connection the
    fallback ever made."""
    guard = Guard(
        {"casa": "s" * 32},
        "https://brain.local:8443",
        "https://192.168.100.58:8443",
    )

    assert guard.origin_ok("https://brain.local:8443") is True
    assert guard.origin_ok("https://192.168.100.58:8443") is True


def test_a_second_origin_widens_nothing_else() -> None:
    guard = Guard(
        {"casa": "s" * 32},
        "https://brain.local:8443",
        "https://192.168.100.58:8443",
    )

    assert guard.origin_ok("https://brain.local.evil.com:8443") is False
    assert guard.origin_ok("http://192.168.100.58:8443") is False
    assert guard.origin_ok("https://192.168.100.59:8443") is False
    assert guard.origin_ok("https://192.168.100.58:9999") is False
