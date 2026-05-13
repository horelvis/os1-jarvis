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
