"""T2-E — Durable agent-to-agent coordination ledger (additive, idempotent DDL).

Implements Phase 3 §5-6 (shared team communication + controlled coordination)
with a durable, tenant/user-scoped record of agent-to-agent requests/responses
that preserves traceability and enforces a delegation/loop depth guard. All
additions are additive (CREATE TABLE IF NOT EXISTS); no existing table/column is
changed.
"""
import sqlite3

T2E_DDL = """
CREATE TABLE IF NOT EXISTS agent_comm_messages (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    thread_id TEXT,
    parent_id TEXT,
    from_agent TEXT NOT NULL,
    to_agent TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'request',
    content TEXT NOT NULL,
    depth INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_agent_comm_owner_thread
    ON agent_comm_messages (tenant_id, user_id, thread_id);
CREATE INDEX IF NOT EXISTS idx_agent_comm_status
    ON agent_comm_messages (tenant_id, user_id, status);
"""


def apply_t2e_tables(c):
    """Create the T2-E additive tables (CREATE TABLE IF NOT EXISTS)."""
    c.executescript(T2E_DDL)
