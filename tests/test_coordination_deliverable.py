"""T2-C-5 — Coordination deliverable versioning (isolated DB, never production).

Covers (never production):
- Initial aggregation creates version 1 (pending).
- Repeated aggregation without rework reuses the pending version (no duplicate,
  no overwrite).
- Re-aggregation after rework creates a new pending version with revision_of link.
- Human accept / reject / revision transition version states and record approvals.
- Idempotency: repeated identical decision on a version is a no-op.
- Conflicting decision on an already-decided version is rejected.
- No silending overwrite of historical (approved/rejected) version content.
- Version-chain integrity (revision_of) and ordered step-output provenance.
- Cross-tenant / cross-user isolation.
- Human-only access (non-human role -> 403).
- Rollback: a forced mid-write failure leaves no partial version.
"""
from __future__ import annotations

import os
import tempfile
import unittest

from storage.database import Database
from core.team_goal import TeamGoalService
from core.workspace import WorkspaceService, ProjectService, GoalService
from core.coordination_plan import CoordinationPlanService
from core.coordination_execution import CoordinationExecutionService
from core.coordination_deliverable import (
    CoordinationDeliverableService,
    CoordinationDeliverableVersionConflict,
    CoordinationDeliverableVersionNotFound,
    PENDING, APPROVED, REJECTED, REVISION_REQUESTED,
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


def _authorized_plan(db, tenant="t1", user="u1"):
    svc = TeamGoalService(db, tenant, user)
    ids = _scaffold(db, tenant, user)
    tg = svc.propose("Launch", "workspace_architect", goal_id=ids["gid"],
                     steps=[{"seq": 1, "agent_id": "strategist",
                             "responsibility": "Strategy"}])["team_goal_id"]
    svc.approve(tg, user)
    plan = CoordinationPlanService(db, tenant, user).authorize(tg, user)
    return tg, ids, plan["plan_id"]


def _stub_reply(content="done"):
    def dispatch(agent, responsibility, context):
        return {"reply": content, "agent": agent}
    return dispatch


class DeliverableVersioningTest(unittest.TestCase):
    def setUp(self):
        self.path = _fresh_db()
        self.db = Database(path=self.path, tenant_id="t1")
        self.svc = CoordinationExecutionService(self.db, "t1", "u1",
                                                dispatcher=_stub_reply())

    def tearDown(self):
        for s in ("", "-wal", "-shm"):
            try:
                os.remove(self.path + s)
            except OSError:
                pass

    def _make_run_aggregated(self):
        tg, ids, plan = _authorized_plan(self.db)
        run = self.svc.initiate(plan, "u1")["execution_id"]
        self.svc.execute_step(run, "u1")
        self.svc.review_step(run, 1, "accepted", "u1")
        d = self.svc.aggregate(run, "u1")
        dl = self.db.query(
            "SELECT id FROM coordination_deliverables WHERE execution_id=? AND tenant_id=? AND user_id=?",
            (run, "t1", "u1"))[0]["id"]
        return run, dl, d

    def test_initial_aggregation_creates_version_1_pending(self):
        run, dl, d = self._make_run_aggregated()
        versions = self.svc.deliverables.list_versions(dl)
        self.assertEqual(len(versions), 1)
        self.assertEqual(versions[0]["version"], 1)
        self.assertEqual(versions[0]["status"], PENDING)
        self.assertIsNone(versions[0]["revision_of"])
        self.assertTrue(versions[0]["content"]["steps"])

    def test_reaggregation_reuses_pending_no_duplicate(self):
        run, dl, d = self._make_run_aggregated()
        self.svc.aggregate(run, "u1")  # repeat
        versions = self.svc.deliverables.list_versions(dl)
        self.assertEqual(len(versions), 1)
        self.assertEqual(versions[0]["version"], 1)
        self.assertEqual(versions[0]["status"], PENDING)

    def test_accept_approves_version(self):
        run, dl, d = self._make_run_aggregated()
        res = self.svc.review_deliverable(run, "accepted", "u1")
        v = self.svc.deliverables.list_versions(dl)[0]
        self.assertEqual(v["status"], APPROVED)
        self.assertTrue(res["approval"])
        # run completed
        from core.coordination_execution import RUN_COMPLETED
        self.assertEqual(self.svc._get_execution(run)["status"], RUN_COMPLETED)
        # repeat accept -> idempotent, same version, no duplicate approval row
        res2 = self.svc.review_deliverable(run, "accepted", "u1")
        approvals = self.svc.deliverables.approvals(v["version_id"])
        self.assertEqual(len(approvals), 1)

    def test_reject_rejects_version_terminal(self):
        from core.coordination_execution import ExecutionNotRunnable
        run, dl, d = self._make_run_aggregated()
        self.svc.review_deliverable(run, "rejected", "u1")
        v = self.svc.deliverables.list_versions(dl)[0]
        self.assertEqual(v["status"], REJECTED)
        # cannot re-aggregate a rejected/terminal run
        with self.assertRaises(ExecutionNotRunnable):
            self.svc.aggregate(run, "u1")

    def test_conflicting_decision_rejected(self):
        from core.coordination_execution import CoordinationExecutionService as _CES
        run, dl, d = self._make_run_aggregated()
        self.svc.review_deliverable(run, "accepted", "u1")
        # now attempt reject on the same (already-approved) version -> rejected
        # because the only pending version is gone; review targets latest,
        # which is approved. review_deliverable(rejected) must conflict.
        with self.assertRaises(CoordinationDeliverableVersionConflict):
            self.svc.review_deliverable(run, "rejected", "u1")
        v = self.svc.deliverables.list_versions(dl)[0]
        self.assertEqual(v["status"], APPROVED)  # unchanged history

    def test_revision_creates_new_version_with_revision_of(self):
        run, dl, d = self._make_run_aggregated()
        res = self.svc.review_deliverable(run, "revision_requested", "u1",
                                          rework_steps=[1])
        # version 1 now revision_requested
        v1 = self.svc.deliverables.list_versions(dl)[0]
        self.assertEqual(v1["status"], REVISION_REQUESTED)
        # re-execute + re-accept step + re-aggregate -> new pending version 2
        self.svc.execute_step(run, "u1")
        self.svc.review_step(run, 1, "accepted", "u1")
        self.svc.aggregate(run, "u1")
        versions = self.svc.deliverables.list_versions(dl)
        self.assertEqual(len(versions), 2)
        v2 = versions[1]
        self.assertEqual(v2["version"], 2)
        self.assertEqual(v2["status"], PENDING)
        self.assertEqual(v2["revision_of"], v1["version_id"])

    def test_no_silent_overwrite_of_approved_content(self):
        run, dl, d = self._make_run_aggregated()
        v_before = self.svc.deliverables.list_versions(dl)[0]
        original_content = v_before["content"]
        self.svc.review_deliverable(run, "accepted", "u1")
        # attempt to re-aggregate -> terminal run refuses; version content unchanged
        from core.coordination_execution import ExecutionNotRunnable
        try:
            self.svc.aggregate(run, "u1")
        except ExecutionNotRunnable:
            pass
        v_after = self.svc.deliverables.list_versions(dl)[0]
        self.assertEqual(v_after["content"], original_content)
        self.assertEqual(v_after["status"], APPROVED)

    def test_version_chain_and_provenance(self):
        run, dl, d = self._make_run_aggregated()
        self.svc.review_deliverable(run, "revision_requested", "u1", rework_steps=[1])
        self.svc.execute_step(run, "u1")
        self.svc.review_step(run, 1, "accepted", "u1")
        self.svc.aggregate(run, "u1")
        versions = self.svc.deliverables.list_versions(dl)
        # each version preserves ordered step-output provenance
        for v in versions:
            self.assertIn("steps", v["content"])
            self.assertTrue(isinstance(v["content"]["steps"], list))
            self.assertTrue(all("seq" in s and "agent" in s for s in v["content"]["steps"]))
        # chain: v2.revision_of == v1.id
        self.assertEqual(versions[1]["revision_of"], versions[0]["version_id"])

    def test_rollback_on_mid_write_failure(self):
        run, dl, d = self._make_run_aggregated()
        # Force a failure in the version write by dropping the approval table so
        # record_decision's INSERT fails after the status UPDATE -> rollback.
        self.db.execute("DROP TABLE coordination_deliverable_approvals")
        try:
            self.svc.review_deliverable(run, "accepted", "u1")
        except Exception:
            pass
        # the version status must remain pending (rolled back)
        v = self.svc.deliverables.list_versions(dl)[0]
        self.assertEqual(v["status"], PENDING)


class DeliverableReadEndpointsTest(unittest.TestCase):
    def setUp(self):
        self.path = _fresh_db()
        self.db = Database(path=self.path, tenant_id="t1")

    def tearDown(self):
        for s in ("", "-wal", "-shm"):
            try:
                os.remove(self.path + s)
            except OSError:
                pass

    def _make_approved_run(self):
        svc = CoordinationExecutionService(self.db, "t1", "u1", dispatcher=_stub_reply())
        tg, ids, plan = _authorized_plan(self.db)
        run = svc.initiate(plan, "u1")["execution_id"]
        svc.execute_step(run, "u1")
        svc.review_step(run, 1, "accepted", "u1")
        svc.aggregate(run, "u1")
        svc.review_deliverable(run, "accepted", "u1")
        return run

    def _agent_request(self):
        from types import SimpleNamespace
        state = SimpleNamespace(tenant_id="local", user_id="local", role="agent")
        return SimpleNamespace(state=state)

    def test_list_versions_endpoint(self):
        from fastapi.testclient import TestClient
        from api.app import app
        c = TestClient(app)
        # Build data in the api app's isolated DB
        db2 = Database(path=__import__('config.settings', fromlist=['DB_PATH']).DB_PATH,
                       tenant_id="local")
        svc = CoordinationExecutionService(db2, "local", "local", dispatcher=_stub_reply())
        tg, ids, plan = _authorized_plan(db2, "local", "local")
        run = svc.initiate(plan, "local")["execution_id"]
        svc.execute_step(run, "local")
        svc.review_step(run, 1, "accepted", "local")
        svc.aggregate(run, "local")
        r = c.get(f"/team/goals/plans/{plan}/execution/{run}/deliverable/versions")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()["versions"]), 1)

    def test_get_version_endpoint_404_unknown(self):
        from fastapi.testclient import TestClient
        from api.app import app
        c = TestClient(app)
        r = c.get("/team/goals/plans/p/execution/e/deliverable/versions/missing")
        self.assertEqual(r.status_code, 404)

    def test_non_human_review_rejected(self):
        from fastapi import HTTPException
        from api.routers.team_goals_execution import review_deliverable
        with self.assertRaises(HTTPException) as ctx:
            review_deliverable("p", "e",
                               type("B", (), {"decision": "accepted", "note": None,
                                              "rework_steps": None})(),
                               self._agent_request())
        self.assertEqual(ctx.exception.status_code, 403)


