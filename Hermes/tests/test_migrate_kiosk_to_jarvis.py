"""The migration, against a database built to look like the real one.

The real state.db has 32 session rows, 459 obligations and 1 routing
row on the old key (measured 2026-08-28). The shape is what matters
here: messages hang off session_id, NOT off the session key, which is
why 1,750 message rows and ten FTS tables are untouched by this.
"""

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import importlib.util

# The script has a hyphen in its name, so it cannot be imported by name.
# `SourceFileLoader.load_module()` would also work on 3.12 and is
# removed in 3.13; this is the API that survives.
_path = Path(__file__).resolve().parents[1] / "migrate-kiosk-to-jarvis.py"
_spec = importlib.util.spec_from_file_location("migrate_kiosk_to_jarvis", _path)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
migrate = _mod.migrate

OLD = "agent:main:samantha_kiosk:dm:kiosk"
NEW = "agent:main:jarvis:dm:jarvis"


# The real `sessions` table has 56 columns; this fixture models only the
# ones this migration reads or writes: session_key, chat_id, display_name,
# origin_json, and source (source.value gates session recovery in
# hermes_state.py's find_latest_gateway_session_for_peer — see the
# migration script's own comment on the sessions UPDATE). Anything this
# migration is ever taught to touch must be added here too, or a test can
# pass while the real table silently keeps the old value — which is
# exactly how the missing `source` column got past 346 green tests.
def _db(tmp_path):
    path = tmp_path / "state.db"
    c = sqlite3.connect(path)
    c.executescript(
        """
        CREATE TABLE sessions (id INTEGER PRIMARY KEY, session_key TEXT,
            chat_id TEXT, display_name TEXT, origin_json TEXT, source TEXT);
        CREATE TABLE delivery_obligations (obligation_id TEXT PRIMARY KEY,
            session_key TEXT, platform TEXT, chat_id TEXT);
        CREATE TABLE gateway_routing (scope TEXT NOT NULL DEFAULT '',
            session_key TEXT NOT NULL, entry_json TEXT NOT NULL,
            updated_at REAL NOT NULL, PRIMARY KEY (scope, session_key));
        CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT,
            content TEXT);
        """
    )
    origin = json.dumps(
        {
            "platform": "samantha_kiosk",
            "chat_id": "kiosk",
            "chat_name": "Kiosk",
            "chat_type": "dm",
            "user_id": "primary",
        }
    )
    c.execute(
        "INSERT INTO sessions VALUES (1, ?, 'kiosk', 'Kiosk', ?, 'samantha_kiosk')",
        (OLD, origin),
    )
    c.execute("INSERT INTO sessions VALUES (2, NULL, NULL, NULL, NULL, NULL)")
    c.execute(
        "INSERT INTO delivery_obligations VALUES ('o1', ?, 'samantha_kiosk', 'kiosk')",
        (OLD,),
    )
    c.execute(
        "INSERT INTO gateway_routing VALUES ('/root', ?, ?, 1.0)",  # scope, key, entry_json, updated_at
        (
            OLD,
            json.dumps(
                {
                    "session_key": OLD,
                    "platform": "samantha_kiosk",
                    "display_name": "Kiosk",
                    "origin": {
                        "platform": "samantha_kiosk",
                        "chat_id": "kiosk",
                        "chat_name": "Kiosk",
                    },
                }
            ),
        ),
    )
    c.execute("INSERT INTO messages VALUES (1, 'sess-1', 'hola')")
    c.commit()
    c.close()
    return path


