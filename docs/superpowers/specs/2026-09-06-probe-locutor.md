# Probe: is there a speaker-embedding model this box can actually use?

**Question:** does a speaker-embedding model exist that (a) is already an
ONNX file whose graph goes straight from raw audio to a vector — no
external fbank/mel front end, no torch anywhere in the chain — (b)
carries a licence that permits use in a private household, and (c) runs
fast enough on this box's CPU for a real-time turn?

**Verdict: yes.** `pyannote/embedding`, exported to ONNX, takes raw
16 kHz mono audio directly — its SincNet front end is convolutions baked
into the graph itself, not a separately-computed feature matrix — is
MIT-licensed, and answers a 3-second utterance in ~2.3 ms of CPU time.
**Chosen. No new dependency is needed anywhere: `onnxruntime` and numpy
are enough.**

## Revision note (fix round 1)

The first version of this document chose CAM++ (3D-Speaker), which needs
an 80-dim fbank feature matrix rather than raw audio, and named
`kaldi-native-fbank` as the library to compute it. The instruction that
reached this task at the time was that the dependency was ruled out; a
raw-audio alternative was asked for. This revision found one —
`pyannote/embedding` — and it is chosen below.

## Correction (fix round 2)

**CAM++ was never disqualified, and the previous revision said it was.**
The instruction to look for an alternative was exactly that — a request
to look, not a ruling against the dependency. The user's own words, once
they reached this document: *"no he dicho cero dependencia, solo buscar
alternativa"* ("I didn't say zero dependency, only to look for an
alternative"). `kaldi-native-fbank` was never forbidden; a candidate that
needs no front end at all was found regardless, and it is better on both
axes that matter here — no dependency, and roughly eight times faster.

So: **CAM++'s licence chain is clean and its measurements stand. It is
not chosen, and it was never rejected or declined.** `pyannote/embedding`
is the better candidate on the numbers, not the last one standing. The
sections below restore CAM++ and WeSpeaker's full licence sourcing,
quoted with URLs to the same standard the chosen model gets, so whoever
reads this later can weigh CAM++ on its own merits rather than being
told — wrongly, as this document said in fix round 1 — that it was
ruled out.

## What was checked, this round

The three self-supervised `*-sv` architectures the coordinator named
(wav2vec2 / WavLM / UniSpeech-SAT), plus the one that actually turned out
to fit: pyannote's SincNet-based x-vector model, also raw-waveform from
the ground up but far smaller than a wav2vec2-family transformer.

