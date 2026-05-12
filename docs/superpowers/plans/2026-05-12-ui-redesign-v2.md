# Samantha UI v2 Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the vanilla-JS frontend with a React + Vite + TypeScript app and extend backend memory with short-term + long-term + facts, gated by a persistence layer that prevents onboarding repetition.

**Architecture:** Two clean halves with a stable HTTP/WS contract. Backend (Python FastAPI) gains: (a) Memory with short-term SQLite ring buffer, long-term ChromaDB+fastembed, and `role: "fact"` chunks; (b) `/profile` endpoints that route through Memory (no `profile.json`). Frontend (`frontend/` separate from `backend/`) is React + Vite + TS with 4 screens (Boot, Onboarding, Ambient, Conversation) and a traveling-wave-packet visualization.

**Tech Stack:**
- **Backend:** Python 3.12, FastAPI, uvicorn, ChromaDB, fastembed, httpx, pytest
- **Frontend:** React 18, Vite, TypeScript, zustand, Three.js (via importmap in Vite)
- **LLM:** llama-server (Qwen3-8B-Q8_0 on GPU server at LAN `192.168.100.58:8000`)
- **Embeddings:** fastembed local ONNX (`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`)

**Spec:** `docs/superpowers/specs/2026-05-12-ui-redesign-design.md` (commit `12a1002` on `development`).

---

## File map

### Files created

```
backend/samantha/
├── profile.py                 ← NEW (Phase 2). Thin facade over Memory.
└── short_term.py              ← NEW (Phase 1). SQLite ring buffer.

frontend/                      ← NEW (Phase 4). Replaces backend/static/.
├── .gitignore
├── package.json
├── tsconfig.json
├── tsconfig.node.json
├── vite.config.ts
├── index.html
├── public/                    ← (intentionally empty for now)
└── src/
    ├── main.tsx
    ├── App.tsx
    ├── styles/
    │   ├── tokens.css
    │   ├── base.css
    │   └── components.css
    ├── core/
    │   ├── types.ts
    │   ├── store.ts
    │   ├── router.ts
    │   └── useKeys.ts
    ├── net/
    │   ├── wsClient.ts
    │   ├── tts.ts
    │   ├── mic.ts
    │   └── profile.ts
    ├── components/
    │   ├── Wave.tsx
    │   └── OS1Loader.tsx
    └── screens/
        ├── BootScreen.tsx
        ├── OnboardingScreen.tsx
        ├── AmbientScreen.tsx
        └── ConversationScreen.tsx

docs/superpowers/
└── plans/2026-05-12-ui-redesign-v2.md   ← THIS FILE
```

### Files modified

```
backend/samantha/memory.py     ← Phase 1. Extended with set_fact/get_fact/short-term integration.
backend/samantha/config.py     ← Phase 1. Adds memory_short_term_capacity, memory_top_k_recall.
backend/samantha/api.py        ← Phase 2-3. /profile routes, prompt assembly via §9.6.
backend/samantha/schemas.py    ← Phase 2. ProfileCreate, ProfileResponse, etc.
backend/samantha/real_llm.py   ← Phase 3. New _format_memories signature.
backend/samantha/personality.py← (untouched; SYSTEM_PROMPT v2 stays)
backend/tests/test_api.py      ← Phase 2-9. Endpoint tests adapted.
backend/tests/test_memory.py   ← NEW (Phase 1). Memory unit tests.
backend/tests/test_profile.py  ← NEW (Phase 2). Profile facade tests.
backend/pyproject.toml         ← Phase 1. Adds fastembed to main deps.
CLAUDE.md                      ← Phase 9. §2.4, §2.7, §2.10 new, §3, §5, §7, §12.
PROGRESS.md                    ← Phase 9. Phase entry.
.gitignore                     ← Phase 4. Adds frontend/node_modules, frontend/dist.
```

### Files deleted

```
backend/static/                ← Phase 9 entirely (after frontend reaches feature parity)
```

---

## Phase overview

| # | Phase | Output | Checkpoint |
|---|---|---|---|
| 1 | Memory architecture (backend) | `memory.py` extended; `short_term.py`; fastembed embedder; new tests | All memory tests green |
| 2 | Profile + endpoints (backend) | `profile.py`; `/profile` GET/POST/DELETE; `has_profile` in `/ping`; new tests | All endpoint tests green |
| 3 | Prompt assembly (backend) | `api.py` builds SYSTEM + facts + recall + short-term; existing chat/ws stream still works | All existing api tests green |
| 4 | Frontend scaffolding | `frontend/` with Vite+React+TS; Boot screen with profile-check; navigates to placeholder Ambient | `npm run dev` shows boot → ambient placeholder; `pytest` still green |
| 5 | Wave component | `Wave.tsx` traveling wave packet, 4 modes, integrated in placeholder | Visual check in browser |
| 6 | Ambient screen | `AmbientScreen.tsx` with time/day/phrase/wave | Visual check; tap → Conversation placeholder |
| 7 | Conversation screen | `ConversationScreen.tsx` immersive + history toggle + keybindings + WS chat | End-to-end chat in real mode |
| 8 | Onboarding screen | `OnboardingScreen.tsx` port of existing 6-screen flow; POST /profile | First-encounter → Ambient |
| 9 | Cleanup & docs | Delete `backend/static/`; update CLAUDE.md; update PROGRESS.md; final commit | All tests pass; clean git status |

**Each phase ends with a `git commit` and a clear checkpoint for human review before proceeding.**

---

## Phase 1 — Memory architecture

**Goal:** Extend `Memory` to support short-term ring buffer + facts + multilingual fastembed embedder. Keep `recall()` filtering out short-term and `role: "fact"` chunks.

### Task 1.1: Add fastembed to backend deps

**Files:**
- Modify: `backend/pyproject.toml`

- [ ] **Step 1: Edit pyproject.toml**

Move `fastembed` from optional `[real]` to main `dependencies`. The file is at `backend/pyproject.toml`. The current main deps section already contains `chromadb`. Add this line after `chromadb`:

```toml
    "fastembed>=0.5",            # multilingual ONNX embedder for memory recall (Phase 1)
```

Remove `fastembed` from the `[real]` extras if present.

- [ ] **Step 2: Reinstall venv**

```bash
cd backend && .venv/bin/pip install -q -e ".[dev]"
```

Expected: completes without errors.

- [ ] **Step 3: Verify fastembed imports**

```bash
cd backend && .venv/bin/python -c "from fastembed import TextEmbedding; print('ok')"
```

Expected: prints `ok`.

- [ ] **Step 4: Commit**

```bash
git add backend/pyproject.toml
git commit -m "deps: promote fastembed to main deps (Phase 1)"
```

---

### Task 1.2: Add config flags for short-term capacity and recall k

**Files:**
- Modify: `backend/samantha/config.py`

- [ ] **Step 1: Add config fields**

Add to the `Config` dataclass in `backend/samantha/config.py`, near the existing `memory_persist_dir` line:

```python
    memory_short_term_capacity: int = 20
    memory_recall_top_k: int = 5
    memory_embedder_model: str = (
        "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    )
```

And add the corresponding env mappings in `Config.from_env`, near the existing `memory_persist_dir` line:

```python
            memory_short_term_capacity=_get(
                "MEMORY_SHORT_TERM_CAPACITY", cls.memory_short_term_capacity
            ),
            memory_recall_top_k=_get("MEMORY_RECALL_TOP_K", cls.memory_recall_top_k),
            memory_embedder_model=_get(
                "MEMORY_EMBEDDER_MODEL", cls.memory_embedder_model
            ),
```

- [ ] **Step 2: Verify import**

```bash
cd backend && .venv/bin/python -c "from samantha.config import config; print(config.memory_recall_top_k, config.memory_embedder_model[:40])"
```

Expected: prints `5 sentence-transformers/paraphrase-multilingual-MiniL` (truncated).

- [ ] **Step 3: Commit**

```bash
git add backend/samantha/config.py
git commit -m "config: add short-term capacity, recall k, and embedder model flags"
```

---

### Task 1.3: Create ShortTermBuffer (SQLite ring)

**Files:**
- Create: `backend/samantha/short_term.py`
- Create: `backend/tests/test_short_term.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_short_term.py`:

```python
"""Tests for short-term ring-buffer memory."""

import pytest

from samantha.short_term import ShortTermBuffer


def test_append_and_retrieve(tmp_path):
    buf = ShortTermBuffer(tmp_path / "state.db", capacity=5)
    buf.append("user", "hola", user_id="u1")
    buf.append("samantha", "Hola. ¿Cómo va?", user_id="u1")
    entries = buf.list(user_id="u1")
    assert len(entries) == 2
    assert entries[0].role == "user"
    assert entries[0].text == "hola"
    assert entries[1].role == "samantha"
    assert entries[1].text == "Hola. ¿Cómo va?"


def test_ring_eviction(tmp_path):
    buf = ShortTermBuffer(tmp_path / "state.db", capacity=3)
    for i in range(5):
        buf.append("user", f"msg{i}", user_id="u1")
    entries = buf.list(user_id="u1")
    assert len(entries) == 3
    assert [e.text for e in entries] == ["msg2", "msg3", "msg4"]


def test_isolation_by_user(tmp_path):
    buf = ShortTermBuffer(tmp_path / "state.db", capacity=5)
    buf.append("user", "alice msg", user_id="alice")
    buf.append("user", "bob msg", user_id="bob")
    assert [e.text for e in buf.list(user_id="alice")] == ["alice msg"]
    assert [e.text for e in buf.list(user_id="bob")] == ["bob msg"]


def test_rejects_invalid_role(tmp_path):
    buf = ShortTermBuffer(tmp_path / "state.db", capacity=5)
    with pytest.raises(ValueError):
        buf.append("robot", "hi", user_id="u1")


def test_ids_are_unique_uuids(tmp_path):
    buf = ShortTermBuffer(tmp_path / "state.db", capacity=5)
    id1 = buf.append("user", "a", user_id="u1")
    id2 = buf.append("user", "b", user_id="u1")
    assert id1 != id2
    assert len(id1) == 36
```

- [ ] **Step 2: Verify tests fail**

```bash
cd backend && .venv/bin/pytest tests/test_short_term.py -q
```

Expected: 5 errors (ImportError — `samantha.short_term` not found).

- [ ] **Step 3: Implement ShortTermBuffer**

Create `backend/samantha/short_term.py`:

```python
"""Short-term memory: SQLite ring buffer for the last N conversation turns.

Stored at `state.db` inside the memory persist dir. Each entry has a
role ("user" | "samantha"), text, timestamp, user_id, and a UUID id.
When capacity is exceeded for a given user_id, the oldest entry is
deleted — but its content is preserved in long-term memory (see
`Memory.remember`) so nothing is truly forgotten.
"""

from __future__ import annotations

import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from loguru import logger


_VALID_ROLES = {"user", "samantha"}


@dataclass(frozen=True)
class ShortTermEntry:
    id: str
    role: str
    text: str
    timestamp: int
    user_id: str


class ShortTermBuffer:
    def __init__(self, db_path: str | Path, *, capacity: int = 20) -> None:
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.capacity = capacity
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS short_term ("
            "  id TEXT PRIMARY KEY,"
            "  role TEXT NOT NULL,"
            "  text TEXT NOT NULL,"
            "  timestamp INTEGER NOT NULL,"
            "  user_id TEXT NOT NULL"
            ")"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_short_term_user_ts "
            "ON short_term(user_id, timestamp)"
        )
        self._conn.commit()
        logger.info(
            f"short_term: opened {self.path} (capacity={capacity})"
        )

    def append(
        self, role: str, text: str, *, user_id: str = "primary"
    ) -> str:
        if role not in _VALID_ROLES:
            raise ValueError(f"role must be in {_VALID_ROLES}, got {role!r}")
        if not text or not text.strip():
            return ""
        entry_id = str(uuid.uuid4())
        ts = int(time.time())
        with self._conn:
            self._conn.execute(
                "INSERT INTO short_term (id, role, text, timestamp, user_id) "
                "VALUES (?, ?, ?, ?, ?)",
                (entry_id, role, text.strip(), ts, user_id),
            )
            self._conn.execute(
                "DELETE FROM short_term WHERE id IN ("
                "  SELECT id FROM short_term WHERE user_id = ? "
                "  ORDER BY timestamp ASC, id ASC "
                "  LIMIT MAX(0, ("
                "    SELECT COUNT(*) FROM short_term WHERE user_id = ?"
                "  ) - ?)"
                ")",
                (user_id, user_id, self.capacity),
            )
        return entry_id

    def list(self, *, user_id: str = "primary") -> list[ShortTermEntry]:
        cur = self._conn.execute(
            "SELECT id, role, text, timestamp, user_id "
            "FROM short_term WHERE user_id = ? "
            "ORDER BY timestamp ASC, id ASC",
            (user_id,),
        )
        return [
            ShortTermEntry(id=row[0], role=row[1], text=row[2],
                           timestamp=row[3], user_id=row[4])
            for row in cur.fetchall()
        ]

    def ids(self, *, user_id: str = "primary") -> set[str]:
        cur = self._conn.execute(
            "SELECT id FROM short_term WHERE user_id = ?", (user_id,)
        )
        return {row[0] for row in cur.fetchall()}

    def clear(self, *, user_id: str = "primary") -> int:
        with self._conn:
            cur = self._conn.execute(
                "DELETE FROM short_term WHERE user_id = ?", (user_id,)
            )
            return cur.rowcount

    def close(self) -> None:
        self._conn.close()
```