def _empty_db(tmp_path, name="edge.db"):
    """A database with the same shape as `_db`, but no rows — so each
    edge-case test can insert exactly the row it needs to probe."""
    path = tmp_path / name
    c = sqlite3.connect(path)
    c.executescript(
        """
        CREATE TABLE sessions (id INTEGER PRIMARY KEY, session_key TEXT,
            chat_id TEXT, display_name TEXT, origin_json TEXT, source TEXT);
        CREATE TABLE delivery_obligations (obligation_id TEXT PRIMARY KEY,
            session_key TEXT, platform TEXT, chat_id TEXT);
        CREATE TABLE gateway_routing (scope TEXT NOT NULL DEFAULT '',
            session_key TEXT NOT NULL, entry_json TEXT NOT NULL,
            updated_at REAL NOT NULL, PRIMARY KEY (scope, session_key));
        CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT,
            content TEXT);
        """
    )
    c.commit()
    c.close()
    return path


def test_every_row_moves_to_the_new_key(tmp_path):
    path = _db(tmp_path)
    counts = migrate(path)
    assert counts == {
        "sessions": 1,
        "delivery_obligations": 1,
        "gateway_routing": 1,
        "skipped": 0,
    }
    c = sqlite3.connect(path)
    assert c.execute(
        "SELECT session_key, source FROM sessions WHERE id=1"
    ).fetchone() == (NEW, "jarvis")
    assert c.execute(
        "SELECT session_key, platform FROM delivery_obligations"
    ).fetchone() == (NEW, "jarvis")
    assert c.execute("SELECT session_key FROM gateway_routing").fetchone()[0] == NEW


def test_the_origin_json_is_rewritten_not_just_the_key(tmp_path):
    path = _db(tmp_path)
    migrate(path)
    c = sqlite3.connect(path)
    origin = json.loads(
        c.execute("SELECT origin_json FROM sessions WHERE id=1").fetchone()[0]
    )
    assert origin["platform"] == "jarvis"
    assert origin["chat_id"] == "jarvis"
    assert origin["chat_name"] == "JARVIS"
    assert c.execute(
        "SELECT chat_id, display_name FROM sessions WHERE id=1"
    ).fetchone() == ("jarvis", "JARVIS")


def test_the_routing_blob_is_rewritten_too(tmp_path):
    path = _db(tmp_path)
    migrate(path)
    c = sqlite3.connect(path)
    blob = json.loads(c.execute("SELECT entry_json FROM gateway_routing").fetchone()[0])
    assert blob["platform"] == "jarvis"
    assert blob["session_key"] == NEW
    assert blob["display_name"] == "JARVIS"
    assert blob["origin"]["chat_name"] == "JARVIS"


def test_messages_and_sessions_without_a_key_are_untouched(tmp_path):
    path = _db(tmp_path)
    migrate(path)
    c = sqlite3.connect(path)
    assert c.execute("SELECT content FROM messages").fetchone()[0] == "hola"
    assert (
        c.execute("SELECT session_key FROM sessions WHERE id=2").fetchone()[0] is None
    )


def test_running_it_twice_changes_nothing_the_second_time(tmp_path):
    path = _db(tmp_path)
    migrate(path)
    assert migrate(path) == {
        "sessions": 0,
        "delivery_obligations": 0,
        "gateway_routing": 0,
        "skipped": 0,
    }


def test_unparseable_origin_json_leaves_the_whole_row_alone(tmp_path):
    path = _empty_db(tmp_path)
    c = sqlite3.connect(path)
    c.execute(
        "INSERT INTO sessions VALUES (1, ?, 'kiosk', 'Kiosk', ?, 'samantha_kiosk')",
        (OLD, "{not valid json"),
    )
    c.commit()
    c.close()

    counts = migrate(path)
    assert counts["sessions"] == 0
    assert counts["skipped"] == 1

    c = sqlite3.connect(path)
    row = c.execute(
        "SELECT session_key, chat_id, display_name, origin_json, source "
        "FROM sessions WHERE id=1"
    ).fetchone()
    # Every column, not just the blob: the row must be untouched entirely,
    # source included.
    assert row == (OLD, "kiosk", "Kiosk", "{not valid json", "samantha_kiosk")

    # And a second run does not magically find it either — it is keyed
    # on OLD_KEY, which this row still carries, so it will be retried
    # forever rather than silently abandoned.
    counts2 = migrate(path)
    assert counts2["skipped"] == 1


