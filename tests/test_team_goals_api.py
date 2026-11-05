"""T2-C-3 — CoordinationPlanService + TeamGoal/coordination-plan API.

Covers (isolated DB, never production):
- Transient plan review (never persists).
- Successful authorization persists an exact, frozen snapshot (coordinator,
  ordered agent assignments, dependencies, capability/delegation results,
  effective permissions, expected deliverable).
- Idempotent re-authorization returns the existing authorized plan.
- Invalid / ineligible goals rejected.
- FAIL-CLOSED delegation guard: a step whose delegation grants ZERO effective
  permissions is refused and nothing is persisted.
- Atomic rollback after a forced mid-persistence failure.
- Authorization never starts episodes/tool executions/writes delegation logs or
  mutates the TeamGoal status.
- Owner/tenant isolation and human-only authorization.
- TeamGoal approve/reject endpoints.
"""
from __future__ import annotations

import os
import tempfile
import unittest
import uuid

from storage.database import Database
from core.team_goal import TeamGoalService
from core.workspace import WorkspaceService, ProjectService, GoalService
from core.coordination_plan import (
    CoordinationPlanService,
    CoordinationPlanNotFound,
    CoordinationPlanInvalid,
    CoordinationPlanPermissionError,
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


def _valid_goal(db, tenant="t1", user="u1"):
    """Create + approve a TeamGoal that yields a valid plan: coordinator is the
    workspace_architect and the step hands off to the strategist (the only
    declared delegation)."""
    svc = TeamGoalService(db, tenant, user)
    ids = _scaffold(db, tenant, user)
    tg = svc.propose(
        "Launch", "workspace_architect", goal_id=ids["gid"],
        steps=[{"seq": 1, "agent_id": "strategist",
                "responsibility": "Strategy for the launch"}])["team_goal_id"]
    svc.approve(tg, user)
    return tg, ids


class _NoPermissionsDelegation:
    """A DelegationService stand-in that reports 'declared' delegation with an
    EMPTY effective permission intersection — the latent concern that must be
    fail-closed at the authorization gate."""
    def can_delegate(self, from_agent, to_agent, depth=0):
        return True, set()


class CoordinationPlanServiceTest(unittest.TestCase):
    def setUp(self):
        self.path = _fresh_db()
        self.db = Database(path=self.path, tenant_id="t1")
        self.svc = CoordinationPlanService(self.db, "t1", "u1")

    def tearDown(self):
        for s in ("", "-wal", "-shm"):
            try:
                os.remove(self.path + s)
            except OSError:
                pass

    def test_review_is_transient_and_valid(self):
        tg, _ = _valid_goal(self.db)
        plan = self.svc.review(tg)
        self.assertTrue(plan["plan_valid"])
        self.assertTrue(plan["transient"])
        self.assertEqual(plan["coordinator"], "workspace_architect")
        self.assertEqual(len(plan["steps"]), 1)
        self.assertTrue(plan["steps"][0]["valid"])
        # nothing persisted by review
        self.assertEqual(len(self.db.query("SELECT id FROM coordination_plans")), 0)

    def test_review_unknown_goal_raises_not_found(self):
        with self.assertRaises(CoordinationPlanNotFound):
            self.svc.review("does-not-exist")

    def test_review_proposed_goal_raises_invalid(self):
        svc = TeamGoalService(self.db, "t1", "u1")
        ids = _scaffold(self.db)
        tg = svc.propose("X", "workspace_architect", goal_id=ids["gid"],
                         steps=[{"seq": 1, "agent_id": "strategist",
                                 "responsibility": "strategy"}])["team_goal_id"]
        with self.assertRaises(CoordinationPlanInvalid):
            self.svc.review(tg)

    def test_authorize_persists_exact_snapshot(self):
        tg, ids = _valid_goal(self.db)
        result = self.svc.authorize(tg, "u1")
        self.assertFalse(result["reused"])
        self.assertEqual(result["status"], "authorized")
        self.assertEqual(result["coordinator"], "workspace_architect")
        self.assertEqual(result["expected_deliverable"],
                         TeamGoalService(self.db, "t1", "u1").get(tg).get("expected_deliverable"))
        self.assertEqual(result["goal_id"], ids["gid"])
        self.assertEqual(len(result["steps"]), 1)
        step = result["steps"][0]
        self.assertEqual(step["agent_id"], "strategist")
        self.assertEqual(step["seq"], 1)
        self.assertTrue(step["capability_ok"])
        self.assertTrue(step["delegation_ok"])
        self.assertTrue(step["valid"])
        # effective permissions persisted (non-empty intersection)
        self.assertTrue(isinstance(step["effective_permissions"], list))
        self.assertTrue(len(step["effective_permissions"]) > 0)
        # exactly one plan row + one step row
        self.assertEqual(len(self.db.query("SELECT id FROM coordination_plans")), 1)
        self.assertEqual(len(self.db.query("SELECT id FROM coordination_plan_steps")), 1)

    def test_authorize_idempotent_no_duplicate_steps(self):
        tg, _ = _valid_goal(self.db)
        first = self.svc.authorize(tg, "u1")
        second = self.svc.authorize(tg, "u1")
        self.assertTrue(second["reused"])
        self.assertEqual(second["plan_id"], first["plan_id"])
        self.assertEqual(len(self.db.query("SELECT id FROM coordination_plans")), 1)
        self.assertEqual(len(self.db.query("SELECT id FROM coordination_plan_steps")), 1)

    def test_authorize_unknown_goal_not_found(self):
        with self.assertRaises(CoordinationPlanNotFound):
            self.svc.authorize("missing", "u1")

    def test_authorize_non_owner_denied(self):
        tg, _ = _valid_goal(self.db)
        with self.assertRaises(CoordinationPlanPermissionError):
            self.svc.authorize(tg, "someone-else")

    def test_authorize_not_approved_goal_rejected(self):
        svc = TeamGoalService(self.db, "t1", "u1")
        ids = _scaffold(self.db)
        tg = svc.propose("X", "workspace_architect", goal_id=ids["gid"],
                         steps=[{"seq": 1, "agent_id": "strategist",
                                 "responsibility": "strategy"}])["team_goal_id"]
        # still 'proposed' — not approved
        with self.assertRaises(CoordinationPlanInvalid):
            self.svc.authorize(tg, "u1")

    def test_authorize_rejected_goal_rejected(self):
        svc = TeamGoalService(self.db, "t1", "u1")
        ids = _scaffold(self.db)
        tg = svc.propose("X", "workspace_architect", goal_id=ids["gid"],
                         steps=[{"seq": 1, "agent_id": "strategist",
                                 "responsibility": "strategy"}])["team_goal_id"]
        svc.approve(tg, "u1")
        svc.reject(tg, "u1", reason="no")
        with self.assertRaises(CoordinationPlanInvalid):
            self.svc.authorize(tg, "u1")

    def test_authorize_zero_effective_permissions_refused(self):
        """Fail-closed: a delegation whose effective permission intersection is
        empty must be refused and nothing persisted."""
        tg, _ = _valid_goal(self.db)
        # Substitute a delegation service that returns declared-but-empty perms.
        self.svc.delegation = _NoPermissionsDelegation()
        with self.assertRaises(CoordinationPlanInvalid) as ctx:
            self.svc.authorize(tg, "u1")
        self.assertIn("zero effective permissions", str(ctx.exception))
        # nothing was persisted
        self.assertEqual(len(self.db.query("SELECT id FROM coordination_plans")), 0)
        self.assertEqual(len(self.db.query("SELECT id FROM coordination_plan_steps")), 0)

    def test_authorize_concurrent_duplicate_reuses_existing(self):
        """Duplicate-authorization path (read missed the existing row): the
        INSERT OR IGNORE is ignored, the existing authorized plan is re-fetched
        (verified tenant/user/goal/status), returned with reused=True, and no
        duplicate plan/steps are created or snapshot mutated."""
        tg, _ = _valid_goal(self.db)
        first = self.svc.authorize(tg, "u1")
        self.assertFalse(first["reused"])

        # Simulate the check-then-insert race: the idempotency read misses the
        # row (returns None) while the authorized plan already exists in DB.
        self.svc._existing_authorized = lambda _goal_id: None
        second = self.svc.authorize(tg, "u1")

        self.assertTrue(second["reused"])
        # same snapshot returned unchanged
        self.assertEqual(second["plan_id"], first["plan_id"])
        self.assertEqual(second["coordinator"], first["coordinator"])
        self.assertEqual(second["steps"], first["steps"])
        # only one plan and one set of steps
        self.assertEqual(len(self.db.query("SELECT id FROM coordination_plans")), 1)
        self.assertEqual(len(self.db.query("SELECT id FROM coordination_plan_steps")), 1)

    def test_authorize_does_not_mutate_goal_or_execute(self):
        tg, _ = _valid_goal(self.db)
        goal = TeamGoalService(self.db, "t1", "u1").get(tg)
        self.assertEqual(goal["status"], "approved")
        before = {
            "episodes": len(self.db.query("SELECT id FROM episodes")),
            "tool_exec": len(self.db.query("SELECT id FROM tool_executions")),
            "deleg_log": len(self.db.query("SELECT id FROM delegation_log")),
        }
        self.svc.authorize(tg, "u1")
        after_goal = TeamGoalService(self.db, "t1", "u1").get(tg)
        self.assertEqual(after_goal["status"], "approved")  # unchanged
        self.assertEqual(len(self.db.query("SELECT id FROM episodes")), before["episodes"])
        self.assertEqual(len(self.db.query("SELECT id FROM tool_executions")), before["tool_exec"])
        self.assertEqual(len(self.db.query("SELECT id FROM delegation_log")), before["deleg_log"])

    def test_authorize_rolls_back_on_mid_persistence_failure(self):
        tg, _ = _valid_goal(self.db)
        # Break the second step insert (invalid effective_permissions JSON arg is
        # fine; force a column violation by widening seq beyond INTEGER is bad —
        # instead monkeypatch to raise on the steps insert. We simulate a failure
        # AFTER the plan row insert by injecting an extra required step column
        # violation through a trigger-free approach: drop the steps table so the
        # insert fails.
        self.db.execute("DROP TABLE coordination_plan_steps")
        with self.assertRaises(Exception):
            self.svc.authorize(tg, "u1")
        # The plan row was inserted but the transaction rolled back -> none remain.
        self.assertEqual(len(self.db.query("SELECT id FROM coordination_plans")), 0)


class CoordinationIsolationTest(unittest.TestCase):
    def setUp(self):
        self.path = _fresh_db()

    def tearDown(self):
        for s in ("", "-wal", "-shm"):
            try:
                os.remove(self.path + s)
            except OSError:
                pass

    def test_cross_tenant_goal_invisible(self):
        a = Database(path=self.path, tenant_id="tenantA")
        tg, _ = _valid_goal(a, "tenantA", "uA")
        b = Database(path=self.path, tenant_id="tenantB")
        svcB = CoordinationPlanService(b, "tenantB", "uB")
        with self.assertRaises(CoordinationPlanNotFound):
            svcB.review(tg)
        with self.assertRaises(CoordinationPlanNotFound):
            svcB.authorize(tg, "uB")

    def test_cross_user_goal_invisible(self):
        a = Database(path=self.path, tenant_id="t1")
        tg, _ = _valid_goal(a, "t1", "u1")
        svc2 = CoordinationPlanService(a, "t1", "u2")
        with self.assertRaises(CoordinationPlanNotFound):
            svc2.review(tg)
        with self.assertRaises(CoordinationPlanNotFound):
            svc2.authorize(tg, "u2")


class TestTeamGoalApi(unittest.TestCase):
    """Endpoint-level checks (isolated DB via test bootstrap, local mode)."""

    def _make_approved_goal(self):
        from api.routers.team_goals import _db
        from api.routers.team_goals import _goal_svc
        svc = _goal_svc("local", "local")
        ids = _scaffold(_db, "local", "local")
        tg = svc.propose("Launch", "workspace_architect", goal_id=ids["gid"],
                         steps=[{"seq": 1, "agent_id": "strategist",
                                 "responsibility": "Strategy"}])["team_goal_id"]
        svc.approve(tg, "local")
        return tg

    def test_list_and_get_goals(self):
        from fastapi.testclient import TestClient
        from api.app import app
        c = TestClient(app)
        tg = self._make_approved_goal()
        r = c.get("/team/goals")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["items"])
        r2 = c.get(f"/team/goals/{tg}")
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.json()["team_goal_id"] if False else r2.json()["id"], tg)

    def test_review_plan_endpoint(self):
        from fastapi.testclient import TestClient
        from api.app import app
        c = TestClient(app)
        tg = self._make_approved_goal()
        r = c.get(f"/team/goals/{tg}/coordination-plan")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["plan_valid"])
        self.assertTrue(r.json()["transient"])

    def test_authorize_endpoint_persists_plan(self):
        from fastapi.testclient import TestClient
        from api.app import app
        c = TestClient(app)
        tg = self._make_approved_goal()
        r = c.post(f"/team/goals/{tg}/coordination-plan/authorize")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["status"], "authorized")
        self.assertEqual(data["coordinator"], "workspace_architect")
        self.assertTrue(data["steps"])
        # idempotent repeat
        r2 = c.post(f"/team/goals/{tg}/coordination-plan/authorize")
        self.assertEqual(r2.status_code, 200)
        self.assertTrue(r2.json()["reused"])

    def test_authorize_unknown_goal_404(self):
        from fastapi.testclient import TestClient
        from api.app import app
        c = TestClient(app)
        r = c.post("/team/goals/nope/coordination-plan/authorize")
        self.assertEqual(r.status_code, 404)

    def test_authorize_non_approved_goal_422(self):
        from fastapi.testclient import TestClient
        from api.app import app
        from api.routers.team_goals import _goal_svc, _db
        c = TestClient(app)
        svc = _goal_svc("local", "local")
        ids = _scaffold(_db, "local", "local")
        tg = svc.propose("X", "workspace_architect", goal_id=ids["gid"],
                         steps=[{"seq": 1, "agent_id": "strategist",
                                 "responsibility": "strategy"}])["team_goal_id"]
        r = c.post(f"/team/goals/{tg}/coordination-plan/authorize")
        self.assertEqual(r.status_code, 422)

    def test_reject_endpoint(self):
        from fastapi.testclient import TestClient
        from api.app import app
        from api.routers.team_goals import _goal_svc, _db
        c = TestClient(app)
        svc = _goal_svc("local", "local")
        ids = _scaffold(_db, "local", "local")
        tg = svc.propose("X", "workspace_architect", goal_id=ids["gid"],
                         steps=[{"seq": 1, "agent_id": "strategist",
                                 "responsibility": "strategy"}])["team_goal_id"]
        r = c.post(f"/team/goals/{tg}/reject", json={"reason": "nope"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "rejected")


    # ------------------------------------------------------------------ non-human
    def _agent_request(self):
        """A request whose authenticated identity resolves to a non-human role.
        Mirrors what security middleware would set for an agent; exercises the
        real _require_human() gate without bypassing it or the DB."""
        from types import SimpleNamespace
        state = SimpleNamespace(tenant_id="local", user_id="local", role="agent")
        return SimpleNamespace(state=state)

    def test_non_human_cannot_approve(self):
        from fastapi import HTTPException
        from api.routers.team_goals import approve_team_goal
        with self.assertRaises(HTTPException) as ctx:
            approve_team_goal("tg", self._agent_request())
        self.assertEqual(ctx.exception.status_code, 403)

    def test_non_human_cannot_reject(self):
        from fastapi import HTTPException
        from api.routers.team_goals import reject_team_goal
        with self.assertRaises(HTTPException) as ctx:
            reject_team_goal("tg", body=None, request=self._agent_request())
        self.assertEqual(ctx.exception.status_code, 403)

    def test_non_human_cannot_authorize_plan(self):
        from fastapi import HTTPException
        from api.routers.team_goals import authorize_coordination_plan
        with self.assertRaises(HTTPException) as ctx:
            authorize_coordination_plan("tg", self._agent_request())
        self.assertEqual(ctx.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
