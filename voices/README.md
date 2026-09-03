# voices/ — Samantha reference voice

Source assets for CosyVoice 3 zero-shot voice cloning (see
`backend/samantha/config.py`, `tts_cosyvoice_ref_*`):

- `samantha.wav` — ~8 s reference recording of Samantha's voice.
- `samantha.txt` — LITERAL transcript of the WAV. CosyVoice 3
  conditions prosody on this text (`inference_zero_shot`); if the WAV
  is re-recorded, this file MUST be updated to match word-for-word.

## Deploy

The backend loads these from `~/.samantha/voices/ref/`, not from the
repo. Copy on each box that runs the backend:

```bash
mkdir -p ~/.samantha/voices/ref
cp voices/samantha.wav voices/samantha.txt ~/.samantha/voices/ref/
```

Override paths via `JARVIS_TTS_COSYVOICE_REF_WAV` /
`JARVIS_TTS_COSYVOICE_REF_TRANSCRIPT_PATH` if they live elsewhere.
