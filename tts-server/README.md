# Samantha TTS server

Standalone HTTP server that exposes Qwen3-TTS over a single
`/speak` endpoint. Designed to run on a GPU box (e.g. RTX 4090) so the
mini-PC running Samantha + Qwen LLM doesn't have to fit the TTS model
in its own 8 GB VRAM.

## Setup

```bash
# On the GPU host
python3.11 -m venv .venv
source .venv/bin/activate
# llvmlite needs pre-built wheels, install separately before qwen-tts.
pip install --only-binary=:all: llvmlite numba
pip install -r requirements.txt

# Pull the model (one-off, ~4.2 GB).
pip install huggingface_hub
python -c "from huggingface_hub import snapshot_download; \
  snapshot_download('Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice', \
  local_dir='$HOME/.samantha/qwen3-tts/1.7B-CustomVoice')"

# Optional but recommended on a Linux GPU host:
pip install flash-attn --no-build-isolation
```

## Run

```bash
TTS_PORT=9000 \
TTS_MODEL_PATH=$HOME/.samantha/qwen3-tts/1.7B-CustomVoice \
TTS_DEFAULT_SPEAKER=serena \
TTS_DEFAULT_LANGUAGE=spanish \
python server.py
```

Probe:

```bash
curl http://localhost:9000/ping | jq
curl -X POST http://localhost:9000/speak \
     -H 'Content-Type: application/json' \
     -d '{"text":"Hola. Soy Samantha."}' \
     -o out.wav
```

The response is mono 24 kHz 16-bit WAV with metadata headers:

- `X-TTS-Backend: qwen3`
- `X-TTS-Speaker: serena`
- `X-TTS-RTF: 0.18`  *(real-time factor — <1 means faster than realtime)*
- `X-TTS-Audio-Duration-S: 3.84`

## Wiring Samantha to this server

In Samantha's backend config (`backend/samantha/config.py` or env):

```bash
SAMANTHA_TTS_BACKEND=qwen3_remote
SAMANTHA_QWEN3_TTS_URL=http://<gpu-host>:9000
SAMANTHA_TTS_SPEAKER=serena
```

The Samantha `/speak` endpoint will proxy each sentence to this
server. Failure to reach the remote falls back to local Piper so the
kiosk stays usable if the GPU box is down.

## Supported voices

`get_supported_speakers()` returns:

```
aiden, dylan, eric, ono_anna, ryan, serena, sohee, uncle_fu, vivian
```

Female-presenting in Spanish: `serena`, `vivian`, `sohee`,
`ono_anna`. Samantha's default is **serena** — the name itself fits
the warmth-without-effusion brief from CLAUDE.md §7.

## Style control

Qwen3-TTS supports natural-language style instructions via the
`instruct` field:

```json
{
  "text": "Es tarde y deberías dormir.",
  "instruct": "Soft, slightly tired voice."
}
```

Useful for time-of-day / mood inflection without retraining.

## License

See the model card on Hugging Face for `Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice`
(Apache 2.0 for the code; weights under Qwen's terms).
