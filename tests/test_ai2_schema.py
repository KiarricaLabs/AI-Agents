"""AI Team 2.0 (T2-A) — schema + migration idempotency (isolated DB).

Covers:
- Fresh DB: all new columns/tables created correctly.
- thread_type defaults to 'agent' (existing threads unchanged).
- Repeated init (Database constructed twice on same file) is idempotent.
- Existing DB with prior data: guarded ADD COLUMN is a no-op; no data loss.
- Milestones + dependencies rows writable.
- goals.milestone_id / assignments.milestone_id populated and linked.
"""
from __future__ import annotations

import os
import tempfile
import unittest

from storage.database import Database
from core.workspace import WorkspaceService, ProjectService, GoalService, AssignmentService


def _fresh():
    fd, p = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.remove(p)
    return p


class SchemaTest(unittest.TestCase):
    def setUp(self):
        self.path = _fresh()
        self.db = Database(path=self.path, tenant_id="t1")

    def tearDown(self):
        for s in ("", "-wal", "-shm"):
            try:
                os.remove(self.path + s)
            except OSError:
                pass

    def _cols(self, table):
        return [r["name"] for r in self.db.query(f"PRAGMA table_info({table})")]

    def test_group_thread_columns_present(self):
        cols = self._cols("conversation_threads")
        self.assertIn("thread_type", cols)
        self.assertIn("workspace_id", cols)

    def test_milestone_columns_present(self):
        self.assertIn("milestone_id", self._cols("goals"))
        self.assertIn("milestone_id", self._cols("assignments"))

    def test_new_tables_present(self):
        tabs = [r["name"] for r in self.db.query(
            "SELECT name FROM sqlite_master WHERE type='table'")]
        for t in ("conversation_participants", "milestones", "dependencies"):
            self.assertIn(t, tabs)

    def test_thread_type_defaults_agent(self):
        # Existing-style single-agent thread gets default 'agent' and renders as before.
        from core.memory import MemoryService
        MemoryService(db=self.db, tenant_id="t1").get_or_create_thread(
            "u1", "tid", "strategist", "hello")
        row = self.db.query(
            "SELECT thread_type FROM conversation_threads WHERE thread_id='tid' AND tenant_id='t1'")[0]
        self.assertEqual(row["thread_type"], "agent")

    def test_idempotent_reinit_no_duplicate_or_error(self):
        # Reconstruct Database on the same path: guarded ALTER no-ops, tables exist.
        db2 = Database(path=self.path, tenant_id="t1")
        db2.query("SELECT 1 FROM conversation_participants LIMIT 1")
        self.assertIn("thread_type", self._cols("conversation_threads"))

    def test_existing_data_preserved_on_reinit(self):
        # seed a workspace+project, re-init DB, confirm rows intact.
        ws = WorkspaceService(self.db, "t1", "u1").create("Existing")
        pid = ProjectService(self.db, "t1", "u1").create(ws, "Keep Me")
        db2 = Database(path=self.path, tenant_id="t1")
        proj = db2.query("SELECT name FROM projects WHERE id=?", (pid,))
        self.assertEqual(proj[0]["name"], "Keep Me")

    def test_milestone_and_milestone_id_population(self):
        ws = WorkspaceService(self.db, "t1", "u1").create("WS")
        pid = ProjectService(self.db, "t1", "u1").create(ws, "Proj")
        # create milestone
        mid = "mil-1"
        self.db.execute(
            "INSERT INTO milestones "
            "(id,tenant_id,user_id,project_id,title,ord,status,deadline,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (mid, "t1", "u1", pid, "M1", 1, "planned", None, "now", "now"))
        # goal + assignment linked to the milestone
        gid = GoalService(self.db, "t1", "u1").create(pid, "Goal")
        self.db.execute("UPDATE goals SET milestone_id=? WHERE id=? AND tenant_id=?",
                        (mid, gid, "t1"))
        aid = AssignmentService(self.db, "t1", "u1").assign(gid, "communications", 0)
        self.db.execute("UPDATE assignments SET milestone_id=? WHERE id=? AND tenant_id=?",
                        (mid, aid, "t1"))
        g = self.db.query("SELECT milestone_id FROM goals WHERE id=?", (gid,))[0]
        a = self.db.query("SELECT milestone_id FROM assignments WHERE id=?", (aid,))[0]
        self.assertEqual(g["milestone_id"], mid)
        self.assertEqual(a["milestone_id"], mid)

    def test_dependencies_writable(self):
        self.db.execute(
            "INSERT INTO dependencies "
            "(id,tenant_id,user_id,from_type,from_id,to_type,to_id,created_at) "
            "VALUES ('d1','t1','u1','task','t1','task','t2','now')")
        rows = self.db.query("SELECT from_id, to_id FROM dependencies WHERE id='d1' AND tenant_id='t1'")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["to_id"], "t2")


if __name__ == "__main__":
    unittest.main()