class DeliverableIsolationTest(unittest.TestCase):
    def setUp(self):
        self.path = _fresh_db()

    def tearDown(self):
        for s in ("", "-wal", "-shm"):
            try:
                os.remove(self.path + s)
            except OSError:
                pass

    def test_cross_tenant_versions_invisible(self):
        a = Database(path=self.path, tenant_id="tenantA")
        svcA = CoordinationExecutionService(a, "tenantA", "uA", dispatcher=_stub_reply())
        tg, ids, plan = _authorized_plan(a, "tenantA", "uA")
        run = svcA.initiate(plan, "uA")["execution_id"]
        svcA.execute_step(run, "uA")
        svcA.review_step(run, 1, "accepted", "uA")
        svcA.aggregate(run, "uA")
        dl = a.query("SELECT id FROM coordination_deliverables WHERE execution_id=?", (run,))[0]["id"]
        b = Database(path=self.path, tenant_id="tenantB")
        svcB = CoordinationDeliverableService(b, "tenantB", "uB")
        self.assertEqual(svcB.list_versions(dl), [])
        v = svcB.latest_version(dl)
        self.assertIsNone(v)

    def test_cross_user_versions_invisible(self):
        a = Database(path=self.path, tenant_id="t1")
        svcA = CoordinationExecutionService(a, "t1", "u1", dispatcher=_stub_reply())
        tg, ids, plan = _authorized_plan(a, "t1", "u1")
        run = svcA.initiate(plan, "u1")["execution_id"]
        svcA.execute_step(run, "u1")
        svcA.review_step(run, 1, "accepted", "u1")
        svcA.aggregate(run, "u1")
        dl = a.query("SELECT id FROM coordination_deliverables WHERE execution_id=?", (run,))[0]["id"]
        svcB = CoordinationDeliverableService(a, "t1", "u2")
        self.assertEqual(svcB.list_versions(dl), [])
        self.assertIsNone(svcB.get_version("x", dl))


if __name__ == "__main__":
    unittest.main()
