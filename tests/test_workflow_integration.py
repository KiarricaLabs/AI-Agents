"""T2-C-7 Phase 1A/1B — real HTTP + database integration and isolation tests.

Drives the T2-C workflow through the actual FastAPI app (TestClient) against the
isolated shared test database (bootstrap in tests/__init__.py).

TeamGoal *propose* has no HTTP endpoint (deliberately service-level in T2-C-1),
so scaffolding uses the services; every step after a goal exists is exercised
over HTTP: approve -> plan review -> authorize (frozen snapshot) ->
re-authorize (idempotent reuse) -> initiate -> execution status.

Security is exercised over HTTP too:
- foreign user / foreign tenant → 404 (no existence leak);
- non-human roles → 403 on every mutating endpoint;
- TeamGoal approval and coordination-plan authorization are separate decisions.

No agent/model dependency: a step is never actually dispatched here (dispatch
and the permission-ceiling are proven at the service layer in
test_coordination_execution.py).
"""
from __future__ import annotations

import unittest
import uuid

from fastapi.testclient import TestClient

from api.app import app  # noqa: E402  (registers routers + auth middleware)
from config.settings import DB_PATH
from core.auth import issue_token
from core.team_goal import TeamGoalService
from core.workspace import WorkspaceService, ProjectService, GoalService
from storage.database import Database


def _scaffold(db, tenant, user):
    ws = WorkspaceService(db, tenant, user).create("W")
    pid = ProjectService(db, tenant, user).create(ws, "P")
    gid = GoalService(db, tenant, user).create(pid, "G", 0)
    return {"wid": ws, "pid": pid, "gid": gid}


def _propose(db, tenant, user):
    """Create a TeamGoal that yields a valid plan: workspace_architect coordinator
    handing off to the strategist (the only declared delegation)."""
    svc = TeamGoalService(db, tenant, user)
    ids = _scaffold(db, tenant, user)
    return svc.propose(
        "Launch",
        "workspace_architect",
        goal_id=ids["gid"],
        steps=[{"seq": 1, "agent_id": "strategist",
                "responsibility": "Strategy for the launch"}],
    )["team_goal_id"]


def _propose_approved(db, tenant, user):
    tg = _propose(db, tenant, user)
    TeamGoalService(db, tenant, user).approve(tg, user)
    return tg


