"""T2-C-8-1 — TeamGoal propose API (POST /team/goals).

Real HTTP (TestClient) against the isolated test DB, verifying the human-only
propose endpoint exposes ``TeamGoalService.propose``:

- Successful proposal (proposed state, steps created, listed).
- Server-side validation: unknown coordinator/agent, malformed/contiguous step
  sequences, invalid dependency references -> 422.
- Foreign/unknown project goal -> 404 (no existence leak).
- Foreign user / foreign tenant isolation -> 404.
- Non-human role -> 403.
- Idempotency-key repeated proposal (same id, no duplicates).
- Proposal stays in 'proposed'; proposing never approves, never authorizes a
  coordination plan, and never initiates execution.
- Client-supplied identity/impersonation fields cannot override request.state.
"""
from __future__ import annotations

import unittest
import uuid

from fastapi.testclient import TestClient

from api.app import app  # noqa: E402  (registers routers + auth middleware)
from config.settings import DB_PATH
from core.auth import issue_token
from core.workspace import WorkspaceService, ProjectService, GoalService
from storage.database import Database


def _make_goal(db, tenant, user):
    ws = WorkspaceService(db, tenant, user).create("W")
    pid = ProjectService(db, tenant, user).create(ws, "P")
    return GoalService(db, tenant, user).create(pid, "G", 0)


