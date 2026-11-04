"""Phase 4 (UX restructuring) — additive, idempotent, backward-compatible DDL.

All changes are additive (new nullable columns / flags) applied with guarded
ALTER TABLE statements so repeated application on fresh or existing databases is
safe, and rollback never destroys existing rows.

New fields:
- assignments.title / assignments.description
    Give a user-facing "task" its own readable title/description. The task model
    *is* an assignment (goal -> agent), so no new table is introduced. Existing
    rows leave these NULL and the UI falls back to a derived label.
- work_proposals.requested_changes INTEGER (0/1, default 0)
    Distinguish "revision/request changes" from a hard "reject". A revision
    request keeps work active and requires changes; it is NOT a permanent
    rejection. The proposal row is preserved with its history.
- deliverable_versions.requested_changes INTEGER (0/1, default 0)
    Same semantics for deliverable version review: reject a version outright, or
    flag that revisions were requested (version remains open/draft for rework).
"""

import sqlite3


def _guard(c, stmt):
    """Run an additive ALTER ... no-op if the column already exists."""
    try:
        c.execute(stmt)
    except sqlite3.OperationalError:
        pass  # column already exists


def apply_phase4_columns(c):
    """Apply all Phase 4 additive columns idempotently."""
    _guard(c,
        "ALTER TABLE assignments ADD COLUMN title TEXT")
    _guard(c,
        "ALTER TABLE assignments ADD COLUMN description TEXT")
    _guard(c,
        "ALTER TABLE work_proposals ADD COLUMN requested_changes INTEGER NOT NULL DEFAULT 0")
    _guard(c,
        "ALTER TABLE work_proposals ADD COLUMN revision_of TEXT")
    _guard(c,
        "ALTER TABLE deliverable_versions ADD COLUMN requested_changes INTEGER NOT NULL DEFAULT 0")
    _guard(c,
        "ALTER TABLE deliverable_versions ADD COLUMN review_note TEXT")
    _guard(c,
        "ALTER TABLE deliverable_versions ADD COLUMN revision_of TEXT")
