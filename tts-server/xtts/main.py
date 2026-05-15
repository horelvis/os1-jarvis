"""Local override of Coqui xtts-streaming-server's main.py.

Adds five optional knobs to /tts_stream so we can tune expressiveness
from the client (the upstream server hardcodes all GPT sampling
defaults, which produces flat/"mono" prosody on cloned voices).

Mounted into the container at /app/main.py via docker compose.

Diff from upstream (https://github.com/coqui-ai/xtts-streaming-server):
- StreamingInputs gains: temperature, top_p, top_k, repetition_penalty,
  speed, length_penalty (all optional, with documented defaults).
- predict_streaming_generator() unpacks them and forwards to
  model.inference_stream().
- Our defaults nudge above upstream's so the out-of-the-box output is
  more expressive (temperature 0.75 vs 0.65, repetition_penalty 1.5
  vs 2.0); per-request override still works.

Everything else (clone_speaker, /tts non-streaming, /studio_speakers,
/languages) is byte-identical to upstream.
"""

import base64
import io
import os
import tempfile
import wave
import torch
import numpy as np
from typing import List, Optional
from pydantic import BaseModel

from fastapi import FastAPI, UploadFile, Body
from fastapi.responses import StreamingResponse

from TTS.tts.configs.xtts_config import XttsConfig
from TTS.tts.models.xtts import Xtts
from TTS.utils.generic_utils import get_user_data_dir
from TTS.utils.manage import ModelManager

torch.set_num_threads(int(os.environ.get("NUM_THREADS", os.cpu_count())))
device = torch.device("cuda" if os.environ.get("USE_CPU", "0") == "0" else "cpu")
if not torch.cuda.is_available() and device == "cuda":
    raise RuntimeError("CUDA device unavailable, please use Dockerfile.cpu instead.")

custom_model_path = os.environ.get("CUSTOM_MODEL_PATH", "/app/tts_models")

if os.path.exists(custom_model_path) and os.path.isfile(custom_model_path + "/config.json"):
    model_path = custom_model_path
    print("Loading custom model from", model_path, flush=True)
else:
    print("Loading default model", flush=True)
    model_name = "tts_models/multilingual/multi-dataset/xtts_v2"
    print("Downloading XTTS Model:", model_name, flush=True)
    ModelManager().download_model(model_name)
    model_path = os.path.join(get_user_data_dir("tts"), model_name.replace("/", "--"))
    print("XTTS Model downloaded", flush=True)

print("Loading XTTS", flush=True)
config = XttsConfig()
config.load_json(os.path.join(model_path, "config.json"))
model = Xtts.init_from_config(config)
model.load_checkpoint(config, checkpoint_dir=model_path, eval=True, use_deepspeed=True if device == "cuda" else False)
model.to(device)
print("XTTS Loaded.", flush=True)

print("Running XTTS Server (with expressiveness knobs) ...", flush=True)

app = FastAPI(
    title="XTTS Streaming server (tuned)",
    description="Upstream server + temperature/top_p/top_k/repetition_penalty/speed knobs.",
    version="0.0.1-tuned",
    docs_url="/",
)


@app.post("/clone_speaker")
def predict_speaker(wav_file: UploadFile):
    """Compute conditioning inputs from reference audio file."""
    temp_audio_name = next(tempfile._get_candidate_names())
    with open(temp_audio_name, "wb") as temp, torch.inference_mode():
        temp.write(io.BytesIO(wav_file.file.read()).getbuffer())
        gpt_cond_latent, speaker_embedding = model.get_conditioning_latents(
            temp_audio_name
        )
    return {
        "gpt_cond_latent": gpt_cond_latent.cpu().squeeze().half().tolist(),
        "speaker_embedding": speaker_embedding.cpu().squeeze().half().tolist(),
    }


def postprocess(wav):
    if isinstance(wav, list):
        wav = torch.cat(wav, dim=0)
    wav = wav.clone().detach().cpu().numpy()
    wav = wav[None, : int(wav.shape[0])]
    wav = np.clip(wav, -1, 1)
    wav = (wav * 32767).astype(np.int16)
    return wav


