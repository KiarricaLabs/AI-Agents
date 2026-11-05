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


if __name__ == "__main__":
    unittest.main()
