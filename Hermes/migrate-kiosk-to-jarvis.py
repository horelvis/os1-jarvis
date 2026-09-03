"""Move the strip's conversation from the kiosk key to the JARVIS one.

Run ONCE, with the gateway stopped, after the rename lands:

    systemctl --user stop jarvis-hermes.service
    cp .hermes/home/state.db .hermes/home/state.db.bak-20260828
    python Hermes/migrate-kiosk-to-jarvis.py .hermes/home/state.db

What it does NOT touch, and why that is the whole reason it is small:
`messages` hangs off `session_id`, not off the session key, so the
1,750 rows of conversation and the ten FTS tables with their six
triggers are not part of this. Only the key, the two JSON blobs that
repeat it, and the obligations move.

Idempotent: a second run reports zero rows changed and zero skipped.

A row whose JSON blob cannot be parsed is left ENTIRELY alone — its
outer columns are not updated either — and is counted under
`skipped`, with a warning naming the table and the row. This matters
because every WHERE in this script is keyed on the OLD identity: a row
whose outer columns moved but whose blob did not would sit permanently
split between the two identities, invisible to a second run. A skipped
row must be fixed by hand before the migration can be called complete.
"""

# ruff: noqa: N999
# Hyphenated filename, deliberately: it sits beside apply-config.sh,
# run-gateway.sh and setup-runtime.sh in this directory, and Task 8
# invokes this script by that exact path.

import json
import sqlite3
import sys
from pathlib import Path

# CLAUDE.md §6 asks for loguru, not print() — deliberately not followed
# here. This is a hand-run one-shot meant to work under a bare `python3`
# with nothing installed (see the docstring above), and pulling loguru
# into a database migration to print one warning would cost more than it
# buys.
OLD_KEY = "agent:main:samantha_kiosk:dm:kiosk"
NEW_KEY = "agent:main:jarvis:dm:jarvis"
OLD_PLATFORM, NEW_PLATFORM = "samantha_kiosk", "jarvis"
OLD_CHAT, NEW_CHAT = "kiosk", "jarvis"
OLD_NAME, NEW_NAME = "Kiosk", "JARVIS"

# The only keys this migration may touch inside a JSON blob, and what
# each moves from/to. Field-name-aware, not value-aware: a value that
# happens to equal "kiosk" or "Kiosk" in some unrelated field (a
# user_id, a message preview) must survive untouched.
_IDENTITY_FIELDS = {
    "platform": (OLD_PLATFORM, NEW_PLATFORM),
    "chat_id": (OLD_CHAT, NEW_CHAT),
    "chat_name": (OLD_NAME, NEW_NAME),
    "display_name": (OLD_NAME, NEW_NAME),
    "session_key": (OLD_KEY, NEW_KEY),
}


def _walk(node):
    """Rewrite only the identity fields above, wherever they are nested."""
    if isinstance(node, dict):
        out = {}
        for k, v in node.items():
            if isinstance(v, (dict, list)):
                out[k] = _walk(v)
            elif k in _IDENTITY_FIELDS and v == _IDENTITY_FIELDS[k][0]:
                out[k] = _IDENTITY_FIELDS[k][1]
            else:
                out[k] = v
        return out
    if isinstance(node, list):
        return [_walk(v) for v in node]
    return node


def _rewrite(blob: str | None) -> tuple[bool, str | None]:
    """Try to rewrite one JSON blob's identity fields.

    Returns (ok, new_blob). ok is False when the blob is not valid
    JSON — None and the empty string included, which json.loads
    rejects exactly as it rejects any other malformed text. On
    failure the original blob comes back byte-for-byte unchanged; the
    caller must then leave the WHOLE row alone, not only the blob,
    or the row ends up split between the two identities with no way
    for a second run to find it again.
    """
    try:
        parsed = json.loads(blob)
    except (TypeError, ValueError):
        return False, blob
    return True, json.dumps(_walk(parsed))


def migrate(db_path: Path | str) -> dict[str, int]:
    """Move every row on the old key.

    Returns rows changed per table, plus `skipped`: rows left
    completely alone because their JSON blob would not parse. Normally
    0 — if it is not, the caller must investigate before trusting the
    migration is complete.
    """
    con = sqlite3.connect(str(db_path))
    counts = {
        "sessions": 0,
        "delivery_obligations": 0,
        "gateway_routing": 0,
        "skipped": 0,
    }
    try:
        with con:
            rows = con.execute(
                "SELECT id, origin_json FROM sessions WHERE session_key = ?",
                (OLD_KEY,),
            ).fetchall()
            for sid, origin in rows:
                ok, new_origin = _rewrite(origin)
                if not ok:
                    counts["skipped"] += 1
                    print(
                        f"  WARNING: sessions.id={sid} has an unparseable "
                        "origin_json — row left completely untouched, "
                        "fix it by hand",
                        file=sys.stderr,
                    )
                    continue
                con.execute(
                    "UPDATE sessions SET session_key = ?, chat_id = ?, "
                    "display_name = ?, origin_json = ?, source = ? WHERE id = ?",
                    (NEW_KEY, NEW_CHAT, NEW_NAME, new_origin, NEW_PLATFORM, sid),
                )
                counts["sessions"] += 1

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
                ok, new_entry = _rewrite(entry)
                if not ok:
                    counts["skipped"] += 1
                    print(
                        f"  WARNING: gateway_routing.scope={scope!r} has an "
                        "unparseable entry_json — row left completely "
                        "untouched, fix it by hand",
                        file=sys.stderr,
                    )
                    continue
                con.execute(
                    "UPDATE gateway_routing SET session_key = ?, entry_json = ? "
                    "WHERE scope = ? AND session_key = ?",
                    (NEW_KEY, new_entry, scope, OLD_KEY),
                )
                counts["gateway_routing"] += 1
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
    result = migrate(target)
    for table in ("sessions", "delivery_obligations", "gateway_routing"):
        print(f"  {table}: {result[table]} rows")
    if result["skipped"]:
        print(
            f"  SKIPPED: {result['skipped']} row(s) had a blob that would "
            "not parse and were left completely untouched. See the "
            "warnings above — each must be fixed by hand before this "
            "migration can be considered complete."
        )
    else:
        print("  skipped: 0")
