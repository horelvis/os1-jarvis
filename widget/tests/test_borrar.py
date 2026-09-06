"""What a pairing destroys, and what it must not.

This suite is the thing that stands between a future "let's just clear
~/.jarvis" and 87 GB of re-downloaded model weights. Every tree here is
built under `tmp_path` — CLAUDE.md is explicit that no test in this
repo touches a real home directory, and `inventario`/`ejecutar` take
their roots as arguments precisely so that discipline is enforceable
rather than just asked for.
"""

import io
import os

import pytest
from loguru import logger

from jarvis_widget import borrar


@pytest.fixture
def captured_logs():
    """Same fixture as `test_casa.py` / `test_remote_auth.py`: a fix
    that logs something is only proven by a test that reads it back."""
    sink = io.StringIO()
    handler = logger.add(sink, level="DEBUG")
    try:
        yield sink
    finally:
        logger.remove(handler)


def _rutas(borrado: borrar.Borrado) -> set:
    return {n.ruta for n in borrado.nodos}


def _presentes(borrado: borrar.Borrado) -> set:
    return {n.ruta for n in borrado.nodos if n.presente}


# --- what goes, all of it ---------------------------------------------


def test_lists_every_fixed_path_in_the_goes_table(tmp_path):
    raiz_jarvis = tmp_path / "jarvis"
    raiz_hermes = tmp_path / "hermes"

    borrado = borrar.inventario(raiz_jarvis, raiz_hermes)

    rutas = _rutas(borrado)
    esperadas = {
        raiz_hermes / "state.db",
        raiz_hermes / "sessions",
        raiz_hermes / "profiles",
        raiz_jarvis / "memory",
        raiz_jarvis / "teacher",
        raiz_jarvis / "personas.json",
        raiz_jarvis / "remote.token",
        raiz_jarvis / "certs",
        raiz_jarvis / "ref-candidates",
        raiz_jarvis / "casa.json",
        raiz_jarvis / "voces",
        # Not in the brief's table, added per the task instructions:
        # task 4's recorded household voices.
        raiz_jarvis / "medicion",
    }
    assert esperadas <= rutas


def test_a_path_that_does_not_exist_is_reported_absent_not_raised(tmp_path):
    raiz_jarvis = tmp_path / "jarvis"
    raiz_hermes = tmp_path / "hermes"
    # Neither root exists at all yet.

    borrado = borrar.inventario(raiz_jarvis, raiz_hermes)

    nodo_state_db = next(n for n in borrado.nodos if n.ruta == raiz_hermes / "state.db")
    assert nodo_state_db.presente is False
    assert _presentes(borrado) == set()


def test_present_paths_are_marked_present(tmp_path):
    raiz_jarvis = tmp_path / "jarvis"
    raiz_hermes = tmp_path / "hermes"
    raiz_jarvis.mkdir()
    raiz_hermes.mkdir()
    (raiz_hermes / "state.db").write_bytes(b"sessions go here")
    (raiz_jarvis / "personas.json").write_text("{}")

    borrado = borrar.inventario(raiz_jarvis, raiz_hermes)

    assert raiz_hermes / "state.db" in _presentes(borrado)
    assert raiz_jarvis / "personas.json" in _presentes(borrado)
    # Untouched paths in the same roots stay absent.
    assert raiz_jarvis / "teacher" not in _presentes(borrado)


def test_memories_glob_lists_each_md_file_found(tmp_path):
    raiz_jarvis = tmp_path / "jarvis"
    raiz_hermes = tmp_path / "hermes"
    memorias = raiz_hermes / "home" / "memories"
    memorias.mkdir(parents=True)
    (memorias / "marta.md").write_text("lo que sabe de ella")
    (memorias / "casa.md").write_text("lo que sabe de la casa")
    (memorias / "no-es-markdown.txt").write_text("ignorar")

    borrado = borrar.inventario(raiz_jarvis, raiz_hermes)

    presentes = _presentes(borrado)
    assert memorias / "marta.md" in presentes
    assert memorias / "casa.md" in presentes
    assert memorias / "no-es-markdown.txt" not in presentes


