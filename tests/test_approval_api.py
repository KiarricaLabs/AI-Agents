import os
import tempfile
import unittest
from fastapi.testclient import TestClient

from api.app import app
from storage.database import Database


class ApprovalAPITests(unittest.TestCase):
    def setUp(self):
        self.db_path = os.path.join(tempfile.gettempdir(), "appr_api.db")
        try:
            os.remove(self.db_path)
        except FileNotFoundError:
            pass
        os.environ["PAT_DB_PATH"] = self.db_path
        self.db = Database(path=self.db_path, tenant_id="local")
        import api.routers.agents as ar
        self._orig_db = ar._db
        ar._db = self.db
        self.client = TestClient(app)

    def tearDown(self):
        import api.routers.agents as ar
        ar._db = self._orig_db
        try:
            os.remove(self.db_path)
        except FileNotFoundError:
            pass

    def test_create_approval_requires_fields(self):
        r = self.client.post("/agents/approvals/tool", json={})
        self.assertIn(r.status_code, (400, 422))

    def test_create_approval_for_declared_tool(self):
        r = self.client.post("/agents/approvals/tool", json={"agent_id": "communications", "tool": "email_send", "args": {"to": "a@b.com"}})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "pending")

    def test_approve_and_reject(self):
        r = self.client.post("/agents/approvals/tool", json={"agent_id": "communications", "tool": "email_send", "args": {"to": "a@b.com"}})
        aid = r.json()["approval_id"]
        r2 = self.client.post(f"/agents/approvals/tool/{aid}/approve")
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.json()["status"], "approved")
        # reject a new one
        r3 = self.client.post("/agents/approvals/tool", json={"agent_id": "communications", "tool": "email_send", "args": {"to": "x@y.com"}})
        aid2 = r3.json()["approval_id"]
        r4 = self.client.post(f"/agents/approvals/tool/{aid2}/reject")
        self.assertEqual(r4.json()["status"], "rejected")

    def test_unauthorized_tool_not_declared(self):
        r = self.client.post("/agents/approvals/tool", json={"agent_id": "communications", "tool": "calendar_create", "args": {}})
        self.assertEqual(r.status_code, 403)

    def test_run_with_consumed_approval(self):
        # create + approve
        r = self.client.post("/agents/approvals/tool", json={"agent_id": "communications", "tool": "email_send", "args": {"to": "a@b.com", "subject": "s", "body": "b"}})
        aid = r.json()["approval_id"]
        self.client.post(f"/agents/approvals/tool/{aid}/approve")
        # run agent with approval_id
        with __import__("unittest.mock", fromlist=["patch"]).patch("smtplib.SMTP") as m:
            srv = __import__("unittest.mock", fromlist=["MagicMock"]).MagicMock()
            m.return_value.__enter__.return_value = srv
            r2 = self.client.post("/agents/communications/run", json={"task": "send", "tool_calls": [{"tool": "email_send", "args": {"to": "a@b.com", "subject": "s", "body": "b"}, "approval_id": aid}]})
            self.assertEqual(r2.status_code, 200)

    def test_reuse_approval_rejected(self):
        r = self.client.post("/agents/approvals/tool", json={"agent_id": "communications", "tool": "email_send", "args": {"to": "a@b.com", "subject": "s", "body": "b"}})
        aid = r.json()["approval_id"]
        self.client.post(f"/agents/approvals/tool/{aid}/approve")
        import unittest.mock as m
        with m.patch("smtplib.SMTP") as smtp:
            srv = m.MagicMock()
            smtp.return_value.__enter__.return_value = srv
            self.client.post("/agents/communications/run", json={"task": "send", "tool_calls": [{"tool": "email_send", "args": {"to": "a@b.com", "subject": "s", "body": "b"}, "approval_id": aid}]})
        # second use should not execute (approval consumed)
        with m.patch("smtplib.SMTP") as smtp:
            srv = m.MagicMock()
            smtp.return_value.__enter__.return_value = srv
            self.client.post("/agents/communications/run", json={"task": "send", "tool_calls": [{"tool": "email_send", "args": {"to": "a@b.com", "subject": "s", "body": "b"}, "approval_id": aid}]})
            # smtp should not be called (approval consumed) -> check call count
            self.assertEqual(smtp.call_count, 0)


if __name__ == "__main__":
    unittest.main()