"""T2-C-5 — Coordination deliverable versioning (additive, idempotent DDL).

Adds durable versioned review for the T2-C-4 coordination deliverable. Each
human-reviewed aggregation of accepted step outputs becomes an immutable VERSION
with an ordered step-output provenance snapshot, a server-assigned version
number, a `revision_of` predecessor link, and a dedicated approval row per
decision. Historical version content is never mutated.

- coordination_deliverable_versions  — one entry per aggregation/review round:
  version, content_json (exact aggregated content), status
  (pending/approved/rejected/revision_requested), review_note, revision_of.
  UNIQUE(tenant_id, user_id, deliverable_id, version) prevents duplicate numbers.
- coordination_deliverable_approvals — one row per human decision on a version:
  decision (accepted/revision_requested/rejected), user, note, created_at.

Existing tables (T2-C-3 snapshot, T2-C-4 execution/step-outputs/deliverable) are
not altered, rewritten, removed, or combined. This is purely additive and does
not touch the project-scoped deliverable_versions / deliverable_approvals tables.
"""

import sqlite3

T2C5_DDL = """
CREATE TABLE IF NOT EXISTS coordination_deliverable_versions (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    execution_id TEXT NOT NULL,
    deliverable_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    content_json TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    review_note TEXT,
    revision_of TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(tenant_id, user_id, deliverable_id, version)
);
CREATE TABLE IF NOT EXISTS coordination_deliverable_approvals (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    version_id TEXT NOT NULL,
    decision TEXT NOT NULL,
    note TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_coord_deliv_versions
    ON coordination_deliverable_versions (tenant_id, user_id, deliverable_id, version);
CREATE INDEX IF NOT EXISTS idx_coord_deliv_approvals
    ON coordination_deliverable_approvals (tenant_id, user_id, version_id);
"""


def apply_t2c5_tables(c):
    """Create the T2-C-5 additive tables (CREATE TABLE IF NOT EXISTS)."""
    c.executescript(T2C5_DDL)
