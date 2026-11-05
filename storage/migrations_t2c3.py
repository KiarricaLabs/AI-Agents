"""T2-C-3 — Authoritative coordination plan snapshot (additive, idempotent DDL).

Introduces the persisted, human-authorized snapshot of a validated coordination
plan so a later execution phase (T2-C-4) can consume it as the authoritative
execution source. All additions are additive (CREATE TABLE IF NOT EXISTS); no
existing table or column is altered, rewritten, removed, or combined.

- coordination_plans        — one authoritative plan per TeamGoal (goal_id,
                              coordinator, expected deliverable, approval metadata).
                              UNIQUE(tenant_id, user_id, team_goal_id) enforces a
                              single authoritative plan per goal.
- coordination_plan_steps   — the exact validated per-agent step snapshot
                              (ordered, dependency-aware, capability + delegation
                              results, effective permissions).

A plan is NOT revised, rebuilt, or reassigned during execution; it is the frozen
source of truth for T2-C-4. Authorizing a plan never starts any episode, agent,
tool execution, or background work (that remains a separately human-triggered
phase).
"""

import sqlite3

T2C3_DDL = """
CREATE TABLE IF NOT EXISTS coordination_plans (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    team_goal_id TEXT NOT NULL,
    goal_id TEXT,
    coordinator_agent TEXT NOT NULL,
    expected_deliverable TEXT,
    status TEXT NOT NULL DEFAULT 'authorized',
    version INTEGER NOT NULL DEFAULT 1,
    approved_by TEXT,
    approved_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(tenant_id, user_id, team_goal_id)
);
CREATE TABLE IF NOT EXISTS coordination_plan_steps (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    plan_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    agent_id TEXT NOT NULL,
    responsibility TEXT,
    depends_on_seq INTEGER,
    capability_ok INTEGER NOT NULL DEFAULT 0,
    delegation_ok INTEGER NOT NULL DEFAULT 0,
    effective_permissions TEXT,
    valid INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    status TEXT NOT NULL DEFAULT 'planned',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_coordination_plans_owner
    ON coordination_plans (tenant_id, user_id, team_goal_id);
CREATE INDEX IF NOT EXISTS idx_coordination_plan_steps_plan
    ON coordination_plan_steps (tenant_id, user_id, plan_id, seq);
"""


def apply_t2c3_tables(c):
    """Create the T2-C-3 additive tables (CREATE TABLE IF NOT EXISTS)."""
    c.executescript(T2C3_DDL)
