"""Phase D tests: goal data model, proposals, approval, scoping, migration."""
import os
import sqlite3
import tempfile
import unittest

from storage.database import Database
from core.workspace import WorkspaceService, ProjectService, GoalService, AssignmentService
from core.policy import PolicyEngine
from core.memory import MemoryService
from core.memory_scope import ScopedMemory


def _allow(agent, resource, action="goal"):
    return PolicyEngine.from_dict({"rules": [
        {"subject": agent, "action": action, "resource": resource, "effect": "allow"},
    ]})


def _man(*perms):
    return {"name": "tutor", "permissions": list(perms)}


class TestGoalService(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.remove(self.path)
        self.db = Database(path=self.path, tenant_id="t1")
        self.ws = WorkspaceService(self.db, "t1", "u1")
        self.ps = ProjectService(self.db, "t1", "u1")
        self.gs = GoalService(self.db, "t1", "u1")
        self.ass = AssignmentService(self.db, "t1", "u1")

    def tearDown(self):
        os.remove(self.path)

    def _mk_goal(self, title="g1"):
        wid = self.ws.create("w1")
        pid = self.ps.create(wid, "p1")
        return self.gs.create(pid, title)

    def test_create_and_get(self):
        gid = self._mk_goal()
        g = self.gs.get(gid)
        self.assertEqual(g["title"], "g1")
        self.assertEqual(g["status"], "open")
        self.assertEqual(g["progress"], 0)
        self.assertEqual(g["version"], 0)

    def test_cross_tenant_invisible(self):
        gid = self._mk_goal()
        db2 = Database(path=self.path, tenant_id="t2")
        gs2 = GoalService(db2, "t2", "u1")
        self.assertIsNone(gs2.get(gid))

    def test_cross_user_invisible(self):
        gid = self._mk_goal()
        gs2 = GoalService(self.db, "t1", "u2")
        self.assertIsNone(gs2.get(gid))

    def test_secret_title_rejected(self):
        wid = self.ws.create("w1")
        pid = self.ps.create(wid, "p1")
        with self.assertRaises(ValueError):
            self.gs.create(pid, "password=hunter2")


class TestGoalProposals(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.remove(self.path)
        self.db = Database(path=self.path, tenant_id="t1")
        self.ws = WorkspaceService(self.db, "t1", "u1")
        self.ps = ProjectService(self.db, "t1", "u1")
        self.gs = GoalService(self.db, "t1", "u1")
        self.ass = AssignmentService(self.db, "t1", "u1")

    def tearDown(self):
        os.remove(self.path)

    def _mk_goal(self, title="g1"):
        wid = self.ws.create("w1")
        pid = self.ps.create(wid, "p1")
        return self.gs.create(pid, title)

    def _propose(self, gid, patch, agent="strategist", manifest=None, policy=None):
        return self.gs.propose_update(
            gid, agent, patch,
            manifest=manifest if manifest is not None else _man("goal:propose"),
            policy=policy if policy is not None else _allow(agent, "propose"))

    def test_propose_requires_manifest_permission(self):
        gid = self._mk_goal()
        with self.assertRaises(PermissionError):
            self.gs.propose_update(gid, "strategist", {"title": "x"},
                                   manifest=_man("memory:propose"), policy=_allow("strategist", "propose"))

    def test_propose_requires_policy(self):
        gid = self._mk_goal()
        with self.assertRaises(PermissionError):
            self.gs.propose_update(gid, "strategist", {"title": "x"},
                                   manifest=_man("goal:propose"),
                                   policy=PolicyEngine.from_dict({"rules": []}))

    def test_propose_and_approve_title(self):
        gid = self._mk_goal()
        pid = self._propose(gid, {"title": "renamed"})
        self.gs.approve_update(pid, "u1")
        self.assertEqual(self.gs.get(gid)["title"], "renamed")
        self.assertEqual(self.gs.get(gid)["version"], 1)

    def test_progress_and_status_transition(self):
        gid = self._mk_goal()
        p1 = self._propose(gid, {"status": "in_progress", "progress": 50})
        self.gs.approve_update(p1, "u1")
        g = self.gs.get(gid)
        self.assertEqual(g["status"], "in_progress")
        self.assertEqual(g["progress"], 50)
        p2 = self._propose(gid, {"status": "done", "progress": 100})
        self.gs.approve_update(p2, "u1")
        g = self.gs.get(gid)
        self.assertEqual(g["status"], "done")
        self.assertEqual(g["progress"], 100)
        self.assertEqual(g["version"], 2)

    def test_invalid_transition_rejected(self):
        gid = self._mk_goal()  # open
        p = self._propose(gid, {"status": "done", "progress": 100})  # open->done invalid
        with self.assertRaises(ValueError):
            self.gs.approve_update(p, "u1")
        # unchanged
        self.assertEqual(self.gs.get(gid)["status"], "open")

    def test_done_requires_progress_100(self):
        gid = self._mk_goal()
        p1 = self._propose(gid, {"status": "in_progress", "progress": 50})
        self.gs.approve_update(p1, "u1")
        p2 = self._propose(gid, {"status": "done", "progress": 50})
        with self.assertRaises(ValueError):
            self.gs.approve_update(p2, "u1")
        self.assertEqual(self.gs.get(gid)["status"], "in_progress")

    def test_progress_100_requires_done(self):
        gid = self._mk_goal()
        p1 = self._propose(gid, {"status": "in_progress", "progress": 0})
        self.gs.approve_update(p1, "u1")
        p2 = self._propose(gid, {"progress": 100})
        with self.assertRaises(ValueError):
            self.gs.approve_update(p2, "u1")
        self.assertEqual(self.gs.get(gid)["progress"], 0)

    def test_agent_cannot_approve(self):
        # Approval is user-only: the service only accepts a proposal for the matching
        # tenant/user; there is no agent-facing approve path.
        gid = self._mk_goal()
        pid = self._propose(gid, {"title": "x"})
        gs_other_user = GoalService(self.db, "t1", "u2")
        with self.assertRaises(ValueError):
            gs_other_user.approve_update(pid, "u2")

    def test_reject(self):
        gid = self._mk_goal()
        pid = self._propose(gid, {"title": "x"})
        self.gs.reject_update(pid, "u1")
        rows = self.gs.list_proposals(status="rejected")
        self.assertEqual(len(rows), 1)

    def test_stale_proposal_rejected(self):
        gid = self._mk_goal()
        p1 = self._propose(gid, {"title": "first"})
        p2 = self._propose(gid, {"title": "second"})
        self.gs.approve_update(p2, "u1")  # bumps version to 1
        with self.assertRaises(ValueError) as ctx:
            self.gs.approve_update(p1, "u1")  # base_version 0 != current 1
        self.assertIn("changed since proposal", str(ctx.exception))
        self.assertEqual(self.gs.get(gid)["title"], "second")
        rows = self.gs.list_proposals(status="stale")
        self.assertEqual(len(rows), 1)

    def test_expire_stale(self):
        gid = self._mk_goal()
        p1 = self._propose(gid, {"title": "first"})
        p2 = self._propose(gid, {"title": "second"})
        self.gs.approve_update(p2, "u1")
        n = self.gs.expire_stale()
        self.assertEqual(n, 1)
        self.assertEqual(self.gs.list_proposals(status="stale")[0]["id"], p1)

    def test_secret_rejected(self):
        gid = self._mk_goal()
        with self.assertRaises(ValueError):
            self._propose(gid, {"title": "api_key=xyz"})

        # reason with secret
        with self.assertRaises(ValueError):
            self.gs.propose_update(gid, "strategist", {"title": "ok"}, reason="my token is abc",
                                   manifest=_man("goal:propose"), policy=_allow("strategist", "propose"))

    def test_events_append_only(self):
        gid = self._mk_goal()
        p = self._propose(gid, {"status": "in_progress", "progress": 10})
        self.gs.approve_update(p, "u1")
        events = self.gs.list_events(gid)
        self.assertEqual(events[0]["status"], "created")
        self.assertIn("updated", [e["status"] for e in events])
        # created event still present (history not overwritten)
        self.assertEqual(events[0]["status"], "created")


class TestGoalScoping(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.remove(self.path)
        self.db = Database(path=self.path, tenant_id="t1")
        self.ms = MemoryService(db=self.db, tenant_id="t1")
        self.ws = WorkspaceService(self.db, "t1", "u1")
        self.ps = ProjectService(self.db, "t1", "u1")
        self.gs = GoalService(self.db, "t1", "u1")
        self.ass = AssignmentService(self.db, "t1", "u1")

    def tearDown(self):
        os.remove(self.path)

    def _mk_goal(self, title, agent=None):
        wid = self.ws.create("w1")
        pid = self.ps.create(wid, "p1")
        gid = self.gs.create(pid, title)
        if agent:
            self.ass.assign(gid, agent)
        return gid

    def test_assigned_goal_returned(self):
        self._mk_goal("learn algebra", agent="tutor")
        manifest = {"name": "tutor", "memory": {"read": ["goals"]}, "permissions": []}
        sm = ScopedMemory(self.ms, manifest, "tutor", "u1")
        facts = [f for f in sm.retrieve() if f["category"] == "goals"]
        self.assertEqual(len(facts), 1)
        self.assertIn("learn algebra", facts[0]["key"])

    def test_unassigned_goal_not_returned(self):
        self._mk_goal("personal goal")  # no assignment
        manifest = {"name": "tutor", "memory": {"read": ["goals"]}, "permissions": []}
        sm = ScopedMemory(self.ms, manifest, "tutor", "u1")
        facts = [f for f in sm.retrieve() if f["category"] == "goals"]
        self.assertEqual(facts, [])

    def test_goals_all_requires_manifest_and_policy(self):
        self._mk_goal("g1")  # unassigned (only reachable via goals:all)
        manifest_all = {"name": "strategist", "memory": {"read": ["goals"]}, "permissions": ["goals:all"]}
        # manifest permission present but no policy -> assigned-only -> empty
        sm1 = ScopedMemory(self.ms, manifest_all, "strategist", "u1")
        self.assertEqual([f for f in sm1.retrieve() if f["category"] == "goals"], [])
        # manifest + policy -> broad read works
        pol = _allow("strategist", "read_all")
        sm2 = ScopedMemory(self.ms, manifest_all, "strategist", "u1", policy=pol)
        self.assertEqual(len([f for f in sm2.retrieve() if f["category"] == "goals"]), 1)
        # policy present but no manifest permission -> still assigned-only
        manifest_no = {"name": "strategist", "memory": {"read": ["goals"]}, "permissions": []}
        sm3 = ScopedMemory(self.ms, manifest_no, "strategist", "u1", policy=pol)
        self.assertEqual([f for f in sm3.retrieve() if f["category"] == "goals"], [])


class TestGoalMigration(unittest.TestCase):
    def test_new_db_has_tables_and_columns(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.remove(path)
        db = Database(path=path, tenant_id="t1")
        cols = [r["name"] for r in db.query("PRAGMA table_info(goals)")]
        for c in ("progress", "updated_at", "version"):
            self.assertIn(c, cols)
        for t in ("goal_events", "goal_update_proposals"):
            rows = db.query("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (t,))
            self.assertTrue(rows, t)
        os.remove(path)

    def test_existing_goals_table_migrates_additively(self):
        old_goals = (
            "CREATE TABLE goals ("
            "id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, user_id TEXT NOT NULL,"
            "title TEXT NOT NULL, priority INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'open',"
            "created_at TEXT NOT NULL)"
        )
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.remove(path)
        conn = sqlite3.connect(path)
        conn.execute(old_goals)
        conn.execute(
            "INSERT INTO goals (id,tenant_id,project_id,user_id,title,priority,status,created_at) "
            "VALUES ('g1','t1','p1','u1','keep',5,'open','now')")
        conn.commit()
        conn.close()

        db = Database(path=path, tenant_id="t1")  # migration adds progress/updated_at/version
        cols = [r["name"] for r in db.query("PRAGMA table_info(goals)")]
        for c in ("progress", "updated_at", "version"):
            self.assertIn(c, cols)
        row = db.query("SELECT * FROM goals WHERE id='g1'")[0]
        self.assertEqual(row["title"], "keep")  # data preserved
        self.assertEqual(row["progress"], 0)
        # idempotent re-open
        Database(path=path, tenant_id="t1")
        os.remove(path)

    def test_rollback_drops_new_schema_preserves_data(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.remove(path)
        db = Database(path=path, tenant_id="t1")
        ws = WorkspaceService(db, "t1", "u1")
        ps = ProjectService(db, "t1", "u1")
        gs = GoalService(db, "t1", "u1")
        wid = ws.create("w1")
        pid = ps.create(wid, "p1")
        gid = gs.create(pid, "keep")

        # Rollback procedure: drop new tables, then the added goals columns.
        conn = sqlite3.connect(path)
        conn.execute("DROP TABLE IF EXISTS goal_events")
        conn.execute("DROP TABLE IF EXISTS goal_update_proposals")
        conn.execute("ALTER TABLE goals DROP COLUMN progress")
        conn.execute("ALTER TABLE goals DROP COLUMN updated_at")
        conn.execute("ALTER TABLE goals DROP COLUMN version")
        conn.commit()
        conn.close()

        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM goals WHERE id=?", (gid,)).fetchone()
        self.assertEqual(row["title"], "keep")  # original row intact
        self.assertIn("created_at", row.keys())
        for c in ("progress", "updated_at", "version"):
            self.assertNotIn(c, row.keys())
        conn.close()
        os.remove(path)


if __name__ == "__main__":
    unittest.main()
