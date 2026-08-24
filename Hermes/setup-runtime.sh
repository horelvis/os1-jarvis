#!/usr/bin/env bash
#
# Install the Hermes runtime this project pins, inside this project.
#
# Why in-repo: the plugins under Hermes/plugins/ are written against the
# contracts captured in docs/superpowers/specs/hermes-contracts-v0.20.5.md.
# A Hermes of any other version silently fails to match them — the shims the
# tests run against cannot tell you so. Pinning the runtime next to the
# plugins is what makes "clone and start" reproducible.
#
# What this does NOT touch: ~/.hermes, ~/.local/bin/hermes, or any gateway
# already running. Those belong to the machine's owner, not to Samantha.
#
# Idempotent: safe to re-run. Re-running after editing HERMES_COMMIT below
# is how you move the pin.
#
#   Usage: Hermes/setup-runtime.sh
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HERMES_SRC="$REPO_ROOT/.hermes/src"
HERMES_HOME="$REPO_ROOT/.hermes/home"

# The pin. The tag is for humans; the commit is what is verified, because a
# tag can be moved and a commit cannot.
HERMES_REPO="https://github.com/NousResearch/hermes-agent.git"
HERMES_TAG="v2026.8.19"          # pyproject version 0.20.5
# The COMMIT the tag points at, not the tag object's own hash. `git ls-remote
# --tags` prints the latter for an annotated tag (v2026.8.19 -> b05e680e…);
# checking that out lands on the commit below and the verification here fails,
# which is how this line got corrected in the first place. Read it with
# `git ls-remote --tags <repo> "v2026.8.19^{}"`.
HERMES_COMMIT="fcbd1076a93841fa88855acce810e342a5b78101"

# Declared in the plugin.yaml manifests. Hermes parses `python_dependencies`
# and warns when one is missing, but never installs them — a plugin whose
# import fails still shows as "enabled" in `hermes plugins list`. This is the
# "No module named loguru" failure the manifests warn about.
#
# `av`, `onnxruntime` and `numpy` are samantha-vision's, and `uv sync` does
# NOT bring them: the `voice` extra was removed from `[all]` in Hermes'
# pyproject in favour of lazy install, so on this box they exist only because
# Hermes lazy-installed them for STT. A fresh box that skipped that path gets
# a plugin that loads and logs `no detector, no cameras watched — No module
# named 'onnxruntime'`, and no camera is ever watched.
PLUGIN_DEPS=(loguru httpx aiohttp av onnxruntime numpy)

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }

command -v uv >/dev/null || {
  echo "uv not found. Install it first: https://docs.astral.sh/uv/" >&2
  exit 1
}

say "1/6  Source at $HERMES_COMMIT"
if [ ! -d "$HERMES_SRC/.git" ]; then
  mkdir -p "$(dirname "$HERMES_SRC")"
  # blobless clone: full history, file contents fetched on demand. Cuts the
  # clone down without the caveats of a shallow one (which cannot check out
  # an arbitrary commit later).
  git clone --filter=blob:none "$HERMES_REPO" "$HERMES_SRC"
fi
git -C "$HERMES_SRC" fetch --tags --quiet origin
git -C "$HERMES_SRC" -c advice.detachedHead=false checkout --quiet "$HERMES_COMMIT"

actual="$(git -C "$HERMES_SRC" rev-parse HEAD)"
[ "$actual" = "$HERMES_COMMIT" ] || {
  echo "checkout landed on $actual, expected $HERMES_COMMIT" >&2
  exit 1
}
echo "    $HERMES_TAG @ ${HERMES_COMMIT:0:12}"

say "2/6  Runtime venv (Python 3.11)"
# --python 3.11: Hermes' own developer path. uv downloads the interpreter if
# the system has none, which is the case on a box that ships only 3.12.
(cd "$HERMES_SRC" && uv sync --python 3.11)

say "3/6  Plugin dependencies Hermes will not install"
uv pip install --quiet --python "$HERMES_SRC/.venv/bin/python" "${PLUGIN_DEPS[@]}"
echo "    ${PLUGIN_DEPS[*]}"

say "4/6  HERMES_HOME at $HERMES_HOME"
mkdir -p "$HERMES_HOME/plugins"
# Symlinks, not copies: the plugins are versioned source in this repo and
# must stay editable in place. Same pattern the plan documents use.
for plugin in samantha_voice samantha_kiosk samantha_vision; do
  ln -sfn "$REPO_ROOT/Hermes/plugins/$plugin" "$HERMES_HOME/plugins/$plugin"
  echo "    plugins/$plugin -> Hermes/plugins/$plugin"
done

say "5/6  Enable them"
# All three are opt-in: `kind: standalone` and `kind: platform` stay dark
# until listed in HERMES_HOME/config.yaml's plugins.enabled, and `hermes
# plugins list` reports "not enabled" until then. The manifest name is
# kebab-case even though the directory is snake_case.
#
# --no-allow-tool-override answers the capability prompt with "no", which is
# what all three want (samantha_voice declares allow_tool_override: false)
# and what makes this scriptable. None of them replaces a built-in tool.
for plugin in samantha-voice samantha-kiosk samantha-vision; do
  HERMES_HOME="$HERMES_HOME" "$HERMES_SRC/.venv/bin/hermes" plugins enable \
    "$plugin" --no-allow-tool-override >/dev/null 2>&1 || true
  echo "    $plugin"
done

say "6/6  Done"
cat <<EOF
    Runtime:     $HERMES_SRC
    HERMES_HOME: $HERMES_HOME
    Start it:    Hermes/run-gateway.sh
    Check it:    Hermes/run-gateway.sh --version
                 Hermes/run-gateway.sh plugins list

    Nothing was read from or written to ~/.hermes.

    Two things this cannot do for you:
      * the cameras. They carry a credential, so they live only in
        \$HERMES_HOME/config.yaml — see
        Hermes/plugins/samantha_vision/README.md.
      * the credential itself. Copy .env.example to .env at the repo root
        and fill it in; run-gateway.sh sources it.
EOF
