"""Additive storage for scoped human feedback and approved lessons."""
from __future__ import annotations

FEEDBACK_DDL = """
CREATE TABLE IF NOT EXISTS agent_feedback (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    scope_type TEXT NOT NULL,
    scope_id TEXT,
    agent_id TEXT,
    task_type TEXT,
    rating TEXT NOT NULL,
    feedback TEXT NOT NULL,
    output_snapshot TEXT,
    lesson TEXT,
    status TEXT NOT NULL DEFAULT 'recorded',
    created_at TEXT NOT NULL,
    approved_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_agent_feedback_scope
    ON agent_feedback(tenant_id, user_id, scope_type, scope_id, status);
"""


def apply_feedback_tables(c) -> None:
    c.executescript(FEEDBACK_DDL)
