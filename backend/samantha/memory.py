"""Persistent semantic memory for Samantha.

Backed by ChromaDB (SQLite + HNSW). Every user message and every reply
from Samantha is stored as a chunk with a timestamp and a role. Before
generating a new reply, `recall()` retrieves the top-k most similar
past chunks so the LLM can be reminded of context that's no longer in
the chat window.

Design principle (per user directive 2026-05-12): **Samantha never
forgets anything**. The `forget()` and `clear()` methods exist for
admin / test use only — they are NOT wired to user input. If the
person asks Samantha to forget something, the LLM responds in
character (declining), and the memory chunks stay.

Storage layout (per CLAUDE.md §2.7):
  ~/.samantha/memory/                    ← persist_dir
    chroma.sqlite3                       ← ChromaDB index
    <hash>/                              ← collection segment files

Schema per chunk:
  id        UUIDv4
  document  raw text
  metadata  {role: "user"|"samantha", timestamp: int, user_id: str}

Embedder: ChromaDB's default ONNX MiniLM-L6-v2. Primarily English but
covers enough multilingual signal for short Spanish chunks. TODO: swap
to `paraphrase-multilingual-MiniLM-L12-v2` via sentence-transformers
once we've validated retrieval quality in real conversation.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loguru import logger


# ============================================================
# Data
# ============================================================


@dataclass
class MemoryChunk:
    id: str
    role: str          # "user" or "samantha"
    text: str
    timestamp: int     # Unix epoch seconds
    user_id: str
    distance: float = 0.0   # Set by recall(); 0 = closest match


# ============================================================
# Embedding function builder
# ============================================================


def _make_fastembed_embedding_fn(model_name: str):
    """Build a Chroma-compatible embedding function backed by fastembed.

    fastembed runs ONNX models locally with no Python ML stack heft.
    `paraphrase-multilingual-MiniLM-L12-v2` outperforms the chroma
    default (English MiniLM-L6-v2) on Spanish, our primary language.
    """
    from fastembed import TextEmbedding

    embedder = TextEmbedding(model_name=model_name)

    class _FastembedFn:
        def __init__(self, model_name: str) -> None:
            self._name = model_name

        def name(self) -> str:
            return f"fastembed::{self._name}"

        def _embed(self, texts: list[str]) -> list[list[float]]:
            return [list(v) for v in embedder.embed(texts)]

        def __call__(self, input):  # noqa: A002 — chroma's required arg name
            texts = input if isinstance(input, list) else [input]
            return self._embed(texts)

        # Chroma's EmbeddingFunction protocol (chromadb/api/types.py:826)
        # expects both methods to return Embeddings (= list[list[float]]),
        # not a single vector.
        def embed_documents(self, input):  # noqa: A002
            texts = input if isinstance(input, list) else [input]
            return self._embed(texts)

        def embed_query(self, input):  # noqa: A002
            texts = input if isinstance(input, list) else [input]
            return self._embed(texts)

    return _FastembedFn(model_name)


# ============================================================
# Memory store
# ============================================================


class Memory:
    """Persistent semantic memory store.

    Two layers backed by the same chunk ids:
      - long-term: ChromaDB (HNSW, semantic recall)
      - short-term: SQLite ring buffer (last N turns verbatim)
    `remember` writes to both. `recall` queries long-term but excludes
    any chunk currently in the short-term ring (those entries already
    appear in the conversation window the LLM sees).

    ChromaDB's PersistentClient is process-local. Our backend is a
    single process so concurrent-writer concerns don't apply.
    """

    COLLECTION_NAME = "samantha_memories"

    def __init__(
        self,
        persist_dir: str,
        *,
        collection_name: str | None = None,
        embedding_function: Any | None = None,
        embedder_model: str = (
            "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
        ),
        short_term_capacity: int = 20,
    ) -> None:
        # Lazy import — chromadb is heavy. Importing it inside __init__
        # means tests that don't touch memory pay nothing.
        import chromadb
        from chromadb.config import Settings

        from .short_term import ShortTermBuffer

        path = Path(persist_dir).expanduser()
        path.mkdir(parents=True, exist_ok=True)
        self._persist_dir = str(path)
        self._collection_name = collection_name or self.COLLECTION_NAME

        self._client = chromadb.PersistentClient(
            path=str(path / "chroma"),
            settings=Settings(anonymized_telemetry=False, allow_reset=True),
        )
        if embedding_function is None:
            embedding_function = _make_fastembed_embedding_fn(embedder_model)
        self._collection = self._client.get_or_create_collection(
            name=self._collection_name,
            metadata={"hnsw:space": "cosine"},
            embedding_function=embedding_function,
        )

        self._short_term = ShortTermBuffer(
            path / "state.db", capacity=short_term_capacity
        )

        logger.info(
            f"memory: opened {self._persist_dir} "
            f"({self._collection.count()} long-term chunks, "
            f"{len(self._short_term.list())} short-term entries)"
        )

    # ------------- write -------------

    def remember(
        self, role: str, text: str, *, user_id: str = "primary"
    ) -> str:
        """Store a chunk in both long-term and short-term layers.

        Returns the chunk id (empty string if skipped).
        """
        if not text or not text.strip():
            return ""
        if role not in ("user", "samantha"):
            raise ValueError(f"role must be 'user' or 'samantha', got {role!r}")
        chunk_id = str(uuid.uuid4())
        ts = int(time.time())
        self._collection.add(
            ids=[chunk_id],
            documents=[text.strip()],
            metadatas=[{
                "role": role,
                "timestamp": ts,
                "user_id": user_id,
            }],
        )
        # Mirror into short-term ring with the SAME id so recall can
        # dedupe without a cross-store lookup.
        self._short_term.append_with_id(chunk_id, role, text, user_id=user_id)
        return chunk_id

    # ------------- read -------------

    def short_term(self, *, user_id: str = "primary") -> list:
        """Last N conversation entries (oldest-first) from short-term ring."""
        return self._short_term.list(user_id=user_id)

    def recall(
        self,
        query: str,
        *,
        k: int = 5,
        user_id: str = "primary",
    ) -> list[MemoryChunk]:
        """Return up to `k` chunks most similar to `query`.

        Excludes anything currently in the short-term ring — those
        entries are already part of the conversation window the LLM
        sees, so re-injecting them via recall would be redundant.

        Returns an empty list if the store is empty or the query is blank.
        """
        if not query or not query.strip():
            return []
        total = self._collection.count()
        if total == 0:
            return []
        # Over-fetch by the short-term ring size so we still return k
        # after dropping ring entries.
        n_results = min(k + self._short_term.capacity, total)
        res = self._collection.query(
            query_texts=[query.strip()],
            n_results=n_results,
            where={"user_id": user_id},
        )
        chunks = self._unpack_query_result(res, user_id)
        short_ids = self._short_term.ids(user_id=user_id)
        chunks = [c for c in chunks if c.id not in short_ids]
        return chunks[:k]

    def all(
        self,
        *,
        user_id: str = "primary",
        limit: int = 1000,
    ) -> list[MemoryChunk]:
        """Return all chunks for `user_id`, newest first."""
        res = self._collection.get(
            where={"user_id": user_id},
            limit=limit,
            include=["documents", "metadatas"],
        )
        chunks = self._unpack_get_result(res, user_id)
        chunks.sort(key=lambda c: c.timestamp, reverse=True)
        return chunks

    # ------------- delete -------------

    # NOTE: the following deletion methods are ADMIN-ONLY. They exist
    # for tests and future maintenance tooling (resetting the device,
    # GDPR-style erasure, etc.). They are deliberately NOT wired to the
    # user-facing chat flow — Samantha never forgets anything she's been
    # told. See module docstring.

    def forget(
        self,
        query: str,
        *,
        k: int = 3,
        user_id: str = "primary",
    ) -> list[str]:
        """ADMIN: find chunks similar to `query` and delete them."""
        matches = self.recall(query, k=k, user_id=user_id)
        if not matches:
            return []
        ids = [m.id for m in matches]
        self._collection.delete(ids=ids)
        logger.warning(
            f"memory: ADMIN deleted {len(ids)} chunks matching '{query[:40]}'"
        )
        return ids

    def forget_id(self, chunk_id: str) -> bool:
        """ADMIN: delete a specific chunk by id."""
        existing = self._collection.get(ids=[chunk_id])
        if not existing.get("ids"):
            return False
        self._collection.delete(ids=[chunk_id])
        return True

    def clear(self, *, user_id: str = "primary") -> int:
        """ADMIN: delete every chunk for `user_id`. Returns count deleted."""
        existing = self.all(user_id=user_id, limit=100000)
        if not existing:
            return 0
        self._collection.delete(ids=[c.id for c in existing])
        return len(existing)

    # ------------- info -------------

    def stats(self) -> dict[str, Any]:
        return {
            "persist_dir": self._persist_dir,
            "total_chunks": self._collection.count(),
            "collection": self._collection_name,
        }

    # ------------- internals -------------

    @staticmethod
    def _unpack_query_result(
        res: dict[str, Any], user_id: str
    ) -> list[MemoryChunk]:
        ids = (res.get("ids") or [[]])[0]
        docs = (res.get("documents") or [[]])[0]
        metas = (res.get("metadatas") or [[]])[0]
        dists = (res.get("distances") or [[]])[0]
        out: list[MemoryChunk] = []
        for i, doc_id in enumerate(ids):
            meta = metas[i] or {}
            out.append(MemoryChunk(
                id=doc_id,
                role=str(meta.get("role", "unknown")),
                text=docs[i],
                timestamp=int(meta.get("timestamp", 0)),
                user_id=str(meta.get("user_id", user_id)),
                distance=float(dists[i]) if dists else 0.0,
            ))
        return out

    @staticmethod
    def _unpack_get_result(
        res: dict[str, Any], user_id: str
    ) -> list[MemoryChunk]:
        ids = res.get("ids") or []
        docs = res.get("documents") or []
        metas = res.get("metadatas") or []
        out: list[MemoryChunk] = []
        for i, doc_id in enumerate(ids):
            meta = metas[i] or {}
            out.append(MemoryChunk(
                id=doc_id,
                role=str(meta.get("role", "unknown")),
                text=docs[i],
                timestamp=int(meta.get("timestamp", 0)),
                user_id=str(meta.get("user_id", user_id)),
            ))
        return out


# Note: a `detect_forget_intent()` helper was previously defined here
# to route "olvida X" messages into `Memory.forget()`. It was removed
# on 2026-05-12 per the directive that Samantha never forgets anything.
# Such messages now flow to the LLM like any other, and the system
# prompt instructs Samantha to decline (in character) rather than delete.
