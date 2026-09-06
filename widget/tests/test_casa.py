"""Whose house this is, on disk.

`casa.json` holds names and the one `amo` flag; every voiceprint is its
own `.npy` under a sibling `voces/` directory — see the module docstring
in `jarvis_widget/casa.py` for why the two stay apart. This suite
follows `test_remote_auth.py`'s shape on purpose: that module argued,
one fix round at a time, for every one of the corruption cases repeated
here, and there is no reason to relearn them.
"""

import io
import os
import stat
import threading

import numpy as np
import pytest
from loguru import logger

from jarvis_widget import casa


def _v(*xs: float) -> np.ndarray:
    return np.array(xs, dtype=np.float32)


@pytest.fixture
def captured_logs():
    """Everything loguru writes during one test — same fixture as
    `test_remote_auth.py`, for the same reason: a fix that adds a log
    line is only proven by a test that reads it back."""
    sink = io.StringIO()
    handler = logger.add(sink, level="DEBUG")
    try:
        yield sink
    finally:
        logger.remove(handler)


# --- a missing register --------------------------------------------------


def test_a_missing_register_has_no_amo_and_no_people(tmp_path):
    registro = casa.Registro(tmp_path / "casa.json")

    assert registro.amo is None
    assert registro.personas() == []
    assert len(registro.huellas()) == 0


# --- pairing ---------------------------------------------------------------


def test_pairing_writes_an_amo_that_survives_a_reload(tmp_path):
    ruta = tmp_path / "casa.json"
    casa.Registro(ruta).emparejar("Marta", [_v(1, 0, 0)])

    reabierto = casa.Registro(ruta)

    assert reabierto.amo == "marta"


def test_pairing_registers_the_person_with_the_display_name_kept_as_given(tmp_path):
    """The id folds through `normalizar`; the name he says out loud does
    not — 'Lucía' keeps its accent, stored beside the id, never as it."""
    registro = casa.Registro(tmp_path / "casa.json")

    persona = registro.emparejar("Marta", [_v(1, 0, 0)])

    assert persona.id == "marta"
    assert persona.nombre == "Marta"
    assert persona.amo is True
    assert [p.id for p in registro.personas()] == ["marta"]
    assert registro.personas()[0].nombre == "Marta"


def test_a_second_pairing_when_an_amo_exists_raises(tmp_path):
    """The founding act happens once. If it could be repeated, anything
    that reaches this code twice takes the house — this is a security
    property, not an ergonomic one."""
    registro = casa.Registro(tmp_path / "casa.json")
    registro.emparejar("Marta", [_v(1, 0, 0)])

    with pytest.raises(ValueError):
        registro.emparejar("Lucia", [_v(0, 1, 0)])

    # And the first amo is exactly as it was — not replaced, not joined.
    assert registro.amo == "marta"
    assert [p.id for p in registro.personas()] == ["marta"]


def test_a_name_that_survives_to_nothing_is_refused(tmp_path):
    registro = casa.Registro(tmp_path / "casa.json")

    with pytest.raises(ValueError):
        registro.emparejar("!!!", [_v(1, 0, 0)])

    # Refused outright, not silently filed under the reserved id.
    assert registro.amo is None
    assert registro.personas() == []


def test_an_accented_name_pairs_with_an_ascii_id_and_keeps_its_accent(tmp_path):
    """Corrected: this used to assert the opposite — that an accented
    name was refused exactly like '!!!' is. It was wrong, and not a
    small wrong: 'lucía', 'martín' and 'josé' cover most of the names in
    this house, and the amo himself could easily be one of them, which
    would have meant the owner of the machine could not give his own
    name at the founding act. `emparejar` now derives the id through
    `personas.id_desde_nombre`, which strips diacritics before handing
    the result to `normalizar` — so the id folds to plain ASCII while
    `Persona.nombre` keeps the accent exactly as spoken."""
    registro = casa.Registro(tmp_path / "casa.json")

    persona = registro.emparejar("Lucía", [_v(1, 0, 0)])

    assert persona.id == "lucia"
    assert persona.nombre == "Lucía"
    assert registro.amo == "lucia"


def test_pairing_as_the_reserved_name_casa_is_refused(tmp_path):
    registro = casa.Registro(tmp_path / "casa.json")

    with pytest.raises(ValueError):
        registro.emparejar("casa", [_v(1, 0, 0)])

    assert registro.amo is None


def test_pairing_with_no_samples_at_all_is_refused(tmp_path):
    """An amo whose voiceprint is founded on nothing would never clear
    any floor `voz.Huellas.quien` sets, which is a broken amo, not an
    empty one — refusing it here is cheaper than debugging it later."""
    registro = casa.Registro(tmp_path / "casa.json")

    with pytest.raises(ValueError):
        registro.emparejar("Marta", [])


# --- permissions -------------------------------------------------------


def test_the_register_file_is_not_world_readable(tmp_path):
    ruta = tmp_path / "casa.json"
    casa.Registro(ruta).emparejar("Marta", [_v(1, 0, 0)])

    assert stat.S_IMODE(ruta.stat().st_mode) == 0o600


