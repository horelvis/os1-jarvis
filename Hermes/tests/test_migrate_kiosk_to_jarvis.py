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


def _db(tmp_path):
    path = tmp_path / "state.db"
    c = sqlite3.connect(path)
    c.executescript(
        """
        CREATE TABLE sessions (id INTEGER PRIMARY KEY, session_key TEXT,
            chat_id TEXT, display_name TEXT, origin_json TEXT);
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
    c.execute("INSERT INTO sessions VALUES (1, ?, 'kiosk', 'Kiosk', ?)", (OLD, origin))
    c.execute("INSERT INTO sessions VALUES (2, NULL, NULL, NULL, NULL)")
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


def test_every_row_moves_to_the_new_key(tmp_path):
    path = _db(tmp_path)
    counts = migrate(path)
    assert counts == {"sessions": 1, "delivery_obligations": 1, "gateway_routing": 1}
    c = sqlite3.connect(path)
    assert c.execute("SELECT session_key FROM sessions WHERE id=1").fetchone()[0] == NEW
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
    }
