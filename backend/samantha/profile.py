"""Thin facade over Memory that synthesizes a "profile" from facts +
conversational chunks. No `profile.json` — everything lives in
Samantha's memory.

Onboarding question slots are mapped to the Big Five dimensions
(TIPI / NEO-FFI lineage), one per slot (skipping slot 0 = name).
Each answer is double-written: as a role='user' chunk for
conversational recall, and as a role='fact' with `kind=big5_{dim}`
so the dimension always appears in `# Lo que sabes de ella` in the
system prompt — not only when semantic recall happens to surface it.
"""

from __future__ import annotations

import time

from .memory import Memory


# Big Five dimension per question position. Position 0 is the name
# anchor (not a Big Five trait). Positions 1-5 are E / O / C / A / N
# — the canonical TIPI ordering.
BIG5_BY_INDEX: dict[int, str] = {
    1: "extraversion",
    2: "openness",
    3: "conscientiousness",
    4: "agreeableness",
    5: "neuroticism",
}

BIG5_FACT_KINDS: tuple[str, ...] = tuple(f"big5_{d}" for d in BIG5_BY_INDEX.values())

# Facts that constitute the pairing itself. delete_profile() wipes
# these and only these — conversational chunks survive.
PROFILE_FACT_KINDS: frozenset[str] = frozenset(
    {"name", "onboarding_completed_at"} | set(BIG5_FACT_KINDS)
)


def is_onboarded(mem: Memory, *, user_id: str = "primary") -> bool:
    return mem.get_fact("onboarding_completed_at", user_id=user_id) is not None


def get_profile(mem: Memory, *, user_id: str = "primary") -> dict | None:
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
    # Each big-5 answer is also promoted to a fact so it surfaces in
    # every prompt, not just when semantic recall pulls it in.
    for i, entry in enumerate(answers):
        q = (entry.get("q") or "").strip()
        a = entry.get("a")
        if not q or not a or not str(a).strip():
            continue
        a_clean = str(a).strip()
        chunk_text = f"[Q] {q} → [A] {a_clean}"
        mem.remember("user", chunk_text, user_id=user_id)
        dim = BIG5_BY_INDEX.get(i)
        if dim is not None:
            mem.set_fact(
                f"big5_{dim}",
                a_clean,
                text=chunk_text,
                user_id=user_id,
            )

    mem.set_fact(
        "name",
        name,
        text=f"El usuario se llama {name}",
        user_id=user_id,
    )
    ts = int(time.time())
    mem.set_fact(
        "onboarding_completed_at",
        ts,
        text=f"Onboarding completado en {ts}",
        user_id=user_id,
    )

    profile = get_profile(mem, user_id=user_id)
    assert profile is not None
    return profile


def delete_profile(mem: Memory, *, user_id: str = "primary") -> bool:
    """ADMIN-ONLY. Removes all facts that constitute the pairing —
    name, onboarding_completed_at, and the five Big-Five trait facts.
    Both the latest and any historical/overwritten versions of these facts
    for this user are deleted.
    The 6 answer chunks stay (Samantha never forgets)."""
    res = mem._collection.get(
        where={
            "$and": [
                {"user_id": user_id},
                {"role": "fact"},
                {"kind": {"$in": list(PROFILE_FACT_KINDS)}},
            ]
        }
    )
    ids = res.get("ids") or []
    if not ids:
        return False
    mem._collection.delete(ids=ids)
    return True


def _recover_answers(mem: Memory, anchor_ts: int, *, user_id: str = "primary") -> list[dict]:
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
