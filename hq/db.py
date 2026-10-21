"""SQLite storage shared by the Boss, the agents and the dashboard."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY,
    agent TEXT NOT NULL,
    instructions TEXT NOT NULL,
    params TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'queued',      -- queued, running, done, failed
    result TEXT,
    created_by TEXT NOT NULL DEFAULT 'boss',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS clips (
    id INTEGER PRIMARY KEY,
    task_id INTEGER,
    creator TEXT,
    source_url TEXT,
    source_title TEXT,
    start_s REAL NOT NULL,
    end_s REAL NOT NULL,
    path TEXT NOT NULL,
    title TEXT,
    caption TEXT,
    hashtags TEXT,
    score REAL,
    reason TEXT,
    captioned INTEGER,                           -- 1 if words were burned in, 0 if the clip has no captions
    boss_note TEXT,                              -- the Boss's review note, shown on the approval card
    status TEXT NOT NULL DEFAULT 'pending_approval', -- pending_approval, approved, rejected, posted, failed
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY,
    clip_id INTEGER NOT NULL,
    platform TEXT NOT NULL,
    account TEXT NOT NULL,
    status TEXT NOT NULL,                        -- posted, failed, skipped
    external_id TEXT,
    url TEXT,
    error TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS boss_messages (
    id INTEGER PRIMARY KEY,
    conversation INTEGER NOT NULL DEFAULT 1,
    role TEXT NOT NULL,
    content TEXT NOT NULL,                       -- JSON content blocks
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS relay_sent (
    kind TEXT NOT NULL,
    ref_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (kind, ref_id)
);
CREATE TABLE IF NOT EXISTS llm_usage (
    id INTEGER PRIMARY KEY,
    agent TEXT NOT NULL,
    model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens INTEGER NOT NULL DEFAULT 0,
    cache_write_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS activity (
    id INTEGER PRIMARY KEY,
    agent TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init():
    with connect() as c:
        c.executescript(SCHEMA)
        # Databases made before these columns existed get them added in place.
        have = {r["name"] for r in c.execute("PRAGMA table_info(clips)")}
        for col, kind in (("captioned", "INTEGER"), ("boss_note", "TEXT")):
            if col not in have:
                c.execute(f"ALTER TABLE clips ADD COLUMN {col} {kind}")


def rows(sql: str, *args) -> list[dict]:
    with connect() as c:
        return [dict(r) for r in c.execute(sql, args).fetchall()]


def execute(sql: str, *args) -> int:
    with connect() as c:
        return c.execute(sql, args).lastrowid


def log(agent: str, message: str):
    execute("INSERT INTO activity (agent, message, created_at) VALUES (?, ?, ?)", agent, message, now())


def create_task(agent: str, instructions: str, params: dict | None = None, created_by: str = "boss") -> int:
    ts = now()
    task_id = execute(
        "INSERT INTO tasks (agent, instructions, params, created_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        agent, instructions, json.dumps(params or {}), created_by, ts, ts,
    )
    log(created_by, f"Assigned task #{task_id} to {agent}: {instructions[:120]}")
    return task_id


def update_task(task_id: int, status: str, result: str | None = None):
    execute("UPDATE tasks SET status = ?, result = COALESCE(?, result), updated_at = ? WHERE id = ?",
            status, result, now(), task_id)


def set_clip_status(clip_id: int, status: str):
    execute("UPDATE clips SET status = ? WHERE id = ?", status, clip_id)
