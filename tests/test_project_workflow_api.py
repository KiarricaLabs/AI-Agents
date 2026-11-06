"""Structured project workflow API integration (no live model).

Drives the /projects approval -> review -> summary lifecycle over HTTP with
seeded data (project/task/action rows), verifying BOTH the returned HTTP
responses and persisted state. NO planner/model/Ollama is invoked.

Covers:
- plan approve transitions awaiting_plan_approval -> running
- draft review (approve) transitions to done and updates the coordinator summary
- non-human role gets 403 on every human-only mutation
- foreign user/tenant gets 404 on read/review of a project
- pending outward action: agent can queue it, only a human can approve/execute
"""
from __future__ import annotations

import json
import unittest
import uuid
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from api.app import app  # noqa: E402
from config.settings import DB_PATH
from core.auth import issue_token
from storage.database import Database


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProjectWorkflowApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def setUp(self):
        self.tenant = "fwp_" + uuid.uuid4().hex[:10]
        self.user = "fu_" + uuid.uuid4().hex[:8]
        self.db = Database(path=DB_PATH, tenant_id=self.tenant)

    def _h(self, user=None, tenant=None, role="user"):
        return {"x-token": issue_token(user or self.user, tenant or self.tenant, role)}

    def _seed_project(self, project_id, goal, status, tasks):
        """Insert a project and its tasks directly (no model). tasks is a list of
        dicts: id, agent, instruction, depends_on, status, output, review_status."""
        now = _now()
        self.db.execute(
            "INSERT INTO agent_projects "
            "(id,tenant_id,user_id,goal,status,plan_json,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (project_id, self.tenant, self.user, goal, status,
             json.dumps({"goal": goal, "tasks": []}), now, now),
        )
        for t in tasks:
            self.db.execute(
                "INSERT INTO agent_tasks "
                "(id,project_id,tenant_id,user_id,agent,instruction,depends_on,status,"
                "output,created_at,updated_at,review_status,deliverable_type,acceptance_criteria) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (t["id"], project_id, self.tenant, self.user, t.get("agent", "strategist"),
                 t.get("instruction", "produce a draft"), json.dumps(t.get("depends_on", [])),
                 t["status"], t.get("output"), now, now, t.get("review_status", "pending"),
                 t.get("deliverable_type", "draft"), json.dumps(t.get("acceptance_criteria", []))),
            )

    def test_plan_approve_transitions_to_running(self):
        pid = "prj-%s" % uuid.uuid4().hex[:8]
        tid = "task-%s" % uuid.uuid4().hex[:8]
        self._seed_project(pid, "Promote On Us", "awaiting_plan_approval",
                           [dict(id=tid, status="pending")])
        r = self.client.post(f"/projects/{pid}/plan/approve", headers=self._h())
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["status"], "running")
        # persisted
        rows = self.db.query("SELECT status FROM agent_projects WHERE id=?", (pid,))
        self.assertEqual(rows[0]["status"], "running")

    def test_draft_review_approve_reaches_done_and_summary(self):
        pid = "prj-%s" % uuid.uuid4().hex[:8]
        tid = "task-%s" % uuid.uuid4().hex[:8]
        self._seed_project(pid, "Promote On Us", "awaiting_review",
                           [dict(id=tid, agent="strategist", status="done",
                                 output="Positioning: community-first.",
                                 review_status="pending")])
        # summary before approval
        s = self.client.get(f"/projects/{pid}/summary", headers=self._h())
        self.assertEqual(s.json()["summary"], "0 of 1 task drafts approved. 0 outward actions await approval.")
        # approve the draft
        r = self.client.post(f"/projects/tasks/{tid}/review", headers=self._h(),
                             json={"action": "approve"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["status"], "done")
        # persisted + summary updated
        rows = self.db.query(
            "SELECT review_status FROM agent_tasks WHERE id=? AND tenant_id=? AND user_id=?",
            (tid, self.tenant, self.user))
        self.assertEqual(rows[0]["review_status"], "approved")
        s2 = self.client.get(f"/projects/{pid}/summary", headers=self._h())
        self.assertEqual(s2.json()["summary"], "1 of 1 task drafts approved. 0 outward actions await approval.")

    def test_non_human_gets_403_on_human_only_mutations(self):
        pid = "prj-%s" % uuid.uuid4().hex[:8]
        tid = "task-%s" % uuid.uuid4().hex[:8]
        self._seed_project(pid, "Promote On Us", "awaiting_plan_approval",
                           [dict(id=tid, status="pending")])
        h_agent = self._h(role="agent")
        self.assertEqual(self.client.post(f"/projects/{pid}/plan/approve", headers=h_agent).status_code, 403)
        self.assertEqual(self.client.post(f"/projects/tasks/{tid}/review", headers=h_agent,
                                          json={"action": "approve"}).status_code, 403)
        self.assertEqual(self.client.post(f"/projects/{pid}/run", headers=h_agent).status_code, 403)
        self.assertEqual(self.client.post(f"/projects/{pid}/plan/reject", headers=h_agent,
                                          json={"feedback": "no"}).status_code, 403)

    def test_foreign_user_and_tenant_get_404(self):
        pid = "prj-%s" % uuid.uuid4().hex[:8]
        tid = "task-%s" % uuid.uuid4().hex[:8]
        self._seed_project(pid, "Promote On Us", "awaiting_plan_approval",
                           [dict(id=tid, status="pending")])
        other_user = "fu_" + uuid.uuid4().hex[:8]
        self.assertEqual(self.client.get(f"/projects/{pid}", headers=self._h(user=other_user)).status_code, 404)
        other_tenant = "fwp_" + uuid.uuid4().hex[:10]
        self.assertEqual(self.client.get(f"/projects/{pid}", headers=self._h(tenant=other_tenant)).status_code, 404)
        self.assertEqual(self.client.post(f"/projects/{pid}/plan/approve",
                                          headers=self._h(user=other_user)).status_code, 404)

    def test_action_agent_can_queue_but_only_human_executes(self):
        pid = "prj-%s" % uuid.uuid4().hex[:8]
        self._seed_project(pid, "Promote On Us", "awaiting_review",
                           [dict(id="t1", agent="communications", status="done",
                                 output="campaign draft", review_status="pending")])
        # an agent queues a pending action (no human needed to queue)
        h_agent = self._h(role="agent")
        create = self.client.post("/actions", headers=h_agent, json={
            "project_id": pid, "task_id": "t1", "agent": "communications",
            "type": "ig_post", "payload": {"caption": "Join On Us"},
        })
        self.assertEqual(create.status_code, 200, create.text)
        action_id = create.json()["id"]
        # an agent cannot approve/execute it
        self.assertEqual(self.client.post(f"/actions/{action_id}/approve", headers=h_agent).status_code, 403)
        # the owner (human) approves -> executor stub runs, still no external call
        r = self.client.post(f"/actions/{action_id}/approve", headers=self._h())
        self.assertEqual(r.status_code, 200, r.text)
        execution = r.json().get("execution", {})
        self.assertFalse(execution.get("performed", True))
        self.assertTrue(execution.get("stub", False))
        rows = self.db.query(
            "SELECT status FROM pending_actions WHERE id=? AND tenant_id=? AND user_id=?",
            (action_id, self.tenant, self.user))
        self.assertEqual(rows[0]["status"], "executed")


if __name__ == "__main__":
    unittest.main()
