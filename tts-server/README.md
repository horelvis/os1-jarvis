# Samantha TTS server — install guide

Standalone HTTP server that exposes Qwen3-TTS over a single `/speak`
endpoint. Designed to run on a GPU host (4090, A100, etc.) while
Samantha herself runs on a smaller box. Talks plain JSON in, WAV out.

This guide walks the full install on a Linux host with an NVIDIA GPU.
Tested with Ubuntu 22.04 LTS and Ubuntu Server 24.04. Steps for
other distros are similar.

---

## 0. Prerequisites

- **GPU**: NVIDIA RTX 4090 (24 GB) is the target. Anything from a
  3060 (12 GB) up works for the 1.7B model. The 0.6B variant fits
  in ~6 GB.
- **OS**: Linux (kernel 5.15+). The model and server work on Windows
  and macOS too, but the systemd unit at the end is Linux-only.
- **Network**: the GPU host must be reachable from the mini-PC over
  LAN. Static IP recommended.
- **Disk**: ~5 GB for the 1.7B model, ~2 GB for the 0.6B, plus
  ~1.5 GB of Python deps (torch + transformers).

---

## 1. Verify the GPU is alive

```bash
nvidia-smi
```

You should see something like:
```
+-----------------------------------------------------------------------+
| NVIDIA-SMI 545.xx       Driver Version: 545.xx     CUDA Version: 12.3 |
| GPU  Name        ...    Memory-Usage              GPU-Util            |
|   0  NVIDIA GeForce RTX 4090   23018MiB / 24564MiB   0%               |
+-----------------------------------------------------------------------+
```

If `nvidia-smi` isn't there or shows "ERR!", fix drivers before going
further:

```bash
sudo ubuntu-drivers autoinstall   # Ubuntu auto-pick
sudo reboot
```

---

## 2. System packages

```bash
sudo apt update
sudo apt install -y \
  python3.11 python3.11-venv python3.11-dev \
  build-essential git curl ffmpeg sox \
  libsndfile1
```

`ffmpeg` and `sox` are runtime deps of `librosa` (which `qwen-tts`
pulls in). `libsndfile1` is needed for `soundfile`.

If `python3.11` isn't in your distro yet, add the deadsnakes PPA on
Ubuntu:

```bash
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt update
sudo apt install python3.11 python3.11-venv python3.11-dev
```

---

## 3. Clone Samantha (just for `tts-server/`)

```bash
cd ~
git clone https://github.com/horelvis/os1-samantha.git
cd os1-samantha/tts-server
```

Only `tts-server/` is needed on the GPU host. The backend + frontend
stay on the mini-PC.

---

## 4. Create the venv

### Shortcut: run `./setup.sh`

For the impatient: after step 2 (system packages) and step 3 (clone),
just run:

```bash
./setup.sh                    # 1.7B model (default)
./setup.sh --model 0.6B       # smaller variant
```

It does steps 4–7 (venv, deps in the right order, torch CUDA check,
model download) end-to-end. Idempotent — safe to rerun if something
broke. Then jump to step 7 (smoke test) below.

### Manual path

If you'd rather do it by hand:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
```

---

## 5. Install dependencies (order matters)

### 5.1 Pre-built llvmlite + numba

`qwen-tts` transitively pulls `librosa` → `numba` → `llvmlite`.
Building `llvmlite` from source fails without the right LLVM in PATH;
just use pre-built wheels:

```bash
pip install --only-binary=:all: llvmlite numba
```

### 5.2 Everything else

```bash
pip install -r requirements.txt
```

This installs `qwen-tts`, `torch`, `fastapi`, etc. Allow ~5 minutes
on a fresh box (torch is ~700 MB).

### 5.3 (Recommended) FlashAttention 2 for speed

Big speed-up for the transformer pass. Only on Linux + Ada/Hopper:

```bash
pip install flash-attn --no-build-isolation
```

Build can take ~10 min. Worth it: ~2× faster synth.

### 5.4 Sanity-check torch sees the GPU

```bash
python -c "import torch; print('cuda:', torch.cuda.is_available()); print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'no gpu')"
```

Expected:
```
cuda: True
NVIDIA GeForce RTX 4090
```

If `cuda: False`, the installed torch is the CPU build. Force the
CUDA build:

```bash
pip uninstall -y torch torchaudio
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121
```

(Replace `cu121` with the CUDA version `nvidia-smi` reports if it's
not 12.x.)

---

## 6. Download the voice model

The 1.7B-CustomVoice is the recommended default (better prosody,
fits comfortably on a 4090):

```bash
mkdir -p ~/.samantha/qwen3-tts
python -c "from huggingface_hub import snapshot_download; \
snapshot_download( \
  'Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice', \
  local_dir='$HOME/.samantha/qwen3-tts/1.7B-CustomVoice')"
