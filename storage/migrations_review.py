"""T2-E Review Center — non-destructive dismissal ledger.

Lets a human owner hide individual Review & Action Center items from their
attention list WITHOUT destroying the underlying coordination evidence. Each row
is owner-scoped and keyed by (item_type, item_key), so dismissal never mutates
frozen plans, step outputs, deliverable versions, or audit rows.

Additive and idempotent (``CREATE TABLE IF NOT EXISTS`` / guarded index), so
repeated application is a no-op on existing databases.
"""
from __future__ import annotations

REVIEW_DISMISS_DDL = """
CREATE TABLE IF NOT EXISTS review_dismissals (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    item_type TEXT NOT NULL,
    item_key TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_review_dismissals_owner
    ON review_dismissals(tenant_id, user_id, item_type, item_key);
"""


def apply_review_tables(c) -> None:
    """Create the additive review_dismissals table (idempotent)."""
    c.executescript(REVIEW_DISMISS_DDL)
