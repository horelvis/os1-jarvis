#!/usr/bin/env bash
#
# Run this project's pinned Hermes with the environment its plugins need.
#
# Two exports are load-bearing:
#
#   HERMES_HOME  keeps config, SOUL.md, state.db and sessions inside the
#                repo, so Samantha's Hermes and the machine owner's personal
#                ~/.hermes never share state or fight over a version.
#   PYTHONPATH   makes `samantha.tts` importable from inside a plugin. Hermes
#                cannot install the `samantha` package (it is not on PyPI),
#                and without this both TTS providers fail at import — which
#                Hermes logs as a warning and carries on from, leaving the
#                whole-file path falling through to Edge TTS.
#
# With no arguments it starts the gateway. Any arguments are passed straight
# through, so this is also how you run the CLI against the pinned runtime:
#
#   Hermes/run-gateway.sh --version
#   Hermes/run-gateway.sh plugins list
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HERMES_BIN="$REPO_ROOT/.hermes/src/.venv/bin/hermes"

[ -x "$HERMES_BIN" ] || {
  echo "No Hermes runtime at $HERMES_BIN — run Hermes/setup-runtime.sh first." >&2
  exit 1
}

export HERMES_HOME="$REPO_ROOT/.hermes/home"
export PYTHONPATH="$REPO_ROOT/backend:$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}"

[ $# -eq 0 ] && set -- gateway
exec "$HERMES_BIN" "$@"
