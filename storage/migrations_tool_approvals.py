"""Additive storage for tool approval requests (Stage 4.3)."""
TOOL_APPROVALS_DDL = """
CREATE TABLE IF NOT EXISTS tool_approvals (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    args_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    consumed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_tool_approvals_status ON tool_approvals(status, expires_at);
"""


def apply_tool_approvals_table(c):
    c.executescript(TOOL_APPROVALS_DDL)
    c.commit()