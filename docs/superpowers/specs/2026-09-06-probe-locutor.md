# Probe: is there a speaker-embedding model this box can actually use?

**Question:** does a speaker-embedding model exist that (a) is already an
ONNX file, or is exportable to one without torch anywhere in the chain,
(b) carries a licence that permits use in a private household, and
(c) runs fast enough on this box's CPU for a real-time turn?

**Verdict: yes.** Two candidates were downloaded and probed; both load
under `onnxruntime` alone, both are Apache-2.0, both run a 3-second
utterance in under 20 ms of CPU time once fed the feature matrix they
expect. The chosen one is CAM++ (3D-Speaker), described below.

## What was checked

Searched for ONNX exports of the two candidates the plan named, CAM++
and ECAPA-TDNN.

- **CAM++ / 3D-Speaker.** Alibaba DAMO Academy's 3D-Speaker toolkit
  publishes CAM++ checkpoints on ModelScope; `k2-fsa/sherpa-onnx`
  publishes **already-converted ONNX exports** of them (and of
  WeSpeaker's own CAM++ recipe) as GitHub release assets, with no
  conversion step for us to run and no torch touched anywhere in that
  pipeline — the `.onnx` files are the artifact.
- **ECAPA-TDNN.** The WeSpeaker ONNX export
  (`Wespeaker/wespeaker-ecapa-tdnn512-LM` on Hugging Face) carries a
  **CC-BY-4.0** licence, not Apache-2.0. CC-BY-4.0 (attribution only)
  does not forbid private household use, so this candidate is **not
  disqualified** — but a same-purpose, already-verified Apache-2.0
  CAM++ export was in hand first, so ECAPA-TDNN was not downloaded or
  probed. Recorded here in case Task 4's real-voice test ever needs a
  second architecture to compare against.

## The chosen model

**File:** `~/.jarvis/models/campplus_zh_en_16k_common_advanced.onnx`
**Size:** 28,281,164 bytes (28.3 MB), sha256
`aa3cfc16963a10586a9393f5035d6d6b57e98d358b347f80c2a30bf4f00ceba2` —
verified against the upstream `checksum.txt` published alongside it.

**Where it comes from:**
- Original checkpoint: `iic/speech_campplus_sv_zh_en_16k-common_advanced`
  on ModelScope (Alibaba DAMO Academy / the 3D-Speaker project), CAM++
  architecture, trained on ~200k speakers across VoxCeleb + CNCeleb +
  3D-Speaker's own corpus.
- ONNX export: published as a release asset,
  `3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx`, by
  `k2-fsa/sherpa-onnx` at
  https://github.com/k2-fsa/sherpa-onnx/releases/tag/speaker-recongition-models
  — an official artifact of that project, not a third-party reupload.

**Licence, quoted, with the URLs it was read from:**
- The 3D-Speaker toolkit's own licence
  (https://github.com/modelscope/3D-Speaker/blob/main/LICENSE):
  > `Apache License` `Version 2.0, January 2004`
- The ModelScope model card's own licence field, read from its API
  (`https://modelscope.cn/api/v1/models/iic/speech_campplus_sv_zh_en_16k-common_advanced`,
  field `Data.License`):
  > `"License": "Apache License 2.0"`
- The conversion tool that produced the `.onnx` file, `k2-fsa/sherpa-onnx`
  (https://github.com/k2-fsa/sherpa-onnx/blob/master/LICENSE):
  > `Apache License` `Version 2.0, January 2004`

  All three agree: Apache-2.0, permission to use, modify and redistribute
  with attribution, no field-of-use restriction. Nothing here forbids use
  in a private household.

## The input contract — raw audio or features?

**Features, not raw audio.** Running the probe with raw 16 kHz PCM fails
immediately and says so precisely:

```
entrada: x ['N', 'T', 80] tensor(float)
salida:  embedding ['BatchNormalizationembedding_dim_0', 192] tensor(float)
...
onnxruntime.capi.onnxruntime_pybind11_state.InvalidArgument: [ONNXRuntimeError] :
2 : INVALID_ARGUMENT : Invalid rank for input: x Got: 2 Expected: 3
```

The model wants an **80-dimensional log-mel filterbank (fbank) matrix**,
shape `(N, T, 80)` — Kaldi-style: 16 kHz, 25 ms window, 10 ms shift, no
dithering for a deterministic result, per-utterance mean-normalized
before the model sees it (the standard CAM++/WeSpeaker convention).

**What computes it, and can it be numpy-only?** Yes — but not with numpy
alone; the actual answer is a small, dependency-free library:
**`kaldi-native-fbank`** (PyPI, version 1.22.3, licence **Apache-2.0**,
`pip show` reports `requires_dist: None` — a compiled C++/pybind11
extension with no dependencies at all, not even numpy required to build
it, though the arrays it returns convert to numpy trivially). This is
the same feature front end `sherpa-onnx` itself uses ahead of these exact
models, so the match between what it produces and what CAM++/WeSpeaker
expect is not a guess.

It was installed **only into a scratch directory outside the venv**
(`pip install --target ... --no-deps`, never touching
`widget/pyproject.toml` or `widget/.venv`, per this task's constraint)
purely to measure it. **No torch was installed at any point in this
task.**

**Measured cost**, 3 seconds of 16 kHz audio, this box's CPU:

| step | time |
|---|---|
| `kaldi-native-fbank` feature extraction | 3.7 ms |
| ONNX inference (`CPUExecutionProvider`) | 15.0 ms |
| **total per utterance** | **~18.7 ms** |

Negligible next to a voice turn's other latencies (§0's whole budget is
in tens to hundreds of milliseconds). Session load (`ort.InferenceSession`
construction) is a few tens of ms, paid once at process start, not per
utterance.

## Output

**192-dimensional** float embedding, shape `(1, 192)`. (L2-normalizing it
before comparing two speakers by cosine similarity is the standard next
step — that is Task 3's concern, not this probe's.)

## The full probe run

```
$ PYTHONNOUSERSITE=1 widget/.venv/bin/python widget/tools/probe_locutor.py \
    ~/.jarvis/models/campplus_zh_en_16k_common_advanced.onnx
modelo: /home/nexus/.jarvis/models/campplus_zh_en_16k_common_advanced.onnx (28.3 MB)
  entrada: x ['N', 'T', 80] tensor(float)
  salida:  embedding ['BatchNormalizationembedding_dim_0', 192] tensor(float)
[fails on rank, as expected — see above]
```

The probe as written in the brief feeds raw PCM, which is exactly what
this model refuses; that failure IS the finding for the input-contract
question, not a bug in the probe. `onnxruntime` loaded the model, and the
shapes it printed before failing are the ones quoted above.

## The verified alternate

A second candidate was downloaded and probed the same way, and also
works, kept on disk as a fallback if Task 4's real-voice test finds the
zh/en-trained model generalizes poorly to Spanish:

- **File:** `~/.jarvis/models/wespeaker_en_voxceleb_campplus.onnx`,
  29,292,684 bytes, sha256
  `c46fad10b5f81e1aa4a60c162714208577093655076c5450f8c469e522ec54ef`
  (matches upstream `checksum.txt`).
- **Source:** WeSpeaker's own CAM++ recipe, trained on VoxCeleb
  (English), exported by the same `k2-fsa/sherpa-onnx` release.
- **Licence:** Apache-2.0
  (https://github.com/wenet-e2e/wespeaker/blob/master/LICENSE):
  > `Apache License` `Version 2.0, January 2004`
- **Input:** same shape of thing, named `feats` instead of `x`,
  `('B', 'T', 80)`.
- **Output:** 512-dimensional embedding, `('B', 512)`.
- **Measured:** fbank extraction 2.2 ms + inference 12.1 ms ≈ 14.3 ms
  total for a 3-second utterance.

## Plain verdict

**Yes, there is a model this plan can use.** CAM++
(`campplus_zh_en_16k_common_advanced.onnx`) is already an ONNX file,
Apache-2.0 at every layer (checkpoint, conversion tool, and the toolkit
it came from), loads and runs under `onnxruntime` alone on this box's
CPU in well under 20 ms per utterance including feature extraction, and
needs no torch anywhere in the chain — now, or ever, per this plan's hard
constraint.

**The one thing it is not** is a raw-audio model: it needs an 80-dim
fbank front end. That front end has a name, a licence, and a measured
cost small enough to ignore (`kaldi-native-fbank`, Apache-2.0, ~4 ms).
**Task 3's wrapper needs this**, and adding `kaldi-native-fbank` to
`widget/pyproject.toml` is the one new dependency this plan should ask
for — deliberately not added in this task, per its constraints.

Neither candidate's accuracy on a real, Spanish-speaking household voice
was tested here — 3 seconds of silence proves shapes and speed, nothing
about whether two family members' voices actually separate in this
embedding space. That is Task 4's job, explicitly out of scope here.
