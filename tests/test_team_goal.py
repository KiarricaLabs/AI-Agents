"""T2-C-1 — TeamGoal schema + service (isolated DB, never production).

Covers:
- Schema & additive migrations (tables present, idempotent re-init).
- Propose / get / list / steps.
- Approval + lifecycle transitions (proposed -> approved -> ...).
- Invalid transitions rejected.
- Tenant / user isolation.
- Idempotent approval (re-approve returns same state, no duplicate).
- Approving a Team Goal does NOT start any episode or agent execution.
"""
from __future__ import annotations

import os
import tempfile
import unittest

from storage.database import Database
from core.team_goal import TeamGoalService
from core.workspace import (
    WorkspaceService, ProjectService, GoalService,
)


def _fresh_db() -> str:
    fd, p = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.remove(p)
    return p


def _scaffold(db, tenant="t1", user="u1"):
    ws = WorkspaceService(db, tenant, user).create("WS")
    pid = ProjectService(db, tenant, user).create(ws, "PROJ")
    gid = GoalService(db, tenant, user).create(pid, "GOAL", 0)
    return {"wid": ws, "pid": pid, "gid": gid}


def _steps():
    return [
        {"seq": 1, "agent_id": "strategist", "responsibility": "Strategy"},
        {"seq": 2, "agent_id": "communications", "responsibility": "Draft",
         "depends_on_seq": 1},
    ]


