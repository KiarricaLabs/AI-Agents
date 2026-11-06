"""Phase 8 §15 — team progress ledger tests.

Covers the ProgressService + real HTTP endpoints:
- record writes a tenant/user-scoped progress row; list returns it;
- list is owner-scoped: foreign users/tenants see nothing;
- POST is human-gated (non-human -> 403); invalid status -> 400;
- the group-chat dispatch records completed progress when a thread is supplied.
"""
from __future__ import annotations

import unittest
import uuid

from fastapi.testclient import TestClient

from api.app import app  # noqa: E402
from core.auth import issue_token
from core.progress import ProgressService
from config.settings import DB_PATH
from storage.database import Database

DB = Database(path=DB_PATH)


class ProgressServiceTest(unittest.TestCase):
    def setUp(self):
        self.tenant = "fpr_" + uuid.uuid4().hex[:10]
        self.user = "fu_" + uuid.uuid4().hex[:8]
        self.svc = ProgressService(DB, self.tenant, self.user)

    def test_record_and_list(self):
        r = self.svc.record("thr-1", "strategist", "completed", "plan ready")
        self.assertEqual(r["status"], "completed")
        items = self.svc.list("thr-1")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["agent_id"], "strategist")

    def test_rejects_unknown_status(self):
        with self.assertRaises(ValueError):
            self.svc.record("thr-1", "strategist", "nonsense")

    def test_isolation(self):
        self.svc.record("thr-1", "strategist", "working", "x")
        other = ProgressService(DB, self.tenant, "fu_other")
        self.assertEqual(other.list("thr-1"), [])


class ProgressAPITest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def _h(self, user, tenant, role="user"):
        return {"x-token": issue_token(user, tenant, role)}

    def test_record_and_list_over_http(self):
        t, u = ("fp_%s" % uuid.uuid4().hex[:8], "fu_%s" % uuid.uuid4().hex[:8])
        r = self.client.post("/team/progress/record", json={
            "thread_id": "thr-a", "agent_id": "strategist", "status": "blocked", "detail": "needs input",
        }, headers=self._h(u, t))
        self.assertEqual(r.status_code, 200, r.text)
        lst = self.client.get("/team/progress?thread_id=thr-a", headers=self._h(u, t)).json()["items"]
        self.assertEqual(len(lst), 1)
        self.assertEqual(lst[0]["status"], "blocked")

    def test_foreign_user_sees_nothing(self):
        t, u1 = ("fp_%s" % uuid.uuid4().hex[:8], "fu_%s" % uuid.uuid4().hex[:8])
        u2 = "fu_%s" % uuid.uuid4().hex[:8]
        self.client.post("/team/progress/record", json={
            "thread_id": "thr-a", "agent_id": "strategist", "status": "working",
        }, headers=self._h(u1, t))
        lst = self.client.get("/team/progress?thread_id=thr-a", headers=self._h(u2, t)).json()["items"]
        self.assertEqual(lst, [])

    def test_non_human_403_on_record(self):
        t, u = ("fp_%s" % uuid.uuid4().hex[:8], "fu_%s" % uuid.uuid4().hex[:8])
        r = self.client.post("/team/progress/record", json={
            "thread_id": "thr-a", "agent_id": "strategist", "status": "working",
        }, headers=self._h(u, t, role="agent"))
        self.assertEqual(r.status_code, 403)

    def test_invalid_status_400(self):
        t, u = ("fp_%s" % uuid.uuid4().hex[:8], "fu_%s" % uuid.uuid4().hex[:8])
        r = self.client.post("/team/progress/record", json={
            "thread_id": "thr-a", "agent_id": "strategist", "status": "bogus",
        }, headers=self._h(u, t))
        self.assertEqual(r.status_code, 400)


