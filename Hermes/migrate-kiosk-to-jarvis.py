#!/usr/bin/env python3
"""Move the strip's conversation from the kiosk key to the JARVIS one.

Run ONCE, with the gateway stopped, after the rename lands:

    systemctl --user stop samantha-hermes.service
    cp .hermes/home/state.db .hermes/home/state.db.bak-20260828
    python Hermes/migrate-kiosk-to-jarvis.py .hermes/home/state.db

What it does NOT touch, and why that is the whole reason it is small:
`messages` hangs off `session_id`, not off the session key, so the
1,750 rows of conversation and the ten FTS tables with their six
triggers are not part of this. Only the key, the two JSON blobs that
repeat it, and the obligations move.

Idempotent: a second run reports zero rows and changes nothing.
"""

import json
import sqlite3
import sys
from pathlib import Path

OLD_KEY = "agent:main:samantha_kiosk:dm:kiosk"
NEW_KEY = "agent:main:jarvis:dm:jarvis"
OLD_PLATFORM, NEW_PLATFORM = "samantha_kiosk", "jarvis"
OLD_CHAT, NEW_CHAT = "kiosk", "jarvis"
OLD_NAME, NEW_NAME = "Kiosk", "JARVIS"


def _rewrite(blob: str | None) -> str | None:
    """Rewrite one JSON blob's platform/chat/name fields, at any depth."""
    if not blob:
        return blob

    def walk(node):
        if isinstance(node, dict):
            return {k: walk(v) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(v) for v in node]
        if node == OLD_KEY:
            return NEW_KEY
        if node == OLD_PLATFORM:
            return NEW_PLATFORM
        if node == OLD_CHAT:
            return NEW_CHAT
        if node == OLD_NAME:
            return NEW_NAME
        return node

    try:
        return json.dumps(walk(json.loads(blob)))
    except (TypeError, ValueError):
        # A blob we cannot parse is left exactly as it was. Losing the
        # key is recoverable from the backup; corrupting a row is not.
        return blob


def migrate(db_path: Path | str) -> dict[str, int]:
    """Move every row on the old key. Returns rows changed per table."""
    con = sqlite3.connect(str(db_path))
    counts = {"sessions": 0, "delivery_obligations": 0, "gateway_routing": 0}
    try:
        with con:
            rows = con.execute(
                "SELECT id, origin_json FROM sessions WHERE session_key = ?",
                (OLD_KEY,),
            ).fetchall()
            for sid, origin in rows:
                con.execute(
                    "UPDATE sessions SET session_key = ?, chat_id = ?, "
                    "display_name = ?, origin_json = ? WHERE id = ?",
                    (NEW_KEY, NEW_CHAT, NEW_NAME, _rewrite(origin), sid),
                )
            counts["sessions"] = len(rows)

            cur = con.execute(
                "UPDATE delivery_obligations SET session_key = ?, platform = ?, "
                "chat_id = ? WHERE session_key = ?",
                (NEW_KEY, NEW_PLATFORM, NEW_CHAT, OLD_KEY),
            )
            counts["delivery_obligations"] = cur.rowcount

            # (scope, session_key) is this table's PRIMARY KEY, so the
            # UPDATE is addressed by both — there is no surrogate id to
            # hold on to. Columns verified against the live schema
            # 2026-08-28: scope, session_key, entry_json, updated_at.
            rows = con.execute(
                "SELECT scope, entry_json FROM gateway_routing WHERE session_key = ?",
                (OLD_KEY,),
            ).fetchall()
            for scope, entry in rows:
                con.execute(
                    "UPDATE gateway_routing SET session_key = ?, entry_json = ? "
                    "WHERE scope = ? AND session_key = ?",
                    (NEW_KEY, _rewrite(entry), scope, OLD_KEY),
                )
            counts["gateway_routing"] = len(rows)
    finally:
        con.close()
    return counts


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        raise SystemExit(2)
    target = Path(sys.argv[1])
    if not target.exists():
        raise SystemExit(f"no such database: {target}")
    for table, n in migrate(target).items():
        print(f"  {table}: {n} rows")