# --- corruption: never raises, never hangs, and the file is left alone ---


def test_invalid_json_yields_an_empty_register(tmp_path):
    ruta = tmp_path / "casa.json"
    ruta.write_text("{esto no es json en absoluto")

    registro = casa.Registro(ruta)

    assert registro.amo is None
    assert registro.personas() == []
    assert ruta.read_text() == "{esto no es json en absoluto"  # left untouched


def test_a_top_level_array_yields_an_empty_register(tmp_path):
    ruta = tmp_path / "casa.json"
    ruta.write_text("[1, 2, 3]")

    registro = casa.Registro(ruta)

    assert registro.amo is None
    assert registro.personas() == []


def test_non_utf8_bytes_yield_an_empty_register(tmp_path):
    ruta = tmp_path / "casa.json"
    ruta.write_bytes(b"\xff\xfe\x00\xff not valid utf-8")

    registro = casa.Registro(ruta)

    assert registro.amo is None
    assert ruta.read_bytes() == b"\xff\xfe\x00\xff not valid utf-8"


def test_a_directory_at_the_path_yields_an_empty_register(tmp_path):
    """A directory left where the register expects a file is the
    portable way to provoke `OSError` on open — `chmod 000` proves
    nothing when the test runs as root, which it may."""
    ruta = tmp_path / "casa.json"
    ruta.mkdir()

    registro = casa.Registro(ruta)

    assert registro.amo is None
    assert registro.personas() == []
    assert ruta.is_dir()  # left exactly as it was


def test_a_dangling_symlink_yields_an_empty_register(tmp_path):
    ruta = tmp_path / "casa.json"
    ruta.symlink_to(tmp_path / "no-existe-nada-aqui")

    registro = casa.Registro(ruta)

    assert registro.amo is None
    assert registro.personas() == []


def test_a_fifo_at_the_path_does_not_hang(tmp_path):
    """A FIFO does not raise when opened for reading with nobody on the
    write end — it simply blocks forever. Run off the main thread with
    a real deadline, daemon so a regression fails THIS test rather than
    freezing the whole suite."""
    if not hasattr(os, "mkfifo"):
        pytest.skip("no FIFOs on this platform")
    ruta = tmp_path / "casa.json"
    os.mkfifo(ruta)

    resultado: list[object] = []
    hilo = threading.Thread(
        target=lambda: resultado.append(casa.Registro(ruta).amo),
        daemon=True,
    )
    hilo.start()
    hilo.join(timeout=5)

    assert not hilo.is_alive(), "Registro.amo hung reading a FIFO"
    assert resultado == [None]


def test_an_unreadable_register_is_logged_by_path_not_by_contents(
    tmp_path, captured_logs
):
    ruta = tmp_path / "casa.json"
    ruta.write_text("un-nombre-que-no-debe-salir esto no es json")

    casa.Registro(ruta).amo

    logged = captured_logs.getvalue()
    assert str(ruta) in logged
    assert "un-nombre-que-no-debe-salir" not in logged


# --- recordar ----------------------------------------------------------


def test_recordar_adds_a_vector_and_the_centroid_moves(tmp_path):
    registro = casa.Registro(tmp_path / "casa.json")
    registro.emparejar("Marta", [_v(1, 0, 0)])
    antes = registro.huellas()

    registro.recordar("marta", _v(0, 1, 0))

    despues = registro.huellas()
    assert not np.array_equal(_centroide(antes, "marta"), _centroide(despues, "marta"))


def test_recordar_persists_across_a_reload(tmp_path):
    ruta = tmp_path / "casa.json"
    casa.Registro(ruta).emparejar("Marta", [_v(1, 0, 0)])

    casa.Registro(ruta).recordar("marta", _v(1, 0, 0))
    casa.Registro(ruta).recordar("marta", _v(1, 0, 0))

    # Three identical samples on file: the centroid is still that same
    # direction, and `quien` recognises it clearly.
    huellas = casa.Registro(ruta).huellas()
    assert huellas.quien(_v(1, 0, 0), piso=0.5) == "marta"


def test_recordar_for_an_unknown_person_is_a_no_op(tmp_path, captured_logs):
    registro = casa.Registro(tmp_path / "casa.json")
    registro.emparejar("Marta", [_v(1, 0, 0)])

    registro.recordar("nadie-registrado", _v(0, 0, 1))

    assert [p.id for p in registro.personas()] == ["marta"]
    assert "nadie-registrado" in captured_logs.getvalue()


def _centroide(huellas: casa.Huellas, quien: str) -> np.ndarray:
    """The private centroid a `Huellas` holds, reached only because this
    suite needs to compare two snapshots of it — `voz.Huellas` exposes
    no getter of its own, deliberately, since nothing else needs one."""
    return huellas._centroides[quien]


# --- huellas() reflects what emparejar/recordar wrote -------------------


def test_huellas_recognises_a_paired_person(tmp_path):
    registro = casa.Registro(tmp_path / "casa.json")
    registro.emparejar("Marta", [_v(1, 0, 0), _v(1, 0, 0)])

    assert registro.huellas().quien(_v(1, 0, 0), piso=0.5) == "marta"
