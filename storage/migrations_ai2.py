"""AI Team 2.0 (T2-A) — additive, idempotent, backward-compatible DDL.

Everything here is ADDITIVE:
- New nullable columns / flags via guarded ALTER ... no destructive ops.
- New tables via CREATE TABLE IF NOT EXISTS.
- Existing tables (workspaces/projects/goals/assignments/deliverables/episodes,
  work_proposals, conversation_threads, work_links, etc.) are never altered in
  a destructive way. Existing single-agent conversations default to
  thread_type='agent' and keep rendering exactly as before.

Introduces:
- conversation_threads.thread_type ('agent' default | 'team' | 'project')
- conversation_threads.workspace_id  (binds a project conversation to a workspace)
- conversation_participants          (which agents participate in a group/project thread)
- milestones                         (real, trackable plan milestones)
- dependencies                       (task<->task / milestone<->milestone ordering edges)
- goals.milestone_id, assignments.milestone_id (roll tasks up to a milestone)

Repeated application on fresh or existing databases is safe; rollback is simply
ignoring the new columns/tables (no row deletion, no rewrite).
"""

import sqlite3

MILESTONES_DDL = """
CREATE TABLE IF NOT EXISTS milestones (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    title TEXT NOT NULL,
    ord INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'planned',
    deadline TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS dependencies (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    from_type TEXT NOT NULL,
    from_id TEXT NOT NULL,
    to_type TEXT NOT NULL,
    to_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (tenant_id, from_type, from_id, to_type, to_id)
);
CREATE TABLE IF NOT EXISTS conversation_participants (
    id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    joined_at TEXT NOT NULL,
    UNIQUE (thread_id, agent_id)
);
"""


def _guard(c, stmt):
    """Run an additive ALTER; no-op if the column already exists."""
    try:
        c.execute(stmt)
    except sqlite3.OperationalError:
        pass  # column already exists


def apply_ai2_columns(c):
    """Apply all AI2 additive columns (guarded, no-op if already present)."""
    _guard(c,
        "ALTER TABLE conversation_threads ADD COLUMN thread_type TEXT NOT NULL DEFAULT 'agent'")
    _guard(c,
        "ALTER TABLE conversation_threads ADD COLUMN workspace_id TEXT")
    _guard(c,
        "ALTER TABLE goals ADD COLUMN milestone_id TEXT")
    _guard(c,
        "ALTER TABLE assignments ADD COLUMN milestone_id TEXT")


def apply_ai2_tables(c):
    """Create the AI2 additive tables (CREATE TABLE IF NOT EXISTS)."""
    c.executescript(MILESTONES_DDL)