```

~4.2 GB download. Saves to `~/.samantha/qwen3-tts/1.7B-CustomVoice/`.

If you'd rather start with the 0.6B (faster cold-load, slightly
less prosodic):

```bash
python -c "from huggingface_hub import snapshot_download; \
snapshot_download( \
  'Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice', \
  local_dir='$HOME/.samantha/qwen3-tts/0.6B-CustomVoice')"
```

You can keep both on disk and switch via `TTS_MODEL_PATH`.

---

## 7. First run — foreground smoke test

```bash
cd ~/os1-samantha/tts-server
source .venv/bin/activate
TTS_PORT=9000 python server.py
```

Logs should show:
```
INFO  Samantha TTS server starting on 0.0.0.0:9000
INFO  Model: /home/<user>/.samantha/qwen3-tts/1.7B-CustomVoice
INFO  Default speaker: serena (spanish)
INFO  Uvicorn running on http://0.0.0.0:9000
```

In a second terminal:

```bash
curl http://localhost:9000/ping | python3 -m json.tool
```

Expected (first call cold-loads the model, ~3-10 s):
```json
{
  "status": "ok",
  "model": "/home/<user>/.samantha/qwen3-tts/1.7B-CustomVoice",
  "default_speaker": "serena",
  "default_language": "spanish",
  "languages": ["auto", "chinese", "english", "french", ...],
  "speakers": ["aiden", "dylan", "eric", "ono_anna", "ryan",
               "serena", "sohee", "uncle_fu", "vivian"]
}
```

And a full synth:

```bash
curl -X POST http://localhost:9000/speak \
  -H 'Content-Type: application/json' \
  -d '{"text":"Hola. Soy Samantha. Es bonito hablar contigo."}' \
  -D - -o /tmp/sam.wav | grep -i x-tts
```

You should see something like:
```
x-tts-backend: qwen3
x-tts-speaker: serena
x-tts-rtf: 0.18
x-tts-audio-duration-s: 3.84
```

`RTF < 1` = synth is faster than realtime. On a 4090 with FlashAttn
expect `RTF ~ 0.1-0.2`.

Play the WAV to verify (any local audio player). Press `Ctrl+C` in
the server terminal to stop.

---

## 8. Permanent install (systemd)

Copy the unit file and enable it. The unit assumes the venv is at
`tts-server/.venv` and the model lives at
`~/.samantha/qwen3-tts/1.7B-CustomVoice`. Adjust `User=`,
`WorkingDirectory=` and `EnvironmentFile=` to your username.

```bash
# 1. Edit samantha-tts.service in this directory if needed
#    (mostly User= and ReadWritePaths=).
# 2. Install it.
sudo cp samantha-tts.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now samantha-tts.service
```

Verify:

```bash
systemctl status samantha-tts.service
journalctl -u samantha-tts.service -f
```

On reboot the service auto-starts and listens on port 9000.

---

## 9. Open the port (LAN only)

The server listens on `0.0.0.0:9000`. Restrict it to the LAN with
`ufw`:

```bash
# Assume your LAN is 192.168.100.0/24
sudo ufw allow from 192.168.100.0/24 to any port 9000 proto tcp
sudo ufw status
```

Don't expose 9000 to the internet — there's no auth.

---

## 10. Wire Samantha to point at it

On the **mini-PC** (where the Samantha backend runs):

```bash
export SAMANTHA_TTS_BACKEND=qwen3_remote
export SAMANTHA_QWEN3_TTS_URL=http://192.168.100.58:9000
export SAMANTHA_QWEN3_SPEAKER=serena       # or vivian / sohee / ...
# Optional style steering:
# export SAMANTHA_QWEN3_INSTRUCT="Soft, warm voice."