- [ ] **Step 4: Run tests, expect pass**

```bash
cd backend && .venv/bin/pytest tests/test_short_term.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/samantha/short_term.py backend/tests/test_short_term.py
git commit -m "feat(memory): add ShortTermBuffer with SQLite ring eviction"
```

---

### Task 1.4: Swap embedder to fastembed multilingual + integrate short-term into Memory

**Files:**
- Modify: `backend/samantha/memory.py`
- Modify: `backend/tests/test_api.py`

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/test_api.py`:

```python
def test_memory_uses_fastembed_multilingual_by_default(tmp_path):
    """The embedder swap to fastembed multilingual is the default."""
    from samantha.memory import Memory
    mem = Memory(persist_dir=str(tmp_path / "mem"))
    mem.remember("user", "Mi mascota se llama Toby, es un labrador.", user_id="u1")
    mem.remember("user", "Mi color favorito es el azul cobalto.", user_id="u1")
    mem.remember("user", "Trabajo en una agencia de publicidad.", user_id="u1")
    results = mem.recall("¿qué mascota tiene?", k=2, user_id="u1")
    assert results, "expected at least one result"
    top_text = results[0].text.lower()
    assert "toby" in top_text or "labrador" in top_text or "mascota" in top_text


def test_memory_remember_writes_to_short_term(tmp_path):
    from samantha.memory import Memory
    mem = Memory(persist_dir=str(tmp_path / "mem"), short_term_capacity=3)
    mem.remember("user", "uno", user_id="u1")
    mem.remember("samantha", "dos", user_id="u1")
    short = mem.short_term(user_id="u1")
    assert [e.text for e in short] == ["uno", "dos"]
    assert short[0].role == "user"
    assert short[1].role == "samantha"


def test_memory_recall_excludes_short_term_entries(tmp_path):
    from samantha.memory import Memory
    mem = Memory(persist_dir=str(tmp_path / "mem"), short_term_capacity=10)
    mem.remember("user", "hablamos del café por la mañana", user_id="u1")
    short_ids = {e.id for e in mem.short_term(user_id="u1")}
    results = mem.recall("café por la mañana", k=5, user_id="u1")
    result_ids = {r.id for r in results}
    assert not (result_ids & short_ids), \
        "recall should exclude short-term entries"
```

- [ ] **Step 2: Run tests, expect failures**

```bash
cd backend && .venv/bin/pytest tests/test_api.py::test_memory_uses_fastembed_multilingual_by_default tests/test_api.py::test_memory_remember_writes_to_short_term tests/test_api.py::test_memory_recall_excludes_short_term_entries -v
```

Expected: 3 failures.

- [ ] **Step 3: Update memory.py — constructor**

Open `backend/samantha/memory.py`. Replace the existing `Memory.__init__` body with this. Also add `_make_fastembed_embedding_fn` at module top-level:

```python
def _make_fastembed_embedding_fn(model_name: str):
    """Build a Chroma-compatible embedding function backed by fastembed."""
    from fastembed import TextEmbedding

    embedder = TextEmbedding(model_name=model_name)

    class _FastembedFn:
        def __init__(self, model_name: str) -> None:
            self._name = model_name

        def name(self) -> str:
            return f"fastembed::{self._name}"

        def __call__(self, input):  # noqa: A002
            texts = input if isinstance(input, list) else [input]
            return [list(v) for v in embedder.embed(texts)]

    return _FastembedFn(model_name)
```

And the new `Memory.__init__`:

```python
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
```

- [ ] **Step 4: Update `remember` to write to both layers**

Replace the existing `Memory.remember` body:

```python
    def remember(
        self, role: str, text: str, *, user_id: str = "primary"
    ) -> str:
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
        # Mirror into short-term ring using the SAME id so recall
        # exclusion works without a lookup join.
        self._short_term._conn.execute(
            "INSERT INTO short_term (id, role, text, timestamp, user_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (chunk_id, role, text.strip(), ts, user_id),
        )
        self._short_term._conn.commit()
        self._short_term._conn.execute(
            "DELETE FROM short_term WHERE id IN ("
            "  SELECT id FROM short_term WHERE user_id = ? "
            "  ORDER BY timestamp ASC, id ASC "
            "  LIMIT MAX(0, ("
            "    SELECT COUNT(*) FROM short_term WHERE user_id = ?"
            "  ) - ?)"
            ")",
            (user_id, user_id, self._short_term.capacity),
        )
        self._short_term._conn.commit()
        return chunk_id

    def short_term(self, *, user_id: str = "primary") -> list:
        """Last N conversation entries (oldest-first) from short-term buffer."""
        return self._short_term.list(user_id=user_id)
```

- [ ] **Step 5: Update `recall` to exclude short-term entries**

Replace `Memory.recall`:

```python
    def recall(
        self,
        query: str,
        *,
        k: int = 5,
        user_id: str = "primary",
    ) -> list[MemoryChunk]:
        if not query or not query.strip():
            return []
        total = self._collection.count()
        if total == 0:
            return []
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
```

- [ ] **Step 6: Run tests**

```bash
cd backend && .venv/bin/pytest tests/test_api.py::test_memory_uses_fastembed_multilingual_by_default tests/test_api.py::test_memory_remember_writes_to_short_term tests/test_api.py::test_memory_recall_excludes_short_term_entries -v
```

Expected: 3 passed. **First run will be slow** (~30 s) because fastembed downloads the ONNX model.

- [ ] **Step 7: Run full suite**

```bash
cd backend && .venv/bin/pytest tests/ -q
```

Expected: all green.

- [ ] **Step 8: Commit**

```bash
git add backend/samantha/memory.py backend/tests/test_api.py
git commit -m "feat(memory): fastembed multilingual + short-term integration"
```

---

### Task 1.5: Add facts (set_fact / get_fact / all_facts) to Memory

**Files:**
- Modify: `backend/samantha/memory.py`
- Modify: `backend/tests/test_api.py`

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/test_api.py`:

```python
def test_memory_set_and_get_fact(tmp_path):
    from samantha.memory import Memory
    mem = Memory(persist_dir=str(tmp_path / "mem"))
    fact_id = mem.set_fact("name", "Horelvis", user_id="u1")
    assert fact_id
    fact = mem.get_fact("name", user_id="u1")
    assert fact is not None
    assert fact["value"] == "Horelvis"
    assert fact["kind"] == "name"


def test_memory_get_fact_returns_newest(tmp_path):
    import time
    from samantha.memory import Memory
    mem = Memory(persist_dir=str(tmp_path / "mem"))
    mem.set_fact("name", "Old Name", user_id="u1")
    time.sleep(1.1)
    mem.set_fact("name", "New Name", user_id="u1")
    fact = mem.get_fact("name", user_id="u1")
    assert fact["value"] == "New Name"


def test_memory_facts_excluded_from_conversational_recall(tmp_path):
    from samantha.memory import Memory
    mem = Memory(persist_dir=str(tmp_path / "mem"))
    mem.set_fact("name", "Horelvis", user_id="u1",
                 text="El usuario se llama Horelvis")
    mem.remember("user", "Me encanta el café por la mañana", user_id="u1")
    results = mem.recall("Horelvis", k=5, user_id="u1")
    for r in results:
        assert r.role != "fact"


def test_memory_all_facts_filters_by_kind(tmp_path):
    from samantha.memory import Memory
    mem = Memory(persist_dir=str(tmp_path / "mem"))
    mem.set_fact("name", "Alice", user_id="u1")
    mem.set_fact("preferred_tone", "direct", user_id="u1")
    names = mem.all_facts(kind="name", user_id="u1")
    assert len(names) == 1
    assert names[0]["value"] == "Alice"
    everything = mem.all_facts(user_id="u1")
    assert len(everything) == 2
```

- [ ] **Step 2: Run tests, expect failures**

```bash
cd backend && .venv/bin/pytest tests/test_api.py::test_memory_set_and_get_fact -v
```

Expected: AttributeError.

- [ ] **Step 3: Implement set_fact / get_fact / all_facts**

In `backend/samantha/memory.py` add these methods to `Memory` (after `recall`):

```python
    def set_fact(
        self,
        kind: str,
        value,
        *,
        text: str | None = None,
        user_id: str = "primary",
    ) -> str:
        """Append a fact chunk (role='fact'). Older facts with same kind
        are NOT deleted; get_fact returns the newest by timestamp."""
        import json
        if not kind:
            raise ValueError("kind is required")
        chunk_id = str(uuid.uuid4())
        ts = int(time.time())
        doc = text or f"{kind} = {value}"
        if not isinstance(value, (str, int, float, bool)):
            value_serialized = json.dumps(value)
            value_kind = "json"
        else:
            value_serialized = value
            value_kind = "scalar"
        self._collection.add(
            ids=[chunk_id],
            documents=[doc],
            metadatas=[{
                "role": "fact",
                "kind": kind,
                "value": value_serialized,
                "value_kind": value_kind,
                "timestamp": ts,
                "user_id": user_id,
            }],
        )
        return chunk_id

    def get_fact(
        self, kind: str, *, user_id: str = "primary"
    ) -> dict | None:
        res = self._collection.get(
            where={
                "$and": [
                    {"user_id": user_id},
                    {"role": "fact"},
                    {"kind": kind},
                ]
            },
            include=["documents", "metadatas"],
        )
        ids = res.get("ids") or []
        if not ids:
            return None
        metas = res.get("metadatas") or []
        docs = res.get("documents") or []
        candidates = []
        for i, fid in enumerate(ids):
            m = metas[i] or {}
            candidates.append({
                "id": fid,
                "kind": m.get("kind"),
                "value": self._deserialize_fact_value(m),
                "text": docs[i] if i < len(docs) else "",
                "timestamp": int(m.get("timestamp", 0)),
            })
        candidates.sort(key=lambda c: c["timestamp"], reverse=True)
        return candidates[0]

    def all_facts(
        self,
        kind: str | None = None,
        *,
        user_id: str = "primary",
    ) -> list[dict]:
        where = {
            "$and": [
                {"user_id": user_id},
                {"role": "fact"},
            ]
        }
        if kind is not None:
            where["$and"].append({"kind": kind})
        res = self._collection.get(where=where, include=["documents", "metadatas"])
        ids = res.get("ids") or []
        metas = res.get("metadatas") or []
        docs = res.get("documents") or []
        out = []
        for i, fid in enumerate(ids):
            m = metas[i] or {}
            out.append({
                "id": fid,
                "kind": m.get("kind"),
                "value": self._deserialize_fact_value(m),
                "text": docs[i] if i < len(docs) else "",
                "timestamp": int(m.get("timestamp", 0)),
            })
        out.sort(key=lambda c: c["timestamp"], reverse=True)
        return out

    @staticmethod
    def _deserialize_fact_value(metadata: dict):
        import json
        v = metadata.get("value")
        vk = metadata.get("value_kind", "scalar")
        if vk == "json" and isinstance(v, str):
            try:
                return json.loads(v)
            except Exception:
                return v
        return v
```

Also update the `recall` `where` clause to exclude `role: "fact"`:

```python
        res = self._collection.query(
            query_texts=[query.strip()],
            n_results=n_results,
            where={
                "$and": [
                    {"user_id": user_id},
                    {"role": {"$ne": "fact"}},
                ]
            },
        )
```

- [ ] **Step 4: Run tests**

```bash
cd backend && .venv/bin/pytest tests/test_api.py -k "fact" -v
```

