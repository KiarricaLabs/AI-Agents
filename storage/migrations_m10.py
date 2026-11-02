"""M10 — Agent-to-Workspace integration: additive, idempotent DDL (Phase A).

Phase A introduces structured, approval-gated *work proposals* plus durable
conversation-to-work *links*. No existing table or column is altered, rewritten,
removed, or combined. The base application schema (including the uncommitted
Conversation History `conversation_threads` change) lives untouched in
``storage/database.py``; these tables are applied by an isolated init hook.

``work_proposals`` stores the pending change (intent) only — it never creates or
mutates a project/goal/assignment/deliverable/task/episode. Approved execution
is a later phase.

``work_links`` records the durable, bidirectional link between an approved work
record and its originating conversation thread. Phase A creates the table; rows
are written only by later approval code.

Both statements are idempotent (``CREATE TABLE IF NOT EXISTS``), so repeated
application on fresh or existing databases is safe.
"""

M10_DDL = """
CREATE TABLE IF NOT EXISTS work_proposals (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    thread_id TEXT,
    work_type TEXT NOT NULL,
    action TEXT NOT NULL DEFAULT 'create',
    target_id TEXT,
    workspace_id TEXT,
    project_id TEXT,
    goal_id TEXT,
    subject_id TEXT,
    payload_json TEXT NOT NULL,
    reason TEXT,
    context TEXT,
    confidence REAL DEFAULT 0.5,
    status TEXT NOT NULL DEFAULT 'proposed',
    result_id TEXT,
    idempotency_key TEXT NOT NULL,
    decided_at TEXT,
    decided_by TEXT,
    rejection_reason TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (tenant_id, idempotency_key)
);

CREATE TABLE IF NOT EXISTS work_links (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    work_type TEXT NOT NULL,
    work_id TEXT NOT NULL,
    thread_id TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (tenant_id, work_type, work_id, thread_id)
);
"""

# Additive, idempotent columns added after Phase A/B for existing databases that
# already created work_proposals. Fresh databases get them from the CREATE above.
M10_PHASE_C_COLUMNS = (
    "ALTER TABLE work_proposals ADD COLUMN decided_by TEXT",
    "ALTER TABLE work_proposals ADD COLUMN rejection_reason TEXT",
)


def apply_m10_phase_c_columns(c):
    """Apply the Phase C additive columns idempotently (guarded, no-op if present)."""
    import sqlite3

    for stmt in M10_PHASE_C_COLUMNS:
        try:
            c.execute(stmt)
        except sqlite3.OperationalError:
            pass  # column already exists


# --- M10 Phase D2: execution gating & episode tracking (additive) ---
# Additive, nullable columns on episodes / episode_events plus a DB-level
# partial unique index that enforces at most one ACTIVE (running) episode per
# (tenant, user, work_type, work_id, agent_id). Existing rows are unaffected.
M10_PHASE_D2_EPISODE_COLUMNS = (
    "ALTER TABLE episodes ADD COLUMN work_type TEXT",
    "ALTER TABLE episodes ADD COLUMN work_id TEXT",
)

M10_PHASE_D2_EVENT_COLUMNS = (
    "ALTER TABLE episode_events ADD COLUMN evidence_json TEXT",
    "ALTER TABLE episode_events ADD COLUMN progress INTEGER",
)

M10_PHASE_D2_INDEX = (
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_episodes_active_work "
    "ON episodes(tenant_id, user_id, work_type, work_id, agent_id) "
    "WHERE status='running' AND work_type IS NOT NULL AND work_id IS NOT NULL"
)


def apply_m10_phase_d2_columns(c):
    """Add the D2 additive columns idempotently (no-op if present)."""
    import sqlite3

    for stmt in M10_PHASE_D2_EPISODE_COLUMNS + M10_PHASE_D2_EVENT_COLUMNS:
        try:
            c.execute(stmt)
        except sqlite3.OperationalError:
            pass  # column already exists


def apply_m10_phase_d2_index(c):
    """Create the D2 partial unique index idempotently."""
    c.execute(M10_PHASE_D2_INDEX)
