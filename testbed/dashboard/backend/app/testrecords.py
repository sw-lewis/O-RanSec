"""Permanent records of tests run on the testbed (SQLite on the dashboard's volume).

A record holds what the tester entered (name, purpose, description, tester, type, the
components involved) and what happened (start and end time, notes, result, export file)."""
import datetime as dt
import json
import os
import pathlib
import sqlite3
import uuid

DATA = pathlib.Path(os.environ.get("DATA_DIR", "/data"))
DATA.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA / "tests.db"

KINDS = {
    "device-test": "Device connection test",
    "attack-scenario": "Attack scenario run",
    "free-test": "Free-form test",
}
LIST_FIELDS = ("components",)

SCHEMA = """
CREATE TABLE IF NOT EXISTS tests (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    purpose TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    tester TEXT NOT NULL DEFAULT '',
    components TEXT NOT NULL DEFAULT '[]',
    state TEXT NOT NULL,            -- planned | running | finished
    created REAL NOT NULL,
    started REAL,
    finished REAL,
    notes TEXT NOT NULL DEFAULT '',
    outcome TEXT NOT NULL DEFAULT '', -- pass | fail | inconclusive
    export_file TEXT,
    export_bytes INTEGER
)"""


def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute(SCHEMA)
    return c


def _to_dict(row):
    if row is None:
        return None
    d = dict(row)
    for f in LIST_FIELDS:
        d[f] = json.loads(d[f] or "[]")
    d["kindLabel"] = KINDS.get(d["kind"], d["kind"])
    return d


def all_tests():
    with _conn() as c:
        return [_to_dict(r) for r in c.execute("SELECT * FROM tests ORDER BY created DESC")]


def one(test_id):
    with _conn() as c:
        return _to_dict(c.execute("SELECT * FROM tests WHERE id = ?", (test_id,)).fetchone())


def new(name, kind, purpose="", description="", tester="", components=()):
    name = (name or "").strip()
    if not name:
        raise ValueError("A test needs a name.")
    if kind not in KINDS:
        raise ValueError(f"Unknown test type '{kind}'.")
    test_id = dt.datetime.now().strftime("T%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
    with _conn() as c:
        c.execute(
            "INSERT INTO tests (id, name, kind, purpose, description, tester, components, state, created)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, 'planned', ?)",
            (test_id, name, kind, purpose.strip(), description.strip(), tester.strip(),
             json.dumps(list(components)), dt.datetime.now().timestamp()))
    return one(test_id)


def update(test_id, **fields):
    if not fields:
        return one(test_id)
    for f in LIST_FIELDS:
        if f in fields:
            fields[f] = json.dumps(list(fields[f]))
    cols = ", ".join(f"{k} = ?" for k in fields)
    with _conn() as c:
        c.execute(f"UPDATE tests SET {cols} WHERE id = ?", (*fields.values(), test_id))
    return one(test_id)


def remove(test_id):
    with _conn() as c:
        c.execute("DELETE FROM tests WHERE id = ?", (test_id,))