Expected: 4 passed.

- [ ] **Step 5: Run full suite**

```bash
cd backend && .venv/bin/pytest tests/ -q
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add backend/samantha/memory.py backend/tests/test_api.py
git commit -m "feat(memory): add facts (role='fact') with set_fact/get_fact/all_facts"
```

---

### Phase 1 Checkpoint

Pause for human review. Confirm `pytest tests/ -v` is fully green before continuing.

---

## Phase 2 — Profile facade + `/profile` endpoints

**Goal:** Thin `profile.py` over Memory + `/profile` HTTP endpoints + `has_profile` in `/ping`.

### Task 2.1: Create profile.py facade

**Files:**
- Create: `backend/samantha/profile.py`
- Create: `backend/tests/test_profile.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_profile.py`:

```python
"""Tests for the profile facade over Memory."""

from samantha.memory import Memory
from samantha.profile import (
    complete_onboarding,
    delete_profile,
    get_profile,
    is_onboarded,
)


def _six_answers() -> list[dict]:
    return [
        {"q": "¿Cómo te llamo?", "a": "Bob"},
        {"q": "¿Cómo estás hoy?", "a": "regular"},
        {"q": "¿Qué te gusta hacer?", "a": "salir a correr"},
        {"q": "Cuéntame algo que te haya hecho ilusión",
         "a": "encontré un café nuevo"},
        {"q": "¿Algo que te ronde la cabeza?", "a": "mi color favorito es el azul"},
        {"q": "¿Directa o cuidadosa?", "a": "directa"},
    ]


def _make_mem(tmp_path):
    return Memory(persist_dir=str(tmp_path / "mem"))


def test_not_onboarded_initially(tmp_path):
    mem = _make_mem(tmp_path)
    assert is_onboarded(mem) is False
    assert get_profile(mem) is None


def test_complete_onboarding_sets_facts(tmp_path):
    mem = _make_mem(tmp_path)
    profile = complete_onboarding(mem, name="Horelvis", answers=_six_answers())
    assert profile["name"] == "Horelvis"
    assert profile["onboarding_completed_at"] > 0
    assert len(profile["answers"]) == 6


def test_onboarding_persists_across_reopen(tmp_path):
    mem1 = _make_mem(tmp_path)
    complete_onboarding(mem1, name="Alice", answers=_six_answers())
    del mem1
    mem2 = _make_mem(tmp_path)
    assert is_onboarded(mem2) is True
    profile = get_profile(mem2)
    assert profile["name"] == "Alice"


def test_onboarding_answers_become_user_memory_chunks(tmp_path):
    mem = _make_mem(tmp_path)
    complete_onboarding(mem, name="Bob", answers=_six_answers())
    results = mem.recall("color favorito", k=10)
    expected_substrings = ["azul", "café", "correr"]
    matched = any(
        any(s.lower() in r.text.lower() for s in expected_substrings)
        for r in results
    )
    assert matched, f"recall returned {[r.text for r in results]}"


def test_delete_profile_removes_facts_only(tmp_path):
    mem = _make_mem(tmp_path)
    complete_onboarding(mem, name="Carlos", answers=_six_answers())
    delete_profile(mem)
    assert is_onboarded(mem) is False
    results = mem.recall("color favorito", k=10)
    assert results, "user memory chunks must survive profile deletion"
```

- [ ] **Step 2: Verify tests fail**

```bash
cd backend && .venv/bin/pytest tests/test_profile.py -q
```

Expected: 5 errors (ImportError on `samantha.profile`).

- [ ] **Step 3: Implement profile.py**

Create `backend/samantha/profile.py`:

```python
"""Thin facade over Memory that synthesizes a "profile" from facts +
conversational chunks. No `profile.json` — everything lives in
Samantha's memory.
"""

from __future__ import annotations

import time

from .memory import Memory


def is_onboarded(mem: Memory, *, user_id: str = "primary") -> bool:
    return mem.get_fact("onboarding_completed_at", user_id=user_id) is not None


def get_profile(
    mem: Memory, *, user_id: str = "primary"
) -> dict | None:
    if not is_onboarded(mem, user_id=user_id):
        return None
    name_fact = mem.get_fact("name", user_id=user_id)
    ts_fact = mem.get_fact("onboarding_completed_at", user_id=user_id)
    name = name_fact["value"] if name_fact else "tú"
    ts = int(ts_fact["value"]) if ts_fact else 0
    return {
        "name": name,
        "onboarding_completed_at": ts,
        "answers": _recover_answers(mem, ts, user_id=user_id),
    }


def complete_onboarding(
    mem: Memory,
    name: str,
    answers: list[dict],
    *,
    user_id: str = "primary",
) -> dict:
    name = (name or "").strip()
    if not name:
        raise ValueError("name must be non-empty")
    if len(answers) != 6:
        raise ValueError(f"answers must have length 6, got {len(answers)}")

    # Insert the 6 answer chunks FIRST so they share a tight timestamp
    # window with the onboarding marker (recovery uses ±5s window).
    for entry in answers:
        q = (entry.get("q") or "").strip()
        a = entry.get("a")
        if not q or not a or not str(a).strip():
            continue
        mem.remember(
            "user",
            f"[Q] {q} → [A] {str(a).strip()}",
            user_id=user_id,
        )

    mem.set_fact(
        "name", name,
        text=f"El usuario se llama {name}",
        user_id=user_id,
    )
    ts = int(time.time())
    mem.set_fact(
        "onboarding_completed_at", ts,
        text=f"Onboarding completado en {ts}",
        user_id=user_id,
    )

    profile = get_profile(mem, user_id=user_id)
    assert profile is not None
    return profile


def delete_profile(mem: Memory, *, user_id: str = "primary") -> bool:
    """ADMIN-ONLY. Removes name + onboarding_completed_at facts.
    The 6 answer chunks stay (Samantha never forgets)."""
    facts = mem.all_facts(user_id=user_id)
    if not facts:
        return False
    to_delete = [
        f["id"] for f in facts
        if f.get("kind") in ("name", "onboarding_completed_at")
    ]
    if not to_delete:
        return False
    mem._collection.delete(ids=to_delete)
    return True


def _recover_answers(
    mem: Memory, anchor_ts: int, *, user_id: str = "primary"
) -> list[dict]:
    """Find role='user' chunks inserted within ±5 s of the onboarding marker."""
    if anchor_ts <= 0:
        return []
    res = mem._collection.get(
        where={
            "$and": [
                {"user_id": user_id},
                {"role": "user"},
                {"timestamp": {"$gte": anchor_ts - 5}},
                {"timestamp": {"$lte": anchor_ts + 5}},
            ]
        },
        include=["documents", "metadatas"],
    )
    docs = res.get("documents") or []
    metas = res.get("metadatas") or []
    items = list(zip(docs, metas))
    items.sort(key=lambda x: int(x[1].get("timestamp", 0)))
    out = []
    for doc, _meta in items:
        if "[Q]" in doc and "→ [A]" in doc:
            q = doc.split("[Q]", 1)[1].split("→ [A]", 1)[0].strip()
            a = doc.split("→ [A]", 1)[1].strip()
            out.append({"q": q, "a": a})
    return out
```

- [ ] **Step 4: Run tests**

```bash
cd backend && .venv/bin/pytest tests/test_profile.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Run full suite**

```bash
cd backend && .venv/bin/pytest tests/ -q
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add backend/samantha/profile.py backend/tests/test_profile.py
git commit -m "feat(profile): add thin facade over Memory (no profile.json)"
```

---

### Task 2.2: Add `/profile` HTTP endpoints + has_profile in /ping

**Files:**
- Modify: `backend/samantha/schemas.py`
- Modify: `backend/samantha/api.py`
- Modify: `backend/tests/test_api.py`

- [ ] **Step 1: Add Pydantic schemas**

Append to `backend/samantha/schemas.py`:

```python
# ========================================================================
# /profile
# ========================================================================


class ProfileAnswer(BaseModel):
    q: str = Field(min_length=1, max_length=400)
    a: str | None = Field(default=None, max_length=2000)


class ProfileCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    answers: list[ProfileAnswer] = Field(min_length=6, max_length=6)


class ProfileResponse(BaseModel):
    name: str
    onboarding_completed_at: int
    answers: list[ProfileAnswer]
```

Update the existing `PingResponse` to add `has_profile`:

```python
class PingResponse(BaseModel):
    status: str = Field(description="'ok' si todo va bien")
    version: str = Field(description="Versión del backend")
    timestamp: int = Field(description="Unix timestamp en segundos")
    mode: str = Field(description="'mock' o 'real'")
    has_profile: bool = Field(default=False, description="True si Samantha ya conoce a esta persona")
```

- [ ] **Step 2: Write failing endpoint tests**

Append to `backend/tests/test_api.py`:

```python
def test_get_profile_404_when_no_profile():
    response = client.get("/profile")
    # Memory disabled in conftest → 503 expected. We just assert it's not 200.
    assert response.status_code in (404, 503)


def test_ping_includes_has_profile():
    response = client.get("/ping")
    assert response.status_code == 200
    data = response.json()
    assert "has_profile" in data
    assert isinstance(data["has_profile"], bool)


def test_profile_endpoints_full_cycle(tmp_path, monkeypatch):
    """End-to-end: profile starts missing, becomes onboarded after POST."""
    from samantha import api as api_mod
    from samantha.memory import Memory

    mem = Memory(persist_dir=str(tmp_path / "mem"))
    monkeypatch.setattr(api_mod, "_memory", mem)
    monkeypatch.setattr(api_mod.config, "memory_enabled", True)
    api_mod._memory_init_failed = False

    r = client.get("/profile")
    assert r.status_code == 404
    ping = client.get("/ping").json()
    assert ping["has_profile"] is False

    body = {
        "name": "Horelvis",
        "answers": [
            {"q": "¿Cómo te llamo?", "a": "Horelvis"},
            {"q": "¿Cómo estás hoy?", "a": "bien"},
            {"q": "¿Qué te gusta?", "a": "leer"},
            {"q": "¿Algo que te ilusione?", "a": "un viaje a Lisboa"},
            {"q": "¿Algo que te ronde?", "a": "trabajo"},
            {"q": "¿Directa o cuidadosa?", "a": "directa"},
        ],
    }
    r = client.post("/profile", json=body)
    assert r.status_code == 200, r.text
    saved = r.json()
    assert saved["name"] == "Horelvis"

    r = client.get("/profile")
    assert r.status_code == 200
    ping = client.get("/ping").json()
    assert ping["has_profile"] is True

    r = client.delete("/profile")
    assert r.status_code == 200
    r = client.get("/profile")
    assert r.status_code == 404


def test_profile_post_rejects_empty_body():
    r = client.post("/profile", json={})
    assert r.status_code == 422


def test_profile_post_rejects_short_answers():
    r = client.post("/profile", json={
        "name": "Foo",
        "answers": [{"q": "q", "a": "a"}],
    })
    assert r.status_code == 422
```

- [ ] **Step 3: Run tests, expect failures on full_cycle + ping**

```bash
cd backend && .venv/bin/pytest tests/test_api.py::test_ping_includes_has_profile tests/test_api.py::test_profile_endpoints_full_cycle -v
```

Expected: failures (endpoints don't exist, ping missing field).

- [ ] **Step 4: Implement endpoints in api.py**

Add to imports at the top of `backend/samantha/api.py`:

```python
from .profile import (
    complete_onboarding as _complete_onboarding,
    delete_profile as _delete_profile,
    get_profile as _get_profile,
    is_onboarded as _is_onboarded,
)
from .schemas import (
    ChatRequest,
    ChatResponse,
    PingResponse,
    ProfileCreateRequest,
    ProfileResponse,
    SpeakRequest,
    TranscribeResponse,
)
```

Replace the existing `ping` handler:

```python
@app.get("/ping", response_model=PingResponse)
async def ping() -> PingResponse:
    mem = get_memory()
    has_profile = bool(mem and _is_onboarded(mem))
    return PingResponse(
        status="ok",
        version=__version__,
        timestamp=int(time.time()),
        mode=config.mode,
        has_profile=has_profile,
    )
```

Add three new endpoints (anywhere after `chat`, before `/transcribe`):

```python
@app.get("/profile", response_model=ProfileResponse)
async def get_profile_endpoint() -> ProfileResponse:
    mem = get_memory()
    if mem is None:
        raise HTTPException(status_code=503, detail="memory_disabled")
    profile = _get_profile(mem)
    if profile is None:
        raise HTTPException(status_code=404, detail="not_onboarded")
    return ProfileResponse(**profile)


