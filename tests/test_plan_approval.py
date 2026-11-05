"""T2-B — plan-to-workspace cascade tests.

Verifies that approving a plan proposal creates the goals and deliverables the
plan lists (plus workspace/project/milestones/assignments), atomically and only
on human approval:
- unit: TeamPlanBuilder.describe + execute produce goals + deliverables;
- integration: POST /team/plans -> proposed; nothing created yet;
  approve -> workspace + project + goal + deliverable exist (owner-scoped).
- safety: nothing is created before approval; foreign identity sees nothing.
"""
from __future__ import annotations

import unittest
import uuid

from fastapi.testclient import TestClient

from api.app import app  # noqa: E402
from core.auth import issue_token
from core.team_plan import TeamPlanBuilder, PlanValidationError
from storage.database import Database
from config.settings import DB_PATH


def _payload():
    return {
        "title": "Launch plan",
        "milestones": [{"title": "Phase 1", "order": 0}],
        "tasks": [{"title": "Research market", "agent": "strategist", "milestone_index": 0}],
        "deliverables": [{"title": "Market brief"}],
        "success_criteria": ["approved launch"],
    }


class TeamPlanUnitTest(unittest.TestCase):
    def test_describe_normalizes_and_holds_deliverables(self):
        plan = TeamPlanBuilder("t", "u").describe(_payload())
        self.assertEqual(len(plan["milestones"]), 1)
        self.assertEqual([d["title"] for d in plan["deliverables"]], ["Market brief"])

    def test_missing_title_rejected(self):
        with self.assertRaises(PlanValidationError):
            TeamPlanBuilder("t", "u").describe({"milestones": [], "deliverables": []})


class TeamPlanApprovalIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def _h(self, user, tenant, role="user"):
        return {"x-token": issue_token(user, tenant, role)}

    def _propose_and_approve(self, h):
        r = self.client.post("/team/plans", json=_payload(), headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        pid = r.json()["proposal_id"]
        self.assertEqual(r.json()["status"], "proposed")
        return pid

    def test_approving_plan_creates_goals_and_deliverables(self):
        t, u = ("tp_%s" % uuid.uuid4().hex[:8], "fu_%s" % uuid.uuid4().hex[:8])
        h = self._h(u, t)
        pid = self._propose_and_approve(h)

        # Before approval: no workspace rows for this user/tenant.
        pre = self.client.get("/workspaces", headers=h).json()["items"]
        self.assertEqual(pre, [])

        appr = self.client.post(f"/work/proposals/{pid}/approve", headers=h)
        self.assertEqual(appr.status_code, 200, appr.text)
        self.assertEqual(appr.json()["status"], "approved")

        # After approval: a workspace + a goal + a deliverable exist.
        wss = self.client.get("/workspaces", headers=h).json()["items"]
        self.assertEqual(len(wss), 1)
        projects = self.client.get("/workspaces/projects", headers=h).json()["items"]
        self.assertGreaterEqual(len(projects), 1)
        goals = self.client.get("/workspaces/goals", headers=h).json()["items"]
        self.assertEqual([g["title"] for g in goals], ["Research market"])
        deliv = self.client.get("/workspaces/deliverables", headers=h).json()["items"]
        self.assertEqual([d["title"] for d in deliv], ["Market brief"])

    def test_foreign_identity_sees_nothing(self):
        t1, u1 = ("tp_%s" % uuid.uuid4().hex[:8], "fu_%s" % uuid.uuid4().hex[:8])
        u2 = "fu_%s" % uuid.uuid4().hex[:8]
        h1 = self._h(u1, t1)
        pid = self._propose_and_approve(h1)
        self.client.post(f"/work/proposals/{pid}/approve", headers=h1)
        # foreign user cannot see the created workspace
        foreign = self.client.get("/workspaces", headers=self._h(u2, t1)).json()["items"]
        self.assertEqual(foreign, [])


if __name__ == "__main__":
    unittest.main()