def test_null_origin_json_is_skipped_not_touched(tmp_path):
    path = _empty_db(tmp_path)
    c = sqlite3.connect(path)
    c.execute(
        "INSERT INTO sessions VALUES (1, ?, 'kiosk', 'Kiosk', NULL, 'samantha_kiosk')",
        (OLD,),
    )
    c.commit()
    c.close()

    counts = migrate(path)
    assert counts["sessions"] == 0
    assert counts["skipped"] == 1

    c = sqlite3.connect(path)
    row = c.execute(
        "SELECT session_key, chat_id, display_name, origin_json, source "
        "FROM sessions WHERE id=1"
    ).fetchone()
    assert row == (OLD, "kiosk", "Kiosk", None, "samantha_kiosk")


def test_empty_origin_json_is_skipped_not_touched(tmp_path):
    path = _empty_db(tmp_path)
    c = sqlite3.connect(path)
    c.execute(
        "INSERT INTO sessions VALUES (1, ?, 'kiosk', 'Kiosk', '', 'samantha_kiosk')",
        (OLD,),
    )
    c.commit()
    c.close()

    counts = migrate(path)
    assert counts["sessions"] == 0
    assert counts["skipped"] == 1

    c = sqlite3.connect(path)
    row = c.execute(
        "SELECT session_key, chat_id, display_name, origin_json, source "
        "FROM sessions WHERE id=1"
    ).fetchone()
    assert row == (OLD, "kiosk", "Kiosk", "", "samantha_kiosk")


def test_unrelated_fields_with_colliding_values_are_left_alone(tmp_path):
    path = _empty_db(tmp_path)
    origin = json.dumps(
        {
            "platform": "samantha_kiosk",
            "chat_id": "kiosk",
            "chat_name": "Kiosk",
            "user_id": "kiosk",
            "last_message_preview": "Kiosk",
        }
    )
    c = sqlite3.connect(path)
    c.execute(
        "INSERT INTO sessions VALUES (1, ?, 'kiosk', 'Kiosk', ?, 'samantha_kiosk')",
        (OLD, origin),
    )
    c.commit()
    c.close()

    migrate(path)

    c = sqlite3.connect(path)
    row = c.execute("SELECT origin_json, source FROM sessions WHERE id=1").fetchone()
    blob = json.loads(row[0])
    assert blob["platform"] == "jarvis"
    assert blob["chat_id"] == "jarvis"
    assert blob["chat_name"] == "JARVIS"
    # Not identity fields — their value happens to collide, but the
    # field name does not, so they must survive untouched.
    assert blob["user_id"] == "kiosk"
    assert blob["last_message_preview"] == "Kiosk"
    assert row[1] == "jarvis"


def test_nested_origin_object_is_rewritten_at_any_depth(tmp_path):
    path = _empty_db(tmp_path)
    origin = json.dumps(
        {
            "platform": "samantha_kiosk",
            "chat_id": "kiosk",
            "chat_name": "Kiosk",
            "origin": {
                "platform": "samantha_kiosk",
                "chat_id": "kiosk",
                "chat_name": "Kiosk",
            },
        }
    )
    c = sqlite3.connect(path)
    c.execute(
        "INSERT INTO sessions VALUES (1, ?, 'kiosk', 'Kiosk', ?, 'samantha_kiosk')",
        (OLD, origin),
    )
    c.commit()
    c.close()

    migrate(path)

    c = sqlite3.connect(path)
    row = c.execute("SELECT origin_json, source FROM sessions WHERE id=1").fetchone()
    blob = json.loads(row[0])
    # A field-aware walk that stopped at the top level would leave
    # these nested copies on the old identity — guard against that.
    assert blob["origin"]["platform"] == "jarvis"
    assert blob["origin"]["chat_id"] == "jarvis"
    assert blob["origin"]["chat_name"] == "JARVIS"
    assert row[1] == "jarvis"