@app.post("/profile", response_model=ProfileResponse)
async def create_profile_endpoint(req: ProfileCreateRequest) -> ProfileResponse:
    mem = get_memory()
    if mem is None:
        raise HTTPException(status_code=503, detail="memory_disabled")
    try:
        profile = _complete_onboarding(
            mem,
            name=req.name,
            answers=[a.model_dump() for a in req.answers],
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return ProfileResponse(**profile)


@app.delete("/profile")
async def delete_profile_endpoint() -> dict:
    mem = get_memory()
    if mem is None:
        raise HTTPException(status_code=503, detail="memory_disabled")
    deleted = _delete_profile(mem)
    return {"deleted": deleted}
```

- [ ] **Step 5: Run full test suite**

```bash
cd backend && .venv/bin/pytest tests/ -q
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add backend/samantha/api.py backend/samantha/schemas.py backend/tests/test_api.py
git commit -m "feat(api): add /profile endpoints + has_profile in /ping"
```

---

### Phase 2 Checkpoint

Stop. Confirm `pytest tests/` fully green and manual smoke:

```bash
cd backend && .venv/bin/python -m samantha.api &
sleep 1
curl -s http://127.0.0.1:7777/ping
curl -s http://127.0.0.1:7777/profile -i
kill %1
```

---

## Phase 3 — Prompt assembly with facts + recall + short-term

**Goal:** `real_llm._build_payload` accepts `facts`, `recall`, `short_term` kwargs and assembles them per spec §9.6. `api.py` `/chat` and `/ws` thread the context through.

### Task 3.1: Extend `real_llm` builders

**Files:**
- Modify: `backend/samantha/real_llm.py`
- Modify: `backend/tests/test_api.py`

- [ ] **Step 1: Write failing test**

Append to `backend/tests/test_api.py`:

```python
def test_real_llm_build_payload_includes_facts_recall_and_short_term():
    """Spec §9.6 — the prompt has 3 labeled sections in order."""
    from samantha import real_llm
    from samantha.memory import MemoryChunk

    facts = [
        {"kind": "name", "value": "Horelvis",
         "text": "El usuario se llama Horelvis"},
        {"kind": "onboarding_completed_at", "value": 1778000000,
         "text": "Onboarding completado en 1778000000"},
    ]
    recall = [
        MemoryChunk(id="r1", role="user", text="Trabajo en una agencia",
                    timestamp=1778001000, user_id="primary"),
    ]
    short_term = [
        MemoryChunk(id="s1", role="user", text="¿qué tal el día?",
                    timestamp=1778002000, user_id="primary"),
        MemoryChunk(id="s2", role="samantha", text="Bien. ¿Y tú?",
                    timestamp=1778002005, user_id="primary"),
    ]

    payload = real_llm._build_payload(
        message="me siento perdido",
        facts=facts,
        recall=recall,
        short_term=short_term,
    )
    system = payload["messages"][0]["content"]
    assert "# Lo que sabes de ella" in system
    assert "Horelvis" in system
    assert "# Lo que recuerdas" in system
    assert "agencia" in system
    assert "# Conversación reciente" in system
    assert "¿qué tal el día?" in system
    assert (
        system.find("# Lo que sabes")
        < system.find("# Lo que recuerdas")
        < system.find("# Conversación reciente")
    )
    assert payload["messages"][-1]["role"] == "user"
    assert payload["messages"][-1]["content"] == "me siento perdido\n/no_think"
```

Also update the existing `test_real_llm_injects_memories_into_system_prompt` to use the new kwarg name `recall=` instead of `memories=`. Find it and replace its body:

```python
def test_real_llm_injects_memories_into_system_prompt():
    """When recall chunks are passed, they appear under '# Lo que recuerdas'."""
    from samantha import real_llm
    from samantha.memory import MemoryChunk

    memories = [
        MemoryChunk(id="x1", role="user", text="Tengo un perro Toby",
                    timestamp=1700000000, user_id="primary"),
    ]
    payload = real_llm._build_payload("¿cómo está Toby?", recall=memories)
    system = payload["messages"][0]["content"]
    assert "# Lo que recuerdas" in system
    assert "Toby" in system
    assert payload["messages"][-1]["content"] == "¿cómo está Toby?\n/no_think"
```

- [ ] **Step 2: Run tests, expect failures**

```bash
cd backend && .venv/bin/pytest tests/test_api.py::test_real_llm_build_payload_includes_facts_recall_and_short_term -v
```

Expected: TypeError on `_build_payload`.

- [ ] **Step 3: Replace `_format_memories` and `_build_payload`**

In `backend/samantha/real_llm.py`, replace the existing `_format_memories` function and `_build_payload` with these. Keep the rest of the module unchanged.

```python
def _format_facts(facts: list[dict]) -> str:
    if not facts:
        return ""
    lines = ["", "# Lo que sabes de ella"]
    for f in facts:
        line = f.get("text") or f"{f.get('kind')} = {f.get('value')}"
        lines.append(f"- {line}")
    return "\n".join(lines)


def _format_recall(chunks: list) -> str:
    if not chunks:
        return ""
    lines = ["", "# Lo que recuerdas"]
    for c in chunks:
        when = (
            time.strftime("%Y-%m-%d", time.localtime(c.timestamp))
            if c.timestamp else "?"
        )
        who = "tú dijiste" if c.role == "samantha" else "ella"
        snippet = c.text if len(c.text) <= 280 else c.text[:277] + "..."
        lines.append(f"- {when}  ({who}): {snippet}")
    return "\n".join(lines)


def _format_short_term(chunks: list) -> str:
    if not chunks:
        return ""
    lines = ["", "# Conversación reciente"]
    for c in chunks:
        who = "tú" if c.role == "samantha" else "ella"
        lines.append(f"{who}: {c.text}")
    return "\n".join(lines)


def _build_payload(
    message: str,
    *,
    facts: list[dict] | None = None,
    recall: list | None = None,
    short_term: list | None = None,
) -> dict:
    system = SYSTEM_PROMPT
    if facts:
        system += _format_facts(facts)
    if recall:
        system += _format_recall(recall)
    if short_term:
        system += _format_short_term(short_term)
    return {
        "model": config.llm_model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": f"{message}\n/no_think"},
        ],
        "stream": True,
    }
```

Update the signatures of `stream_reply` and `generate_reply` to accept the new kwargs and pass them through:

```python
async def stream_reply(
    message: str,
    *,
    facts: list[dict] | None = None,
    recall: list | None = None,
    short_term: list | None = None,
) -> AsyncIterator[str]:
    url = f"{config.llm_server_url.rstrip('/')}/v1/chat/completions"
    payload = _build_payload(
        message, facts=facts, recall=recall, short_term=short_term,
    )
    client = _get_client()
    logger.debug(
        f"real_llm: POST {url} prompt_version={SYSTEM_PROMPT_VERSION} "
        f"chars={len(message)} facts={len(facts) if facts else 0} "
        f"recall={len(recall) if recall else 0} "
        f"short_term={len(short_term) if short_term else 0}"
    )
    # ... keep the existing try/async-with stream + SSE parsing body ...
```

Only modify the function signature and the `payload = ...`/`logger.debug` lines. The rest of `stream_reply` stays the same.

Do the same for `generate_reply`:

```python
async def generate_reply(
    message: str,
    *,
    facts: list[dict] | None = None,
    recall: list | None = None,
    short_term: list | None = None,
) -> str:
    chunks: list[str] = []
    async for tok in stream_reply(
        message, facts=facts, recall=recall, short_term=short_term
    ):
        chunks.append(tok)
    return "".join(chunks).strip() or _FALLBACK_REPLY
```

- [ ] **Step 4: Run tests**

```bash
cd backend && .venv/bin/pytest tests/ -q
```

Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add backend/samantha/real_llm.py backend/tests/test_api.py
git commit -m "feat(llm): prompt assembly with facts + recall + short-term (§9.6)"
```

---

### Task 3.2: Wire api.py /chat and /ws to assemble the new prompt

**Files:**
- Modify: `backend/samantha/api.py`

- [ ] **Step 1: Add `_collect_facts` helper near the top of api.py (after `get_memory`)**

```python
def _collect_facts(mem, *, user_id: str) -> list[dict]:
    """Gather facts surfaced into the system prompt. Today: name +
    onboarding_completed_at. Future preferences land here too."""
    out: list[dict] = []
    for kind in ("name", "onboarding_completed_at"):
        f = mem.get_fact(kind, user_id=user_id)
        if f is not None:
            out.append(f)
    return out
```

- [ ] **Step 2: Update `_stream_tokens` to forward context**

Replace the existing `_stream_tokens` function with:

```python
async def _stream_tokens(
    message: str,
    *,
    facts: list[dict] | None = None,
    recall: list | None = None,
    short_term: list | None = None,
) -> AsyncIterator[str]:
    if config.mode == "real":
        from .real_llm import stream_reply as real_stream_reply
        async for tok in real_stream_reply(
            message, facts=facts, recall=recall, short_term=short_term
        ):
            yield tok
        return

    await asyncio.sleep(random.uniform(0.2, 0.6))
    reply = mock_generate_reply(message)
    for token in tokenize_for_streaming(reply):
        await asyncio.sleep(config.mock_streaming_delay_s)
        yield token
```

- [ ] **Step 3: Update `chat` handler**

Replace the body of `chat` (after the logger.info line, before returning):

```python
@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    start = time.perf_counter()
    logger.info(f"chat: user_id={req.user_id} message='{req.message[:60]}'")

    mem = get_memory()
    facts: list[dict] = []
    recall: list = []
    short: list = []
    if mem is not None:
        mem.remember("user", req.message, user_id=req.user_id)
        facts = _collect_facts(mem, user_id=req.user_id)
        recall = mem.recall(
            req.message, k=config.memory_recall_top_k, user_id=req.user_id
        )
        short = mem.short_term(user_id=req.user_id)

    if config.mode == "real":
        from .real_llm import generate_reply as real_generate_reply
        reply = await real_generate_reply(
            req.message, facts=facts, recall=recall, short_term=short
        )
    else:
        latency = random.uniform(config.mock_min_latency_s, config.mock_max_latency_s)
        await asyncio.sleep(latency)
        reply = mock_generate_reply(req.message)

    if mem is not None and reply:
        mem.remember("samantha", reply, user_id=req.user_id)

    elapsed_ms = int((time.perf_counter() - start) * 1000)
    logger.info(f"chat: replied in {elapsed_ms}ms — '{reply[:60]}'")
    return ChatResponse(
        reply=reply,
        thinking_ms=elapsed_ms,
        model=None if config.mode == "mock" else config.llm_model,
    )
```

- [ ] **Step 4: Update `_ws_stream_chat`**

Replace its body:

```python
async def _ws_stream_chat(websocket: WebSocket, message: str, user_id: str) -> None:
    start = time.perf_counter()
    logger.info(
        f"ws chat: user_id={user_id} mode={config.mode} "
        f"message='{message[:60]}'"
    )

    mem = get_memory()
    facts: list[dict] = []
    recall: list = []
    short: list = []
    if mem is not None:
        mem.remember("user", message, user_id=user_id)
        facts = _collect_facts(mem, user_id=user_id)
        recall = mem.recall(
            message, k=config.memory_recall_top_k, user_id=user_id
        )
        short = mem.short_term(user_id=user_id)

    reply_chunks: list[str] = []
    async for token in _stream_tokens(
        message, facts=facts, recall=recall, short_term=short
    ):
        reply_chunks.append(token)
        await websocket.send_text(
            json.dumps({"type": "token", "token": token})
        )

    if mem is not None and reply_chunks:
        full_reply = "".join(reply_chunks).strip()
        if full_reply:
            mem.remember("samantha", full_reply, user_id=user_id)

    elapsed_ms = int((time.perf_counter() - start) * 1000)
    await websocket.send_text(
        json.dumps({"type": "done", "thinking_ms": elapsed_ms})
    )
```

- [ ] **Step 5: Run full suite**

```bash
cd backend && .venv/bin/pytest tests/ -q
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add backend/samantha/api.py
git commit -m "feat(api): /chat and /ws assemble facts + recall + short-term per §9.6"
```

---

### Phase 3 Checkpoint

Smoke test with real GPU if available:

