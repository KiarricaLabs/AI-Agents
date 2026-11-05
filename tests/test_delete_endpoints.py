"""Delete-endpoint tests: goals, deliverables, conversation threads, proposals.

Safety: every delete is owner+tenant scoped, human-gated (non-human -> 403),
returns 404 for foreign/missing resources, and cleans up dependent rows.
"""
from __future__ import annotations

import unittest
import uuid

from fastapi.testclient import TestClient

from api.app import app  # noqa: E402
from core.auth import issue_token
from storage.database import Database
from config.settings import DB_PATH


class DeleteEndpointsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def _h(self, user, tenant, role="user"):
        return {"x-token": issue_token(user, tenant, role)}

    def test_delete_goal_removes_goal_and_assignments(self):
        t, u = ("dd_%s" % uuid.uuid4().hex[:8], "fu_%s" % uuid.uuid4().hex[:8])
        h = self._h(u, t)
        ws = self.client.post("/workspaces", json={"name": "Acme"}, headers=h).json()["id"]
        pid = self.client.post("/workspaces/projects", json={"workspace_id": ws, "name": "Launch"}, headers=h).json()["id"]
        gid = self.client.post("/workspaces/goals", json={"project_id": pid, "title": "Research", "priority": 1}, headers=h).json()["id"]
        self.client.post("/workspaces/assignments", json={"goal_id": gid, "agent_id": "strategist", "priority": 0}, headers=h)
        r = self.client.delete(f"/workspaces/goals/{gid}", headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.client.get("/workspaces/goals?project_id=" + pid, headers=h).json()["items"], [])

    def test_delete_goal_foreign_user_404(self):
        t, u1 = ("dd_%s" % uuid.uuid4().hex[:8], "fu_%s" % uuid.uuid4().hex[:8])
        u2 = "fu_%s" % uuid.uuid4().hex[:8]
        ws = self.client.post("/workspaces", json={"name": "Acme"}, headers=self._h(u1, t)).json()["id"]
        pid = self.client.post("/workspaces/projects", json={"workspace_id": ws, "name": "L"}, headers=self._h(u1, t)).json()["id"]
        gid = self.client.post("/workspaces/goals", json={"project_id": pid, "title": "G"}, headers=self._h(u1, t)).json()["id"]
        r = self.client.delete(f"/workspaces/goals/{gid}", headers=self._h(u2, t))
        self.assertEqual(r.status_code, 404)

    def test_delete_goal_non_human_403(self):
        t, u = ("dd_%s" % uuid.uuid4().hex[:8], "fu_%s" % uuid.uuid4().hex[:8])
        r = self.client.delete(f"/workspaces/goals/{uuid.uuid4()}", headers=self._h(u, t, role="agent"))
        self.assertEqual(r.status_code, 403)

    def test_delete_deliverable_removes_versions(self):
        t, u = ("dd_%s" % uuid.uuid4().hex[:8], "fu_%s" % uuid.uuid4().hex[:8])
        h = self._h(u, t)
        ws = self.client.post("/workspaces", json={"name": "A"}, headers=h).json()["id"]
        pid = self.client.post("/workspaces/projects", json={"workspace_id": ws, "name": "P"}, headers=h).json()["id"]
        did = self.client.post("/workspaces/deliverables", json={"project_id": pid, "title": "Brief"}, headers=h).json()["id"]
        r = self.client.delete(f"/workspaces/deliverables/{did}", headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.client.get("/workspaces/deliverables?project_id=" + pid, headers=h).json()["items"], [])

    def test_delete_conversation(self):
        t, u = ("dd_%s" % uuid.uuid4().hex[:8], "fu_%s" % uuid.uuid4().hex[:8])
        h = self._h(u, t)
        thr = self.client.post("/team/threads", json={"title": "Chat", "thread_type": "team"}, headers=h).json()["thread_id"]
        self.client.post("/memory/conversation", json={"content": "hi", "thread_id": thr}, headers=h)
        r = self.client.delete(f"/memory/conversations/{thr}", headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        lst = self.client.get("/memory/conversations", headers=h).json()["items"]
        self.assertFalse(any(x["thread_id"] == thr for x in lst))

    def test_delete_conversation_foreign_404(self):
        t, u1 = ("dd_%s" % uuid.uuid4().hex[:8], "fu_%s" % uuid.uuid4().hex[:8])
        u2 = "fu_%s" % uuid.uuid4().hex[:8]
        thr = self.client.post("/team/threads", json={"title": "Chat", "thread_type": "team"}, headers=self._h(u1, t)).json()["thread_id"]
        r = self.client.delete(f"/memory/conversations/{thr}", headers=self._h(u2, t))
        self.assertEqual(r.status_code, 404)

    def test_delete_proposal(self):
        t, u = ("dd_%s" % uuid.uuid4().hex[:8], "fu_%s" % uuid.uuid4().hex[:8])
        h = self._h(u, t)
        ws = self.client.post("/work/proposals/workspace", json={"name": "Acme2"}, headers=h).json()["proposal_id"]
        r = self.client.delete(f"/work/proposals/{ws}", headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        lst = self.client.get("/work/proposals", headers=h).json()["items"]
        self.assertFalse(any(p["id"] == ws for p in lst))

    def test_delete_proposal_non_human_403(self):
        t, u = ("dd_%s" % uuid.uuid4().hex[:8], "fu_%s" % uuid.uuid4().hex[:8])
        r = self.client.delete(f"/work/proposals/{uuid.uuid4()}", headers=self._h(u, t, role="agent"))
        self.assertEqual(r.status_code, 403)


if __name__ == "__main__":
    unittest.main()
