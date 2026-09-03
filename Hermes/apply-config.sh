#!/usr/bin/env bash
#
# Merge samantha-config.yaml into the repo's Hermes config.
#
# `.hermes/home/config.yaml` cannot be committed — it sits beside
# auth.json, state.db and the session store. So the settings Samantha
# needs live in samantha-config.yaml, and this puts them in place on a
# machine that does not have them yet.
#
# Deep merge, not overwrite: anything Hermes itself wrote (onboarding
# flags, _config_version, whatever a future version adds) is left alone.
# Idempotent — run it as often as you like. It backs up first.
#
#   Hermes/apply-config.sh          apply
#   Hermes/apply-config.sh --check  report differences, change nothing
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE="$REPO_ROOT/Hermes/samantha-config.yaml"
TARGET="${HERMES_HOME:-$REPO_ROOT/.hermes/home}/config.yaml"
PYTHON="$REPO_ROOT/.hermes/src/.venv/bin/python"

[ -f "$SOURCE" ] || { echo "No existe $SOURCE" >&2; exit 1; }
[ -x "$PYTHON" ] || { echo "No hay runtime de Hermes en $PYTHON — Hermes/setup-runtime.sh primero" >&2; exit 1; }

MODE="apply"
[ "${1:-}" = "--check" ] && MODE="check"

SOURCE="$SOURCE" TARGET="$TARGET" MODE="$MODE" "$PYTHON" - <<'PY'
import os
import shutil
import sys
from pathlib import Path

import yaml

source = Path(os.environ["SOURCE"])
target = Path(os.environ["TARGET"])
check_only = os.environ["MODE"] == "check"

wanted = yaml.safe_load(source.read_text()) or {}
current = yaml.safe_load(target.read_text()) if target.is_file() else {}
current = current or {}

changes: list[str] = []


def merge(want, have, path=""):
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
            merge(value, child, here)
            have[key] = child
        else:
            if have.get(key) != value:
                changes.append(f"  {here}: {have.get(key)!r} -> {value!r}")
                have[key] = value
    return have


merged = merge(wanted, dict(current))

if not changes:
    print(f"Nada que cambiar — {target} ya está al día.")
    sys.exit(0)

print(("Faltan estos ajustes en " if check_only else "Aplicando en ") + str(target) + ":")
print("\n".join(changes))

if check_only:
    sys.exit(1)

if target.is_file():
    backup = target.with_suffix(".yaml.bak")
    shutil.copy2(target, backup)
    print(f"\nCopia previa en {backup}")

target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(yaml.safe_dump(merged, sort_keys=False, allow_unicode=True))
print(f"Escrito {target}")
print("\nReinicia el gateway para que surta efecto:")
print("  systemctl --user restart jarvis-hermes.service")
PY
