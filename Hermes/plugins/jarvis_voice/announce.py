"""The seam where JARVIS says out loud that she has lost her voice.

A turn where CosyVoice produced no audio at all is indistinguishable,
from the sofa, from JARVIS thinking — or from a dead appliance. The
ruling of 2026-08-22 (decision record, finding 4) is that our plugins
fail loudly, and that the announcement is a **pre-recorded clip in
JARVIS' own voice**. Two reasons, both load-bearing:

- A voice plugin that cannot synthesise cannot announce its own
  failure by synthesising. Whatever says "me he quedado sin voz" has to
  already exist as audio on disk before the failure happens.
- Handing the sentence to Hermes' default TTS would mean speaking
  through Microsoft's Edge cloud to say that we do not want to speak
  through anyone's cloud. That is not a fallback; it is the failure.

So there is exactly one acceptable source for these bytes: a file
recorded ahead of time by the same CosyVoice voice. **Do not add a
fallback that synthesises this at failure time, and do not route it
through another provider.** If the clip is absent, this module returns
nothing and the caller raises instead — silence with an exception is
worse than the clip, and better than a stranger's voice.

STATUS: the clip does not exist yet. Recording it needs the CosyVoice
server, which was powered off when this was written. Everything else
here is finished: put the file at `ANNOUNCEMENT_CLIP_PATH`, saying
`ANNOUNCEMENT_TEXT`, and it plays. To produce it:

    python - <<'EOF'
    import asyncio, wave, io
    from pathlib import Path
    from Hermes.plugins.jarvis_voice import tts
    from Hermes.plugins.jarvis_voice.announce import (
        ANNOUNCEMENT_TEXT, ANNOUNCEMENT_CLIP_PATH,
    )
    wav, _ = tts.synth(ANNOUNCEMENT_TEXT)
    with wave.open(io.BytesIO(wav)) as wf:
        assert wf.getframerate() == tts.OUTPUT_SAMPLE_RATE
        assert (wf.getnchannels(), wf.getsampwidth()) == (1, 2)
        pcm = wf.readframes(wf.getnframes())
    out = Path(ANNOUNCEMENT_CLIP_PATH).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(pcm)
    EOF

Listen to it before trusting it. This is the one line she says when
everything else has already failed; a bad take is a bad take forever.
"""

from __future__ import annotations

from pathlib import Path

from loguru import logger

# What the clip says, and the only text it may say. Kept here rather
# than in the recording script so the sentence is reviewable in the
# repo: it is user-facing, it is JARVIS speaking, and it has to read
# like her (personality spec: tuteo, coloquial, one or two sentences,
# no apology for being what she is). It also has to be actionable —
# whoever hears it is the only person who can go and turn the machine
# back on.
ANNOUNCEMENT_TEXT = (
    "Oye, me he quedado sin voz. Sigo aquí, pero la máquina que me la pone no responde."
)

# Headerless int16 little-endian mono PCM at tts.OUTPUT_SAMPLE_RATE —
# the exact format `stream()` yields, so the clip goes straight into
# the same audio path as any other clause with nothing to decode,
# resample or re-wrap. A WAV here would put a 44-byte header in the
# middle of the PCM stream and click.
ANNOUNCEMENT_CLIP_PATH = "~/.jarvis/voices/announcements/sin-voz.pcm"


def announcement_pcm() -> bytes:
    """Return the pre-recorded clip's PCM, or b"" if it is not on disk.

    Never raises. This runs on a path where something has already gone
    wrong; an error here would replace a useful failure with a useless
    one. An empty return is the honest answer and the caller handles it.
    """
    path = Path(ANNOUNCEMENT_CLIP_PATH).expanduser()
    try:
        return path.read_bytes()
    except OSError as exc:
        # Expected today — the clip is not recorded yet (see the module
        # docstring). Logged at warning rather than error because the
        # caller is about to raise, which is the louder signal.
        logger.warning(
            f"jarvis-voice: no announcement clip at {path} "
            f"({exc}); the turn stays silent and raises instead"
        )
        return b""
