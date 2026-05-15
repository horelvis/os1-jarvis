# CosyVoice 3 FastAPI server. We build our own image because:
# - Upstream Dockerfile uses Aliyun pip mirrors that 404 outside CN.
# - Upstream targets the gRPC runtime; we want the FastAPI one.
# - Community images on Docker Hub are pinned to CosyVoice 2.
#
# Base is the same torch / CUDA combo CosyVoice's requirements.txt
# expects (torch 2.0.1 + CUDA 11.7). The -devel variant (vs -runtime)
# ships the CUDA toolkit + sets CUDA_HOME, which DeepSpeed probes at
# import time. Without it the transformers→modelscope import chain
# fails with `CUDA_HOME does not exist`. ~3 GB larger image; worth
# the simpler dep chain.

FROM pytorch/pytorch:2.0.1-cuda11.7-cudnn8-devel

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update -y && \
    apt-get install -y --no-install-recommends \
        git unzip git-lfs g++ ffmpeg libsndfile1 && \
    git lfs install && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /opt
RUN git clone --recursive https://github.com/FunAudioLLM/CosyVoice.git

WORKDIR /opt/CosyVoice

# openai-whisper==20231117 (pinned by CosyVoice's requirements.txt)
# imports pkg_resources at setup-time, but setuptools 70+ removed
# the implicit pkg_resources export. Pin setuptools<70 so the
# module is still importable; install whisper with
# --no-build-isolation so its setup.py sees this layer's setuptools
# instead of pip's fresh build env (which would re-install latest).
RUN pip install --upgrade --no-cache-dir pip wheel "setuptools<70"
RUN pip install --no-cache-dir --no-build-isolation \
    "openai-whisper==20231117"
RUN pip install --no-cache-dir -r requirements.txt

# DeepSpeed is in CosyVoice's requirements but only matters for
# training. For inference it just adds an import-time CUDA probe
# that can fail on subtle env mismatches. Drop it after install —
# transformers detects its absence and uses the non-deepspeed path.
RUN pip uninstall -y deepspeed

# The FastAPI server lives here; it speaks zero-shot / cross-lingual /
# instruct cloning. Default port 50000 inside the container.
EXPOSE 50000

# The model dir is mounted from the host at /models/cosyvoice3. The
# user pre-downloads CosyVoice 3 via huggingface_hub so container
# rebuilds don't redownload ~2 GB. See docker-compose.yml.
CMD ["python", "runtime/python/fastapi/server.py", \
     "--port", "50000", \
     "--model_dir", "/models/cosyvoice3"]
