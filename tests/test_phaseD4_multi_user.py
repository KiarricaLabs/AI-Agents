"""D4.3 #3 — multi-user isolation & role enforcement.

Closes the gap that the plan/proposal endpoints were only exercised in
single-user LOCAL_MODE. Uses real signed tokens (core.auth.issue_token) so a
second user and a non-human role are genuinely tested end-to-end against the
running API middleware + ownership checks.

Covers:
- Cross-USER plan access: user B cannot plan/ground on user A's project (404).
- owner access succeeds for the owner (with a stubbed planner).
- Cross-USER proposal creation is rejected (422) for a foreign parent.
- Feed isolation: user B never sees user A's proposals.
- Non-human role is rejected with 403 on plan and proposal endpoints.
"""
from __future__ import annotations
import os, tempfile, unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from config.settings import DB_PATH
from storage.database import Database
from core.auth import issue_token
from core.workspace import WorkspaceService, ProjectService
from api.app import app


class MultiUserBase(unittest.TestCase):
    def setUp(self):
        self.db = Database(path=DB_PATH, tenant_id="local")
        self.wa = WorkspaceService(self.db, "local", "userA").create("A WS")
        self.pa = ProjectService(self.db, "local", "userA").create(self.wa, "A Project")
        self.tokA = issue_token("userA", "local", "user")
        self.tokB = issue_token("userB", "local", "user")
        self.tokAgent = issue_token("agentX", "local", "agent")

    def client(self, token):
        c = TestClient(app)
        c.headers.update({"x-token": token})
        return c


class TestCrossUserPlan(MultiUserBase):
    def test_cross_user_project_not_found(self):
        # user B must not see (or leak) user A's project when grounding a plan.
        r = self.client(self.tokB).post("/agents/plan",
                                        json={"objective": "organize", "project_id": self.pa})
        self.assertEqual(r.status_code, 404)
        self.assertNotIn(self.pa, r.text)

    def test_owner_can_plan_on_own_project(self):
        fake = {"agent": "strategist", "reply": "sum",
                "steps": [{"work_type": "goal", "title": "G"}],
                "provider": "ollama", "model": "m", "location": "local"}
        with patch("agents.base.BaseAgent.plan_steps", return_value=fake):
            r = self.client(self.tokA).post("/agents/plan",
                                            json={"objective": "organize", "project_id": self.pa})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["objective"], "organize")


class TestCrossUserProposals(MultiUserBase):
    def test_cross_user_proposal_rejected(self):
        body = {"work_type": "goal", "action": "create",
                "payload": {"project_id": self.pa, "title": "X"}, "agent_id": "strategist"}
        r = self.client(self.tokB).post("/work/proposals", json=body)
        self.assertEqual(r.status_code, 422)

    def test_owner_proposal_ok(self):
        body = {"work_type": "goal", "action": "create",
                "payload": {"project_id": self.pa, "title": "Owned"}, "agent_id": "strategist"}
        r = self.client(self.tokA).post("/work/proposals", json=body)
        self.assertEqual(r.status_code, 200)

    def test_feed_is_isolated(self):
        # user A files a proposal; user B's feed stays empty.
        body = {"work_type": "goal", "action": "create",
                "payload": {"project_id": self.pa, "title": "Secret"}, "agent_id": "strategist"}
        self.assertEqual(self.client(self.tokA).post("/work/proposals", json=body).status_code, 200)
        r = self.client(self.tokB).get("/work/feed")
        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.json() or {}).get("items", []), [])


class TestRoleEnforcement(MultiUserBase):
    def test_plan_rejects_non_human_role(self):
        r = self.client(self.tokAgent).post("/agents/plan",
                                            json={"objective": "organize", "project_id": self.pa})
        self.assertEqual(r.status_code, 403)

    def test_proposal_rejects_non_human_role(self):
        body = {"work_type": "goal", "action": "create",
                "payload": {"project_id": self.pa, "title": "X"}, "agent_id": "strategist"}
        r = self.client(self.tokAgent).post("/work/proposals", json=body)
        self.assertEqual(r.status_code, 403)


if __name__ == "__main__":
    unittest.main()