class ExecutionProgressRouterTest(unittest.TestCase):
    """Phase 8 §15 — coordination step execution writes a durable progress row to
    the source thread's ledger (additive; NO dispatcher / agent / live model).

    Exercises the router helpers the execution endpoint relies on after a
    successful human step: resolve the execution back to its chat thread, then
    record a completed entry for the step's agent."""

    def setUp(self):
        self.tenant = "fxe_" + uuid.uuid4().hex[:10]
        self.user = "fu_" + uuid.uuid4().hex[:8]
        self.db = Database(path=DB_PATH, tenant_id=self.tenant)

    def test_execution_progress_resolves_thread_and_persists(self):
        from core.workspace import WorkspaceService, ProjectService, GoalService
        from core.team_goal import TeamGoalService
        from core.coordination_plan import CoordinationPlanService
        from core.coordination_execution import CoordinationExecutionService
        from api.routers.team_goals_execution import _thread_for_execution, _record_progress

        ws = WorkspaceService(self.db, self.tenant, self.user).create("W")
        pid = ProjectService(self.db, self.tenant, self.user).create(ws, "P")
        gid = GoalService(self.db, self.tenant, self.user).create(pid, "G", 0)
        svc = TeamGoalService(self.db, self.tenant, self.user)
        tg = svc.propose(
            "Launch", "workspace_architect", goal_id=gid, thread_id="thr-exec-1",
            steps=[{"seq": 1, "agent_id": "strategist",
                    "responsibility": "Strategy for the launch"}])["team_goal_id"]
        svc.approve(tg, self.user)
        plan = CoordinationPlanService(self.db, self.tenant, self.user).authorize(tg, self.user)
        run = CoordinationExecutionService(self.db, self.tenant, self.user).initiate(
            plan["plan_id"], self.user)
        exec_id = run["execution_id"]

        # The router hook never dispatches an agent; it only records progress.
        self.assertEqual(_thread_for_execution(self.tenant, self.user, exec_id), "thr-exec-1")
        _record_progress(self.tenant, self.user, exec_id, "strategist", "completed",
                         "step 1 completed — awaiting your review")

        items = ProgressService(self.db, self.tenant, self.user).list("thr-exec-1")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["agent_id"], "strategist")
        self.assertEqual(items[0]["status"], "completed")
        # owner-scoped: another user cannot see it
        other = ProgressService(self.db, self.tenant, "fu_other")
        self.assertEqual(other.list("thr-exec-1"), [])

    def test_autonomous_run_records_per_step_progress(self):
        from core.workspace import WorkspaceService, ProjectService, GoalService
        from core.team_goal import TeamGoalService
        from core.coordination_plan import CoordinationPlanService
        from core.coordination_execution import CoordinationExecutionService
        from api.routers.team_goals_execution import _record_run_progress

        ws = WorkspaceService(self.db, self.tenant, self.user).create("W")
        pid = ProjectService(self.db, self.tenant, self.user).create(ws, "P")
        gid = GoalService(self.db, self.tenant, self.user).create(pid, "G", 0)
        svc = TeamGoalService(self.db, self.tenant, self.user)
        tg = svc.propose(
            "Launch", "workspace_architect", goal_id=gid, thread_id="thr-run-1",
            steps=[{"seq": 1, "agent_id": "strategist", "responsibility": "Strategy"},
                   {"seq": 2, "agent_id": "strategist", "responsibility": "Prioritize",
                    "depends_on_seq": 1}])["team_goal_id"]
        svc.approve(tg, self.user)
        plan = CoordinationPlanService(self.db, self.tenant, self.user).authorize(tg, self.user)
        run = CoordinationExecutionService(self.db, self.tenant, self.user).initiate(
            plan["plan_id"], self.user)
        exec_id = run["execution_id"]

        # One completed ledger entry is recorded PER plan step from the frozen snapshot.
        _record_run_progress(self.tenant, self.user, exec_id)
        items = ProgressService(self.db, self.tenant, self.user).list("thr-run-1")
        self.assertEqual(len(items), 2)
        self.assertTrue(all(i["status"] == "completed" for i in items))
        self.assertTrue(all(i["agent_id"] == "strategist" for i in items))
        # detail identifies each step
        self.assertEqual(sorted(it["detail"] for it in items),
                         sorted(["step 1 completed (run) — awaiting your review",
                                 "step 2 completed (run) — awaiting your review"]))


if __name__ == "__main__":
    unittest.main()
