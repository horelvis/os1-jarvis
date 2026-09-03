"""jarvis-voice — CosyVoice TTS for Hermes, streaming and whole-file."""

from .provider import CosyVoiceStreamingProvider
from .sync_provider import CosyVoiceSyncProvider

__all__ = ["CosyVoiceStreamingProvider", "CosyVoiceSyncProvider"]


def register(ctx):
    """Register both halves of the same voice.

    Hermes keeps two independent TTS registries and consults a different
    one on each path:

    - streaming (`tools.tts_streaming._REGISTRY`) — populated by the
      `@register("cosyvoice")` side effect of importing `.provider`;
    - whole-file (`agent.tts_registry`) — populated here, via
      `ctx.register_tts_provider`.

    Registering only the first left every whole-file path falling
    through to Edge TTS, Microsoft's cloud. See `sync_provider.py`'s
    module docstring for the three ways in.
    """
    ctx.register_tts_provider(CosyVoiceSyncProvider())
    return CosyVoiceStreamingProvider
