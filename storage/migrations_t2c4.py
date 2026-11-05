"""T2-C-4 — Coordination execution + step outputs (additive, idempotent DDL).

Introduces human-initiated, step-by-step execution state for an ALREADY-
AUTHORIZED coordination plan (T2-C-3 authoritative snapshot). All additions are
additive (CREATE TABLE IF NOT EXISTS); no existing table or column is altered.

- coordination_executions    — one human-initiated execution run per authorized
                              plan. status: running -> ready_for_review ->
                              completed | cancelled. UNIQUE(tenant,user,plan_id)
                              enforces a single run per plan (idempotent start).
- coordination_step_outputs  — per-step execution records: the captured agent
                              output + validated evidence, with a step-level
                              lifecycle (pending -> in_progress ->
                              awaiting_review -> accepted | revision_requested |
                              rejected | failed). The step's authoritative
                              assignment/responsibility stays in the frozen T2-C-3
                              snapshot; this table only tracks execution state.
- coordination_deliverables  — the final aggregated deliverable + its human
                              review state (accepted / revision / rejected).

Execution is NEVER autonomous or background: a human initiates the run, a human
requests each eligible step's execution (one step at a time, in order, after
dependencies are accepted), and a human reviews each output and the aggregate.
Evidence-gated completion is preserved via EpisodeService.
"""

import sqlite3

T2C4_DDL = """
CREATE TABLE IF NOT EXISTS coordination_executions (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    plan_id TEXT NOT NULL,
    team_goal_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    initiated_by TEXT,
    initiated_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(tenant_id, user_id, plan_id)
);
CREATE TABLE IF NOT EXISTS coordination_step_outputs (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    execution_id TEXT NOT NULL,
    plan_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    agent_id TEXT NOT NULL,
    episode_id TEXT,
    output_json TEXT,
    evidence_json TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS coordination_deliverables (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    execution_id TEXT NOT NULL,
    plan_id TEXT NOT NULL,
    title TEXT,
    content_json TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    review_note TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(tenant_id, user_id, execution_id)
);
CREATE INDEX IF NOT EXISTS idx_coord_exec_owner
    ON coordination_executions (tenant_id, user_id, plan_id);
CREATE INDEX IF NOT EXISTS idx_coord_stepout_exec
    ON coordination_step_outputs (tenant_id, user_id, execution_id, seq);
CREATE INDEX IF NOT EXISTS idx_coord_deliv_exec
    ON coordination_deliverables (tenant_id, user_id, execution_id);
"""


def apply_t2c4_tables(c):
    """Create the T2-C-4 additive tables (CREATE TABLE IF NOT EXISTS)."""
    c.executescript(T2C4_DDL)
