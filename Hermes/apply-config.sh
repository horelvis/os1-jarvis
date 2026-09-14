#!/usr/bin/env bash
#
# Merge jarvis-config.yaml into the repo's Hermes config.
#
# `.hermes/home/config.yaml` cannot be committed — it sits beside
# auth.json, state.db and the session store. So the settings JARVIS
# needs live in jarvis-config.yaml, and this puts them in place on a
# machine that does not have them yet.
#
# It merges into BOTH the home config and every profile config under
# `.hermes/home/profiles/*/config.yaml`. With `multiplex_profiles` on,
# a profile reads its OWN config.yaml for `model`/`providers`, and until
# 2026-09-13 that second file was never kept in sync: the model name
# drifted there (qwen3.8-27b against gemma-4-26b-a4b-it in the home
# config) and JARVIS kept identifying itself as the model that no longer
# ran. A profile is one more place the same truth must hold.
#
# Deep merge, not overwrite: anything Hermes itself wrote (onboarding
# flags, _config_version, the `platforms` block, whatever a future
# version adds) is left alone — it is not in jarvis-config.yaml, so the
# merge never touches it.
#
# Idempotent — run it as often as you like. It backs up first.
#
#   Hermes/apply-config.sh          apply
#   Hermes/apply-config.sh --check  report differences, change nothing
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE="$REPO_ROOT/Hermes/jarvis-config.yaml"
HERMES_HOME_DIR="${HERMES_HOME:-$REPO_ROOT/.hermes/home}"
PYTHON="$REPO_ROOT/.hermes/src/.venv/bin/python"

[ -f "$SOURCE" ] || { echo "No existe $SOURCE" >&2; exit 1; }
[ -x "$PYTHON" ] || { echo "No hay runtime de Hermes en $PYTHON — Hermes/setup-runtime.sh primero" >&2; exit 1; }

MODE="apply"
[ "${1:-}" = "--check" ] && MODE="check"

SOURCE="$SOURCE" HERMES_HOME="$HERMES_HOME_DIR" MODE="$MODE" "$PYTHON" - <<'PY'
import os
import shutil
import sys
from pathlib import Path

import yaml

source = Path(os.environ["SOURCE"])
home = Path(os.environ["HERMES_HOME"])
check_only = os.environ["MODE"] == "check"

wanted = yaml.safe_load(source.read_text()) or {}

# The home config, then every profile config Hermes has created. Profiles
# are discovered, not named: a family member enrolled later gets their own
# config.yaml and it must inherit the same model/TTS/compression truth.
targets = [home / "config.yaml"]
profiles = home / "profiles"
if profiles.is_dir():
    targets += sorted(profiles.glob("*/config.yaml"))


def merge(want, have, changes, path=""):
    """Deep merge `want` into `have`, recording what actually changes.

    Lists are replaced wholesale rather than concatenated: these are
    allow-lists and toolsets, where appending would silently keep
    something a later edit meant to remove.
    """
    for key, value in want.items():
        here = f"{path}.{key}" if path else key
        if isinstance(value, dict):
            child = have.get(key)
            if not isinstance(child, dict):
                child = {}
            merge(value, child, changes, here)
            have[key] = child
        elif have.get(key) != value:
            changes.append(f"  {here}: {have.get(key)!r} -> {value!r}")
            have[key] = value
    return have


exit_code = 0
for target in targets:
    current = yaml.safe_load(target.read_text()) if target.is_file() else {}
    changes: list[str] = []
    merged = merge(wanted, dict(current or {}), changes)

    if not changes:
        print(f"Nada que cambiar — {target} ya está al día.")
        continue

    print(("Faltan estos ajustes en " if check_only else "Aplicando en ") + str(target) + ":")
    print("\n".join(changes))

    if check_only:
        exit_code = 1
        continue

    if target.is_file():
        backup = target.with_suffix(".yaml.bak")
        shutil.copy2(target, backup)
        print(f"\nCopia previa en {backup}")

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(yaml.safe_dump(merged, sort_keys=False, allow_unicode=True))
    print(f"Escrito {target}")

if not check_only:
    print("\nReinicia el gateway para que surta efecto:")
    print("  systemctl --user restart jarvis-hermes.service")

sys.exit(exit_code)
PY