def test_memories_directory_missing_is_absent_not_raised(tmp_path):
    raiz_jarvis = tmp_path / "jarvis"
    raiz_hermes = tmp_path / "hermes"

    borrado = borrar.inventario(raiz_jarvis, raiz_hermes)

    memorias_nodo = next(
        n for n in borrado.nodos if n.ruta == raiz_hermes / "home" / "memories"
    )
    assert memorias_nodo.presente is False


def test_dump_glob_lists_every_dump_directory(tmp_path):
    raiz_jarvis = tmp_path / "jarvis"
    raiz_hermes = tmp_path / "hermes"
    raiz_jarvis.mkdir()
    (raiz_jarvis / "dump").mkdir()
    (raiz_jarvis / "dump-endpoint").mkdir()
    (raiz_jarvis / "dump-movil").mkdir()
    # A file that merely starts with "dump" is not a dump directory.
    (raiz_jarvis / "dump-report.txt").write_text("no borrar por nombre solo")

    borrado = borrar.inventario(raiz_jarvis, raiz_hermes)

    presentes = _presentes(borrado)
    assert raiz_jarvis / "dump" in presentes
    assert raiz_jarvis / "dump-endpoint" in presentes
    assert raiz_jarvis / "dump-movil" in presentes
    assert raiz_jarvis / "dump-report.txt" not in presentes


# --- what must never appear, asserted by name --------------------------


def test_inventario_never_returns_a_path_under_a_protected_directory(tmp_path):
    """The test that matters: a later 'let's just clear ~/.jarvis' must
    not be able to pass this, so the protected names are checked by
    exact string, not by some looser heuristic that a rename could slip
    past."""
    raiz_jarvis = tmp_path / "jarvis"
    raiz_hermes = tmp_path / "hermes"
    raiz_jarvis.mkdir()
    protegidos = ("models", "cosyvoice3", "qwen3-tts", "xtts-cache", "voices")
    for nombre in protegidos:
        destino = raiz_jarvis / nombre
        destino.mkdir()
        (destino / "no-es-tuyo.bin").write_bytes(b"0" * 1024)

    borrado = borrar.inventario(raiz_jarvis, raiz_hermes)

    for nodo in borrado.nodos:
        primer_paso = nodo.ruta.relative_to(
            raiz_jarvis if _bajo(nodo.ruta, raiz_jarvis) else raiz_hermes
        ).parts[:1]
        assert not (primer_paso and primer_paso[0] in protegidos), (
            f"{nodo.ruta} está bajo un directorio protegido"
        )


def _bajo(ruta, raiz) -> bool:
    try:
        ruta.relative_to(raiz)
        return True
    except ValueError:
        return False


def test_voces_and_voices_are_not_confused():
    """One letter apart, and opposite fates: `voces/` (the voiceprints
    this plan creates) goes; `voices/` (136 MB of TTS reference audio)
    stays. A future reader 'tidying' one into the other is exactly the
    accident this test exists to catch."""
    assert "voces" != "voices"
    assert "voces" not in borrar._PROTEGIDOS_JARVIS
    assert "voices" in borrar._PROTEGIDOS_JARVIS


def test_comprobar_seguro_fires_if_the_fixed_list_ever_grows_a_protected_name(
    tmp_path, monkeypatch
):
    """`_comprobar_seguro` is the line that stops a future edit to
    `_JARVIS_FIJOS` from wiping 87 GB of model weights. The 17 tests
    around it prove it does not fire under today's constants — the easy
    half. This proves it DOES fire when it must, by making the mistake
    on purpose."""
    monkeypatch.setattr(borrar, "_JARVIS_FIJOS", (*borrar._JARVIS_FIJOS, "models"))
    raiz_jarvis = tmp_path / "jarvis"
    raiz_hermes = tmp_path / "hermes"

    with pytest.raises(RuntimeError):
        borrar.inventario(raiz_jarvis, raiz_hermes)