- **`microsoft/wavlm-base-plus-sv`** — raw-waveform input (a
  Wav2Vec2-style CNN feature encoder is the first layers of the graph
  itself, so no external front end either). **Disqualified: no licence
  is declared anywhere.** Checked the Hugging Face API's `tags` field
  (no `license:*` tag), `cardData` (`{"language": ["en"], "tags":
  ["speech"]}`, no `license` key) and the model card text itself
  (https://huggingface.co/microsoft/wavlm-base-plus-sv/raw/main/README.md)
  — no licence is mentioned anywhere in it. Per this task's own rule, "a
  licence that cannot be determined disqualifies the model" — recorded
  and dropped, not assumed permissive.
- **`microsoft/unispeech-sat-base-plus-sv`** and
  **`microsoft/unispeech-sat-base-sv`** — same architecture family, same
  check, same result: no `license` tag, no `license` key in `cardData`,
  nothing found. **Disqualified for the same reason.** (An ONNX export
  of either was not even searched for once the licence question failed —
  a licence that cannot be determined disqualifies the model regardless
  of whether an export exists.)
- **`pyannote/embedding`, ONNX export** — see below. **Qualifies.**

## The chosen model

**File:** `~/.jarvis/models/pyannote_embedding.onnx`
**Size:** 17,631,302 bytes (17.6 MB)
**sha256:** `278528694f907ed19a59a76220dde2060c0f61e0f3956ae8d52f4fe617a39ca9`
(recorded by this task; unlike the CAM++ release there is no
independently-published checksum file to verify it against — noted so
nobody mistakes this for the same level of provenance as the other
candidates below).

**Where it comes from:**
- The weights: `pyannote/embedding` on Hugging Face
  (https://huggingface.co/pyannote/embedding) — a canonical x-vector
  TDNN with a **trainable SincNet filterbank as its own first layer**,
  trained on VoxCeleb by the pyannote.audio project. SincNet learns a set
  of band-pass filters and convolves them directly over raw waveform
  samples — it is a *learned* front end that is part of the network,
  not a fixed, externally-computed fbank/mel matrix. That architectural
  fact is what makes a raw-audio ONNX export possible at all.
- The ONNX export: `deepghs/pyannote-embedding-onnx`
  (https://huggingface.co/deepghs/pyannote-embedding-onnx), a mirror
  that bundles the whole graph — SincNet layers included — into one
  `model.onnx`, ungated, downloaded directly with no login or terms
  acceptance.
- **A gating note, so it isn't mistaken for a licence problem:** the
  original `pyannote/embedding` repository is access-gated on Hugging
  Face (`"gated": "auto"` in its API metadata) — a sign-up form Hugging
  Face puts in front of the download, for usage telemetry, not a licence
  restriction (its own card states this explicitly, quoted below). The
  ONNX mirror this task used is **not** gated, so no account or
  agreement was needed to obtain the file used here. Worth recording:
  someone reproducing this from the original repository, rather than the
  mirror, will hit that form.

**Licence, quoted, with the URLs it was read from:**
- The Hugging Face model card's own licence field, for both the original
  weights and the ONNX mirror, read from their APIs:
  - `pyannote/embedding` (https://huggingface.co/api/models/pyannote/embedding),
    field `cardData.license`: `"mit"`
  - `deepghs/pyannote-embedding-onnx`
    (https://huggingface.co/api/models/deepghs/pyannote-embedding-onnx),
    field `cardData.license`: `"mit"`
- The actual MIT text, from the toolkit that trained it,
  `pyannote/pyannote-audio`
  (https://raw.githubusercontent.com/pyannote/pyannote-audio/develop/LICENSE):
  > `MIT License`
  >
  > `Copyright (c) 2020 CNRS`
  >
  > `Permission is hereby granted, free of charge, to any person obtaining a copy...`

  Permissive, attribution-only (the copyright notice must be kept in
  copies), no field-of-use restriction. Nothing here forbids use in a
  private household.

## The input contract, in full

- **Sample rate:** 16 kHz. (The model was trained at 16 kHz; nothing in
  the graph resamples, so audio at another rate must be resampled before
  it is handed in — this project's audio path is already 16 kHz
  throughout, so this is a non-issue in practice.)
- **Channels:** mono. The tensor has no channel axis at all — see shape,
  below — so a stereo signal must be mixed down to one channel first.
  This project's microphone path is already mono (`audio.py`,
  `vad.py`, `stt.py`).
- **Dtype:** **32-bit floating point** (`float32` — ONNX reports this as
  `tensor(float)`, which is the same thing in plainer words), in
  roughly the `[-1, 1]` range. Raw PCM in this codebase arrives as
  **16-bit signed integers**, and every existing consumer converts the
  same way — `vad.py:211-212` and `stt.py:127` both do
  `np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0`.
  This model wants exactly that same conversion; no new conversion code
  is needed, only reuse of the one that already exists.
- **Tensor shape:** input named `waveform`, shape `('batch', 'frames')`
  — **both dimensions are symbolic**, i.e. fully dynamic: batch size is
  not fixed at 1, and the number of samples is not fixed to any
  particular utterance length. Output named `embeddings`, shape
  `('batch', 512)` — batch dynamic, the embedding width fixed at 512.
- **Variable length: tolerated, down to a measured floor.** This was
  measured directly, not inferred from the symbolic `T` — see below —
  rather than assumed from the shape alone.
- **Minimum duration:** somewhere between 4,000 samples (0.25 s) and
  4,800 samples (0.30 s). Below that floor the graph itself raises an
  `onnxruntime` shape error inside a `Conv` node — it does not silently
  return a meaningless vector, which is a useful safety property.
  Everything from 4,800 samples (0.30 s) up through 160,000 samples
  (10 s, the longest tested) returned a finite `(1, 512)` vector.
- **No maximum was found** in the range tested (up to 10 s); nothing in
  the architecture suggests one exists for utterances of the length a
  voice turn would produce.
- **Output is not L2-normalized by the graph.** The measured vector norm
  varied (roughly 1600–2200 across different lengths of noise, see the
  table below) — a consumer computing cosine similarity should normalize
  both sides itself; comparing raw dot products or un-normalized
  Euclidean distance would be a mistake. (This is Task 3's concern, not
  this probe's — recorded here so it is not missed.)

**Length-behaviour measurement, the script and its exact output:**

```python
# scratch measurement only, run then deleted — reproduce with:
# PYTHONNOUSERSITE=1 widget/.venv/bin/python <this file>
import numpy as np
import onnxruntime as ort

PATH = "/home/nexus/.jarvis/models/pyannote_embedding.onnx"
sess = ort.InferenceSession(PATH, providers=["CPUExecutionProvider"])
in_name = sess.get_inputs()[0].name
print("input:", sess.get_inputs()[0].name, sess.get_inputs()[0].shape, sess.get_inputs()[0].type)
print("output:", sess.get_outputs()[0].name, sess.get_outputs()[0].shape, sess.get_outputs()[0].type)

rng = np.random.default_rng(0)
for d in [0.05, 0.1, 0.2, 0.5, 1.0, 2.0, 3.0, 5.0, 10.0]:
    n = int(16000 * d)
    wav = rng.normal(0, 0.01, n).astype(np.float32)[np.newaxis, :]
    try:
        out = sess.run(None, {in_name: wav})[0]
        print(f"{d:>5.2f}s ({n:>6} samples) -> shape {np.asarray(out).shape}, "
              f"finite={np.all(np.isfinite(out))}, norm={np.linalg.norm(out):.3f}")
    except Exception as e:
        print(f"{d:>5.2f}s ({n:>6} samples) -> ERROR: {e}")
```

Output:

```
input: waveform ['batch', 'frames'] tensor(float)
output: embeddings ['batch', 512] tensor(float)
 0.05s (   800 samples) -> ERROR: ... Conv node ... Invalid input shape: {4}
 0.10s (  1600 samples) -> ERROR: ... FusedConv node ... Invalid input shape: {3}
 0.20s (  3200 samples) -> ERROR: ... FusedConv node ... Invalid input shape: {1}
 0.50s (  8000 samples) -> shape (1, 512), finite=True, norm=1805.480
 1.00s ( 16000 samples) -> shape (1, 512), finite=True, norm=2241.488
 2.00s ( 32000 samples) -> shape (1, 512), finite=True, norm=1927.910
 3.00s ( 48000 samples) -> shape (1, 512), finite=True, norm=1640.411
 5.00s ( 80000 samples) -> shape (1, 512), finite=True, norm=1951.603
10.00s (160000 samples) -> shape (1, 512), finite=True, norm=1667.295
```

**Minimum-duration bisection, the script and its exact output** (noise
floor between failure and success):

```python
# scratch measurement only, run then deleted — same session/model as above
for n in [3200, 4000, 4800, 5600, 6400, 7200, 7500, 7800, 7900, 8000]:
    wav = rng.normal(0, 0.01, n).astype(np.float32)[np.newaxis, :]
    try:
        out = sess.run(None, {in_name: wav})[0]
        print(f"{n:>6} samples ({n/16000:.4f}s) -> OK shape {np.asarray(out).shape}")
    except Exception as e:
        print(f"{n:>6} samples ({n/16000:.4f}s) -> ERROR: {str(e).splitlines()[-1]}")
```

Output:

```
  3200 samples (0.2000s) -> ERROR: ... Invalid input shape: {1}
  4000 samples (0.2500s) -> ERROR: ... Invalid input shape: {4}
  4800 samples (0.3000s) -> OK shape (1, 512)
  5600 samples (0.3500s) -> OK shape (1, 512)
  6400 samples (0.4000s) -> OK shape (1, 512)
  7200 samples (0.4500s) -> OK shape (1, 512)
  7500 samples (0.4688s) -> OK shape (1, 512)
  7800 samples (0.4875s) -> OK shape (1, 512)
  7900 samples (0.4938s) -> OK shape (1, 512)
  8000 samples (0.5000s) -> OK shape (1, 512)
```

Both scripts construct an `ort.InferenceSession` against
`~/.jarvis/models/pyannote_embedding.onnx` with
`providers=["CPUExecutionProvider"]`, feed
`np.random.default_rng(0).normal(0, 0.01, n).astype(np.float32)` reshaped
to `(1, n)`, and either print the output shape/norm or catch and print
the `onnxruntime` exception. They were scratch measurement scripts, run
and then deleted — not part of the deliverable, per the same rule
applied to the probe itself (the probe in `widget/tools/probe_locutor.py`
already answers the base "does it load, what shape, how long" questions
on its own, verbatim from the brief; these extended it only to answer
the length question the review asked for).

## Output

**512-dimensional** embedding, dtype **float32**, shape `(1, 512)` for a
single utterance. Not pre-normalized (see above).

## The probe, run as given, unmodified

The brief's probe needed no changes for this model — it already feeds
raw PCM, which is exactly what this model wants:

```
$ PYTHONNOUSERSITE=1 widget/.venv/bin/python widget/tools/probe_locutor.py \
    ~/.jarvis/models/pyannote_embedding.onnx
modelo: /home/nexus/.jarvis/models/pyannote_embedding.onnx (17.6 MB)
  entrada: waveform ['batch', 'frames'] tensor(float)
  salida:  embeddings ['batch', 512] tensor(float)
  embedding: (1, 512) en 3 ms
```

Unlike CAM++, this run does not fail — the probe's own 3-second silent
utterance is exactly a valid input, and the whole pipeline (load, shape
report, one inference) completes with no exception.

## Measured CPU cost, with its transcript

The probe's own single run above shows 3 ms, but a single timed call
includes `onnxruntime`'s first-call overhead (thread pool spin-up,
kernel selection). Ten repeated inferences on the same 3-second silent
input, same session, same script pattern as before, give a cleaner
number:

```python
n = 16000 * 3
wav = np.zeros((1, n), dtype=np.float32)
times = []
for i in range(10):
    t0 = time.monotonic()
    sess.run(None, {in_name: wav})
    times.append((time.monotonic() - t0) * 1000)
print("all runs (ms):", [f"{t:.1f}" for t in times])
print(f"first run: {times[0]:.1f} ms, min of rest: {min(times[1:]):.1f} ms, "
      f"mean of rest: {sum(times[1:])/len(times[1:]):.1f} ms")
```

Output:

```
--- repeated timing at 3.0s (10 runs, CPUExecutionProvider) ---
all runs (ms): ['2.3', '2.3', '2.2', '2.3', '2.3', '2.2', '2.3', '2.2', '2.4', '2.2']
first run: 2.3 ms, min of rest: 2.2 ms, mean of rest: 2.3 ms
```

**~2.3 ms per 3-second utterance, CPU, no feature-extraction step at
all** — there is nothing to time separately, because the front end is
inside the ONNX graph itself. Session construction
(`ort.InferenceSession(...)`) is a separate one-time cost of a few tens
of ms at process start, not paid per utterance, same as every other
model in this project.

## The other candidate: CAM++ (3D-Speaker), sound but not chosen

This is the model the first version of this document chose. It remains
a valid candidate — its licence chain is clean and its measurements are
real — and it is documented here to the same standard as
`pyannote/embedding`, so a later reader can weigh it on its own merits
rather than take this document's word that something else won.

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

**Input contract:** an 80-dimensional log-mel filterbank (fbank) matrix,
shape `(N, T, 80)`, not raw audio — running the probe with raw 16 kHz PCM
fails immediately with `Invalid rank for input: x Got: 2 Expected: 3`.
Computing that matrix needs something beyond `onnxruntime` and numpy —
`kaldi-native-fbank` (PyPI, Apache-2.0, zero dependencies) was the
candidate found for it, measured at 3.7 ms for a 3-second utterance.
That front end is real, licensed, and cheap — it was simply not needed
once a candidate that requires no front end at all was found.

**A second CAM++ export, also verified working**, kept as a further
fallback:
- **File:** `~/.jarvis/models/wespeaker_en_voxceleb_campplus.onnx`,
  29,292,684 bytes, sha256
  `c46fad10b5f81e1aa4a60c162714208577093655076c5450f8c469e522ec54ef`
  (matches upstream `checksum.txt`).
- **Source:** WeSpeaker's own CAM++ recipe, trained on VoxCeleb
  (English), exported by the same `k2-fsa/sherpa-onnx` release.
- **Licence, quoted, with the URL it was read from** — WeSpeaker's own
  `LICENSE` (https://github.com/wenet-e2e/wespeaker/blob/master/LICENSE):
  > `Apache License` `Version 2.0, January 2004`
- **Input:** same shape of thing, named `feats` instead of `x`,
  `('B', 'T', 80)`.
- **Output:** 512-dimensional embedding, `('B', 512)`.
- **Measured:** fbank extraction 2.2 ms + inference 12.1 ms ≈ 14.3 ms
  total for a 3-second utterance.

## Side-by-side against CAM++'s fbank path

Set out so CAM++ can be weighed against the chosen model with real
numbers, not asserted away:

| | pyannote/embedding (chosen) | CAM++ zh/en + fbank | WeSpeaker CAM++ + fbank |
|---|---|---|---|
| input | raw waveform, `(batch, frames)` | 80-dim fbank matrix | 80-dim fbank matrix |
| extra dependency needed | none | `kaldi-native-fbank` (Apache-2.0, available, not installed) | same |
| file size | 17.6 MB | 28.3 MB | 29.3 MB |
| output dim | 512 | 192 | 512 |
| feature-extraction cost | — (baked into the graph) | 3.7 ms | 2.2 ms |
| inference cost | 2.3 ms | 15.0 ms | 12.1 ms |
| **total per 3 s utterance** | **~2.3 ms** | **~18.7 ms** | **~14.3 ms** |
| licence | MIT (quoted above) | Apache-2.0 (three sources quoted above, all agree) | Apache-2.0 (quoted above) |

`pyannote/embedding` wins on both axes that were being weighed: it needs
no extra dependency, and it is roughly **8× faster** once CAM++'s
feature-extraction step is counted. That is why it is chosen — not
because CAM++ failed a requirement. CAM++ remains a sound fallback: if
`pyannote/embedding` turns out to separate Spanish voices poorly in
Task 4's real-voice test, CAM++'s numbers above are what the trade would
cost.

**One honesty note that still applies:** the CAM++ zh/en model's
suitability for a Spanish-speaking household was never measured — only
guessed at, on the reasoning that its broader multi-corpus training
(VoxCeleb + CNCeleb + 3D-Speaker) should generalize better to an unheard
language than a single-corpus English model. That reasoning was **a
hypothesis, not a measurement**. `pyannote/embedding`'s own
generalization to Spanish speech is *equally* untested here, for the
same reason: 3 seconds of synthetic noise proves shapes, timing and the
minimum-duration floor, nothing about whether two family members' real
voices actually separate in either embedding space. That is Task 4's
job, unchanged from before.

## Plain verdict

**Yes — and the chosen candidate wins on its own merits, not because the
alternative was ruled out.** `pyannote/embedding` (ONNX,
`~/.jarvis/models/pyannote_embedding.onnx`) takes raw 16 kHz mono
float32 audio directly, needs no fbank, no `kaldi-native-fbank`, no
hand-written feature code, and no torch anywhere in the chain; it is
MIT-licensed with the copyright notice quoted above; it produces a
512-dimensional embedding in roughly an eighth the time CAM++'s fbank
path needed once feature extraction is counted. **No new entry belongs
in `widget/pyproject.toml`** — `onnxruntime` and `numpy`, already there,
are enough. CAM++ (3D-Speaker) was never disqualified — its licence
chain is clean, quoted with URLs above, and it remains a documented
fallback if Task 4 finds a reason to prefer it.

The self-supervised alternatives the coordinator named (WavLM-SV,
UniSpeech-SAT-SV) were checked and dropped on licence grounds alone —
none publishes one, anywhere findable, and this task's own rule treats
"cannot be determined" as a disqualification, not a "probably fine".

What remains untested, by design: whether this embedding actually tells
two real household voices apart. That is Task 4, not this one.
