# Copyright (c) 2024 Alibaba Inc (authors: Xiang Lyu)
# Licensed under the Apache License, Version 2.0.
#
# LOCAL OVERLAY of CosyVoice's runtime/python/fastapi/server.py.
#
# Upstream server.py pre-loads each multipart prompt_wav into a
# 16 kHz torch.Tensor and passes the tensor into
# cosyvoice.inference_*. That contract worked for CosyVoice 2; in
# CosyVoice 3 the frontend's `_extract_speech_feat` re-calls
# `load_wav(prompt_wav, 24000)` and crashes with:
#
#     TypeError: Invalid file: tensor([[...]])
#
# Fix: write the upload to a temp file and hand the model the
# *path*. CosyVoice 3 does its own load_wav() from disk and the
# double-load disappears. Same pattern we used for the XTTS overlay.
#
# Mounted into the container at
#   /opt/CosyVoice/runtime/python/fastapi/server.py
# via docker-compose.yml (read-only).

import os
import sys
import argparse
import logging
import tempfile

logging.getLogger('matplotlib').setLevel(logging.WARNING)

from fastapi import BackgroundTasks, FastAPI, UploadFile, Form, File
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import numpy as np

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append('{}/../../..'.format(ROOT_DIR))
sys.path.append('{}/../../../third_party/Matcha-TTS'.format(ROOT_DIR))

from cosyvoice.cli.cosyvoice import AutoModel

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)


def generate_data(model_output):
    for i in model_output:
        # Clip before casting: a sample at/above 1.0 would wrap to
        # -32768 (audible click). Matches the XTTS overlay's handling.
        tts_audio = (np.clip(i['tts_speech'].numpy(), -1.0, 1.0) * 32767).astype(np.int16).tobytes()
        yield tts_audio


# CosyVoice 3's LLM (`CosyVoice3LM` → inherited `Qwen2LM.inference`)
# hard-asserts that token id 151646 (`<|endofprompt|>`) appears in the
# concatenated prompt_text + text tokens. The upstream frontend never
# inserts it — callers are expected to embed the literal string in
# their input, exactly as upstream example.py does:
#
#     inference_cross_lingual(
#         "You are a helpful assistant.<|endofprompt|>...spoken text...",
#         ref_wav,
#     )
#     inference_zero_shot(
#         tts_text,
#         "You are a helpful assistant.<|endofprompt|>" + transcript,
#         ref_wav,
#     )
#     inference_instruct2(tts_text, instruct_text + "<|endofprompt|>", ref_wav)
#
# The frontend's text_normalize() auto-disables splitting when `<|...|>`
# appears in the input, so injecting the marker is safe for long text.
# We do it here so the Samantha client can keep sending plain Spanish.
_EOP = "<|endofprompt|>"
_SYS_PREFIX = "You are a helpful assistant." + _EOP


def _ensure_eop_prefix(s: str) -> str:
    return s if _EOP in s else _SYS_PREFIX + s


def _ensure_eop_suffix(s: str) -> str:
    return s if _EOP in s else s + _EOP


async def _save_upload(upload: UploadFile) -> str:
    """Persist multipart upload to a tempfile and return the path.

    Force flush + fsync so the bytes are durable on disk before any
    worker thread tries to open the file via libsndfile (which has
    been failing with `System error` opening tempfiles that pass the
    NamedTemporaryFile context exit but apparently aren't yet
    reachable for the inference thread).
    """
    data = await upload.read()
    fd, path = tempfile.mkstemp(suffix=".wav")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
    except Exception:
        try:
            os.unlink(path)
        except OSError:
            pass
        raise
    size = os.path.getsize(path)
    logging.info(
        f"_save_upload: wrote {len(data)} bytes (disk size {size}) to {path}"
    )
    if size == 0 or size != len(data):
        raise RuntimeError(
            f"upload save mismatch: got {len(data)} bytes, on disk {size}"
        )
    return path


def _safe_unlink(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


@app.get("/inference_sft")
@app.post("/inference_sft")
async def inference_sft(tts_text: str = Form(), spk_id: str = Form()):
    model_output = cosyvoice.inference_sft(tts_text, spk_id)
    return StreamingResponse(generate_data(model_output))


@app.get("/inference_zero_shot")
@app.post("/inference_zero_shot")
async def inference_zero_shot(
    background_tasks: BackgroundTasks,
    tts_text: str = Form(),
    prompt_text: str = Form(),
    prompt_wav: UploadFile = File(),
):
    path = await _save_upload(prompt_wav)
    # Cleanup runs AFTER the StreamingResponse finishes — using a
    # try/finally here would unlink the file BEFORE the model
    # iterator actually reads it (the function returns immediately;
    # streaming happens later).
    background_tasks.add_task(_safe_unlink, path)
    prompt_text = _ensure_eop_prefix(prompt_text)
    model_output = cosyvoice.inference_zero_shot(tts_text, prompt_text, path)
    return StreamingResponse(generate_data(model_output), background=background_tasks)


@app.get("/inference_cross_lingual")
@app.post("/inference_cross_lingual")
async def inference_cross_lingual(
    background_tasks: BackgroundTasks,
    tts_text: str = Form(),
    prompt_wav: UploadFile = File(),
):
    path = await _save_upload(prompt_wav)
    background_tasks.add_task(_safe_unlink, path)
    tts_text = _ensure_eop_prefix(tts_text)
    model_output = cosyvoice.inference_cross_lingual(tts_text, path)
    return StreamingResponse(generate_data(model_output), background=background_tasks)


@app.get("/inference_instruct")
@app.post("/inference_instruct")
async def inference_instruct(
    tts_text: str = Form(),
    spk_id: str = Form(),
    instruct_text: str = Form(),
):
    model_output = cosyvoice.inference_instruct(tts_text, spk_id, instruct_text)
    return StreamingResponse(generate_data(model_output))


@app.get("/inference_instruct2")
@app.post("/inference_instruct2")
async def inference_instruct2(
    background_tasks: BackgroundTasks,
    tts_text: str = Form(),
    instruct_text: str = Form(),
    prompt_wav: UploadFile = File(),
):
    path = await _save_upload(prompt_wav)
    background_tasks.add_task(_safe_unlink, path)
    instruct_text = _ensure_eop_suffix(instruct_text)
    model_output = cosyvoice.inference_instruct2(tts_text, instruct_text, path)
    return StreamingResponse(generate_data(model_output), background=background_tasks)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=50000)
    parser.add_argument(
        '--model_dir', type=str,
        default='iic/CosyVoice2-0.5B',
        help='local path or modelscope repo id',
    )
    args = parser.parse_args()
    cosyvoice = AutoModel(model_dir=args.model_dir)
    uvicorn.run(app, host="0.0.0.0", port=args.port)
