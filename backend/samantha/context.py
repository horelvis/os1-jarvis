"""Context assembly helpers — shared between api.py and voice_pipeline.py.

Extracted from api.py to prevent a circular import when voice_pipeline
imports from both api (for gather_context) and samantha modules.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .memory import Memory, MemoryChunk


def _collect_facts(mem: "Memory", *, user_id: str) -> list[dict]:
    """Gather facts surfaced into the system prompt.

    Order: name → Big-Five traits → onboarding_completed_at.
    """
    from .profile import BIG5_FACT_KINDS

    kinds = ("name", *BIG5_FACT_KINDS, "onboarding_completed_at")
    out: list[dict] = []
    for kind in kinds:
        f = mem.get_fact(kind, user_id=user_id)
        if f is not None:
            out.append(f)
    return out


async def gather_context(
    mem: "Memory", message: str, user_id: str
) -> "tuple[list[dict], list[MemoryChunk], list[MemoryChunk]]":
    """Collect facts + recall + short-term and persist the user turn,
    off the event loop (embedding + ChromaDB + SQLite are sync/CPU-bound).

    Ordering matters: context FIRST, remember AFTER, so the ring never
    contains the current message when the LLM sees it.
    """
    from .config import config

    def _work() -> "tuple[list[dict], list[MemoryChunk], list[MemoryChunk]]":
        facts = _collect_facts(mem, user_id=user_id)
        recall = mem.recall(message, k=config.memory_top_k, user_id=user_id)
        short = mem.short_term(user_id=user_id)
        mem.remember("user", message, user_id=user_id)
        return facts, recall, short

    return await asyncio.to_thread(_work)