python -m samantha.api
```

Samantha's own `/speak` will proxy each sentence to the 4090. On
network failure / non-200 it falls back to local Piper so the kiosk
stays usable if the GPU box is down.

Verify end-to-end from the mini-PC:

```bash
curl -X POST http://127.0.0.1:7777/speak \
  -H 'Content-Type: application/json' \
  -d '{"text":"Hola","voice":"default"}' \
  -D - -o /tmp/end2end.wav | grep -i x-tts-mode
# Expect: x-tts-mode: qwen3_remote
```

---

## 11. Choosing a voice

`get_supported_speakers()` returns:

```
aiden, dylan, eric, ono_anna, ryan, serena, sohee, uncle_fu, vivian
```

**Female-presenting in Spanish:** `serena`, `vivian`, `sohee`,
`ono_anna`. Samantha's default is **serena** — the name fits the
"warm but not effusive" voice described in CLAUDE.md §7.

To audition them, hit `/speak` with each speaker name:

```bash
for s in serena vivian sohee ono_anna; do
  curl -s -X POST http://localhost:9000/speak \
    -H 'Content-Type: application/json' \
    -d "{\"text\":\"Hola, soy Samantha.\", \"speaker\":\"$s\"}" \
    -o /tmp/voice-$s.wav
done
```

---

## 12. Style control

Qwen3-TTS-CustomVoice supports natural-language style instructions
via the `instruct` field. Examples that work well in Spanish:

```json
{ "text": "Es tarde y deberías dormir.",
  "instruct": "Soft, slightly tired voice." }

{ "text": "¡Lo conseguiste!",
  "instruct": "Excited, warm tone." }

{ "text": "Tranquila, estoy contigo.",
  "instruct": "Whispering, very soft voice." }
```

Useful for time-of-day or emotional inflection without retraining.

---

## 13. Troubleshooting

### `RuntimeError: CUDA out of memory`
The 1.7B at fp16 needs ~3.4 GB. If the GPU is shared:
- Check `nvidia-smi` for hogs; kill the right one.
- Or switch to the 0.6B model: re-download to
  `~/.samantha/qwen3-tts/0.6B-CustomVoice` and set
  `TTS_MODEL_PATH=$HOME/.samantha/qwen3-tts/0.6B-CustomVoice`.

### `ModuleNotFoundError: llvmlite`
You skipped step 5.1. Run:
```bash
pip install --only-binary=:all: llvmlite numba
pip install -r requirements.txt --force-reinstall
```

### `flash-attn` install fails
Optional. Skip it — server still works without, just ~2× slower.

### First /speak takes 10+ seconds
That's the cold load. The model loads on the first request and
stays resident. Hit `/ping` after starting the service to warm up.

### `numpy.dtype size changed, may indicate binary incompatibility`
torch 2.2.x is built against numpy <2. The `requirements.txt`
already pins `numpy<2`, but if you've upgraded numpy by hand:
```bash
pip install 'numpy<2'
```

### Synth is slow on the 4090 (RTF > 1)
- Verify `torch.cuda.is_available()` returns True (step 5.4).
- Install `flash-attn` (step 5.3) — biggest single speed-up.
- Check `nvidia-smi` during synth — GPU utilization should jump.
  If it stays at 0%, torch is on CPU.

---

## 14. License notes

- Server code under MIT (this repo's license).
- Qwen3-TTS weights under Qwen's licensing — see the model card
  on Hugging Face. Apache 2.0 for the surrounding code; check
  the weights' specific terms before commercial use.
