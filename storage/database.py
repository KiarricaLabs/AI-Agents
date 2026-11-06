"""Tenant-aware SQLite database foundation."""
from __future__ import annotations

import sqlite3
import sys
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

from config.settings import DB_PATH, DATA_DIR

SCHEMA = """
CREATE TABLE IF NOT EXISTS tenants (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    email TEXT,
    name TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id)
);
CREATE TABLE IF NOT EXISTS memory_items (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    owner TEXT NOT NULL,
    kind TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    source TEXT,
    confidence REAL DEFAULT 0.5,
    expires_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS memory_proposals (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    agent_id TEXT,
    kind TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    source TEXT,
    reason TEXT,
    context TEXT,
    confidence REAL DEFAULT 0.5,
    status TEXT NOT NULL DEFAULT 'proposed',
    expires_at TEXT,
    created_at TEXT NOT NULL,
    decided_at TEXT
);
CREATE TABLE IF NOT EXISTS audit_log (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    user_id TEXT,
    action TEXT NOT NULL,
    detail TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS conversation_memory (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    thread_id TEXT,
    role TEXT,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS conversation_threads (
    thread_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    agent_id TEXT,
    title TEXT NOT NULL,
    is_renamed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_private_memory (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS refresh_tokens (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    token_hash TEXT NOT NULL,
    family_id TEXT NOT NULL,
    revoked INTEGER NOT NULL DEFAULT 0,
    reused INTEGER NOT NULL DEFAULT 0,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS memory_audit (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    user_id TEXT,
    agent_id TEXT,
    action TEXT NOT NULL,
    target_id TEXT,
    detail TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    payload_json TEXT,
    result_json TEXT,
    error TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    cancelled_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS task_events (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    status TEXT NOT NULL,
    detail TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS episodes (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    progress INTEGER NOT NULL DEFAULT 0,
    checkpoint_json TEXT,
    cancelled_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS episode_events (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    episode_id TEXT NOT NULL,
    status TEXT NOT NULL,
    detail TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS delegation_log (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    from_agent TEXT NOT NULL,
    to_agent TEXT NOT NULL,
    effective_perms TEXT,
    outcome TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workspaces (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS goals (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    title TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'open',
    progress INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT,
    version INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS assignments (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    goal_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    task_id TEXT,
    title TEXT,
    description TEXT,
    priority INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'queued',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS deliverables (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS deliverable_versions (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    deliverable_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    content TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    requested_changes INTEGER NOT NULL DEFAULT 0,
    review_note TEXT,
    revision_of TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS deliverable_approvals (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    version_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    decision TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tool_executions (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    task_id TEXT,
    tool TEXT NOT NULL,
    params_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    error TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS goal_events (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    goal_id TEXT NOT NULL,
    status TEXT NOT NULL,
    detail TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS goal_update_proposals (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    goal_id TEXT NOT NULL,
    agent_id TEXT,
    proposed_json TEXT NOT NULL,
    reason TEXT,
    context TEXT,
    confidence REAL DEFAULT 0.5,
    base_version INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'proposed',
    created_at TEXT NOT NULL,
    decided_at TEXT
);
CREATE TABLE IF NOT EXISTS brands (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    name TEXT NOT NULL,
    is_default INTEGER NOT NULL DEFAULT 0,
    created_by_user_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS brand_facts (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    brand_id TEXT NOT NULL,
    category TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    source TEXT,
    confidence REAL DEFAULT 0.5,
    version INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'approved',
    proposal_id TEXT,
    approved_by_user_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS brand_proposals (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    brand_id TEXT NOT NULL,
    agent_id TEXT,
    category TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    source TEXT,
    reason TEXT,
    context TEXT,
    confidence REAL DEFAULT 0.5,
    status TEXT NOT NULL DEFAULT 'proposed',
    base_version INTEGER,
    created_by_user_id TEXT,
    created_at TEXT NOT NULL,
    decided_at TEXT,
    decided_by_user_id TEXT
);
CREATE TABLE IF NOT EXISTS brand_history (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    brand_id TEXT NOT NULL,
    action TEXT NOT NULL,
    category TEXT,
    key TEXT,
    old_value TEXT,
    new_value TEXT,
    proposal_id TEXT,
    fact_id TEXT,
    user_id TEXT,
    created_at TEXT NOT NULL
);
"""

import uuid
from datetime import datetime, timezone

def _now():
    return datetime.now(timezone.utc).isoformat()


# The real application database that test runs must never open or modify.
_REAL_DB = (Path(DATA_DIR) / "pat.db").resolve()