class WorkflowGoldenPathTest(unittest.TestCase):
    """Every case runs on the shared isolated DB; a unique tenant isolates it."""

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def setUp(self):
        self.tenant = "fwg_" + uuid.uuid4().hex[:10]
        self.user = "fu_" + uuid.uuid4().hex[:8]
        self.db = Database(path=DB_PATH, tenant_id=self.tenant)

    def _h(self, user=None, tenant=None, role="user"):
        return {"x-token": issue_token(user or self.user, tenant or self.tenant, role)}

    def test_golden_path_workflow_over_http(self):
        tg = _propose(self.db, self.tenant, self.user)
        h = self._h()

        # approve the TeamGoal over HTTP (human-only)
        r = self.client.post(f"/team/goals/{tg}/approve", headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["status"], "approved")

        # list the owner's goals
        r = self.client.get("/team/goals", headers=h)
        self.assertEqual(r.status_code, 200)
        self.assertIn(tg, [g["id"] for g in r.json()["items"]])

        # retrieve a single goal
        r = self.client.get(f"/team/goals/{tg}", headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["id"], tg)

        # review the coordination plan (transient, never persists)
        r = self.client.get(f"/team/goals/{tg}/coordination-plan", headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertTrue(body["plan_valid"])
        self.assertEqual(body["coordinator"], "workspace_architect")
        self.assertTrue(body["transient"])

        # authorize the plan (human) -> persisted, frozen snapshot
        r = self.client.post(f"/team/goals/{tg}/coordination-plan/authorize", headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        plan = r.json()
        self.assertEqual(plan["status"], "authorized")
        self.assertEqual(plan["coordinator"], "workspace_architect")
        self.assertFalse(plan["reused"])
        plan_id = plan["plan_id"]
        seqs = [s["seq"] for s in plan["steps"]]
        self.assertEqual(seqs, sorted(seqs))
        # every persisted step carries its effective-permission ceiling
        for s in plan["steps"]:
            self.assertIn("effective_permissions", s)

        # repeat authorization -> idempotent reuse of the exact snapshot
        r = self.client.post(f"/team/goals/{tg}/coordination-plan/authorize", headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        plan2 = r.json()
        self.assertTrue(plan2["reused"])
        self.assertEqual(plan2["plan_id"], plan_id)

        # initiate a human execution run
        r = self.client.post(
            f"/team/goals/plans/{plan_id}/execution/initiate", headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        run = r.json()
        self.assertEqual(run["status"], "running")
        exec_id = run["execution_id"]

        # execution status shape (GET) matches what the frontend consumes
        r = self.client.get(
            f"/team/goals/plans/{plan_id}/execution/{exec_id}", headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        s = r.json()
        self.assertEqual(s["execution_id"], exec_id)
        self.assertEqual(s["plan_id"], plan_id)
        self.assertEqual(s["team_goal_id"], tg)
        self.assertEqual(s["status"], "running")
        self.assertEqual([st["seq"] for st in s["steps"]], seqs)
        # no deliverable until aggregation -> versions endpoint returns 404
        self.assertIsNone(s["deliverable"])
        r = self.client.get(
            f"/team/goals/plans/{plan_id}/execution/{exec_id}/deliverable/versions",
            headers=h)
        self.assertEqual(r.status_code, 404, r.text)

    def test_goal_approval_and_plan_authorization_are_separate(self):
        """Approving the goal does NOT authorize a plan; execution requires the
        explicit, separate plan-authorization decision."""
        tg = _propose(self.db, self.tenant, self.user)  # proposed, NOT approved
        h = self._h()
        # cannot authorize a plan for a non-approved goal
        r = self.client.post(
            f"/team/goals/{tg}/coordination-plan/authorize", headers=h)
        self.assertEqual(r.status_code, 422, r.text)
        r = self.client.post(f"/team/goals/{tg}/approve", headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        # approved but still NOT authorized -> plan is reviewable but not runnable
        r = self.client.get(f"/team/goals/{tg}/coordination-plan", headers=h)
        self.assertTrue(r.json()["plan_valid"])
        # there is no plan_id until authorize; authorize is the explicit gate
        r = self.client.post(
            f"/team/goals/{tg}/coordination-plan/authorize", headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        plan_id = r.json()["plan_id"]
        r = self.client.post(
            f"/team/goals/plans/{plan_id}/execution/initiate", headers=h)
        self.assertEqual(r.status_code, 200, r.text)


class WorkflowSecurityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def _new_ctx(self):
        tenant = "fws_" + uuid.uuid4().hex[:10]
        user = "fu_" + uuid.uuid4().hex[:8]
        db = Database(path=DB_PATH, tenant_id=tenant)
        return tenant, user, db

    def _h(self, user, tenant, role="user"):
        return {"x-token": issue_token(user, tenant, role)}

    def _owner_setup(self, db, tenant, user):
        """Return (team_goal_id, plan_id, execution_id) fully authorized for owner."""
        tg = _propose_approved(db, tenant, user)
        h = self._h(user, tenant)
        plan_id = self.client.post(
            f"/team/goals/{tg}/coordination-plan/authorize", headers=h).json()["plan_id"]
        exec_id = self.client.post(
            f"/team/goals/plans/{plan_id}/execution/initiate", headers=h).json()["execution_id"]
        return tg, plan_id, exec_id

    def test_foreign_user_gets_404(self):
        tenant, owner, db = self._new_ctx()
        tg, plan_id, exec_id = self._owner_setup(db, tenant, owner)
        other = "fu2_" + uuid.uuid4().hex[:8]
        hb = self._h(other, tenant)  # SAME tenant, different user
        for url in (
            f"/team/goals/{tg}",
            f"/team/goals/{tg}/coordination-plan",
            f"/team/goals/plans/{plan_id}/execution/{exec_id}",
            f"/team/goals/plans/{plan_id}/execution/{exec_id}/deliverable/versions",
        ):
            self.assertEqual(self.client.get(url, headers=hb).status_code, 404, url)
        for url in (
            f"/team/goals/{tg}/approve",
            f"/team/goals/{tg}/reject",
            f"/team/goals/{tg}/coordination-plan/authorize",
            f"/team/goals/plans/{plan_id}/execution/initiate",
            f"/team/goals/plans/{plan_id}/execution/{exec_id}/aggregate",
        ):
            self.assertEqual(self.client.post(url, json={}, headers=hb).status_code, 404, url)

    def test_foreign_tenant_gets_404(self):
        tenant, owner, db = self._new_ctx()
        tg, plan_id, exec_id = self._owner_setup(db, tenant, owner)
        alien_tenant = "fwt_" + uuid.uuid4().hex[:10]
        hc = self._h("fu_x", alien_tenant)
        self.assertEqual(self.client.get(f"/team/goals/{tg}", headers=hc).status_code, 404)
        self.assertEqual(
            self.client.post(f"/team/goals/{tg}/approve", json={}, headers=hc).status_code, 404)
        self.assertEqual(
            self.client.get(
                f"/team/goals/plans/{plan_id}/execution/{exec_id}", headers=hc).status_code, 404)

    def test_non_human_role_receives_403_on_every_mutation(self):
        tenant, owner, db = self._new_ctx()
        tg, plan_id, exec_id = self._owner_setup(db, tenant, owner)
        ha = self._h(owner, tenant, role="agent")
        posts = [
            (f"/team/goals/{tg}/approve", {}),
            (f"/team/goals/{tg}/reject", {}),
            (f"/team/goals/{tg}/coordination-plan/authorize", {}),
            (f"/team/goals/plans/{plan_id}/execution/initiate", {}),
            (f"/team/goals/plans/{plan_id}/execution/{exec_id}/step/execute", {}),
            (f"/team/goals/plans/{plan_id}/execution/{exec_id}/step/1/review",
             {"decision": "accepted"}),
            (f"/team/goals/plans/{plan_id}/execution/{exec_id}/aggregate", {}),
            (f"/team/goals/plans/{plan_id}/execution/{exec_id}/deliverable/review",
             {"decision": "accepted"}),
        ]
        for url, body in posts:
            self.assertEqual(self.client.post(url, json=body, headers=ha).status_code, 403, url)

    def test_identity_comes_only_from_request_state(self):
        """A client can never influence identity via body/headers: ownership is
        derived purely from the token, so a foreign-user token with extra body
        fields still cannot reach the resource."""
        tenant, owner, db = self._new_ctx()
        tg = _propose_approved(db, tenant, owner)
        other = "fu3_" + uuid.uuid4().hex[:8]
        # Attempt to "impersonate" the owner by including owner fields in the body.
        r = self.client.post(
            f"/team/goals/{tg}/coordination-plan/authorize",
            json={"user_id": owner, "tenant_id": tenant},
            headers=self._h(other, tenant))
        self.assertEqual(r.status_code, 404, r.text)


if __name__ == "__main__":
    unittest.main()
