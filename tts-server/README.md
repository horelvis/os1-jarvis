# Samantha TTS server (vllm-omni + Qwen3-TTS)

Docker compose deployment of [vllm-omni](https://github.com/vllm-project/vllm-omni)
serving Qwen3-TTS-12Hz-1.7B-Base with **streaming voice cloning** for
Samantha. The host (4090 box) only needs Docker + nvidia-container-toolkit;
everything else lives inside the image.

Wire shape: OpenAI-compatible `POST /v1/audio/speech` with
`response_format: "pcm"` + `stream: true` yields chunked 24 kHz mono int16
PCM in real time. TTFA ~40 ms warm on a 4090. The Samantha backend
proxies this stream through to the browser, which decodes via Web Audio
API.

---

## 0. Prerequisites

- **GPU**: any NVIDIA card with ≥ 8 GB VRAM (the 1.7B model needs ~3.4 GB
  weights + KV cache; we test on an RTX 4090).
- **OS**: Linux (we test on Ubuntu Server 24.04). Other distros work as
  long as nvidia-container-toolkit is available.
- **Docker** + **nvidia-container-toolkit** installed. Verify with:
  ```bash
  docker run --rm --gpus all nvidia/cuda:12.6.0-base-ubuntu22.04 nvidia-smi
  ```
  If that fails, install the toolkit:
  ```bash
  curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
    | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit.gpg
  echo "deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit.gpg] https://nvidia.github.io/libnvidia-container/stable/deb/$(dpkg --print-architecture) /" \
    | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
  sudo apt update && sudo apt install -y nvidia-container-toolkit
  sudo nvidia-ctk runtime configure --runtime=docker
  sudo systemctl restart docker
  ```

---

## 1. Download the Base model

Voice cloning needs the **Base** variant (not CustomVoice / VoiceDesign):

```bash
python -c "from huggingface_hub import snapshot_download; \
snapshot_download( \
  'Qwen/Qwen3-TTS-12Hz-1.7B-Base', \
  local_dir='$HOME/.samantha/qwen3-tts/1.7B-Base')"
```

~4.2 GB download. Lives at `~/.samantha/qwen3-tts/1.7B-Base/`. The compose
file bind-mounts this path read-only into the container.

---

## 2. Voice clone reference (WAV + transcript)

The reference WAV defines how Samantha sounds. Aim for:

- **6–10 seconds** of single-speaker speech.
- **Mono**, any sample rate (the model resamples).
- **Clean**: no music, no overlap, minimal noise / reverb.
- **Acting, not narrating**: audiobook readers ("LibriVox" voices) come
  out flat. A dubbing demo, podcast snippet, or interview clip works
  much better.
- **Native speaker of the target language** — the clone inherits the
  ref's accent.

Place the files at the canonical paths:

```bash
mkdir -p ~/.samantha/voices/ref
cp /path/to/your-clip.wav ~/.samantha/voices/ref/samantha.wav
echo "literal transcript of the wav, with accents and punctuation." \
  > ~/.samantha/voices/ref/samantha.txt
```

The transcript MUST match the audio word-for-word — Qwen3-TTS uses it
for phoneme alignment. Skipping accents (`ayudaria` vs `ayudaría`)
shifts stress and degrades quality.

If you want to source from Mozilla Common Voice ES, note that Mozilla
moved distribution off Hugging Face in October 2025 to the
[Mozilla Data Collective](https://commonvoice.mozilla.org/). Community
mirrors of CV17 on HF exist (`fsicoli/common_voice_17_0`) but they need
`trust_remote_code=True` and `datasets<3.0`; not the simplest path.

---

## 3. Start the server

```bash
cd tts-server
docker compose pull         # first time only — image is ~7.8 GB
docker compose up -d
docker compose logs -f tts  # watch the model cold-load (~30 s)
```

When you see `Uvicorn running on http://0.0.0.0:8091`, the server is up.
Ctrl+C to exit `logs -f` (the container keeps running in the background).

Verify:

```bash
docker compose ps
curl -s http://localhost:8091/ping     # → 200 OK
```

---

## 4. Smoke test: streaming voice cloning

```bash
REF_TEXT=$(cat ~/.samantha/voices/ref/samantha.txt)
curl -sN -X POST http://localhost:8091/v1/audio/speech \
  -H 'Content-Type: application/json' \
  -d "{
    \"input\": \"Hola, soy Samantha. Es bonito hablar contigo.\",
    \"model\": \"/models/qwen3-tts-base\",
    \"task_type\": \"Base\",
    \"language\": \"Spanish\",
    \"ref_audio\": \"file:///refs/samantha.wav\",
    \"ref_text\": \"$REF_TEXT\",
    \"stream\": true,
    \"response_format\": \"pcm\"
  }" --output /tmp/sam.pcm

# /tmp/sam.pcm is raw 24 kHz mono int16. Wrap to WAV to play:
python3 -c "
import wave
with open('/tmp/sam.pcm','rb') as f: pcm = f.read()
with wave.open('/tmp/sam.wav','wb') as w:
  w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000)
  w.writeframes(pcm)
"
aplay /tmp/sam.wav   # or play -t raw -r 24000 -e signed -b 16 -c 1 /tmp/sam.pcm
```

Expected: cloned voice speaking the input phrase. Time-to-first-byte
should be 40–200 ms warm, 1–3 s cold (first request after start).

---

## 5. Wire the Samantha backend

On the mini-PC where `samantha.api` runs:

```bash
export SAMANTHA_TTS_BACKEND=vllm_omni
export SAMANTHA_TTS_REMOTE_URL=http://<this-host-ip>:8091
# Optional overrides (defaults live in backend/samantha/config.py):
# export SAMANTHA_TTS_REMOTE_MODEL=/models/qwen3-tts-base
# export SAMANTHA_TTS_REMOTE_REF_AUDIO=file:///refs/samantha.wav
# export SAMANTHA_TTS_REMOTE_REF_TEXT="..."
# export SAMANTHA_TTS_REMOTE_LANGUAGE=Spanish
# export SAMANTHA_TTS_REMOTE_INSTRUCTIONS="Voz femenina española, cálida pero calmada..."
```

End-to-end from the backend:

```bash
curl -sN -X POST http://127.0.0.1:7777/speak \
  -H 'Content-Type: application/json' \
  -d '{"text":"Hola","voice":"default"}' \
  -D - --output /tmp/end2end.pcm | grep -i x-tts
# Expect: x-tts-mode: vllm_omni
#         x-tts-sample-rate: 24000
#         content-type: audio/pcm
#         transfer-encoding: chunked
```

---

## 6. GPU memory tuning

`docker-compose.yml` pins `--gpu-memory-utilization 0.30` so vllm-omni
plays nice with other GPU consumers on the same host (e.g.
`llama-server` running Qwen3-8B Q8 alongside). Adjust if your host has
only this workload:

| Workload on host | Recommended `--gpu-memory-utilization` |
|---|---|
| vllm-omni alone | 0.5–0.7 |
| vllm-omni + llama-server (Q8, ctx 8k) | 0.30 (current default) |
| vllm-omni + larger LLM | 0.15–0.20 |

Note: vllm-omni runs **two stages** as separate processes (AR generation
+ Code2Wav decoder). The flag is applied PER stage, so actual VRAM
usage is ~2× the requested fraction. With 0.30 on a 24 GB card that's
~12 GB for vllm-omni.

---

## 7. Operations

```bash
# Stop
docker compose down

# Restart (e.g. after replacing samantha.wav — the speaker embedding
# is cached at startup and needs a fresh load to pick up new refs).
docker compose restart tts

# Update image
docker compose pull
docker compose up -d
```

---

## 8. Troubleshooting

### `ValueError: Free memory on device cuda:0 is less than desired GPU memory utilization`
Another process is hogging VRAM. Either lower
`--gpu-memory-utilization` in the compose, or free the offending
process. `nvidia-smi --query-compute-apps=pid,process_name,used_memory
--format=csv` shows who's holding what.

### `Cannot load local files without --allowed-local-media-path`
The compose already passes `--allowed-local-media-path /refs`. If you
mount your refs at a different path, update the flag accordingly.

### `Code2Wav input_ids length 1 not divisible by num_quantizers 16; skipping malformed request`
Benign — a 1-token (or empty) request hit the server. Other requests
still serve normally.

### First /speak takes 30+ seconds
That's the model cold-load. Hit `/ping` once after the container
starts to warm up before the first real request.

### Voice sounds flat / "reading"
The reference WAV is doing too much narration. Pick a clip where the
speaker is actually acting (dubbing demo, conversation, performance)
rather than reading. The `instructions` parameter can nudge but won't
override the ref's natural style.

### Voice sounds off (sultry, robotic, wrong accent)
Either the reference (timbre / register) or the `instructions` (style
hint) is off. Iterate: try a different segment of the same actress,
or rewrite `instructions` to push toward a different mood. The model
obeys instructs about pace and register; accent / phonetic identity
comes from the ref.

---

## 9. License notes

- `docker-compose.yml` and this README under the project's MIT license.
- Qwen3-TTS weights under Qwen's licensing — see the model card on
  Hugging Face. Apache 2.0 for the surrounding code; verify the
  weights' specific terms before commercial use.
- vllm-omni under Apache 2.0.
