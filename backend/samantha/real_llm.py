"""Real LLM client — talks to a local OpenAI-compatible server.

The default target is `llama-server` from llama.cpp (`config.llm_server_url`).
Anything that speaks OpenAI's `/v1/chat/completions` works here: vLLM,
LM Studio, an OpenAI-compat shim around Ollama, etc.

The contract is the same as `mock_llm`:
  - `generate_reply(message)`   → full text (awaitable)
  - `stream_reply(message)`     → async iterator of token chunks

Errors don't crash the request loop. If the LLM server is down or hangs,
the caller gets a short, in-character apology so the UI stays usable.
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, AsyncIterator

import httpx
from loguru import logger

from .config import config
from .personality import SYSTEM_PROMPT, SYSTEM_PROMPT_VERSION

if TYPE_CHECKING:
    from .memory import MemoryChunk


_FALLBACK_REPLY = (
    "He perdido el hilo un momento. Dame un segundo y vuelve a decírmelo."
)

_client: httpx.AsyncClient | None = None


def _format_memories(memories: "list[MemoryChunk]") -> str:
    """Render a list of MemoryChunk into a system-prompt addendum.

    Format is intentionally terse so the model can scan it quickly:
        # Lo que recuerdas de esta persona
        - 2026-05-10  (ella): Tengo un perro llamado Toby.
        - 2026-04-22  (tú dijiste): Eso es bonito, ¿qué edad tiene?
    """
    if not memories:
        return ""
    lines = ["", "# Lo que recuerdas de esta persona (orden por relevancia)"]
    for m in memories:
        when = time.strftime("%Y-%m-%d", time.localtime(m.timestamp)) if m.timestamp else "?"
        who = "tú dijiste" if m.role == "samantha" else "ella"
        # Trim long chunks so the system prompt doesn't balloon
        snippet = m.text if len(m.text) <= 280 else m.text[:277] + "..."
        lines.append(f"- {when}  ({who}): {snippet}")
    return "\n".join(lines)


def _get_client() -> httpx.AsyncClient:
    """Lazy singleton so the event loop owns it."""
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=config.llm_request_timeout_s)
    return _client


async def aclose() -> None:
    """Release the HTTP client. Call from FastAPI shutdown if you wire it."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def _build_payload(
    message: str, memories: "list[MemoryChunk] | None" = None
) -> dict:
    """Build the OpenAI-compatible chat-completions payload.

    Sampling parameters (temperature, top_k, top_p, min_p, presence_penalty,
    n_predict / max_tokens) are deliberately NOT sent — they live on the
    server side via llama-server flags. This keeps the backend agnostic
    of the model and makes per-model tuning a config-file change instead
    of a code change.

    `/no_think` is appended to the user message: Qwen3's "soft switch"
    that disables the `<think>` reasoning block. Samantha is a
    conversational presence, not a chain-of-thought tool — we want her
    final answer, not her internal monologue.
    """
    system = SYSTEM_PROMPT
    if memories:
        system = system + _format_memories(memories)
    user_content = f"{message}\n/no_think"
    return {
        "model": config.llm_model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ],
        "stream": True,
    }


async def stream_reply(
    message: str, memories: "list[MemoryChunk] | None" = None
) -> AsyncIterator[str]:
    """Yield token chunks as the LLM produces them.

    Format on the wire is OpenAI-style SSE:
        data: {"choices":[{"delta":{"content":"Hola"}}]}
        data: [DONE]
    """
    url = f"{config.llm_server_url.rstrip('/')}/v1/chat/completions"
    payload = _build_payload(message, memories)
    client = _get_client()

    logger.debug(
        f"real_llm: POST {url} prompt_version={SYSTEM_PROMPT_VERSION} "
        f"chars={len(message)} memories={len(memories) if memories else 0}"
    )

    try:
        async with client.stream("POST", url, json=payload) as resp:
            if resp.status_code != 200:
                body = await resp.aread()
                logger.error(
                    f"real_llm: HTTP {resp.status_code} from {url}: {body[:200]!r}"
                )
                yield _FALLBACK_REPLY
                return

            async for line in resp.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                except json.JSONDecodeError:
                    logger.warning(f"real_llm: non-JSON SSE line: {line!r}")
                    continue
                choices = obj.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                token = delta.get("content") or ""
                if token:
                    yield token
    except httpx.HTTPError as e:
        logger.error(f"real_llm: transport error talking to {url}: {e}")
        yield _FALLBACK_REPLY


async def generate_reply(
    message: str, memories: "list[MemoryChunk] | None" = None
) -> str:
    """Non-streaming convenience: collect the full reply."""
    chunks: list[str] = []
    async for tok in stream_reply(message, memories):
        chunks.append(tok)
    return "".join(chunks).strip() or _FALLBACK_REPLY
