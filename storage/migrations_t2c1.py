"""T2-C-1 — TeamGoal coordination object (additive, idempotent DDL).

Introduces the foundational coordination object for the AI Team Execution &
Coordination workflow. All additions are additive (CREATE TABLE IF NOT EXISTS);
no existing table or column is altered, rewritten, removed, or combined.

- team_goals           — the reviewable coordination unit tying one goal to a
                         coordinator, aggregated status, and a consolidated
                         deliverable.
- team_goal_steps      — the ordered per-agent contributions (sequenced,
                         dependency-aware) within a team goal.
- team_goal_approvals  — the human review gate for the consolidated deliverable
                         (approve / request_changes / reject).

Lifecycle (user-facing status, reused across the app):
  proposed -> approved -> in_progress -> ready_for_review
            -> revision_requested -> completed  |  rejected

Creating a Team Goal is a human-approved action but NEVER starts any episode or
agent execution on its own (that is a later, still-human-triggered phase).
"""

import sqlite3

T2C1_DDL = """
CREATE TABLE IF NOT EXISTS team_goals (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    goal_id TEXT,
    thread_id TEXT,
    title TEXT NOT NULL,
    coordinator_agent TEXT NOT NULL,
    summary TEXT,
    status TEXT NOT NULL DEFAULT 'proposed',
    expected_deliverable TEXT,
    result_deliverable_id TEXT,
    revision_of TEXT,
    decided_by TEXT,
    decided_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS team_goal_steps (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    team_goal_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    agent_id TEXT NOT NULL,
    responsibility TEXT,
    depends_on_seq INTEGER,
    status TEXT NOT NULL DEFAULT 'planned',
    evidence_episode_id TEXT,
    result_deliverable_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS team_goal_approvals (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    team_goal_id TEXT NOT NULL,
    decision TEXT NOT NULL,
    note TEXT,
    created_at TEXT NOT NULL
);
"""


def apply_t2c1_tables(c):
    """Create the T2-C-1 additive tables (CREATE TABLE IF NOT EXISTS)."""
    c.executescript(T2C1_DDL)