```bash
cd backend && \
SAMANTHA_MODE=real \
SAMANTHA_LLM_SERVER_URL=http://192.168.100.58:8000 \
.venv/bin/python -m samantha.api &
sleep 1
curl -s -X POST -H 'Content-Type: application/json' \
  -d '{"message":"Me llamo Horelvis","user_id":"primary"}' \
  http://127.0.0.1:7777/chat
echo
curl -s -X POST -H 'Content-Type: application/json' \
  -d '{"message":"¿Recuerdas mi nombre?","user_id":"primary"}' \
  http://127.0.0.1:7777/chat
kill %1
```

Second reply should reference "Horelvis" or acknowledge remembering.

**End of backend phases. Frontend begins.**

---

## Phase 4 — Frontend scaffolding (React + Vite + TypeScript)

**Goal:** Spin up `frontend/` with Vite + React + TS. Ship a Boot screen that calls `/ping` and navigates to placeholder Ambient or Onboarding.

### Task 4.1: Init the frontend project

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/tsconfig.json`
- Create: `frontend/tsconfig.node.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/index.html`
- Create: `frontend/.gitignore`
- Modify: `.gitignore` (root)

- [ ] **Step 1: Create directories**

```bash
mkdir -p frontend/src/{styles,core,net,components,screens}
mkdir -p frontend/public
```

- [ ] **Step 2: Write `frontend/package.json`**

```json
{
  "name": "samantha-frontend",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview",
    "typecheck": "tsc --noEmit"
  },
  "dependencies": {
    "react": "^18.3.0",
    "react-dom": "^18.3.0",
    "zustand": "^5.0.0",
    "three": "^0.160.0"
  },
  "devDependencies": {
    "@types/react": "^18.3.0",
    "@types/react-dom": "^18.3.0",
    "@types/three": "^0.160.0",
    "@vitejs/plugin-react": "^4.3.0",
    "typescript": "^5.5.0",
    "vite": "^5.4.0"
  }
}
```

- [ ] **Step 3: Write `frontend/tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "useDefineForClassFields": true,
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true
  },
  "include": ["src"],
  "references": [{ "path": "./tsconfig.node.json" }]
}
```

- [ ] **Step 4: Write `frontend/tsconfig.node.json`**

```json
{
  "compilerOptions": {
    "composite": true,
    "skipLibCheck": true,
    "module": "ESNext",
    "moduleResolution": "bundler",
    "allowSyntheticDefaultImports": true,
    "strict": true
  },
  "include": ["vite.config.ts"]
}
```

- [ ] **Step 5: Write `frontend/vite.config.ts`**

```ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/chat": "http://localhost:7777",
      "/speak": "http://localhost:7777",
      "/transcribe": "http://localhost:7777",
      "/ping": "http://localhost:7777",
      "/profile": "http://localhost:7777",
      "/ws": { target: "ws://localhost:7777", ws: true },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
  },
});
```

- [ ] **Step 6: Write `frontend/index.html`**

```html
<!doctype html>
<html lang="es">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover, user-scalable=no" />
    <meta name="theme-color" content="#d1684e" />
    <title>Samantha</title>
    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
    <link
      href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,300;0,400;1,300;1,400&family=Inter+Tight:wght@200;300;400;500&display=swap"
      rel="stylesheet"
    />
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 7: Write `frontend/.gitignore`**

```
node_modules
dist
*.local
.DS_Store
```

- [ ] **Step 8: Update root `.gitignore`**

Append:

```
# Frontend
frontend/node_modules/
frontend/dist/
```

- [ ] **Step 9: Install deps**

```bash
cd frontend && npm install
```

Expected: completes without errors.

- [ ] **Step 10: Commit**

```bash
git add frontend/package.json frontend/tsconfig.json frontend/tsconfig.node.json frontend/vite.config.ts frontend/index.html frontend/.gitignore .gitignore
git commit -m "feat(frontend): init Vite + React + TypeScript project"
```

---

### Task 4.2: Design tokens + base styles

**Files:**
- Create: `frontend/src/styles/tokens.css`
- Create: `frontend/src/styles/base.css`
- Create: `frontend/src/styles/components.css`

- [ ] **Step 1: Write `tokens.css`**

```css
:root {
  --bg: #d1684e;
  --ink: rgba(255, 255, 255, 1);
  --ink-label: rgba(255, 255, 255, 0.9);
  --ink-soft: rgba(255, 255, 255, 0.85);
  --ink-dim: rgba(255, 255, 255, 0.6);
  --ink-faint: rgba(255, 255, 255, 0.4);
  --ink-trace: rgba(255, 255, 255, 0.2);
  --mic-active: #ffffff;

  --serif: "Cormorant Garamond", Georgia, serif;
  --sans: "Inter Tight", -apple-system, sans-serif;

  --text-display: 2.4rem;
  --text-ambient: 1.5rem;
  --text-her-large: 1.2rem;
  --text-her-history: 0.95rem;
  --text-user: 0.95rem;
  --text-brand: 0.82rem;
  --text-input: 0.75rem;
  --text-label: 0.68rem;

  --space-xs: 8px;
  --space-sm: 16px;
  --space-md: 24px;
  --space-lg: 40px;
  --space-xl: 64px;
}
```

- [ ] **Step 2: Write `base.css`**

```css
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
  -webkit-tap-highlight-color: transparent;
}

html, body, #root {
  width: 100%;
  height: 100%;
  overflow: hidden;
  background: var(--bg);
  color: var(--ink);
  font-family: var(--sans);
  font-weight: 300;
  -webkit-font-smoothing: antialiased;
  user-select: none;
  -webkit-user-select: none;
}

.screen {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 8vh 6vw;
  transition: opacity 0.6s cubic-bezier(0.22, 1, 0.36, 1);
}
```

- [ ] **Step 3: Write `components.css`**

```css
.label {
  font-family: var(--sans);
  font-size: var(--text-label);
  font-weight: 400;
  letter-spacing: 0.34em;
  text-transform: uppercase;
  color: var(--ink-label);
}

.brand {
  font-family: var(--sans);
  font-size: var(--text-brand);
  font-weight: 400;
  letter-spacing: 0.42em;
  text-transform: uppercase;
  color: var(--ink-label);
}

.her-text {
  font-family: var(--serif);
  font-style: italic;
  font-weight: 300;
  color: var(--ink);
}

.user-text {
  font-family: var(--sans);
  font-size: var(--text-user);
  font-weight: 300;
  color: var(--ink-dim);
}

.mic-btn {
  width: 48px;
  height: 48px;
  border-radius: 50%;
  background: var(--mic-active);
  border: none;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
}
.mic-btn svg { width: 22px; height: 22px; fill: var(--bg); }
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/styles/
git commit -m "feat(frontend): add design tokens + base + components CSS"
```

---

### Task 4.3: Core types and store

**Files:**
- Create: `frontend/src/core/types.ts`
- Create: `frontend/src/core/store.ts`

- [ ] **Step 1: Write `types.ts`**

```ts
export type ScreenName = "boot" | "onboarding" | "ambient" | "conversation";

export type WaveMode = "idle" | "listening" | "thinking" | "speaking";

export interface ProfileAnswer {
  q: string;
  a: string | null;
}

export interface Profile {
  name: string;
  onboarding_completed_at: number;
  answers: ProfileAnswer[];
}

export interface PingResponse {
  status: "ok";
  version: string;
  timestamp: number;
  mode: "mock" | "real";
  has_profile: boolean;
}

export type Role = "user" | "samantha";

export interface ChatMessage {
  id: string;
  role: Role;
  text: string;
  timestamp: number;
}

export type WSClientToServer =
  | { type: "chat"; message: string; user_id: string }
  | { type: "listen" };

export type WSServerToClient =
  | { type: "token"; token: string }
  | { type: "done"; thinking_ms: number }
  | { type: "transcription"; text: string }
  | { type: "error"; error: string };
```

- [ ] **Step 2: Write `store.ts`**

```ts
import { create } from "zustand";
import type { ChatMessage, ScreenName } from "./types";

interface SamanthaState {
  screen: ScreenName;
  name: string | null;
  transcript: ChatMessage[];
  setScreen: (s: ScreenName) => void;
  setName: (n: string | null) => void;
  appendMessage: (m: ChatMessage) => void;
  patchMessage: (id: string, text: string) => void;
  resetTranscript: () => void;
}

export const useSamantha = create<SamanthaState>((set) => ({
  screen: "boot",
  name: null,
  transcript: [],
  setScreen: (s) => set({ screen: s }),
  setName: (n) => set({ name: n }),
  appendMessage: (m) =>
    set((state) => ({ transcript: [...state.transcript, m] })),
  patchMessage: (id, text) =>
    set((state) => ({
      transcript: state.transcript.map((m) =>
        m.id === id ? { ...m, text } : m,
      ),
    })),
  resetTranscript: () => set({ transcript: [] }),
}));
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/core/types.ts frontend/src/core/store.ts
git commit -m "feat(frontend): core types + zustand store"
```

---

### Task 4.4: Network clients

**Files:**
- Create: `frontend/src/net/profile.ts`
- Create: `frontend/src/net/tts.ts`
- Create: `frontend/src/net/wsClient.ts`
- Create: `frontend/src/net/mic.ts`

- [ ] **Step 1: Write `profile.ts`**

```ts
import type { Profile, ProfileAnswer } from "../core/types";

export async function fetchProfile(): Promise<Profile | null> {
  const res = await fetch("/profile");
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`fetchProfile failed: ${res.status}`);
  return res.json();
}

export async function createProfile(
  name: string,
  answers: ProfileAnswer[],
): Promise<Profile> {
  const res = await fetch("/profile", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, answers }),
  });
  if (!res.ok) throw new Error(`createProfile failed: ${res.status}`);
  return res.json();
}
```

- [ ] **Step 2: Write `tts.ts`**

```ts
export async function speak(text: string): Promise<void> {
  const res = await fetch("/speak", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, voice: "default" }),
  });
  if (!res.ok) return;
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const audio = new Audio(url);
  await new Promise<void>((resolve) => {
    audio.addEventListener("ended", () => resolve(), { once: true });
    audio.addEventListener("error", () => resolve(), { once: true });
    audio.play().catch(() => resolve());
  });
  URL.revokeObjectURL(url);
}
```

- [ ] **Step 3: Write `wsClient.ts`**

```ts
import type { WSClientToServer, WSServerToClient } from "../core/types";

type Handler<T extends WSServerToClient["type"]> = (
  msg: Extract<WSServerToClient, { type: T }>,
) => void;

export class WSClient {
  private ws: WebSocket | null = null;
  private handlers = new Map<string, (msg: WSServerToClient) => void>();
  private reconnectDelay = 500;
  private maxReconnectDelay = 8000;
  private shouldReconnect = true;

  constructor(public readonly url: string) {
    this.connect();
  }

  private connect() {
    this.ws = new WebSocket(this.url);
    this.ws.addEventListener("open", () => { this.reconnectDelay = 500; });
    this.ws.addEventListener("message", (ev) => {
      try {
        const msg = JSON.parse(ev.data) as WSServerToClient;
        const h = this.handlers.get(msg.type);
        if (h) h(msg);
      } catch {
        // ignore non-JSON
      }
    });
    this.ws.addEventListener("close", () => {
      if (this.shouldReconnect) {
        setTimeout(() => this.connect(), this.reconnectDelay);
        this.reconnectDelay = Math.min(
          this.maxReconnectDelay,
          this.reconnectDelay * 1.8,
        );
      }
    });
  }

  on<T extends WSServerToClient["type"]>(type: T, handler: Handler<T>): void {
    this.handlers.set(type, handler as (msg: WSServerToClient) => void);
  }

  send(msg: WSClientToServer): boolean {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return false;
    this.ws.send(JSON.stringify(msg));
    return true;
  }

  chat(
    message: string,
    onToken: (t: string) => void,
    userId = "primary",
  ): Promise<{ reply: string; thinkingMs: number }> {
    return new Promise((resolve, reject) => {
      let full = "";
      const restore = () => {
        this.handlers.delete("token");
        this.handlers.delete("done");
        this.handlers.delete("error");
      };
      this.on("token", (m) => { full += m.token; onToken(m.token); });
      this.on("done", (m) => { restore(); resolve({ reply: full, thinkingMs: m.thinking_ms }); });
      this.on("error", (m) => { restore(); reject(new Error(m.error)); });
      if (!this.send({ type: "chat", message, user_id: userId })) {
        restore();
        reject(new Error("ws_not_connected"));
      }
    });
  }

  listen(): Promise<string> {
    return new Promise((resolve, reject) => {
      this.on("transcription", (m) => {
        this.handlers.delete("transcription");
        resolve(m.text);
      });
      if (!this.send({ type: "listen" })) {
        reject(new Error("ws_not_connected"));
      }
    });
  }
}

let _singleton: WSClient | null = null;
export function getWSClient(): WSClient {
  if (!_singleton) {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    _singleton = new WSClient(`${proto}://${location.host}/ws`);
  }
  return _singleton;
}
```

- [ ] **Step 4: Write `mic.ts`**

```ts
import { getWSClient } from "./wsClient";

