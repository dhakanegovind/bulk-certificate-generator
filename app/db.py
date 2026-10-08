"""Tiny SQLite layer using only the standard library.

Each caller (a request, or a background worker thread) opens its OWN connection.
SQLite connections must not be shared between threads, and short-lived connections
keep the code simple and safe.
"""
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id            TEXT PRIMARY KEY,
    status        TEXT NOT NULL CHECK (status IN
                    ('pending', 'processing', 'completed', 'completed_with_errors', 'failed')),
    title         TEXT NOT NULL,
    event_name    TEXT NOT NULL,
    issued_by     TEXT NOT NULL,
    issue_date    TEXT NOT NULL,
    total         INTEGER NOT NULL,
    error         TEXT,              -- only set if the whole job crashed unexpectedly
    created_at    TEXT NOT NULL,
    started_at    TEXT,
    completed_at  TEXT
);

CREATE TABLE IF NOT EXISTS certificates (
    id               TEXT PRIMARY KEY,
    job_id           TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    row_index        INTEGER NOT NULL,  -- 0-based position in the request's recipients list
    recipient_name   TEXT,
    recipient_email  TEXT,
    status           TEXT NOT NULL CHECK (status IN ('pending', 'success', 'failed')),
    file_path        TEXT,              -- relative to STORAGE_DIR
    error            TEXT,
    created_at       TEXT NOT NULL,
    completed_at     TEXT,
    UNIQUE (job_id, row_index)
);

CREATE INDEX IF NOT EXISTS idx_certificates_job_status ON certificates (job_id, status);
"""


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def connect(db_path):
    """Open a connection; commit on success, roll back on error, always close."""
    conn = sqlite3.connect(db_path, timeout=30)  # wait up to 30s if another writer holds the lock
    conn.row_factory = sqlite3.Row               # rows behave like dicts: row["status"]
    conn.execute("PRAGMA foreign_keys = ON")     # SQLite ignores foreign keys unless asked
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path):
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with connect(db_path) as conn:
        # WAL lets readers (status polling) work while a worker is writing.
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA)
