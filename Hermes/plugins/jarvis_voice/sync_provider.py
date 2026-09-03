"""CosyVoice as a Hermes whole-file TTSProvider — the privacy backstop.

`provider.py` covers the *streaming* path. Hermes has a second, entirely
separate one: `text_to_speech_tool` writes a whole audio file, and it
resolves plugin backends through a different registry
(`agent.tts_registry`, consulted by `_dispatch_to_plugin_provider` at
`tools/tts_tool.py:3271-3284`). A name that registry does not know falls
through the built-in elif chain to the default at the bottom —
**Edge TTS, Microsoft's cloud** (`tools/tts_tool.py:3379-3396`).

So without this module, "no audio leaves the house" was false. Three
ordinary ways in:

1. `CosyVoiceStreamingProvider.available()` returns False (ref WAV or
   transcript missing on the host), so `resolve_streaming_provider`
   returns None and the caller builds the sync pipeline instead
   (`tools/tts_tool.py:4074`).
2. A turn where nothing ever became audible clears the gateway's
   whole-file suppression (`gateway/streaming_tts_consumer.py:303-306`,
   `gateway/run.py:29288`) and auto-TTS speaks the reply as a file. Our
   own design makes that routine: a reply whose clauses all stay under
   `MIN_CLAUSE_CHARS` yields zero bytes and raises nothing.
3. The model calling the `text_to_speech` tool directly.

Registering the same name in both registries closes all three. What it
does NOT close is a `tts.provider` set to anything other than
`cosyvoice`, or an explicit per-call `provider=` override — both select
a different backend before either registry is consulted, and no plugin
can intercept that. See `plugin.yaml`.

Failure is safe here: `synthesize()` raising does not fall through to
Edge. `_dispatch_to_plugin_provider` lets the exception propagate and
`text_to_speech_tool` turns it into an error envelope, so a dead 4090
produces an error, never a stranger's voice.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, List, Optional

from loguru import logger

from . import tts

try:  # Hermes is absent on dev machines that only run the unit tests.
    from agent.tts_provider import TTSProvider
except ImportError:  # pragma: no cover - exercised only without Hermes

    class TTSProvider:  # type: ignore[no-redef]
        """Stand-in for the ABC so the module imports without Hermes.

        Deliberately not an ABC: the real registration path type-checks
        with `isinstance(provider, TTSProvider)` against Hermes' own
        class, so a shim instance is never accepted by Hermes anyway —
        it exists only to keep this file importable and unit-testable.
        """


class CosyVoiceSyncProvider(TTSProvider):
    """Whole-file synthesis through the same CosyVoice server as the streamer."""

    @property
    def name(self) -> str:
        # Must match the streaming provider's registered name and the
        # user's `tts.provider`, or the two paths diverge and one
        # of them is not JARVIS' voice.
        return "cosyvoice"

    @property
    def display_name(self) -> str:
        return "JARVIS (CosyVoice)"

    def is_available(self) -> bool:
        # Same cheap on-disk probe the streamer uses. Must not raise.
        try:
            return tts.is_available()
        except Exception:  # noqa: BLE001 — availability probes never raise
            return False

    def list_voices(self) -> List[dict]:
        # One cloned voice, defined by the reference WAV on disk — there
        # is no catalog to enumerate and no voice id to pass.
        return []

    def synthesize(
        self,
        text: str,
        output_path: str,
        *,
        voice: Optional[str] = None,
        model: Optional[str] = None,
        speed: Optional[float] = None,
        format: str = "mp3",
        **extra: Any,
    ) -> str:
        """Write CosyVoice WAV bytes to `output_path`; return the path written.

        `voice`, `model` and `speed` are ignored: the voice is the
        reference WAV, the model is whatever the 4090 has loaded, and the
        zero-shot endpoint takes no rate control. Per the ABC contract an
        unsupported `format` is answered with the closest thing we have
        (WAV) and a corrected extension, rather than a wrong-format file
        under the requested name.
        """
        del voice, model, speed, extra
        wav_bytes, backend = tts.synth(text)
        if not wav_bytes:
            # tts.synth() returns ("", "empty") for blank input; anything
            # else empty means the server gave us no audio. Raise — the
            # dispatcher turns this into an error envelope. Writing a
            # zero-byte file would look like success.
            raise RuntimeError(
                f"cosyvoice produced no audio for {text[:60]!r} ({backend})"
            )

        path = Path(output_path)
        if path.suffix.lower() != ".wav":
            path = path.with_suffix(".wav")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(wav_bytes)
        logger.info(f"jarvis-voice: wrote {len(wav_bytes)} bytes of WAV to {path}")
        return str(path)
