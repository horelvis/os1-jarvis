# CosyVoice Overlay

`server.py` is bind-mounted read-only by `docker-compose.yml` over the
upstream FastAPI server. The Dockerfile pins CosyVoice to
`074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc`.

## fp16 autocast (2026-09-19)

`AutoModel`'s default is `fp16=False`, so the server ran the LLM and flow
decoder in fp32 with no tensor cores. The overlay now passes
`fp16=<COSYVOICE_FP16>` (default `1`). This only sets
`torch.cuda.amp.autocast(True)` around inference — the weights stay fp32
on the GPU, so **VRAM does not change** (~5.1 GB either way). Measured on
this 4090, same references and voices:

| texto | fp32 | fp16 |
|---|---|---|
| «Sí.» | 0.42 s | 0.42 s |
| una frase | 0.55 s | 0.51 s |
| tres frases | 1.80 s | 1.52 s |

~15% on anything longer than a clause, nothing on the very short ones.
The fixed cost is ~0.3 s per request. What is still on CPU is small and
deliberate: `campplus.onnx` (27 MB, speaker embedding, hardcoded to
`CPUExecutionProvider` by upstream) and the mel-spectrogram feature
extractor. `speech_tokenizer_v3.onnx` and all of the LLM/flow/hift are
on CUDA. Set `COSYVOICE_FP16=0` to revert.

## Spanish Zero-Shot Fix (2026-09-09)

Reported incident: the September 9 18:40:05 UTC request completed
`session_search` and produced a 642-character final reply. Zero-shot TTS
returned HTTP 200, then failed the chunked read with **zero PCM bytes**.
The reported container traceback was:

```text
server.generate_data
  -> cosyvoice.inference_zero_shot
  -> frontend.text_normalize
  -> en_tn_model.normalize
  -> wetext.TokenParser.load: assert len(input) > 0
```

Read-only inspection of the deployed source confirms that WeText TN runs
its FST when text contains digits, selects English for non-Chinese input,
and passes the tagger result to `TokenParser`. The assertion is on an empty
tagger result, not an empty original reply. The exact offending substring
has not been reproduced; no production text or model requests were used.

Zero-shot now passes the supported `text_frontend=False` argument.
Upstream applies this to both the reply and reference transcript; its early
return preserves the strings exactly and bypasses EN/ZH normalization,
English number expansion, and paragraph splitting. Existing EOP insertion
is unchanged. No exception is swallowed or converted to an empty success.

## Verification And Limits

Offline tests import the real FastAPI app with only the model import
stubbed. They cover multipart input, Spanish accents/digits, default and
custom EOP prompts, deferred reference-file access and successful cleanup,
multiple PCM chunks/clipping, and propagation of a pre-PCM stream failure.

From the repository root, with pytest and the route dependencies available:

```bash
PYTHONNOUSERSITE=1 tts-server/.venv/bin/python -m pytest tts-server/cosyvoice/tests
```

The local TTS venv has route dependencies but not pytest; the tests also run
with `python -m unittest discover -s tts-server/cosyvoice/tests`.

Only zero-shot changes. Other inference modes retain their existing
normalization. Skipping the frontend also skips upstream text splitting;
callers must continue sending bounded clauses. Number pronunciation and
audio quality require a coordinated real synthesis check. Existing streaming
errors still occur after HTTP 200, and background tempfile cleanup on a
failed stream is an existing limitation, not fixed here.

## Deployment (Not Executed)

After coordination, recreate just this service to reload the bind-mounted
overlay (also refreshes the mount if the editor replaced the host inode):

```bash
docker compose -f tts-server/cosyvoice/docker-compose.yml up -d --no-deps --force-recreate cosyvoice
```

No image rebuild is required. Recreating interrupts TTS and reloads the model;
coordinate the window and a Spanish-with-digits audio check first. A healthy
`/docs` response alone does not prove synthesis works.