class Database:
    def __init__(self, path: str = DB_PATH, tenant_id: str = None):
        # Fail closed: a unittest run must never open the real application DB.
        # The trusted test-isolation bootstrap (tests/__init__.py) points the
        # suite at a temp DB; if it did not run (e.g. `unittest` invoked without
        # `-t .`), refuse here before any connection is opened.
        if "unittest" in sys.modules and Path(path).resolve() == _REAL_DB:
            raise RuntimeError(
                "Refusing to open the real application database "
                f"({_REAL_DB}) while running tests. Use an isolated database: "
                "`python -m unittest discover -s tests -t . -v`, or set PAT_DB_PATH."
            )
        self.path = path
        self.default_tenant = tenant_id or "local"
        self._lock = threading.Lock()
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as c:
            c.executescript(SCHEMA)
            # M10 (Agent-to-Workspace) additive DDL — isolated from the base schema
            # and from the Conversation History changes. Idempotent, additive only.
            from storage.migrations_m10 import (
                M10_DDL,
                apply_m10_phase_c_columns,
                apply_m10_phase_d2_columns,
                apply_m10_phase_d2_index,
                apply_m10_phase_d3_columns,
            )
            c.executescript(M10_DDL)
            # Phase C additive columns (guarded; no-op on fresh DBs).
            apply_m10_phase_c_columns(c)
            # Phase D2: episode work-linkage columns + active-uniqueness index.
            apply_m10_phase_d2_columns(c)
            apply_m10_phase_d2_index(c)
            # Phase D3: episode apply markers.
            apply_m10_phase_d3_columns(c)
            # Phase 4 (UX restructuring): additive task/deliverable fields.
            from storage.migrations_phase4 import apply_phase4_columns
            apply_phase4_columns(c)
            # AI Team 2.0 (T2-A): additive group-thread + participants + milestones
            # + dependencies columns/tables. Guarded and idempotent; no-op on fresh DBs.
            from storage.migrations_ai2 import (
                apply_ai2_columns,
                apply_ai2_tables,
            )
            apply_ai2_columns(c)
            apply_ai2_tables(c)
            # T2-C-1: TeamGoal coordination object (additive tables only).
            from storage.migrations_t2c1 import apply_t2c1_tables
            apply_t2c1_tables(c)
            # T2-C-3: authoritative coordination plan snapshot (additive tables only).
            from storage.migrations_t2c3 import apply_t2c3_tables
            apply_t2c3_tables(c)
            # T2-C-4: coordination execution + step outputs (additive tables only).
            from storage.migrations_t2c4 import apply_t2c4_tables
            apply_t2c4_tables(c)
            # T2-C-5: coordination deliverable versioning (additive tables only).
            from storage.migrations_t2c5 import apply_t2c5_tables
            apply_t2c5_tables(c)
            # T2-E: durable agent-to-agent coordination ledger (additive).
            from storage.migrations_t2e import apply_t2e_tables
            apply_t2e_tables(c)
            # Phase 8 §15: durable agent progress ledger (additive).
            from storage.migrations_progress import apply_progress_tables
            apply_progress_tables(c)
            # T2-E Review Center: non-destructive dismissal ledger (additive).
            from storage.migrations_review import apply_review_tables
            apply_review_tables(c)
            self._apply_migrations(c)
            c.execute("INSERT OR IGNORE INTO tenants (id,name,created_at) VALUES (?,?,?)",
                      (self.default_tenant, "Local", _now()))
            c.commit()

    @staticmethod
    def _apply_migrations(c):
        # Additive, idempotent migrations for pre-existing databases.
        # Each is guarded so a freshly-created DB (already has the column) skips it.
        migrations = [
            "ALTER TABLE memory_proposals ADD COLUMN reason TEXT",
            "ALTER TABLE memory_proposals ADD COLUMN context TEXT",
            "ALTER TABLE goals ADD COLUMN progress INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE goals ADD COLUMN updated_at TEXT",
            "ALTER TABLE goals ADD COLUMN version INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE deliverables ADD COLUMN coordination_execution_id TEXT",
        ]
        for m in migrations:
            try:
                c.execute(m)
            except sqlite3.OperationalError:
                pass  # column already exists

    def _connect(self):
        return sqlite3.connect(self.path)

    @contextmanager
    def transaction(self):
        """Yield a raw connection inside one transaction, serialized by _lock.

        Callers must use the yielded cursor directly and MUST NOT call
        self.execute / self.query inside the block (the lock is non-reentrant).
        """
        with self._lock:
            c = self._connect()
            try:
                yield c
                c.commit()
            except Exception:
                c.rollback()
                raise
            finally:
                c.close()

    def execute(self, sql, params=(), tenant_id=None):
        tid = tenant_id or self.default_tenant
        with self._lock, self._connect() as c:
            c.execute(sql, params)
            c.commit()

    def query(self, sql, params=(), tenant_id=None):
        with self._lock, self._connect() as c:
            c.row_factory = sqlite3.Row
            cur = c.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]

    def tenant_filter(self, sql, tenant_id=None):
        tid = tenant_id or self.default_tenant
        if "WHERE" in sql.upper():
            return sql.replace("WHERE", f"WHERE tenant_id=? AND", 1), (tid,)
        return sql + " WHERE tenant_id=?", (tid,)