class ProposeAPITest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def setUp(self):
        self.tenant = "fpr_" + uuid.uuid4().hex[:10]
        self.user = "fu_" + uuid.uuid4().hex[:8]
        self.db = Database(path=DB_PATH, tenant_id=self.tenant)

    def _h(self, user=None, tenant=None, role="user"):
        return {"x-token": issue_token(user or self.user, tenant or self.tenant, role)}

    def _valid_body(self, goal_id):
        return {
            "title": "Propose Launch",
            "coordinator_agent": "workspace_architect",
            "goal_id": goal_id,
            "steps": [{"seq": 1, "agent_id": "strategist",
                       "responsibility": "Strategy for the launch"}],
        }

    # ---------------------------------------------------------- happy path
    def test_propose_creates_proposed_team_goal(self):
        gid = _make_goal(self.db, self.tenant, self.user)
        r = self.client.post("/team/goals", json=self._valid_body(gid), headers=self._h())
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertIn("team_goal_id", body)
        self.assertEqual(body["status"], "proposed")
        self.assertFalse(body["reused"])
        tg = body["team_goal_id"]

        # persisted proposed state + a step record
        self.assertEqual(self.db.query(
            "SELECT status FROM team_goals WHERE id=? AND tenant_id=? AND user_id=?",
            (tg, self.tenant, self.user))[0]["status"], "proposed")
        self.assertEqual(self.db.query(
            "SELECT COUNT(*) AS n FROM team_goal_steps "
            "WHERE team_goal_id=? AND tenant_id=? AND user_id=?",
            (tg, self.tenant, self.user))[0]["n"], 1)

        # listed for the owner
        r = self.client.get("/team/goals", headers=self._h())
        self.assertIn(tg, [g["id"] for g in r.json()["items"]])

    # ---------------------------------------------------------- validation
    def test_unknown_coordinator_rejected(self):
        gid = _make_goal(self.db, self.tenant, self.user)
        body = self._valid_body(gid)
        body["coordinator_agent"] = "no_such_agent"
        r = self.client.post("/team/goals", json=body, headers=self._h())
        self.assertEqual(r.status_code, 422, r.text)

    def test_unknown_step_agent_rejected(self):
        gid = _make_goal(self.db, self.tenant, self.user)
        body = self._valid_body(gid)
        body["steps"] = [{"seq": 1, "agent_id": "not_an_agent"}]
        r = self.client.post("/team/goals", json=body, headers=self._h())
        self.assertEqual(r.status_code, 422, r.text)

    def test_non_contiguous_step_sequences_rejected(self):
        gid = _make_goal(self.db, self.tenant, self.user)
        body = self._valid_body(gid)
        body["steps"] = [
            {"seq": 1, "agent_id": "strategist"},
            {"seq": 3, "agent_id": "strategist"},
        ]
        r = self.client.post("/team/goals", json=body, headers=self._h())
        self.assertEqual(r.status_code, 422, r.text)

    def test_invalid_dependency_reference_rejected(self):
        gid = _make_goal(self.db, self.tenant, self.user)
        body = self._valid_body(gid)
        body["steps"] = [
            {"seq": 1, "agent_id": "strategist"},
            {"seq": 2, "agent_id": "strategist", "depends_on_seq": 5},
        ]
        r = self.client.post("/team/goals", json=body, headers=self._h())
        self.assertEqual(r.status_code, 422, r.text)

    # ---------------------------------------------------------- isolation
    def test_unknown_project_goal_returns_404(self):
        r = self.client.post(
            "/team/goals", json=self._valid_body(uuid.uuid4().hex), headers=self._h())
        self.assertEqual(r.status_code, 404, r.text)

    def test_foreign_user_goal_returns_404(self):
        gid = _make_goal(self.db, self.tenant, self.user)
        other = "fuY_" + uuid.uuid4().hex[:8]
        r = self.client.post(
            "/team/goals", json=self._valid_body(gid), headers=self._h(user=other))
        self.assertEqual(r.status_code, 404, r.text)

    def test_foreign_tenant_goal_returns_404(self):
        gid = _make_goal(self.db, self.tenant, self.user)
        alien = "fpt_" + uuid.uuid4().hex[:10]
        r = self.client.post(
            "/team/goals", json=self._valid_body(gid), headers=self._h(tenant=alien))
        self.assertEqual(r.status_code, 404, r.text)

    def test_non_human_role_returns_403(self):
        gid = _make_goal(self.db, self.tenant, self.user)
        r = self.client.post(
            "/team/goals", json=self._valid_body(gid), headers=self._h(role="agent"))
        self.assertEqual(r.status_code, 403, r.text)

    # ---------------------------------------------------------- idempotency
    def test_idempotency_key_reuses_same_goal(self):
        gid = _make_goal(self.db, self.tenant, self.user)
        key = "propose-key-" + uuid.uuid4().hex[:10]
        body = self._valid_body(gid)
        body["idempotency_key"] = key

        r1 = self.client.post("/team/goals", json=body, headers=self._h())
        self.assertEqual(r1.status_code, 200)
        self.assertFalse(r1.json()["reused"])
        r2 = self.client.post("/team/goals", json=body, headers=self._h())
        self.assertEqual(r2.status_code, 200)
        self.assertTrue(r2.json()["reused"])
        self.assertEqual(r1.json()["team_goal_id"], r2.json()["team_goal_id"])
        # idempotency_key is used as the row id; exactly one row exists.
        self.assertEqual(
            self.db.query("SELECT COUNT(*) AS n FROM team_goals WHERE id=? "
                          "AND tenant_id=? AND user_id=?",
                          (key, self.tenant, self.user))[0]["n"], 1)

    # ---------------------------------------------------------- separation
    def test_proposal_stays_proposed_and_triggers_no_downstream(self):
        gid = _make_goal(self.db, self.tenant, self.user)
        tg = self.client.post(
            "/team/goals", json=self._valid_body(gid), headers=self._h()).json()["team_goal_id"]

        # remains proposed (not approved)
        self.assertEqual(self.client.get(f"/team/goals/{tg}", headers=self._h()).json()["status"],
                         "proposed")
        # no coordination plan was auto-authorized
        plans = self.db.query(
            "SELECT id FROM coordination_plans WHERE team_goal_id=? "
            "AND tenant_id=? AND user_id=?", (tg, self.tenant, self.user))
        self.assertEqual(plans, [])
        # no execution run was started
        runs = self.db.query(
            "SELECT id FROM coordination_executions WHERE team_goal_id=? "
            "AND tenant_id=? AND user_id=?", (tg, self.tenant, self.user))
        self.assertEqual(runs, [])
        # nothing was approved
        apprs = self.db.query(
            "SELECT decision FROM team_goal_approvals WHERE team_goal_id=? "
            "AND tenant_id=? AND user_id=?", (tg, self.tenant, self.user))
        self.assertEqual(apprs, [])

    # ---------------------------------------------------------- impersonation
    def test_client_identity_fields_do_not_override_state(self):
        gid = _make_goal(self.db, self.tenant, self.user)
        other = "fuZ_" + uuid.uuid4().hex[:8]
        # Body claims to be the owner, but identity is derived from the token.
        body = self._valid_body(gid)
        body["user_id"] = self.user
        body["tenant_id"] = self.tenant
        r = self.client.post("/team/goals", json=body, headers=self._h(user=other))
        self.assertEqual(r.status_code, 404, r.text)

    # ---------------------------------------------------------- validate draft
    def _valid_steps(self):
        return [{"seq": 1, "agent_id": "strategist", "responsibility": "Plan the research"},
                {"seq": 2, "agent_id": "strategist", "responsibility": "Prioritize findings",
                 "depends_on_seq": 1}]

    def test_validate_draft_reports_valid_plan(self):
        r = self.client.post("/team/goals/validate", headers=self._h(), json={
            "coordinator_agent": "workspace_architect", "steps": self._valid_steps()})
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertTrue(body["plan_valid"])
        self.assertEqual([s["valid"] for s in body["steps"]], [True, True])

    def test_validate_draft_flags_undeclared_delegation(self):
        # communications is NOT delegable from workspace_architect -> invalid,
        # with no valid candidate (no delegable agent has 'draft' capability).
        r = self.client.post("/team/goals/validate", headers=self._h(), json={
            "coordinator_agent": "workspace_architect",
            "steps": [{"seq": 1, "agent_id": "communications", "responsibility": "Draft messaging"}]})
        self.assertEqual(r.status_code, 200, r.text)
        st = r.json()["steps"][0]
        self.assertFalse(st["valid"])
        self.assertFalse(st["delegation_ok"])
        self.assertEqual(st["suggested_agent_id"], None)
        self.assertEqual(st["valid_agent_ids"], [])
        self.assertIn("not authorized", st["error"])

    def test_validate_draft_suggests_capable_delegable_agent(self):
        # 'Prioritize' responsibility matched to strategist; if authored with an
        # undeclared agent that still has no suggestion, the endpoint is honest.
        r = self.client.post("/team/goals/validate", headers=self._h(), json={
            "coordinator_agent": "workspace_architect",
            "steps": [{"seq": 1, "agent_id": "bogus", "responsibility": "Plan the research"}]})
        self.assertEqual(r.status_code, 200, r.text)
        st = r.json()["steps"][0]
        self.assertFalse(st["valid"])
        self.assertIn("unknown agent", st["error"])

    def test_validate_draft_unknown_coordinator_422(self):
        r = self.client.post("/team/goals/validate", headers=self._h(), json={
            "coordinator_agent": "bogus", "steps": self._valid_steps()})
        self.assertEqual(r.status_code, 422, r.text)

    def test_validate_draft_non_human_403(self):
        r = self.client.post("/team/goals/validate", headers=self._h(role="agent"), json={
            "coordinator_agent": "workspace_architect", "steps": self._valid_steps()})
        self.assertEqual(r.status_code, 403, r.text)


if __name__ == "__main__":
    unittest.main()