class TestSchema(unittest.TestCase):
    def setUp(self):
        self.path = _fresh_db()
        self.db = Database(path=self.path, tenant_id="t1")

    def tearDown(self):
        for s in ("", "-wal", "-shm"):
            try:
                os.remove(self.path + s)
            except OSError:
                pass

    def test_team_goal_tables_present(self):
        tabs = [r["name"] for r in self.db.query(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'team_goal%'")]
        self.assertIn("team_goals", tabs)
        self.assertIn("team_goal_steps", tabs)
        self.assertIn("team_goal_approvals", tabs)

    def test_reinit_idempotent(self):
        Database(path=self.path, tenant_id="t1")
        Database(path=self.path, tenant_id="t1")
        tabs = [r["name"] for r in self.db.query(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='team_goals'")]
        self.assertEqual(len(tabs), 1)


class TestProposeGetList(unittest.TestCase):
    def setUp(self):
        self.path = _fresh_db()
        self.db = Database(path=self.path, tenant_id="t1")
        svc = TeamGoalService(self.db, "t1", "u1")
        self.ids = _scaffold(self.db)
        self.tg_id = svc.propose(
            "Launch", "strategist", goal_id=self.ids["gid"],
            steps=_steps(), idempotency_key="tg1")["team_goal_id"]

    def tearDown(self):
        for s in ("", "-wal", "-shm"):
            try:
                os.remove(self.path + s)
            except OSError:
                pass

    def test_propose_creates_goal_and_steps(self):
        svc = TeamGoalService(self.db, "t1", "u1")
        tg = svc.get(self.tg_id)
        self.assertEqual(tg["status"], "proposed")
        self.assertEqual(tg["goal_id"], self.ids["gid"])
        self.assertEqual(len(tg["steps"]), 2)
        self.assertEqual(tg["steps"][0]["agent_id"], "strategist")
        self.assertEqual(tg["steps"][1]["depends_on_seq"], 1)

    def test_idempotent_propose(self):
        svc = TeamGoalService(self.db, "t1", "u1")
        r2 = svc.propose("Launch", "strategist", goal_id=self.ids["gid"],
                         steps=_steps(), idempotency_key="tg1")
        self.assertTrue(r2["reused"])
        self.assertEqual(r2["team_goal_id"], self.tg_id)
        self.assertEqual(len(svc.get(self.tg_id)["steps"]), 2)  # no duplicate steps

    def test_list_returns_goal(self):
        svc = TeamGoalService(self.db, "t1", "u1")
        lst = svc.list()
        self.assertEqual(len(lst), 1)
        self.assertEqual(lst[0]["title"], "Launch")

    def test_rejects_unknown_coordinator(self):
        svc = TeamGoalService(self.db, "t1", "u1")
        with self.assertRaises(ValueError):
            svc.propose("X", "ghost")

    def test_rejects_unknown_step_agent(self):
        svc = TeamGoalService(self.db, "t1", "u1")
        with self.assertRaises(ValueError):
            svc.propose("X", "strategist",
                        steps=[{"seq": 1, "agent_id": "ghost"}])

    def test_rejects_foreign_goal(self):
        svc = TeamGoalService(self.db, "t1", "u1")
        with self.assertRaises(ValueError):
            svc.propose("X", "strategist", goal_id="nope")


class TestLifecycle(unittest.TestCase):
    def setUp(self):
        self.path = _fresh_db()
        self.db = Database(path=self.path, tenant_id="t1")
        self.svc = TeamGoalService(self.db, "t1", "u1")
        self.ids = _scaffold(self.db)
        self.tg_id = self.svc.propose("Launch", "strategist",
                                      goal_id=self.ids["gid"], steps=_steps())["team_goal_id"]

    def tearDown(self):
        for s in ("", "-wal", "-shm"):
            try:
                os.remove(self.path + s)
            except OSError:
                pass

    def test_approve_then_advance(self):
        self.svc.approve(self.tg_id, "u1")
        self.assertEqual(self.svc.get(self.tg_id)["status"], "approved")
        self.svc.mark_in_progress(self.tg_id, "u1")
        self.assertEqual(self.svc.get(self.tg_id)["status"], "in_progress")
        self.svc.mark_ready_for_review(self.tg_id, "u1")
        self.assertEqual(self.svc.get(self.tg_id)["status"], "ready_for_review")
        self.svc.record_approval(self.tg_id, "u1", "approved")  # -> completed
        self.assertEqual(self.svc.get(self.tg_id)["status"], "completed")

    def test_revision_requested_not_terminal(self):
        self.svc.approve(self.tg_id, "u1")
        self.svc.mark_in_progress(self.tg_id, "u1")
        self.svc.record_approval(self.tg_id, "u1", "requested_changes")  # -> revision_requested
        self.assertEqual(self.svc.get(self.tg_id)["status"], "revision_requested")
        # can continue working from revision_requested -> in_progress
        self.svc.mark_in_progress(self.tg_id, "u1")
        self.assertEqual(self.svc.get(self.tg_id)["status"], "in_progress")

    def test_reject_is_terminal(self):
        self.svc.approve(self.tg_id, "u1")
        self.svc.reject(self.tg_id, "u1", reason="scope")
        self.assertEqual(self.svc.get(self.tg_id)["status"], "rejected")
        with self.assertRaises(Exception):
            self.svc.mark_in_progress(self.tg_id, "u1")

    def test_invalid_transition_rejected(self):
        # cannot jump directly to completed from proposed
        with self.assertRaises(Exception):
            self.svc.record_approval(self.tg_id, "u1", "approved")

    def test_idempotent_approve(self):
        self.svc.approve(self.tg_id, "u1")
        r2 = self.svc.approve(self.tg_id, "u1")
        self.assertEqual(r2["status"], "approved")
        self.assertTrue(r2["reused"])

    def test_approve_by_non_owner_denied(self):
        with self.assertRaises(PermissionError):
            self.svc.approve(self.tg_id, "other")

    def test_mark_in_progress_by_non_owner_denied(self):
        self.svc.approve(self.tg_id, "u1")
        with self.assertRaises(PermissionError):
            self.svc.mark_in_progress(self.tg_id, "other")
        # goal remains approved (not advanced by the unauthorized caller)
        self.assertEqual(self.svc.get(self.tg_id)["status"], "approved")

    def test_mark_ready_for_review_by_non_owner_denied(self):
        self.svc.approve(self.tg_id, "u1")
        self.svc.mark_in_progress(self.tg_id, "u1")
        with self.assertRaises(PermissionError):
            self.svc.mark_ready_for_review(self.tg_id, "other")
        self.assertEqual(self.svc.get(self.tg_id)["status"], "in_progress")

    def test_reject_rolls_back_if_approval_write_fails(self):
        self.svc.approve(self.tg_id, "u1")
        # Force the approval INSERT to fail after the status UPDATE: drop the
        # approval table so the transaction's second statement errors.
        self.db.execute("DROP TABLE team_goal_approvals")
        with self.assertRaises(Exception):
            self.svc.reject(self.tg_id, "u1", reason="scope")
        # The status UPDATE must have been rolled back with the failed INSERT.
        status = self.db.query(
            "SELECT status FROM team_goals WHERE id=?", (self.tg_id,))[0]["status"]
        self.assertEqual(status, "approved")

    def test_record_approval_rolls_back_if_approval_write_fails(self):
        self.svc.approve(self.tg_id, "u1")
        self.svc.mark_in_progress(self.tg_id, "u1")
        self.svc.mark_ready_for_review(self.tg_id, "u1")
        # Force approval INSERT failure -> status must not advance to 'completed'
        self.db.execute("DROP TABLE team_goal_approvals")
        with self.assertRaises(Exception):
            self.svc.record_approval(self.tg_id, "u1", "approved")
        status = self.db.query(
            "SELECT status FROM team_goals WHERE id=?", (self.tg_id,))[0]["status"]
        self.assertEqual(status, "ready_for_review")


class TestIsolation(unittest.TestCase):
    def setUp(self):
        self.path = _fresh_db()

    def tearDown(self):
        for s in ("", "-wal", "-shm"):
            try:
                os.remove(self.path + s)
            except OSError:
                pass

    def test_cross_tenant_not_visible(self):
        a = Database(path=self.path, tenant_id="tenantA")
        svcA = TeamGoalService(a, "tenantA", "uA")
        ids = _scaffold(a, "tenantA", "uA")
        tg = svcA.propose("X", "strategist", goal_id=ids["gid"])["team_goal_id"]
        b = Database(path=self.path, tenant_id="tenantB")
        svcB = TeamGoalService(b, "tenantB", "uB")
        self.assertIsNone(svcB.get(tg))
        self.assertEqual(svcB.list(), [])

    def test_cross_user_not_visible(self):
        a = Database(path=self.path, tenant_id="t1")
        svc1 = TeamGoalService(a, "t1", "u1")
        ids = _scaffold(a, "t1", "u1")
        tg = svc1.propose("X", "strategist", goal_id=ids["gid"])["team_goal_id"]
        svc2 = TeamGoalService(a, "t1", "u2")
        self.assertIsNone(svc2.get(tg))


class TestNoAutoExecution(unittest.TestCase):
    def setUp(self):
        self.path = _fresh_db()
        self.db = Database(path=self.path, tenant_id="t1")
        self.svc = TeamGoalService(self.db, "t1", "u1")
        self.ids = _scaffold(self.db)
        self.tg_id = self.svc.propose("Launch", "strategist",
                                      goal_id=self.ids["gid"], steps=_steps())["team_goal_id"]

    def tearDown(self):
        for s in ("", "-wal", "-shm"):
            try:
                os.remove(self.path + s)
            except OSError:
                pass

    def test_approve_creates_no_episodes(self):
        self.svc.approve(self.tg_id, "u1")
        self.assertEqual(self.svc.get(self.tg_id)["status"], "approved")
        # No episodes / no tool_executions auto-created.
        self.assertEqual(len(self.db.query("SELECT id FROM episodes")), 0)
        self.assertEqual(len(self.db.query("SELECT id FROM tool_executions")), 0)
        # Steps remain in 'planned' (not started).
        for st in self.svc.steps(self.tg_id):
            self.assertEqual(st["status"], "planned")


if __name__ == "__main__":
    unittest.main()
