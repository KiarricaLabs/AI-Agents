"""Additive storage for individual agent run history (V1.6.10.0).

This table is independent of the canonical project-scoped ``agent_runs`` queue.
It records terminal outcomes for direct /agents/{name}/run executions only.
"""
AGENT_RUN_HISTORY_DDL = """
CREATE TABLE IF NOT EXISTS agent_run_history (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    thread_id TEXT,
    status TEXT NOT NULL CHECK (status IN ('completed', 'failed', 'rejected', 'cancelled')),
    task_summary TEXT,
    error_category TEXT,
    created_at TEXT NOT NULL,
    finished_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_agent_run_history_tenant_user_created
    ON agent_run_history(tenant_id, user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_run_history_agent_status
    ON agent_run_history(agent_id, status);
"""


def apply_agent_run_history_table(c):
    c.executescript(AGENT_RUN_HISTORY_DDL)
    c.commit()