export async function listen(): Promise<string> {
  return getWSClient().listen();
}
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/net/
git commit -m "feat(frontend): network clients (profile, tts, ws, mic)"
```

---

### Task 4.5: Router, useKeys, main entry, Boot screen, App shell

**Files:**
- Create: `frontend/src/core/router.ts`
- Create: `frontend/src/core/useKeys.ts`
- Create: `frontend/src/screens/BootScreen.tsx`
- Create: `frontend/src/App.tsx`
- Create: `frontend/src/main.tsx`

- [ ] **Step 1: Write `router.ts`**

```ts
import { useSamantha } from "./store";
import type { ScreenName } from "./types";

export function useRoute() {
  const setScreen = useSamantha((s) => s.setScreen);
  return (target: ScreenName) => setScreen(target);
}

export function useScreen(): ScreenName {
  return useSamantha((s) => s.screen);
}
```

- [ ] **Step 2: Write `useKeys.ts`**

```ts
import { useEffect } from "react";

type KeyHandlers = Record<string, (e: KeyboardEvent) => void>;

export function useKeys(handlers: KeyHandlers): void {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const handler = handlers[e.key];
      if (handler) handler(e);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [handlers]);
}
```

- [ ] **Step 3: Write `BootScreen.tsx`**

```tsx
import { useEffect } from "react";
import { useRoute } from "../core/router";
import { useSamantha } from "../core/store";
import { fetchProfile } from "../net/profile";

export function BootScreen() {
  const route = useRoute();
  const setName = useSamantha((s) => s.setName);

  useEffect(() => {
    let cancelled = false;
    const minDelay = new Promise<void>((r) => setTimeout(r, 1500));
    const load = async () => {
      try {
        const profile = await fetchProfile();
        await minDelay;
        if (cancelled) return;
        if (profile) {
          setName(profile.name);
          route("ambient");
        } else {
          route("onboarding");
        }
      } catch {
        await minDelay;
        if (!cancelled) route("onboarding");
      }
    };
    load();
    return () => { cancelled = true; };
  }, [route, setName]);

  return (
    <div className="screen">
      <div className="brand">samantha</div>
    </div>
  );
}
```

- [ ] **Step 4: Write `App.tsx` with placeholders**

```tsx
import "./styles/tokens.css";
import "./styles/base.css";
import "./styles/components.css";
import { useScreen } from "./core/router";
import { BootScreen } from "./screens/BootScreen";

function Placeholder({ label }: { label: string }) {
  return (
    <div className="screen">
      <div className="label">{label} (placeholder)</div>
    </div>
  );
}

export default function App() {
  const screen = useScreen();
  switch (screen) {
    case "boot":         return <BootScreen />;
    case "onboarding":   return <Placeholder label="onboarding" />;
    case "ambient":      return <Placeholder label="ambient" />;
    case "conversation": return <Placeholder label="conversation" />;
  }
}
```

- [ ] **Step 5: Write `main.tsx`**

```tsx
import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
```

- [ ] **Step 6: Typecheck**

```bash
cd frontend && npm run typecheck
```

Expected: no errors.

- [ ] **Step 7: Smoke test**

Terminal 1: `cd backend && .venv/bin/python -m samantha.api`
Terminal 2: `cd frontend && npm run dev`
Open http://localhost:5173/.

Expected: "samantha" label appears, then transitions to "onboarding (placeholder)" (if no profile) or "ambient (placeholder)" (if profile already exists from Phase 2 smoke testing).

- [ ] **Step 8: Commit**

```bash
git add frontend/src/
git commit -m "feat(frontend): router, App with placeholders, BootScreen + main entry"
```

---

### Phase 4 Checkpoint

Pause. Confirm:
- `npm run typecheck` clean
- `npm run dev` shows Boot → placeholder based on profile
- `pytest tests/` still green

---

## Phase 5 — Wave component (traveling pulses)

**Goal:** Implement `Wave.tsx` per spec §6 — pulses propagate from center outward, gaussian envelope, multi-mode parameters.

### Task 5.1: Wave canvas component

**Files:**
- Create: `frontend/src/components/Wave.tsx`
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Write `Wave.tsx`**

```tsx
import { useEffect, useRef } from "react";
import type { WaveMode } from "../core/types";

interface Pulse {
  tEmit: number;
  dir: 1 | -1;
  amp0: number;
  sigma: number;
  freq: number;
}

interface ModeParams {
  pulseRatePerSec: number;
  amp0: number;
  sigma: number;
  freq: number;
  speedWidthsPerSec: number;
  lifetimeSec: number;
  strokeOpacity: number;
}

const MODES: Record<WaveMode, ModeParams> = {
  idle:      { pulseRatePerSec: 0.1, amp0: 0.04, sigma: 0.10, freq: 3,  speedWidthsPerSec: 0.15, lifetimeSec: 1.5, strokeOpacity: 0.85 },
  listening: { pulseRatePerSec: 0.5, amp0: 0.30, sigma: 0.20, freq: 7,  speedWidthsPerSec: 0.25, lifetimeSec: 1.5, strokeOpacity: 0.95 },
  thinking:  { pulseRatePerSec: 2.0, amp0: 0.20, sigma: 0.15, freq: 10, speedWidthsPerSec: 0.25, lifetimeSec: 0.8, strokeOpacity: 0.95 },
  speaking:  { pulseRatePerSec: 4.0, amp0: 0.80, sigma: 0.20, freq: 10, speedWidthsPerSec: 0.25, lifetimeSec: 1.2, strokeOpacity: 0.95 },
};

interface WaveProps {
  mode: WaveMode;
  className?: string;
}

