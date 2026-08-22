"""CosyVoice as a Hermes StreamingTTSProvider.

Yields raw int16 little-endian mono PCM at 24 kHz — the format
CosyVoice already emits, so nothing is resampled.
"""

from __future__ import annotations

from typing import Dict, Iterator

from loguru import logger

from samantha import tts

from .bridge import iter_sync
from .chunking import safe_clauses

try:  # Hermes is absent on dev machines that only run the unit tests.
    from tools.tts_streaming import StreamingTTSProvider, register
except ImportError:  # pragma: no cover - exercised only without Hermes
    # Minimal shim matching Contract 1's __init__ exactly (see
    # docs/superpowers/specs/hermes-contracts-v0.20.5.md). Plain `object`
    # doesn't work here: `object.__init__` rejects the extra positional
    # args a `super().__init__(tts_config, section)` call would pass it.
    class StreamingTTSProvider:  # type: ignore[no-redef]
        def __init__(self, tts_config: Dict, section: Dict) -> None:
            self.tts_config = tts_config
            self.section = section

    def register(_name):
        return lambda cls: cls


MIN_CLAUSE_CHARS = 40


class CosyVoiceStreamingProvider(StreamingTTSProvider):
    sample_rate: int = tts.OUTPUT_SAMPLE_RATE
    channels: int = 1
    sample_width: int = 2

    def __init__(self, tts_config: Dict, section: Dict) -> None:
        # Contract 1 (docs/superpowers/specs/hermes-contracts-v0.20.5.md):
        # Hermes constructs every StreamingTTSProvider with these two
        # positional args and expects them stored as-is.
        super().__init__(tts_config, section)
        # (clause_text, pcm_bytes_yielded) in emission order. Plan 3
        # turns this into milliseconds to trim an interrupted reply to
        # what the user actually heard — see spec §6. Every clause
        # attempted is recorded here, including one that failed and
        # yielded zero bytes.
        self.bytes_yielded_per_clause: list[tuple[str, int]] = []

    @staticmethod
    def available() -> bool:
        return tts.is_available()

    def stream(self, text: str) -> Iterator[bytes]:
        for clause in safe_clauses([text], min_chars=MIN_CLAUSE_CHARS):
            emitted = 0
            try:
                for chunk in iter_sync(lambda c=clause: _pcm_only(c)):
                    emitted += len(chunk)
                    yield chunk
            except RuntimeError as exc:
                # tts.py raises this when CosyVoice returns 200 with no
                # audio. Losing one clause beats losing the whole reply.
                logger.warning(f"samantha-voice: clause failed, skipping — {exc}")
            finally:
                self.bytes_yielded_per_clause.append((clause, emitted))


async def _pcm_only(clause: str):
    """Drop tts.stream()'s backend label; the provider only wants bytes."""
    async for chunk, _backend in tts.stream(clause):
        yield chunk


CosyVoiceStreamingProvider = register("cosyvoice")(CosyVoiceStreamingProvider)