def test_comprobar_seguro_fires_if_the_dump_glob_ever_matches_a_protected_name(
    tmp_path, monkeypatch
):
    """A careless glob is the likelier way this actually breaks — not a
    typo in the fixed list, but a wildcard someone widens without
    noticing what else it now matches."""
    raiz_jarvis = tmp_path / "jarvis"
    raiz_hermes = tmp_path / "hermes"
    raiz_jarvis.mkdir()
    (raiz_jarvis / "voices").mkdir()
    monkeypatch.setattr(borrar, "_JARVIS_DUMP_GLOB", "vo*")

    with pytest.raises(RuntimeError):
        borrar.inventario(raiz_jarvis, raiz_hermes)


# --- ejecutar: the snapshot comes first ---------------------------------


def test_ejecutar_writes_the_snapshot_before_removing_anything(tmp_path):
    raiz_jarvis = tmp_path / "jarvis"
    raiz_hermes = tmp_path / "hermes"
    raiz_jarvis.mkdir()
    raiz_hermes.mkdir()
    (raiz_jarvis / "personas.json").write_text('{"casa": "secreto"}')
    (raiz_hermes / "state.db").write_bytes(b"una sesion")

    borrado = borrar.inventario(raiz_jarvis, raiz_hermes)
    respaldo = tmp_path / "respaldo"

    resultado = borrar.ejecutar(borrado, respaldo=respaldo)

    assert resultado.completo
    assert resultado.fallidos == ()
    assert not (raiz_jarvis / "personas.json").exists()
    assert not (raiz_hermes / "state.db").exists()
    copia = respaldo / "jarvis" / "personas.json"
    assert copia.read_text() == '{"casa": "secreto"}'
    copia_hermes = respaldo / "hermes" / "state.db"
    assert copia_hermes.read_bytes() == b"una sesion"


def test_ejecutar_refuses_to_delete_if_the_snapshot_directory_cannot_be_made(
    tmp_path, captured_logs
):
    raiz_jarvis = tmp_path / "jarvis"
    raiz_hermes = tmp_path / "hermes"
    raiz_jarvis.mkdir()
    raiz_hermes.mkdir()
    objetivo = raiz_jarvis / "personas.json"
    objetivo.write_text("no debe borrarse")

    borrado = borrar.inventario(raiz_jarvis, raiz_hermes)

    # `respaldo`'s PARENT is a file, so mkdir(parents=True) on the
    # snapshot path must fail with ENOTDIR.
    bloqueador = tmp_path / "bloqueador"
    bloqueador.write_text("soy un archivo, no un directorio")
    respaldo_imposible = bloqueador / "respaldo"

    resultado = borrar.ejecutar(borrado, respaldo=respaldo_imposible)

    assert not resultado.completo
    assert objetivo in resultado.fallidos
    assert objetivo.exists()
    assert objetivo.read_text() == "no debe borrarse"
    assert "respaldo" in captured_logs.getvalue().casefold()


def test_ejecutar_refuses_when_respaldo_is_inside_something_being_erased(
    tmp_path, captured_logs
):
    raiz_jarvis = tmp_path / "jarvis"
    raiz_hermes = tmp_path / "hermes"
    raiz_jarvis.mkdir()
    raiz_hermes.mkdir()
    (raiz_jarvis / "memory").mkdir()
    (raiz_jarvis / "memory" / "algo.json").write_text("recuerdo")

    borrado = borrar.inventario(raiz_jarvis, raiz_hermes)
    respaldo = raiz_jarvis / "memory" / "respaldo"

    resultado = borrar.ejecutar(borrado, respaldo=respaldo)

    # Nothing was removed: the backup destination was inside the tree
    # being erased, which would have destroyed the snapshot along with
    # the original.
    assert (raiz_jarvis / "memory" / "algo.json").exists()
    assert not resultado.completo
    assert raiz_jarvis / "memory" in resultado.fallidos


