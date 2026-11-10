"""V1.6.10.0 — agent_run_history additive migration tests."""
import os
import tempfile
import unittest

from storage.database import Database


def _fresh_path():
    fd, p = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.remove(p)
    return p


def _table_names(db):
    return {r["name"] for r in db.query(
        "SELECT name FROM sqlite_master WHERE type='table'")}


def _columns(db, table):
    return [dict(r) for r in db.query(f"PRAGMA table_info({table})")]


def _index_names(db, table):
    return {r["name"] for r in db.query(
        f"PRAGMA index_list({table})")}


class AgentRunHistoryMigrationTests(unittest.TestCase):
    def test_table_created_with_columns(self):
        path = _fresh_path()
        db = Database(path=path, tenant_id="t1")
        try:
            self.assertIn("agent_run_history", _table_names(db))
            cols = {c["name"]: c for c in _columns(db, "agent_run_history")}
            for name in ("id", "tenant_id", "user_id", "agent_id", "thread_id",
                         "status", "task_summary", "error_category",
                         "created_at", "finished_at"):
                self.assertIn(name, cols)
            # NOT NULL constraints
            for name in ("tenant_id", "user_id", "agent_id", "status", "created_at"):
                self.assertEqual(cols[name]["notnull"], 1, name)
            # nullable
            for name in ("thread_id", "task_summary", "error_category", "finished_at"):
                self.assertEqual(cols[name]["notnull"], 0, name)
            # primary key
            self.assertEqual(cols["id"]["pk"], 1)
        finally:
            db.close() if hasattr(db, "close") else None

    def test_status_check_constraint(self):
        path = _fresh_path()
        db = Database(path=path, tenant_id="t1")
        try:
            with self.assertRaises(Exception):
                db.execute(
                    "INSERT INTO agent_run_history (id, tenant_id, user_id, agent_id, status, created_at) "
                    "VALUES (?,?,?,?,?,?)",
                    ("x", "t1", "u1", "tutor", "queued", "2026-01-01T00:00:00+00:00"),
                )
        finally:
            pass

    def test_indexes_created(self):
        path = _fresh_path()
        db = Database(path=path, tenant_id="t1")
        try:
            idx = _index_names(db, "agent_run_history")
            self.assertIn("idx_agent_run_history_tenant_user_created", idx)
            self.assertIn("idx_agent_run_history_agent_status", idx)
        finally:
            pass

    def test_idempotent_reinit(self):
        path = _fresh_path()
        db1 = Database(path=path, tenant_id="t1")
        db1 = None
        db2 = Database(path=path, tenant_id="t1")
        self.assertIn("agent_run_history", _table_names(db2))

    def test_agent_runs_unaffected(self):
        path = _fresh_path()
        db = Database(path=path, tenant_id="t1")
        self.assertIn("agent_runs", _table_names(db))


if __name__ == "__main__":
    unittest.main()
