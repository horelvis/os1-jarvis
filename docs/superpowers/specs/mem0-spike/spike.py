"""Mem0 spike for Samantha.

Run with:
    cd backend && .venv/bin/python ../docs/superpowers/specs/mem0-spike/spike.py

Environment:
    SAMANTHA_LLM_SERVER_URL  default http://192.168.100.58:8080
    SAMANTHA_LLM_MODEL       default qwen3-8b

What this exercises:
  1. Mem0 connected to llama-server (OpenAI-compatible)
  2. ChromaDB as vector store (Mem0 wraps it)
  3. Embeddings via llama-server's embedding endpoint (if exposed)
  4. add() with infer=True default — see what facts Mem0 extracts in Spanish
  5. add() with infer=False — verify pure-append behaviour
  6. custom_instructions forcing append-only — see if Mem0 obeys
  7. Latency per turn
  8. history() preservation when Mem0 decides to UPDATE/DELETE

Writes to temp dirs; nothing in production memory at ~/.samantha.
"""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

from mem0 import Memory


LLM_URL = os.environ.get("SAMANTHA_LLM_SERVER_URL", "http://192.168.100.58:8000")
LLM_MODEL = os.environ.get("SAMANTHA_LLM_MODEL", "Qwen3-8B-Q8_0.gguf")
EMBEDDER_MODEL = os.environ.get(
    "SAMANTHA_EMBEDDER_MODEL",
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
)
USER_ID = "spike_user"


def banner(s: str) -> None:
    print(f"\n{'=' * 70}\n  {s}\n{'=' * 70}")


def build_memory(workspace: Path, *, append_only_instructions: bool) -> Memory:
    """Build a Memory pointed at llama-server + ChromaDB in a temp workspace."""
    cfg = {
        "llm": {
            "provider": "openai",
            "config": {
                "model": LLM_MODEL,
                "openai_base_url": f"{LLM_URL}/v1",
                "api_key": "fake-key-llama-server",
                "temperature": 0.2,
            },
        },
        "embedder": {
            # llama-server isn't exposing /v1/embeddings (started without
            # --embeddings flag), so we use fastembed (local ONNX) for
            # multilingual embeddings. ~80 MB downloaded once.
            "provider": "fastembed",
            "config": {"model": EMBEDDER_MODEL},
        },
        "vector_store": {
            "provider": "chroma",
            "config": {
                "collection_name": "samantha_mem0_spike",
                "path": str(workspace / "chroma"),
            },
        },
        "history_db_path": str(workspace / "history.db"),
    }
    if append_only_instructions:
        cfg["custom_instructions"] = (
            "INSTRUCCIONES CRÍTICAS DE COMPORTAMIENTO:\n"
            "1. NUNCA elimines un memory item (no devuelvas event DELETE).\n"
            "2. NUNCA hagas UPDATE destructivo. Si la información nueva contradice "
            "la existente, devuelve un event ADD nuevo manteniendo el viejo.\n"
            "3. Sólo se permite el event ADD.\n"
            "4. Extrae los hechos en español. Mantén el texto original cuando puedas."
        )
    return Memory.from_config(cfg)


def test_basic_extraction(mem: Memory) -> None:
    banner("Test 1 — fact extraction en español con infer=True (default)")
    msgs = [
        {"role": "user", "content": "Tengo un perro labrador llamado Toby."},
        {"role": "assistant", "content": "Anda, qué bonito. ¿Cuántos años tiene?"},
    ]
    t0 = time.perf_counter()
    res = mem.add(messages=msgs, user_id=USER_ID)
    dt = time.perf_counter() - t0
    print(f"  latency: {dt:.2f}s")
    print(f"  result:  {res}")


def test_search(mem: Memory, query: str) -> None:
    banner(f"Search: '{query}'")
    t0 = time.perf_counter()
    res = mem.search(query=query, top_k=5, filters={"user_id": USER_ID})
    dt = time.perf_counter() - t0
    print(f"  latency: {dt:.2f}s")
    if isinstance(res, dict) and "results" in res:
        for r in res["results"]:
            print(f"  - {r}")
    else:
        print(f"  {res}")


def test_contradiction(mem: Memory) -> None:
    banner("Test 2 — contradicción (¿Mem0 hace UPDATE o ADD nuevo?)")
    msgs = [
        {"role": "user", "content": "Ya no tengo a Toby, se murió hace una semana."},
    ]
    t0 = time.perf_counter()
    res = mem.add(messages=msgs, user_id=USER_ID)
    dt = time.perf_counter() - t0
    print(f"  latency: {dt:.2f}s")
    print(f"  result:  {res}")
    if isinstance(res, dict) and "results" in res:
        events = [r.get("event") for r in res["results"]]
        print(f"  events:  {events}")
        if "DELETE" in events:
            print("  ⚠  Mem0 quiso ELIMINAR un memory — viola 'nunca olvida'.")
        if "UPDATE" in events:
            print("  ⚠  Mem0 quiso ACTUALIZAR un memory destructivamente.")


def test_history(mem: Memory) -> None:
    banner("Test 3 — ¿el historial preserva versiones anteriores?")
    all_mems = mem.get_all(filters={"user_id": USER_ID}, top_k=50)
    if isinstance(all_mems, dict) and "results" in all_mems:
        items = all_mems["results"]
    else:
        items = all_mems
    print(f"  total memory items: {len(items)}")
    for item in items[:5]:
        mid = item.get("id")
        print(f"  - id={mid}  memory={item.get('memory', '')[:80]}")
        if mid:
            try:
                h = mem.history(memory_id=mid)
                print(f"    history entries: {len(h)}")
                for entry in h:
                    print(f"      • event={entry.get('event')} memory={entry.get('memory', '')[:60]}")
            except Exception as e:
                print(f"    history not available: {e}")


def test_raw_append(mem: Memory) -> None:
    banner("Test 4 — infer=False (append puro, sin LLM extraction)")
    msgs = [{"role": "user", "content": "Mi color favorito es el azul."}]
    t0 = time.perf_counter()
    res = mem.add(messages=msgs, user_id=USER_ID, infer=False)
    dt = time.perf_counter() - t0
    print(f"  latency: {dt:.2f}s   (much faster, no LLM call)")
    print(f"  result:  {res}")


def main() -> None:
    workspace_a = Path(tempfile.mkdtemp(prefix="samantha-mem0-spike-A-"))
    workspace_b = Path(tempfile.mkdtemp(prefix="samantha-mem0-spike-B-"))

    print(f"llama-server: {LLM_URL}")
    print(f"model:        {LLM_MODEL}")
    print(f"workspace A:  {workspace_a}")
    print(f"workspace B:  {workspace_b}")

    banner("PHASE A — Mem0 default behaviour (no custom instructions)")
    mem_a = build_memory(workspace_a, append_only_instructions=False)
    test_basic_extraction(mem_a)
    test_search(mem_a, "¿qué mascota tiene?")
    test_contradiction(mem_a)
    test_history(mem_a)
    test_raw_append(mem_a)
    try:
        mem_a.close()
    except Exception:
        pass

    banner("PHASE B — Mem0 con custom_instructions de append-only")
    mem_b = build_memory(workspace_b, append_only_instructions=True)
    test_basic_extraction(mem_b)
    test_contradiction(mem_b)
    test_history(mem_b)
    try:
        mem_b.close()
    except Exception:
        pass

    banner("RESUMEN — limpieza")
    print(f"  rm -rf '{workspace_a}' '{workspace_b}'")


if __name__ == "__main__":
    main()