def test_a_second_ejecutar_on_an_already_clean_box_is_a_no_op(tmp_path):
    raiz_jarvis = tmp_path / "jarvis"
    raiz_hermes = tmp_path / "hermes"
    raiz_jarvis.mkdir()
    raiz_hermes.mkdir()
    (raiz_jarvis / "personas.json").write_text("{}")

    respaldo = tmp_path / "respaldo"
    primera = borrar.inventario(raiz_jarvis, raiz_hermes)
    resultado_1 = borrar.ejecutar(primera, respaldo=respaldo)
    assert resultado_1.completo

    # The box is now clean. A second inventory finds nothing present.
    segunda = borrar.inventario(raiz_jarvis, raiz_hermes)
    assert _presentes(segunda) == set()

    # And running it again must not raise, and must not touch what
    # stays.
    (raiz_jarvis / "models").mkdir()
    (raiz_jarvis / "models" / "peso.bin").write_bytes(b"87GB, en teoria")

    resultado_2 = borrar.ejecutar(segunda, respaldo=respaldo)

    assert resultado_2.completo
    assert (raiz_jarvis / "models" / "peso.bin").exists()


def test_ejecutar_never_touches_what_stays(tmp_path):
    raiz_jarvis = tmp_path / "jarvis"
    raiz_hermes = tmp_path / "hermes"
    raiz_jarvis.mkdir()
    raiz_hermes.mkdir()
    for nombre in ("models", "cosyvoice3", "qwen3-tts", "xtts-cache", "voices"):
        destino = raiz_jarvis / nombre
        destino.mkdir()
        (destino / "peso.bin").write_bytes(b"no tocar")
    (raiz_jarvis / "personas.json").write_text("{}")

    borrado = borrar.inventario(raiz_jarvis, raiz_hermes)
    resultado = borrar.ejecutar(borrado, respaldo=tmp_path / "respaldo")

    assert resultado.completo
    for nombre in ("models", "cosyvoice3", "qwen3-tts", "xtts-cache", "voices"):
        assert (raiz_jarvis / nombre / "peso.bin").exists()
    assert not (raiz_jarvis / "personas.json").exists()


# --- edges: symlinks -----------------------------------------------------


def test_a_goes_symlink_into_stays_removes_only_the_link(tmp_path):
    raiz_jarvis = tmp_path / "jarvis"
    raiz_hermes = tmp_path / "hermes"
    raiz_jarvis.mkdir()
    raiz_hermes.mkdir()
    modelos = raiz_jarvis / "models"
    modelos.mkdir()
    (modelos / "peso.bin").write_bytes(b"87GB, en teoria")
    # `certs/` is a "goes" entry. Here it is, unusually, a symlink that
    # happens to point INTO the protected `models/` tree.
    (raiz_jarvis / "certs").symlink_to(modelos, target_is_directory=True)

    borrado = borrar.inventario(raiz_jarvis, raiz_hermes)
    resultado = borrar.ejecutar(borrado, respaldo=tmp_path / "respaldo")

    assert resultado.completo
    assert not (raiz_jarvis / "certs").exists()
    assert not (raiz_jarvis / "certs").is_symlink()
    # The target survives untouched.
    assert (modelos / "peso.bin").exists()


