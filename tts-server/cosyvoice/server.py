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

from fastapi import FastAPI, UploadFile, Form, File
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
        tts_audio = (i['tts_speech'].numpy() * (2 ** 15)).astype(np.int16).tobytes()
        yield tts_audio


async def _save_upload(upload: UploadFile) -> str:
    """Persist multipart upload to a tempfile and return the path."""
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp.write(await upload.read())
        return tmp.name


@app.get("/inference_sft")
@app.post("/inference_sft")
async def inference_sft(tts_text: str = Form(), spk_id: str = Form()):
    model_output = cosyvoice.inference_sft(tts_text, spk_id)
    return StreamingResponse(generate_data(model_output))


@app.get("/inference_zero_shot")
@app.post("/inference_zero_shot")
async def inference_zero_shot(
    tts_text: str = Form(),
    prompt_text: str = Form(),
    prompt_wav: UploadFile = File(),
):
    path = await _save_upload(prompt_wav)
    try:
        model_output = cosyvoice.inference_zero_shot(tts_text, prompt_text, path)
        return StreamingResponse(generate_data(model_output))
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


@app.get("/inference_cross_lingual")
@app.post("/inference_cross_lingual")
async def inference_cross_lingual(
    tts_text: str = Form(),
    prompt_wav: UploadFile = File(),
):
    path = await _save_upload(prompt_wav)
    try:
        model_output = cosyvoice.inference_cross_lingual(tts_text, path)
        return StreamingResponse(generate_data(model_output))
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


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
    tts_text: str = Form(),
    instruct_text: str = Form(),
    prompt_wav: UploadFile = File(),
):
    path = await _save_upload(prompt_wav)
    try:
        model_output = cosyvoice.inference_instruct2(tts_text, instruct_text, path)
        return StreamingResponse(generate_data(model_output))
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


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
