"""Real LLM client — talks to an OpenAI-compatible server.

The default target is X.AI's Grok API (`config.llm_server_url`). Any
OpenAI-compatible `/v1/chat/completions` endpoint works: a local
llama-server (no auth), vLLM, LM Studio, OpenAI, Anthropic via a
compat shim, etc. Auth header is added automatically when
`config.llm_api_key` is non-empty.

Contract:
  - `generate_reply(message)`   → full text (awaitable)
  - `stream_reply(message)`     → async iterator of token chunks

Errors are NOT swallowed. If the LLM server is unreachable, the
HTTP layer raises and the caller surfaces it to the user. The
previous canned "He perdido el hilo…" fallback was removed because
it (a) hid LLM outages behind plausible-sounding text and (b) when
the mic re-captured Samantha saying that line it triggered an
infinite echo loop. Fail loud, fail visible.
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


_client: httpx.AsyncClient | None = None


def _format_facts(facts: "list[dict]") -> str:
    """Render structured facts ('# Lo que sabes de ella').

    Facts carry stable knowledge about the user (name, onboarding date,
    later: preferences). One bullet per fact, rendered text-first so
    Samantha sees natural-language statements rather than k/v pairs.
    """
    if not facts:
        return ""
    lines = ["", "# Lo que sabes de ella"]
    for f in facts:
        line = f.get("text") or f"{f.get('kind')} = {f.get('value')}"
        lines.append(f"- {line}")
    return "\n".join(lines)


def _format_recall(chunks: "list[MemoryChunk]") -> str:
    """Render semantic-recall hits ('# Lo que recuerdas').

    Past conversation chunks pulled by similarity to the current
    message. Each gets a date, a 'who said it' marker, and a 280-char
    snippet to keep the prompt bounded.
    """
    if not chunks:
        return ""
    lines = ["", "# Lo que recuerdas"]
    for c in chunks:
        when = time.strftime("%Y-%m-%d", time.localtime(c.timestamp)) if c.timestamp else "?"
        who = "tú dijiste" if c.role == "samantha" else "ella"
        snippet = c.text if len(c.text) <= 280 else c.text[:277] + "..."
        lines.append(f"- {when}  ({who}): {snippet}")
    return "\n".join(lines)


def _format_short_term(chunks: "list[MemoryChunk]") -> str:
    """Render the short-term ring as the immediate conversation window.

    Verbatim, oldest-first, no dates — this is the live thread the LLM
    should treat as 'the current conversation', not as background.
    """
    if not chunks:
        return ""
    lines = ["", "# Conversación reciente"]
    for c in chunks:
        who = "tú" if c.role == "samantha" else "ella"
        lines.append(f"{who}: {c.text}")
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
    message: str,
    *,
    facts: "list[dict] | None" = None,
    recall: "list[MemoryChunk] | None" = None,
    short_term: "list[MemoryChunk] | None" = None,
) -> dict:
    """Build the OpenAI-compatible chat-completions payload.

    Sampling parameters (temperature, top_k, top_p, min_p, presence_penalty,
    n_predict / max_tokens) are deliberately NOT sent — they live on the
    server side via llama-server flags. This keeps the backend agnostic
    of the model and makes per-model tuning a config-file change instead
    of a code change.

    System prompt assembly (spec §9.6):
        SYSTEM_PROMPT
        + facts (# Lo que sabes de ella)
        + recall (# Lo que recuerdas)
        + short_term (# Conversación reciente)

    `/no_think` is appended to the user message: Qwen3's "soft switch"
    that disables the `<think>` reasoning block. Samantha is a
    conversational presence, not a chain-of-thought tool — we want her
    final answer, not her internal monologue.
    """
    if config.llm_provider == "hermes":
        # Hermes keeps its own session history server-side, but facts
        # and semantic recall live only in OUR memory — without them
        # the agent never learns the user's name. Short-term turns go
        # as real chat messages (hermes wants clean history), the rest
        # rides the system prompt like the openai path.
        system = SYSTEM_PROMPT
        if facts:
            system += _format_facts(facts)
        if recall:
            system += _format_recall(recall)

        messages: list[dict] = [{"role": "system", "content": system}]
        if short_term:
            for c in short_term:
                role = "assistant" if c.role == "samantha" else "user"
                messages.append({"role": role, "content": c.text})

        # The ring no longer contains the current message (api.py
        # persists AFTER collecting context), but guard anyway so a
        # direct caller passing it can't double-send.
        last = messages[-1]
        if last["role"] != "user" or last["content"].strip() != message.strip():
            messages.append({"role": "user", "content": message})

        return {
            "model": config.llm_model,
            "messages": messages,
            "stream": True,
        }

    system = SYSTEM_PROMPT
    if facts:
        system += _format_facts(facts)
    if recall:
        system += _format_recall(recall)
    if short_term:
        system += _format_short_term(short_term)

    # `/no_think` is Qwen3's soft switch to skip the <think> block.
    # Other model families just echo it back as part of the prompt, so
    # only append it for Qwen-family models.
    user_content = message
    if "qwen" in (config.llm_model or "").lower():
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
    message: str,
    *,
    facts: "list[dict] | None" = None,
    recall: "list[MemoryChunk] | None" = None,
    short_term: "list[MemoryChunk] | None" = None,
    user_id: str = "primary",
) -> AsyncIterator[str]:
    """Yield token chunks as the LLM produces them.

    Format on the wire is OpenAI-style SSE:
        data: {"choices":[{"delta":{"content":"Hola"}}]}
        data: [DONE]
    """
    url = f"{config.llm_server_url.rstrip('/')}/v1/chat/completions"
    payload = _build_payload(
        message,
        facts=facts,
        recall=recall,
        short_term=short_term,
    )
    client = _get_client()

    logger.debug(
        f"real_llm: POST {url} prompt_version={SYSTEM_PROMPT_VERSION} "
        f"chars={len(message)} facts={len(facts) if facts else 0} "
        f"recall={len(recall) if recall else 0} "
        f"short_term={len(short_term) if short_term else 0}"
    )

    # Add Bearer auth when an API key is configured. Local llama-server
    # ignores the header; Grok/OpenAI/Anthropic-compatible APIs require it.
    headers: dict[str, str] = {}
    if config.llm_api_key:
        headers["Authorization"] = f"Bearer {config.llm_api_key}"
    if config.llm_provider == "hermes":
        headers["X-Hermes-Session-Id"] = user_id

    async with client.stream("POST", url, json=payload, headers=headers) as resp:
        if resp.status_code != 200:
            body = await resp.aread()
            raise httpx.HTTPStatusError(
                f"LLM {resp.status_code}: {body[:200].decode('utf-8', 'replace')}",
                request=resp.request,
                response=resp,
            )

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


async def generate_reply(
    message: str,
    *,
    facts: "list[dict] | None" = None,
    recall: "list[MemoryChunk] | None" = None,
    short_term: "list[MemoryChunk] | None" = None,
    user_id: str = "primary",
) -> str:
    """Non-streaming convenience: collect the full reply."""
    chunks: list[str] = []
    async for tok in stream_reply(
        message, facts=facts, recall=recall, short_term=short_term, user_id=user_id
    ):
        chunks.append(tok)
    return "".join(chunks).strip()
