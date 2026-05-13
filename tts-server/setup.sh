#!/usr/bin/env bash
# tts-server setup — runs steps 4-7 of README.md end-to-end.
# Idempotent: rerun safely if something fails midway.
#
# Usage:  ./setup.sh [--model 1.7B|0.6B]   (default: 1.7B)
#
# Prereqs you must have done manually first:
#   1. nvidia-smi works (drivers + CUDA installed)
#   2. apt deps installed (see README §2)
#   3. Python 3.11 available

set -euo pipefail

# Use `PYTHON=python3.11 ./setup.sh` to pin to a specific interpreter
# when the system `python3` is 3.12+ (qwen-tts doesn't ship wheels for
# 3.12 yet). Default = whatever the system `python3` resolves to.
PYTHON="${PYTHON:-python3}"

MODEL="${MODEL:-1.7B}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --model) MODEL="$2"; shift 2 ;;
    --help|-h)
      sed -n '2,15p' "$0"; exit 0 ;;
    *) echo "unknown arg: $1"; exit 1 ;;
  esac
done

case "$MODEL" in
  1.7B) HF_REPO="Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"; LOCAL_DIR_NAME="1.7B-CustomVoice" ;;
  0.6B) HF_REPO="Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice"; LOCAL_DIR_NAME="0.6B-CustomVoice" ;;
  *)   echo "model must be 1.7B or 0.6B (got: $MODEL)"; exit 1 ;;
esac

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

echo "── 1/5 sanity ──"
"$PYTHON" --version
nvidia-smi -L

echo "── 2/5 venv ──"
if [[ ! -d .venv ]]; then
  "$PYTHON" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip

echo "── 3/5 deps (llvmlite first, then qwen-tts + server) ──"
pip install --only-binary=:all: llvmlite numba
pip install -r requirements.txt

echo "── 4/5 torch sees CUDA? ──"
python - <<'PY'
import torch
ok = torch.cuda.is_available()
print(f"cuda: {ok}")
if ok:
    print(f"device: {torch.cuda.get_device_name(0)}")
else:
    print("WARNING: torch built without CUDA. Reinstall:")
    print("  pip uninstall -y torch torchaudio")
    print("  pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121")
PY

echo "── 5/5 download $HF_REPO ──"
TARGET="$HOME/.samantha/qwen3-tts/$LOCAL_DIR_NAME"
if [[ -d "$TARGET" && -f "$TARGET/model.safetensors" ]]; then
  echo "model already present at $TARGET — skipping download"
else
  mkdir -p "$HOME/.samantha/qwen3-tts"
  python - <<PY
from huggingface_hub import snapshot_download
snapshot_download("$HF_REPO", local_dir="$TARGET")
print("downloaded to $TARGET")
PY
fi

echo
echo "✅ Setup complete."
echo
echo "Smoke test:"
echo "  source .venv/bin/activate"
echo "  TTS_MODEL_PATH=$TARGET python server.py"
echo
echo "In another shell:"
echo "  curl http://localhost:9000/ping | python3 -m json.tool"
echo "  curl -X POST http://localhost:9000/speak -H 'Content-Type: application/json' \\"
echo "       -d '{\"text\":\"Hola. Soy Samantha.\"}' -o /tmp/sam.wav"
echo
echo "For permanent install, see README §8 (systemd)."
