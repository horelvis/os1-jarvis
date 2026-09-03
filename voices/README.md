# voices/ — JARVIS reference voice

Source assets for CosyVoice 3 zero-shot voice cloning (see
`backend/samantha/config.py`, `tts_cosyvoice_ref_*`):

- `jarvis-ref.wav` — ~8 s reference recording of JARVIS' voice.
- `jarvis-ref.txt` — LITERAL transcript of the WAV. CosyVoice 3
  conditions prosody on this text (`inference_zero_shot`); if the WAV
  is re-recorded, this file MUST be updated to match word-for-word.

## Deploy

The backend loads these from `~/.jarvis/voices/ref/`, not from the
repo. Copy on each box that runs the backend:

```bash
mkdir -p ~/.jarvis/voices/ref
cp voices/jarvis-ref.wav voices/jarvis-ref.txt ~/.jarvis/voices/ref/
```

Override paths via `JARVIS_TTS_COSYVOICE_REF_WAV` /
`JARVIS_TTS_COSYVOICE_REF_TRANSCRIPT_PATH` if they live elsewhere.
