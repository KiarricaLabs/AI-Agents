"""Durable job queue with SQLite backend and idempotency."""
from __future__ import annotations

import uuid, json
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Callable
from storage.database import Database

def _now():
    return datetime.now(timezone.utc).isoformat()

# ensure table exists
JOB_SCHEMA = """
CREATE TABLE IF NOT EXISTS durable_jobs (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    idempotency_key TEXT UNIQUE,
    status TEXT NOT NULL DEFAULT 'queued',
    payload_json TEXT,
    result_json TEXT,
    error TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


class DurableJobQueue:
    def __init__(self, db: Database):
        self.db = db
        with db._connect() as c:
            c.executescript(JOB_SCHEMA)
            c.commit()

    def enqueue(self, tenant_id, payload, idempotency_key=None):
        if idempotency_key:
            existing = self.db.query("SELECT id FROM durable_jobs WHERE idempotency_key=?", (idempotency_key,))
            if existing:
                return existing[0]["id"]
        jid = str(uuid.uuid4())
        now = _now()
        self.db.execute(
            "INSERT INTO durable_jobs (id,tenant_id,idempotency_key,status,payload_json,attempts,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",
            (jid, tenant_id, idempotency_key, "queued", json.dumps(payload), 0, now, now))
        return jid

    def claim(self, jid):
        now = _now()
        self.db.execute("UPDATE durable_jobs SET status='running', attempts=attempts+1, updated_at=? WHERE id=? AND status='queued'",
                        (now, jid))
        rows = self.db.query("SELECT * FROM durable_jobs WHERE id=?", (jid,))
        return rows[0] if rows else None

    def complete(self, jid, result):
        now = _now()
        self.db.execute("UPDATE durable_jobs SET status='done', result_json=?, updated_at=? WHERE id=?",
                        (json.dumps(result), now, jid))

    def fail(self, jid, error):
        now = _now()
        self.db.execute("UPDATE durable_jobs SET status='failed', error=?, updated_at=? WHERE id=?",
                        (error[:200], now, jid))