def encode_audio_common(
    frame_input, encode_base64=True, sample_rate=24000, sample_width=2, channels=1
):
    wav_buf = io.BytesIO()
    with wave.open(wav_buf, "wb") as vfout:
        vfout.setnchannels(channels)
        vfout.setsampwidth(sample_width)
        vfout.setframerate(sample_rate)
        vfout.writeframes(frame_input)
    wav_buf.seek(0)
    if encode_base64:
        return base64.b64encode(wav_buf.getbuffer()).decode("utf-8")
    return wav_buf.read()


class StreamingInputs(BaseModel):
    speaker_embedding: List[float]
    gpt_cond_latent: List[List[float]]
    text: str
    language: str
    add_wav_header: bool = True
    stream_chunk_size: str = "20"

    # ── Expressiveness knobs (our overlay) ──
    # Defaults raised vs upstream Coqui (0.65 / 2.0) so the out-of-
    # the-box cloned voice is less monotone. Per-request override
    # still works.
    temperature: Optional[float] = 0.75
    top_p: Optional[float] = 0.9
    top_k: Optional[int] = 50
    repetition_penalty: Optional[float] = 1.5
    length_penalty: Optional[float] = 1.0
    speed: Optional[float] = 1.0


def predict_streaming_generator(parsed_input: dict = Body(...)):
    speaker_embedding = torch.tensor(parsed_input.speaker_embedding).unsqueeze(0).unsqueeze(-1)
    gpt_cond_latent = torch.tensor(parsed_input.gpt_cond_latent).reshape((-1, 1024)).unsqueeze(0)
    text = parsed_input.text
    language = parsed_input.language

    stream_chunk_size = int(parsed_input.stream_chunk_size)
    add_wav_header = parsed_input.add_wav_header

    chunks = model.inference_stream(
        text,
        language,
        gpt_cond_latent,
        speaker_embedding,
        stream_chunk_size=stream_chunk_size,
        enable_text_splitting=True,
        temperature=parsed_input.temperature,
        top_p=parsed_input.top_p,
        top_k=parsed_input.top_k,
        repetition_penalty=parsed_input.repetition_penalty,
        length_penalty=parsed_input.length_penalty,
        speed=parsed_input.speed,
    )

    for i, chunk in enumerate(chunks):
        chunk = postprocess(chunk)
        if i == 0 and add_wav_header:
            yield encode_audio_common(b"", encode_base64=False)
            yield chunk.tobytes()
        else:
            yield chunk.tobytes()


@app.post("/tts_stream")
def predict_streaming_endpoint(parsed_input: StreamingInputs):
    return StreamingResponse(
        predict_streaming_generator(parsed_input),
        media_type="audio/wav",
    )


class TTSInputs(BaseModel):
    speaker_embedding: List[float]
    gpt_cond_latent: List[List[float]]
    text: str
    language: str


@app.post("/tts")
def predict_speech(parsed_input: TTSInputs):
    speaker_embedding = torch.tensor(parsed_input.speaker_embedding).unsqueeze(0).unsqueeze(-1)
    gpt_cond_latent = torch.tensor(parsed_input.gpt_cond_latent).reshape((-1, 1024)).unsqueeze(0)
    text = parsed_input.text
    language = parsed_input.language

    out = model.inference(
        text,
        language,
        gpt_cond_latent,
        speaker_embedding,
    )

    wav = postprocess(torch.tensor(out["wav"]))

    return encode_audio_common(wav.tobytes())


@app.get("/studio_speakers")
def get_speakers():
    if hasattr(model, "speaker_manager") and hasattr(model.speaker_manager, "speakers"):
        return {
            speaker: {
                "speaker_embedding": model.speaker_manager.speakers[speaker]["speaker_embedding"].cpu().squeeze().half().tolist(),
                "gpt_cond_latent": model.speaker_manager.speakers[speaker]["gpt_cond_latent"].cpu().squeeze().half().tolist(),
            }
            for speaker in model.speaker_manager.speakers.keys()
        }
    return {}


@app.get("/languages")
def get_languages():
    return config.languages
