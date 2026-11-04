"""Phase 4 — additive migration & backward-compatibility tests.

Verifies the UX-restructuring schema additions:
- assignments.title / description (nullable, no data loss)
- work_proposals.requested_changes / revision_of (revision != rejection)
- deliverable_versions.requested_changes / review_note

All additive + idempotent: re-opening a DB and re-running the migrations is a
no-op, and pre-existing rows are preserved.
"""
from __future__ import annotations

import os
import tempfile
import unittest

from storage.database import Database
from storage.migrations_phase4 import apply_phase4_columns


def _fresh(path):
    try:
        os.remove(path)
    except OSError:
        pass
    return path


class TestPhase4Migrations(unittest.TestCase):
    def _create_legacy(self, path):
        """Create a DB with the OLD schema (before Phase 4 columns), insert a row,
        then open it through Database (which applies Phase 4 columns)."""
        _fresh(path)
        con = __import__("sqlite3").connect(path)
        con.executescript("""
            CREATE TABLE tenants (id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE assignments (
                id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, goal_id TEXT NOT NULL,
                user_id TEXT NOT NULL, agent_id TEXT NOT NULL, task_id TEXT,
                priority INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'queued',
                created_at TEXT NOT NULL);
            CREATE TABLE work_proposals (
                id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, user_id TEXT NOT NULL,
                agent_id TEXT NOT NULL, thread_id TEXT, work_type TEXT NOT NULL,
                action TEXT NOT NULL DEFAULT 'create', target_id TEXT, workspace_id TEXT,
                project_id TEXT, goal_id TEXT, subject_id TEXT, payload_json TEXT NOT NULL,
                reason TEXT, status TEXT NOT NULL DEFAULT 'proposed', result_id TEXT,
                idempotency_key TEXT NOT NULL, created_at TEXT NOT NULL,
                UNIQUE (tenant_id, idempotency_key));
            CREATE TABLE deliverable_versions (
                id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, deliverable_id TEXT NOT NULL,
                version INTEGER NOT NULL, content TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'draft', created_at TEXT NOT NULL);
        """)
        con.execute(
            "INSERT INTO assignments (id,tenant_id,goal_id,user_id,agent_id,status,created_at) "
            "VALUES ('a1','t1','g1','u1','tutor','queued','now')")
        con.execute(
            "INSERT INTO work_proposals (id,tenant_id,user_id,agent_id,work_type,action,payload_json,idempotency_key,created_at) "
            "VALUES ('w1','t1','u1','tutor','goal','create','{}','k1','now')")
        con.execute(
            "INSERT INTO deliverable_versions (id,tenant_id,deliverable_id,version,content,status,created_at) "
            "VALUES ('d1','t1','dv1','1','hi','draft','now')")
        con.commit()
        con.close()

    def test_existing_db_gains_columns_without_data_loss(self):
        path = _fresh(tempfile.mktemp(suffix=".db"))
        self._create_legacy(path)
        db = Database(path=path, tenant_id="t1")  # opens: runs base SCHEMA + migrations

        a = db.query("SELECT * FROM assignments WHERE id='a1'")
        self.assertEqual(a[0]["agent_id"], "tutor")          # data preserved
        self.assertEqual(a[0]["status"], "queued")
        w = db.query("SELECT * FROM work_proposals WHERE id='w1'")
        self.assertEqual(w[0]["requested_changes"], 0)       # default flag
        d = db.query("SELECT * FROM deliverable_versions WHERE id='d1'")
        self.assertEqual(d[0]["requested_changes"], 0)

        # New columns present
        for t, cols in {
            "assignments": ["title", "description"],
            "work_proposals": ["requested_changes", "revision_of"],
            "deliverable_versions": ["requested_changes", "review_note", "revision_of"],
        }.items():
            present = [r["name"] for r in db.query(f"PRAGMA table_info({t})")]
            for c in cols:
                self.assertIn(c, present, f"{t} missing {c}")
        os.remove(path)

    def test_migrations_are_idempotent(self):
        path = _fresh(tempfile.mktemp(suffix=".db"))
        self._create_legacy(path)
        import sqlite3
        con = sqlite3.connect(path)
        apply_phase4_columns(con)
        apply_phase4_columns(con)  # second run is a no-op
        con.close()
        db = Database(path=path, tenant_id="t1")
        a = db.query("SELECT * FROM assignments WHERE id='a1'")
        self.assertEqual(len(a), 1)
        os.remove(path)

    def test_write_title_and_requested_changes(self):
        path = _fresh(tempfile.mkstemp(suffix=".db")[1])
        db = Database(path=path, tenant_id="t1")
        # assignments may now carry a title
        db.execute(
            "INSERT INTO assignments (id,tenant_id,goal_id,user_id,agent_id,title,description,status,created_at) "
            "VALUES ('a1','t1','g1','u1','tutor','Write launch plan','A short doc','queued','now')")
        row = db.query("SELECT title,description FROM assignments WHERE id='a1'")[0]
        self.assertEqual(row["title"], "Write launch plan")
        self.assertEqual(row["description"], "A short doc")
        # work_proposals may flag requested_changes
        db.execute(
            "INSERT INTO work_proposals (id,tenant_id,user_id,agent_id,work_type,action,payload_json,idempotency_key,requested_changes,created_at) "
            "VALUES ('w1','t1','u1','tutor','assignment','create','{}','k1',1,'now')")
        self.assertEqual(db.query("SELECT requested_changes FROM work_proposals WHERE id='w1'")[0]["requested_changes"], 1)
        os.remove(path)


if __name__ == "__main__":
    unittest.main()
