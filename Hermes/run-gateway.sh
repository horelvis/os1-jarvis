#!/usr/bin/env bash
#
# Run this project's pinned Hermes with the environment its plugins need.
#
# Two exports are load-bearing:
#
#   HERMES_HOME  keeps config, SOUL.md, state.db and sessions inside the
#                repo, so Samantha's Hermes and the machine owner's personal
#                ~/.hermes never share state or fight over a version.
#   PYTHONPATH   makes the `Hermes` package importable as a package root from
#                inside a plugin, and reaches `jarvis_voice.tts` and
#                `jarvis_voice.markers`. Without this both TTS providers
#                fail at import — which Hermes logs as a warning and carries
#                on from, leaving the whole-file path falling through to
#                Edge TTS.
#
# It also sources `.env` (git-ignored, at the repo root) if it is there, which
# is where this box's credentials live — see `.env.example`.
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

# Credentials, by name and never in a tracked file. `.env` at the repo root
# is git-ignored and holds RTSP_PASSWORD, which `.hermes/home/config.yaml`
# references from inside each camera URL as `${RTSP_PASSWORD}`. This is the
# one chokepoint worth teaching: both units that start a Hermes process
# (jarvis-hermes.service, jarvis-hermes-serve.service) and every manual
# invocation come through here, so nothing else has to know.
# jarvis-widget.service does not — it needs no credential.
#
# `set -a` exports everything the file defines; `set +a` puts it back. A
# missing file is normal — a box with no cameras needs no credential — and
# `[ -f ]` keeps `set -e` from ending the script over it. Nothing is echoed.
if [ -f "$REPO_ROOT/.env" ]; then
  set -a
  # shellcheck source=/dev/null
  . "$REPO_ROOT/.env"
  set +a
fi

export HERMES_HOME="$REPO_ROOT/.hermes/home"
export PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}"

# `Hermes/bin` first, so the `claude` the assistant skills run is our
# wrapper: it passes stdout through untouched and tees a copy into
# ~/.jarvis/code-live.log, which `jarvis_code` follows and puts on
# the strip. Without this the work is invisible until `terminal`
# returns, which for a real task is minutes of nothing on screen.
export PATH="$REPO_ROOT/Hermes/bin:$PATH"

[ $# -eq 0 ] && set -- gateway
exec "$HERMES_BIN" "$@"