export function Wave({ mode, className }: WaveProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const modeRef = useRef<WaveMode>(mode);

  useEffect(() => { modeRef.current = mode; }, [mode]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const dpr = Math.min(window.devicePixelRatio, 2);
    const resize = () => {
      const rect = canvas.getBoundingClientRect();
      canvas.width = rect.width * dpr;
      canvas.height = rect.height * dpr;
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.scale(dpr, dpr);
    };
    resize();
    window.addEventListener("resize", resize);

    const pulses: Pulse[] = [];
    let lastEmit = performance.now();
    let frameId = 0;
    let running = true;

    const frame = () => {
      if (!running) return;
      const now = performance.now();
      const params = MODES[modeRef.current];

      const interval = 1000 / params.pulseRatePerSec;
      if (now - lastEmit >= interval) {
        for (const dir of [-1, 1] as const) {
          pulses.push({
            tEmit: now,
            dir,
            amp0: params.amp0 * (0.85 + Math.random() * 0.3),
            sigma: params.sigma,
            freq: params.freq,
          });
        }
        lastEmit = now;
      }

      for (let i = pulses.length - 1; i >= 0; i--) {
        const age = (now - pulses[i].tEmit) / 1000;
        if (age > params.lifetimeSec) pulses.splice(i, 1);
      }

      const rect = canvas.getBoundingClientRect();
      const w = rect.width;
      const h = rect.height;
      const baseline = h / 2;
      const maxAmpPx = h * 0.45;

      ctx.clearRect(0, 0, w, h);
      ctx.strokeStyle = `rgba(255,255,255,${params.strokeOpacity})`;
      ctx.lineWidth = 0.6;
      ctx.lineCap = "round";
      ctx.lineJoin = "round";
      ctx.beginPath();

      const samples = Math.max(120, Math.floor(w * 0.6));
      for (let i = 0; i <= samples; i++) {
        const xn = i / samples;
        let y = baseline;
        for (const p of pulses) {
          const age = (now - p.tEmit) / 1000;
          const center = 0.5 + p.dir * age * params.speedWidthsPerSec;
          const ampScale = Math.max(0, 1 - age / params.lifetimeSec);
          const amp = p.amp0 * ampScale * maxAmpPx;
          const dx = xn - center;
          const env = Math.exp(-(dx * dx) / (p.sigma * p.sigma));
          const osc = Math.cos(2 * Math.PI * p.freq * dx);
          y -= amp * env * osc;
        }
        const px = xn * w;
        if (i === 0) ctx.moveTo(px, y);
        else ctx.lineTo(px, y);
      }
      ctx.stroke();

      frameId = requestAnimationFrame(frame);
    };
    frameId = requestAnimationFrame(frame);

    return () => {
      running = false;
      cancelAnimationFrame(frameId);
      window.removeEventListener("resize", resize);
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      className={className}
      style={{ width: "100%", height: "100%", display: "block" }}
    />
  );
}
```

- [ ] **Step 2: Wire Wave into the Ambient placeholder**

Modify `frontend/src/App.tsx`. Replace the `ambient` case:

```tsx
import { Wave } from "./components/Wave";

// inside switch:
    case "ambient":
      return (
        <div className="screen">
          <div style={{ position: "absolute", inset: 0 }}>
            <Wave mode="idle" />
          </div>
          <div className="label">ambient (wave test)</div>
        </div>
      );
```

- [ ] **Step 3: Typecheck**

```bash
cd frontend && npm run typecheck
```

Expected: no errors.

- [ ] **Step 4: Smoke test in browser**

Navigate to ambient. Confirm the wave renders as a near-flat line with subtle traveling pulses.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Wave.tsx frontend/src/App.tsx
git commit -m "feat(frontend): Wave component with traveling pulses"
```

---

### Phase 5 Checkpoint

Visual check OK. Pause.

---

## Phase 6 — Ambient screen

**Goal:** `AmbientScreen.tsx` — day/time labels, contextual phrase, wave idle, tap → conversation.

### Task 6.1: Ambient screen

**Files:**
- Create: `frontend/src/screens/AmbientScreen.tsx`
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Write `AmbientScreen.tsx`**

```tsx
import { useEffect, useState } from "react";
import { Wave } from "../components/Wave";
import { useRoute } from "../core/router";

const DAYS = ["domingo","lunes","martes","miércoles","jueves","viernes","sábado"];

function contextualPhrase(hour: number): string {
  if (hour < 6)  return "madrugada";
  if (hour < 12) return "buenos días";
  if (hour < 15) return "buena hora";
  if (hour < 20) return "tarde tranquila";
  if (hour < 23) return "ya es de noche";
  return "fin del día";
}

function timeLabel(d: Date): string {
  const h = String(d.getHours()).padStart(2, "0");
  const m = String(d.getMinutes()).padStart(2, "0");
  return `${h}:${m}`;
}

export function AmbientScreen() {
  const route = useRoute();
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    const tick = setInterval(() => setNow(new Date()), 60_000);
    return () => clearInterval(tick);
  }, []);

  return (
    <div
      className="screen"
      onClick={() => route("conversation")}
      style={{ cursor: "pointer", position: "relative" }}
    >
      <div style={{ position: "absolute", top: "5vh", left: "6vw" }}>
        <span className="label">{DAYS[now.getDay()]}</span>
      </div>
      <div style={{ position: "absolute", top: "5vh", right: "6vw" }}>
        <span className="label">{timeLabel(now)}</span>
      </div>

      <div style={{
        position: "absolute", left: 0, right: 0, top: "50%",
        transform: "translateY(-50%)", height: 160,
      }}>
        <Wave mode="idle" />
      </div>

      <div className="her-text" style={{
        position: "absolute", bottom: "12vh", left: 0, right: 0,
        textAlign: "center", fontSize: "var(--text-ambient)",
      }}>
        {contextualPhrase(now.getHours())}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Wire into App.tsx**

```tsx
import { AmbientScreen } from "./screens/AmbientScreen";

// in switch:
    case "ambient": return <AmbientScreen />;
```

- [ ] **Step 3: Typecheck + smoke**

```bash
cd frontend && npm run typecheck
```

`npm run dev`. Navigate to ambient (delete profile first if needed). Expect: day top-left, time top-right, wave idle, phrase bottom, click → "conversation (placeholder)".

- [ ] **Step 4: Commit**

```bash
git add frontend/src/screens/AmbientScreen.tsx frontend/src/App.tsx
git commit -m "feat(frontend): AmbientScreen with time + phrase + idle wave"
```

---

### Phase 6 Checkpoint

Visual check. Pause.

---

## Phase 7 — Conversation screen

**Goal:** Immersive + history toggle + WS chat + keybindings + idle timeout.

### Task 7.1: Conversation screen

**Files:**
- Create: `frontend/src/screens/ConversationScreen.tsx`
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Write `ConversationScreen.tsx`**

```tsx
import { useEffect, useRef, useState } from "react";
import { Wave } from "../components/Wave";
import { useRoute } from "../core/router";
import { useSamantha } from "../core/store";
import { useKeys } from "../core/useKeys";
import { listen } from "../net/mic";
import { speak } from "../net/tts";
import { getWSClient } from "../net/wsClient";
import type { WaveMode } from "../core/types";

const IDLE_TIMEOUT_MS = 5 * 60 * 1000;

export function ConversationScreen() {
  const route = useRoute();
  const transcript = useSamantha((s) => s.transcript);
  const appendMessage = useSamantha((s) => s.appendMessage);
  const patchMessage = useSamantha((s) => s.patchMessage);

  const [showHistory, setShowHistory] = useState(false);
  const [showTextInput, setShowTextInput] = useState(false);
  const [textValue, setTextValue] = useState("");
  const [waveMode, setWaveMode] = useState<WaveMode>("idle");
  const lastActivityRef = useRef<number>(Date.now());

  const bump = () => { lastActivityRef.current = Date.now(); };

  useEffect(() => {
    const tick = setInterval(() => {
      if (Date.now() - lastActivityRef.current > IDLE_TIMEOUT_MS) {
        route("ambient");
      }
    }, 30_000);
    return () => clearInterval(tick);
  }, [route]);

  useKeys({
    Escape: () => {
      if (showTextInput) setShowTextInput(false);
      else route("ambient");
    },
    h: () => { bump(); setShowHistory((v) => !v); },
    H: () => { bump(); setShowHistory((v) => !v); },
    t: () => { bump(); setShowTextInput((v) => !v); },
    T: () => { bump(); setShowTextInput((v) => !v); },
  });

  const sendMessage = async (msg: string) => {
    bump();
    const trimmed = msg.trim();
    if (!trimmed) return;
    appendMessage({
      id: crypto.randomUUID(),
      role: "user",
      text: trimmed,
      timestamp: Date.now(),
    });
    setWaveMode("thinking");

    const replyId = crypto.randomUUID();
    appendMessage({ id: replyId, role: "samantha", text: "", timestamp: Date.now() });

    try {
      let started = false;
      let acc = "";
      const result = await getWSClient().chat(trimmed, (token) => {
        if (!started) { started = true; setWaveMode("speaking"); }
        acc += token;
        patchMessage(replyId, acc);
      });
      patchMessage(replyId, result.reply);
      await speak(result.reply);
    } catch (e) {
      console.warn("chat failed", e);
    } finally {
      setWaveMode("idle");
    }
  };

  const onMicClick = async () => {
    bump();
    setWaveMode("listening");
    try {
      const text = await listen();
      await sendMessage(text);
    } catch {
      setWaveMode("idle");
    }
  };

  const onTextSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const v = textValue;
    setTextValue("");
    setShowTextInput(false);
    sendMessage(v);
  };

  const lastSamantha = [...transcript].reverse().find((m) => m.role === "samantha");

  return (
    <div className="screen" style={{ position: "relative" }} onClick={bump}>
      <div style={{ position: "absolute", top: "3vh", left: "5vw" }}>
        <button
          aria-label="ambient"
          className="label"
          style={{ background: "none", border: 0, color: "var(--ink-label)", cursor: "pointer" }}
          onClick={(e) => { e.stopPropagation(); route("ambient"); }}
        >
          ← ambient
        </button>
      </div>
      <button
        aria-label="historial"
        className="label"
        style={{
          position: "absolute", top: "3vh", right: "5vw",
          background: "none", border: 0, color: "var(--ink-label)", cursor: "pointer",
        }}
        onClick={(e) => { e.stopPropagation(); setShowHistory((v) => !v); }}
      >
        {showHistory ? "× cerrar" : "≡ historial"}
      </button>

      <div style={{
        position: "absolute", inset: 0,
        opacity: showHistory ? 0.3 : 1,
        transition: "opacity 0.3s",
      }}>
        <Wave mode={waveMode} />
      </div>

      {showHistory ? (
        <div style={{
          position: "absolute", inset: "10vh 5vw 18vh",
          overflowY: "auto",
          display: "flex", flexDirection: "column", gap: 12,
          maskImage: "linear-gradient(to bottom, transparent 0%, black 8%, black 100%)",
        }}>
          {transcript.map((m) => (
            <div key={m.id} style={{
              color: m.role === "samantha" ? "var(--ink)" : "var(--ink-dim)",
              fontFamily: m.role === "samantha" ? "var(--serif)" : "var(--sans)",
              fontStyle: m.role === "samantha" ? "italic" : "normal",
              fontSize: "var(--text-her-history)",
              alignSelf: m.role === "samantha" ? "flex-start" : "flex-end",
              textAlign: m.role === "samantha" ? "left" : "right",
              maxWidth: "85%",
            }}>
              {m.role === "user" ? "— " : ""}{m.text}
            </div>
          ))}
        </div>
      ) : (
        <div className="her-text" style={{
          position: "absolute", left: 0, right: 0, bottom: "20vh",
          textAlign: "center", fontSize: "var(--text-her-large)",
          padding: "0 6vw",
        }}>
          {lastSamantha?.text ?? ""}
        </div>
      )}

      {showTextInput && !showHistory && (
        <form onSubmit={onTextSubmit} style={{
          position: "absolute", left: "10vw", right: "10vw", bottom: "13vh",
          display: "flex", justifyContent: "center",
        }}>
          <input
            autoFocus
            value={textValue}
            onChange={(e) => { bump(); setTextValue(e.target.value); }}
            placeholder="dile algo…"
            style={{
              width: "100%", background: "transparent", border: 0,
              borderBottom: "1px solid var(--ink-trace)",
              padding: "8px 4px", color: "var(--ink)",
              fontFamily: "var(--serif)", fontStyle: "italic",
              fontSize: "var(--text-input)", outline: "none", textAlign: "center",
            }}
          />
        </form>
      )}

      <button
        className="mic-btn"
        aria-label="microphone"
        style={{ position: "absolute", left: "50%", bottom: "5vh", transform: "translateX(-50%)" }}
        onClick={(e) => { e.stopPropagation(); onMicClick(); }}
      >
        <svg viewBox="0 0 24 24">
          <path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3zm5.3-3c0 3-2.54 5.1-5.3 5.1S6.7 14 6.7 11H5c0 3.41 2.72 6.23 6 6.72V21h2v-3.28c3.28-.48 6-3.3 6-6.72h-1.7z" />
        </svg>
      </button>
    </div>
  );
}
```

- [ ] **Step 2: Wire into App**

```tsx
import { ConversationScreen } from "./screens/ConversationScreen";

// in switch:
    case "conversation": return <ConversationScreen />;
```

- [ ] **Step 3: Typecheck**

```bash
cd frontend && npm run typecheck
```

- [ ] **Step 4: Full smoke test**

Backend (real mode):
```bash
cd backend && SAMANTHA_MODE=real SAMANTHA_LLM_SERVER_URL=http://192.168.100.58:8000 .venv/bin/python -m samantha.api
```
Frontend: `cd frontend && npm run dev`. Open localhost:5173, click through Boot → Ambient → tap → Conversation. Press `T`, type "Hola", press Enter. Wave should switch to thinking → speaking. Press `H` to view history. Press `Esc` to return.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/screens/ConversationScreen.tsx frontend/src/App.tsx
git commit -m "feat(frontend): ConversationScreen immersive + history + keybindings"
```

---

### Phase 7 Checkpoint

End-to-end verification. Pause.

---

## Phase 8 — Onboarding screen

**Goal:** Port the 6-question flow into `OnboardingScreen.tsx`. On final submit, POST /profile + navigate to Ambient.

### Task 8.1: Onboarding screen

**Files:**
- Create: `frontend/src/screens/OnboardingScreen.tsx`
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Write `OnboardingScreen.tsx`**

```tsx
import { useState } from "react";
import { Wave } from "../components/Wave";
import { useRoute } from "../core/router";
import { useSamantha } from "../core/store";
import { createProfile } from "../net/profile";
import type { ProfileAnswer } from "../core/types";

const QUESTIONS = [
  "¿Cómo te llamo?",
  "¿Cómo estás hoy?",
  "¿Qué te gusta hacer cuando tienes tiempo para ti?",
  "Cuéntame algo que te haya hecho ilusión últimamente. Algo pequeño vale.",
  "¿Y algo que te esté rondando la cabeza estos días?",
  "Una última: conmigo, ¿prefieres que sea más directa o más cuidadosa?",
];

export function OnboardingScreen() {
  const route = useRoute();
  const setName = useSamantha((s) => s.setName);
  const [idx, setIdx] = useState(0);
  const [answers, setAnswers] = useState<(string | null)[]>(Array(6).fill(""));
  const [submitting, setSubmitting] = useState(false);
  const [value, setValue] = useState("");

  const submitCurrent = (skip: boolean) => {
    const next = [...answers];
    next[idx] = skip ? null : value.trim() || null;
    setAnswers(next);
    setValue("");
    if (idx < QUESTIONS.length - 1) setIdx(idx + 1);
    else finalize(next);
  };

  const finalize = async (final: (string | null)[]) => {
    setSubmitting(true);
    const firstAnswer = final[0];
    const name =
      firstAnswer && firstAnswer.trim().length > 0
        ? firstAnswer.trim().split(/\s+/)[0]
        : "tú";
    const payload: ProfileAnswer[] = QUESTIONS.map((q, i) => ({
      q,
      a: final[i] ?? null,
    }));
    try {
      const profile = await createProfile(name, payload);
      setName(profile.name);
      route("ambient");
    } catch (e) {
      console.error("createProfile failed", e);
      setSubmitting(false);
    }
  };

  return (
    <div className="screen" style={{ position: "relative" }}>
      <div style={{ position: "absolute", inset: "5vh 0", height: 100 }}>
        <Wave mode="listening" />
      </div>

      <div style={{
        position: "absolute", top: "20vh", left: 0, right: 0,
        display: "flex", justifyContent: "center", gap: 6,
      }}>
        {QUESTIONS.map((_, i) => (
          <span key={i} style={{
            width: 6, height: 6, borderRadius: "50%",
            background: i === idx
              ? "var(--ink)"
              : i < idx ? "var(--ink-soft)" : "var(--ink-trace)",
            transform: i === idx ? "scale(1.5)" : "none",
            transition: "all 0.4s",
          }} />
        ))}
      </div>

      <div className="her-text" style={{
        position: "absolute", top: "32vh", left: 0, right: 0,
        textAlign: "center", fontSize: "var(--text-display)",
        padding: "0 8vw",
      }}>
        {QUESTIONS[idx]}
      </div>

      <form
        onSubmit={(e) => { e.preventDefault(); submitCurrent(false); }}
        style={{
          position: "absolute", bottom: "10vh", left: "10vw", right: "10vw",
          display: "flex", flexDirection: "column", alignItems: "center", gap: 16,
        }}
      >
        <input
          autoFocus
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="escribe y pulsa enter"
          disabled={submitting}
          style={{
            width: "100%", background: "transparent", border: 0,
            borderBottom: "1px solid var(--ink-trace)",
            padding: "10px 4px", color: "var(--ink)",
            fontFamily: "var(--serif)", fontStyle: "italic",
            fontSize: "1.2rem", outline: "none", textAlign: "center",
          }}
        />
        <div style={{ display: "flex", gap: 16 }}>
          <button
            type="button"
            disabled={submitting}
            onClick={() => submitCurrent(true)}
            className="label"
            style={{
              background: "none", border: 0,
              color: "var(--ink-faint)", cursor: "pointer",
            }}
          >
            saltar
          </button>
          <button
            type="submit"
            disabled={submitting}
            className="label"
            style={{
              background: "rgba(255,255,255,0.08)",
              border: "1px solid var(--ink-trace)",
              padding: "10px 24px", borderRadius: 999,
              color: "var(--ink)", cursor: "pointer",
            }}
          >
            continuar
          </button>
        </div>
      </form>
    </div>
  );
}
```

