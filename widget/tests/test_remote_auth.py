"""Who is allowed to open the phone socket.

Behind that socket is an agent holding the `terminal` toolset — CLAUDE.md
§12 (2026-08-26) says plainly "he can run ANY command on this box". Until
this feature the whole of the project's authentication was "only from
this machine"; these two checks are what replaces it.
"""

import io
import json
import os
import stat

import pytest
from loguru import logger

from jarvis_widget.personas import CASA
from jarvis_widget.remote_auth import (
    Guard,
    load_or_create_roster,
    load_or_create_secret,
    save_roster,
)


@pytest.fixture
def captured_logs():
    """Everything loguru writes during one test. Matches the fixture
    already used in `test_gateway.py` for the same reason: this project
    keeps paying for failures that were silent, so a fix that adds a log
    line is only proven by a test that reads it back."""
    sink = io.StringIO()
    handler = logger.add(sink, level="DEBUG")
    try:
        yield sink
    finally:
        logger.remove(handler)


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
    # Names ASCII, not "papá": an accented id is invalid and is DROPPED
    # on read rather than folded to anything — see
    # `test_an_invalid_key_is_dropped_not_folded`.
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


def test_an_invalid_key_is_dropped_not_folded(tmp_path):
    """The file is edited by hand. An id that only survives by FOLDING
    through `normalizar` (an accent, upper case) used to be kept under
    its folded name — which let a typo overwrite `casa`'s real secret,
    or a second, differently-cased spelling of the same name silently
    replace an earlier entry. Fix round 1: such an entry is dropped
    instead, and `casa` — reached only by the literal key `casa` — is
    never touched by one."""
    ruta = tmp_path / "personas.json"
    ruta.write_text(
        json.dumps(
            {"casa": "CASA-REAL", "papá": "INVALIDO", "MARTA": "M1", "marta": "M2"}
        )
    )
    ruta.chmod(0o600)
    assert load_or_create_roster(ruta) == {"casa": "CASA-REAL", "marta": "M2"}


def test_an_invalid_key_is_logged_by_name_not_by_secret(tmp_path, captured_logs):
    ruta = tmp_path / "personas.json"
    ruta.write_text(json.dumps({"papá": "un-secreto-que-no-debe-salir"}))
    ruta.chmod(0o600)

    load_or_create_roster(ruta)

    logged = captured_logs.getvalue()
    assert "papá" in logged
    assert "un-secreto-que-no-debe-salir" not in logged


def test_save_roster_refuses_a_key_that_is_not_already_canonical(tmp_path):
    """Reaching `save_roster` with an invalid key is a programming
    error — task 4 is what writes into this roster from an enrolment
    flow — so it raises rather than writing a file the read path would
    then have to sanitise again."""
    with pytest.raises(ValueError):
        save_roster({"MARTA": "m"}, tmp_path / "personas.json")


def test_an_empty_roster_file_still_gets_a_casa(tmp_path):
    """An interrupted write, or a file simply emptied by hand, used to
    lock every phone out and 500 the enrolment page — both in silence."""
    ruta = tmp_path / "personas.json"
    ruta.write_text("")
    ruta.chmod(0o600)

    roster = load_or_create_roster(ruta)

    assert CASA in roster
    assert load_or_create_roster(ruta) == roster  # persisted, reused


def test_a_roster_missing_casa_gets_one(tmp_path):
    ruta = tmp_path / "personas.json"
    ruta.write_text(json.dumps({"marta": "m"}))
    ruta.chmod(0o600)

    roster = load_or_create_roster(ruta)

    assert CASA in roster
    assert roster["marta"] == "m"
    assert load_or_create_roster(ruta) == roster  # persisted, not re-minted


def test_a_missing_casa_is_logged(tmp_path, captured_logs):
    ruta = tmp_path / "personas.json"
    ruta.write_text(json.dumps({"marta": "m"}))
    ruta.chmod(0o600)

    load_or_create_roster(ruta)

    assert "casa" in captured_logs.getvalue()


def test_invalid_json_does_not_raise_and_yields_a_usable_roster(tmp_path):
    ruta = tmp_path / "personas.json"
    ruta.write_text("{esto no es json en absoluto")
    ruta.chmod(0o600)

    roster = load_or_create_roster(ruta)

    assert CASA in roster
    # The broken file is left exactly as it was — an operator may want
    # to see it — never deleted or overwritten.
    assert ruta.read_text() == "{esto no es json en absoluto"


def test_a_top_level_array_does_not_raise_and_yields_a_usable_roster(tmp_path):
    ruta = tmp_path / "personas.json"
    ruta.write_text("[1, 2, 3]")
    ruta.chmod(0o600)

    roster = load_or_create_roster(ruta)

    assert CASA in roster
    assert ruta.read_text() == "[1, 2, 3]"


def test_non_utf8_bytes_do_not_raise_and_yield_a_usable_roster(tmp_path):
    """Corruption producing bytes that are not valid UTF-8 at all is at
    least as likely as corruption producing invalid JSON — and until
    fix round 2 only the JSON case was caught, so this one still raised
    `UnicodeDecodeError` out of `_boot`."""
    ruta = tmp_path / "personas.json"
    ruta.write_bytes(b"\xff\xfe\x00\xff not valid utf-8")
    ruta.chmod(0o600)

    roster = load_or_create_roster(ruta)

    assert CASA in roster
    assert ruta.read_bytes() == b"\xff\xfe\x00\xff not valid utf-8"


def test_an_unreadable_path_does_not_raise_and_yields_a_usable_roster(tmp_path):
    """A directory left at the path the roster expects a file is the
    portable way to provoke `OSError` — `chmod 000` proves nothing when
    the test runs as root, which it may."""
    ruta = tmp_path / "personas.json"
    ruta.mkdir()

    roster = load_or_create_roster(ruta)

    assert CASA in roster
    assert ruta.is_dir()  # left exactly as it was


def test_an_unreadable_file_is_logged_by_path_not_by_contents(tmp_path, captured_logs):
    ruta = tmp_path / "personas.json"
    ruta.write_text("un-secreto-que-no-debe-salir esto no es json")
    ruta.chmod(0o600)

    load_or_create_roster(ruta)

    logged = captured_logs.getvalue()
    assert str(ruta) in logged
    assert "un-secreto-que-no-debe-salir" not in logged


def test_save_roster_flushes_and_fsyncs(tmp_path, monkeypatch):
    """A power cut between the write and the flush is what used to
    leave the empty file that then reads back as a roster with no
    `casa` in it at all."""
    calls = []
    real_fsync = os.fsync

    def spy(fd):
        calls.append(fd)
        return real_fsync(fd)

    monkeypatch.setattr(os, "fsync", spy)

    save_roster({CASA: "x" * 32}, tmp_path / "personas.json")

    assert calls


def test_a_non_ascii_offered_token_is_nobody(tmp_path):
    """`compare_digest` raises on a non-ASCII `str`, and `offered`
    reaches `persona_for` straight off an unauthenticated query string
    — `?t=é` must be a refusal, not a 500."""
    guard = Guard({"casa": "s" * 32}, "https://brain.local:8443")
    assert guard.persona_for("é" * 32) is None


def test_a_non_ascii_roster_secret_does_not_break_everyone_else():
    """One corrupted, non-ASCII secret on the roster must not 500 every
    OTHER person's login: the comparison against it is skipped rather
    than raising out of the loop that still has to check them all."""
    guard = Guard({"papa": "café" * 8, "marta": "m" * 32}, "https://brain.local:8443")
    assert guard.persona_for("m" * 32) == "marta"


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
