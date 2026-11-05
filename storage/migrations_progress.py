"""Additive migration: durable agent progress/status ledger (Phase 8 §15).

Stores tenant/user-scoped agent progress updates (working / completed / blocked /
message) tied to a conversation thread, so the human command center can show what
the team is doing without re-running agents. Idempotent (CREATE TABLE IF NOT EXISTS).
"""
import sqlite3

PROGRESS_DDL = """
CREATE TABLE IF NOT EXISTS agent_progress (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    thread_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'working',
    detail TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_agent_progress_owner_thread
    ON agent_progress (tenant_id, user_id, thread_id);
CREATE INDEX IF NOT EXISTS idx_agent_progress_owner
    ON agent_progress (tenant_id, user_id, status);
"""


def apply_progress_tables(c):
    c.executescript(PROGRESS_DDL)
