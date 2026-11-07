"""Additive storage for structured, approval-gated agent projects."""
import sqlite3

AGENT_PROJECTS_DDL = """
CREATE TABLE IF NOT EXISTS agent_projects (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    goal TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'awaiting_plan_approval',
    plan_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    run_attempt INTEGER NOT NULL DEFAULT 0,
    run_key TEXT,
    run_heartbeat_at TEXT,
    idempotency_key TEXT,
    last_error TEXT,
    approved_plan_hash TEXT,
    brand_id TEXT
);
CREATE TABLE IF NOT EXISTS agent_tasks (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    agent TEXT NOT NULL,
    instruction TEXT NOT NULL,
    depends_on TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'pending',
    review_status TEXT NOT NULL DEFAULT 'pending',
    deliverable_type TEXT NOT NULL DEFAULT 'draft',
    acceptance_criteria TEXT NOT NULL DEFAULT '[]',
    output TEXT,
    output_json TEXT,
    task_attempt INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS activity_log (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    agent TEXT,
    event TEXT NOT NULL,
    details TEXT
);
CREATE TABLE IF NOT EXISTS pending_actions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    task_id TEXT,
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    agent TEXT NOT NULL,
    type TEXT NOT NULL,
    payload TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    result TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def apply_agent_project_tables(c):
    c.executescript(AGENT_PROJECTS_DDL)
    try:
        c.execute("ALTER TABLE agent_tasks ADD COLUMN review_status TEXT NOT NULL DEFAULT 'pending'")
    except sqlite3.OperationalError:
        pass
    for statement in (
        "ALTER TABLE agent_tasks ADD COLUMN deliverable_type TEXT NOT NULL DEFAULT 'draft'",
        "ALTER TABLE agent_tasks ADD COLUMN acceptance_criteria TEXT NOT NULL DEFAULT '[]'",
    ):
        try:
            c.execute(statement)
        except sqlite3.OperationalError:
            pass