def test_a_goes_symlink_into_stays_is_relinked_not_copied_in_the_snapshot(tmp_path):
    """The regression this guards against: following a 'goes' symlink to
    copy its CONTENT into the backup would duplicate whatever is on the
    other end — here a stand-in for 69 GB of `models/` — straight into
    the snapshot. The snapshot must recreate the LINK instead."""
    raiz_jarvis = tmp_path / "jarvis"
    raiz_hermes = tmp_path / "hermes"
    raiz_jarvis.mkdir()
    raiz_hermes.mkdir()
    modelos = raiz_jarvis / "models"
    modelos.mkdir()
    (modelos / "peso.bin").write_bytes(b"87GB, en teoria")
    (raiz_jarvis / "certs").symlink_to(modelos, target_is_directory=True)

    borrado = borrar.inventario(raiz_jarvis, raiz_hermes)
    respaldo = tmp_path / "respaldo"
    borrar.ejecutar(borrado, respaldo=respaldo)

    copia = respaldo / "jarvis" / "certs"
    assert copia.is_symlink()
    assert os.readlink(copia) == str(modelos)
    # No duplicate of `peso.bin` was made inside the snapshot itself —
    # only the link was recreated, resolving back to the untouched
    # original.
    assert (copia / "peso.bin").read_bytes() == b"87GB, en teoria"


def test_a_broken_symlink_in_goes_is_removed_without_raising(tmp_path):
    raiz_jarvis = tmp_path / "jarvis"
    raiz_hermes = tmp_path / "hermes"
    raiz_jarvis.mkdir()
    raiz_hermes.mkdir()
    (raiz_jarvis / "remote.token").symlink_to(raiz_jarvis / "no-existe")

    borrado = borrar.inventario(raiz_jarvis, raiz_hermes)
    # Reported present even though the target does not exist: the link
    # itself is a node on disk.
    nodo = next(n for n in borrado.nodos if n.ruta == raiz_jarvis / "remote.token")
    assert nodo.presente is True

    resultado = borrar.ejecutar(borrado, respaldo=tmp_path / "respaldo")

    assert resultado.completo
    assert not (raiz_jarvis / "remote.token").is_symlink()


# --- a directory that is not writable -------------------------------------


def test_ejecutar_reports_a_node_that_could_not_be_removed_while_still_removing_the_rest(
    tmp_path, captured_logs
):
    """The test the fix-round review asked for: one node undeletable
    must not stop the rest, and the failure must be visible to the
    caller through the return value — not only a log line nobody on a
    voice-driven surface will ever read."""
    raiz_jarvis = tmp_path / "jarvis"
    raiz_hermes = tmp_path / "hermes"
    raiz_jarvis.mkdir()
    raiz_hermes.mkdir()
    intocable = raiz_jarvis / "teacher"
    intocable.mkdir()
    (intocable / "curso.json").write_text("{}")
    # A sibling of `teacher`, present at the same time, that CAN be
    # removed — this is what proves the failure is per-node rather than
    # aborting the whole run.
    (raiz_jarvis / "personas.json").write_text("{}")

    modo_original = os.stat(intocable).st_mode
    canario = intocable / "canario"
    canario.write_text("")
    try:
        # Blocking write on `teacher` ITSELF — not its parent — is what
        # isolates the failure to this one node: removing a CHILD of
        # `teacher` (`curso.json`, during `shutil.rmtree`) needs write on
        # `teacher`, while removing `personas.json` — a SIBLING of
        # `teacher` — needs write only on their shared parent
        # (`raiz_jarvis`), which stays untouched. Proved directly with a
        # throwaway file inside `teacher`, rather than guessed from
        # `os.access`.
        os.chmod(intocable, 0o500)
        try:
            canario.unlink()
            pytest.skip("this environment does not enforce permission bits on removal")
        except PermissionError:
            pass

        borrado = borrar.inventario(raiz_jarvis, raiz_hermes)
        resultado = borrar.ejecutar(borrado, respaldo=tmp_path / "respaldo")
    finally:
        os.chmod(intocable, modo_original)

    # The blocked node survives, named in `fallidos` — the caller can
    # say "no he podido borrarlo todo" instead of assuming success from
    # a bare `None`.
    assert not resultado.completo
    assert resultado.fallidos == (intocable,)
    assert intocable.exists()

    # Everything else still went: best-effort per node, not
    # all-or-nothing, is the point of continuing past one failure.
    assert not (raiz_jarvis / "personas.json").exists()
    assert captured_logs.getvalue() != ""
