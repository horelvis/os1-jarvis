"""samantha-voice — CosyVoice streaming TTS for Hermes."""

from .provider import CosyVoiceStreamingProvider

__all__ = ["CosyVoiceStreamingProvider"]


def register(ctx):
    """Importing .provider performs the @register('cosyvoice') side effect."""
    del ctx
    return CosyVoiceStreamingProvider