- [ ] **Step 2: Wire into App**

```tsx
import { OnboardingScreen } from "./screens/OnboardingScreen";

// in switch:
    case "onboarding": return <OnboardingScreen />;
```

- [ ] **Step 3: Typecheck**

```bash
cd frontend && npm run typecheck
```

Expected: no errors.

- [ ] **Step 4: Full first-encounter smoke**

Ensure no profile exists:
```bash
curl -X DELETE http://localhost:7777/profile
```

Open `npm run dev`. Should: Boot → Onboarding → 6 questions → POST /profile → Ambient.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/screens/OnboardingScreen.tsx frontend/src/App.tsx
git commit -m "feat(frontend): OnboardingScreen with 6-question flow + POST /profile"
```

---

### Phase 8 Checkpoint

Run full flow manually. Pause.

---

## Phase 9 — Cleanup, docs, and tests

**Goal:** Point backend at `frontend/dist/`, delete `backend/static/`, update CLAUDE.md per spec §10, update PROGRESS.md, final tests.

### Task 9.1: Build frontend and point backend at dist

**Files:**
- Modify: `backend/samantha/api.py`

- [ ] **Step 1: Production build**

```bash
cd frontend && npm run build
```

Expected: produces `frontend/dist/index.html` and `frontend/dist/assets/`.

- [ ] **Step 2: Update api.py**

In `backend/samantha/api.py`, replace the existing `STATIC_DIR` / `INDEX_FILE` constants and the static mount with:

```python
FRONTEND_DIST = (
    Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
)
INDEX_FILE = FRONTEND_DIST / "index.html"

# Frontend at "/". Vite generates dist/assets/* — mount that subdir if
# it exists (it won't during pure-backend test runs).
if (FRONTEND_DIST / "assets").exists():
    app.mount(
        "/assets",
        StaticFiles(directory=str(FRONTEND_DIST / "assets")),
        name="assets",
    )
```

The `@app.get("/")` handler should already return `FileResponse(INDEX_FILE)` — keep it.

- [ ] **Step 3: Smoke test integrated path**

```bash
cd backend && .venv/bin/python -m samantha.api
```

Open http://localhost:7777/. React app should load directly.

- [ ] **Step 4: Commit**

```bash
git add backend/samantha/api.py
git commit -m "feat(backend): serve frontend/dist at / instead of backend/static/"
```

---

### Task 9.2: Remove `backend/static/` and adapt tests

**Files:**
- Delete: `backend/static/` (entire directory)
- Modify: `backend/tests/test_api.py`

- [ ] **Step 1: Update static-file tests**

In `backend/tests/test_api.py`, find `test_index_serves_html` and replace it with:

```python
def test_index_serves_frontend_html():
    """The root route serves frontend/dist/index.html (built by Vite)."""
    response = client.get("/")
    if response.status_code == 404:
        import pytest
        pytest.skip("frontend not built (frontend/dist/ missing)")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
```

Delete these tests entirely:
- `test_static_css_served`
- `test_static_js_modules_served`

- [ ] **Step 2: Remove the static directory**

```bash
git rm -r backend/static/
```

- [ ] **Step 3: Run tests**

```bash
cd backend && .venv/bin/pytest tests/ -q
```

Expected: all green. The frontend-html test skips if no build.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_api.py
git commit -m "refactor: remove backend/static/ — frontend lives in frontend/"
```

---

### Task 9.3: Update CLAUDE.md per spec §10

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update §2.4 — Backend stack**

In `CLAUDE.md` §2.4 Implications section, append:

```
- The frontend lives in `frontend/` separate from `backend/`. Vite builds to
  `frontend/dist/`, which FastAPI's `StaticFiles` mounts at `/`.
- Phase 7 deployment now requires `cd frontend && npm install && npm run build`
  before starting the systemd services.
```

- [ ] **Step 2: Replace §2.7 — Memory**

Replace the body of §2.7 with:

```
**Decision:** ChromaDB at `~/.samantha/memory/chroma/` for long-term semantic
memory, paired with a SQLite ring buffer at `~/.samantha/memory/state.db` for
short-term (last N turns verbatim) memory. Embedder: fastembed (ONNX runtime)
with `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`.

**Design principle:** Samantha never forgets anything. The store is
append-only from the user's perspective. `Memory.forget()` and
`Memory.clear()` exist as admin/test tools but are NOT wired to user input.
Short-term ring eviction removes from the buffer but the chunk remains in
long-term forever.

**Structured facts** (name, onboarding_completed_at, future preferences) are
stored as `role: "fact"` chunks with `kind`/`value` metadata. Excluded from
conversational recall by default. Replaces the `profile.json` concept —
there is no parallel file.
```

- [ ] **Step 3: Add §2.10 — Frontend stack**

After §2.9 add:

```markdown
### 2.10 Frontend Stack: React + Vite + TypeScript

**Decision:** React 18 + Vite + TypeScript in a separate `frontend/` directory.

**Rationale:** The UI grew beyond what vanilla DOM manipulation handles
cleanly (4 screens with state, a wave canvas, a toggleable history, a
router). Component model + types + HMR pay back the build-step cost
quickly. The original vanilla-JS decision (§12, 2026-05) was correct for
the original scope; that scope changed with the v2 redesign.

**Cost:** Node.js as a dev dependency. Production deploy needs
`npm install && npm run build` once during install. Runtime on the kiosk
still needs only Python + Chromium.
```

- [ ] **Step 4: Update §3 — Rules**

Remove these two lines from §3 (the "MUST NOT" list):

```
- **MUST NOT** add a frontend framework (React, Vue, Svelte, etc.)
- **MUST NOT** add a JS build step (webpack, vite, esbuild, etc.)
```

Leave the other "MUST NOT" rules intact.

- [ ] **Step 5: Add Frontend commands to §5**

After the "Backend (Python)" subsection of §5, add:

````markdown
### Frontend (Vite + React + TS)

```bash
cd frontend

# One time
npm install

# Dev server with HMR on :5173, proxies API to :7777
npm run dev

# Production build to frontend/dist/ (consumed by backend)
npm run build

# Type checking only
npm run typecheck
```
````

- [ ] **Step 6: Update §7 Phase 7 deployment**

In §7's deployment subsection, BEFORE the `cp systemd/*.service` step, add:

```bash
# Build the frontend (Node required at install time, not at runtime)
cd frontend && npm install && npm run build && cd ..
```

- [ ] **Step 7: Add §12 — Decision log entries**

At the TOP of §12 (Decision Log), insert these two entries (newest first):

```markdown
### 2026-05-12 — Vanilla JS → React + Vite + TypeScript

**Decision:** Replace the vanilla-JS-no-build frontend with React + Vite +
TypeScript in a separate `frontend/` directory.

**Rationale:** v2 UI redesign expanded scope (Ambient screen added,
immersive Conversation with history toggle, traveling wave packet,
persistence layer). The "UI scope is small" rationale of the original
vanilla decision no longer applies.

**Cost:** Node.js required for dev and build. `node_modules/` adds ~100 MB
to the dev environment. Production kiosk runs only Python + Chromium.

### 2026-05-12 — Memory architecture: short/long-term + facts + fastembed

**Decision:** Restructure memory into three layers — short-term (SQLite ring
buffer for the last 20 turns), long-term (ChromaDB for semantic recall), and
structured facts (`role: "fact"` chunks in long-term). Swap the embedder to
`paraphrase-multilingual-MiniLM-L12-v2` via fastembed (ONNX). No parallel
`profile.json` file.

**Rationale:** Pure-similarity recall has a continuity gap (the previous
turn isn't always similar to the new one). Short-term solves that. Facts
give structured access to name, onboarding marker, future preferences
without polluting conversational recall. The multilingual embedder fixes
weak Spanish recall.

**Cost:** +130 MB deps (fastembed + ONNX model). One-time model download on
first launch (~30 s).

**Alternatives rejected:**
- **Mem0** (NousResearch): 5 s/turn latency for fact extraction,
  English-leaning output. See `docs/superpowers/specs/mem0-spike/REPORT.md`.
- **Hermes-Agent** (NousResearch): full task-agent runtime, optimizes a
  problem we don't have in v2. Parked for v3 at
  `docs/superpowers/specs/2026-05-12-hermes-agent-spike-scope.md`.
```

- [ ] **Step 8: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(claude.md): update §2, §3, §5, §7, §12 for UI v2 redesign"
```

---

### Task 9.4: PROGRESS.md entry

**Files:**
- Modify: `PROGRESS.md`

- [ ] **Step 1: Prepend new phase entry**

Insert at the top of `PROGRESS.md` (after the header, before existing entries):

```markdown
## 2026-05-12 — Phase 8: UI v2 redesign ✅

Full redesign per `docs/superpowers/specs/2026-05-12-ui-redesign-design.md`.

- **Frontend:** vanilla-JS in `backend/static/` deleted. New `frontend/`
  with React 18 + Vite + TypeScript. 4 screens (Boot, Onboarding, Ambient,
  Conversation immersive + history toggle). Design tokens system in
  `frontend/src/styles/tokens.css`.
- **Wave:** rewritten as a traveling wave packet — pulses propagate from
  the center outward with gaussian envelope and per-mode parameters per
  spec §6. Stroke 0.6 px.
- **Memory:** extended with short-term (SQLite ring buffer, last 20 turns),
  long-term (ChromaDB + fastembed multilingual ONNX embedder), and facts
  (`role: "fact"` chunks). `Memory.set_fact`, `get_fact`, `all_facts`
  added. `recall()` excludes short-term entries AND `role: "fact"` chunks.
- **Persistence:** no `profile.json`. `profile.py` thin facade over Memory.
  `/profile` endpoints (GET/POST/DELETE) routed through facts. `/ping`
  includes `has_profile: bool`.
- **Prompt assembly:** `real_llm._build_payload` accepts `facts`, `recall`,
  `short_term` kwargs. System prompt assembled per spec §9.6:
  `SYSTEM_PROMPT + facts + recall + short-term + user-turn`.
- **CLAUDE.md updated:** §2.4, §2.7 (memory new architecture), §2.10 new
  (frontend stack), §3 (no-framework rule removed), §5 (npm commands), §7
  (build step before systemd), §12 (two decision log entries).

**Tests:** all green. Backend pytest covers Memory, profile facade, and
/profile endpoints. Frontend verified manually via dev server.

**Out of scope (deferred):**
- Samantha proactiva (initiative engine) → v3
- Agentic Samantha (emails, calendar, tools) → v3, scoped at
  `docs/superpowers/specs/2026-05-12-hermes-agent-spike-scope.md`
- Real STT (faster-whisper) + real TTS (Piper) → Phase 5
- Memory browser UI → future
```

- [ ] **Step 2: Commit**

```bash
git add PROGRESS.md
git commit -m "docs(progress.md): record Phase 8 UI v2 redesign"
```

---

### Phase 9 Final Checkpoint

- [ ] **Step 1: Full test run**

```bash
cd backend && .venv/bin/pytest tests/ -v
```

Expected: all green.

- [ ] **Step 2: Frontend typecheck + build**

```bash
cd frontend && npm run typecheck && npm run build
```

Expected: both succeed.

- [ ] **Step 3: End-to-end smoke**

```bash
cd frontend && npm run build && cd ..
cd backend && SAMANTHA_MODE=real SAMANTHA_LLM_SERVER_URL=http://192.168.100.58:8000 .venv/bin/python -m samantha.api &
sleep 2

# Fresh user: ensure no profile
curl -X DELETE http://localhost:7777/profile

# Open localhost:7777 in a browser and walk the full first-encounter:
# Boot → 6 questions → Welcome (Ambient) → tap → Conversation → chat
# Then refresh: Boot → Ambient (skips onboarding)
kill %1
```

If all checks pass, v2 is complete.

---

## Self-review checklist (run yourself before declaring done)

- [ ] Every task's commit step was committed.
- [ ] `git log --oneline | head -30` shows the phase progression.
- [ ] `pytest tests/ -v` fully green.
- [ ] `npm run typecheck` fully green.
- [ ] `npm run build` succeeds.
- [ ] CLAUDE.md no longer says "MUST NOT add a frontend framework".
- [ ] `~/.samantha/profile.json` is NOT created by the running backend (only `~/.samantha/memory/` exists).
- [ ] After `DELETE /profile`, conversational chunks remain — verify with `curl` on `/chat` mentioning a previous answer.

---

End of plan.
