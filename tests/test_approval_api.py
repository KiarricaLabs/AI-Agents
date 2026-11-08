import os
import base64
MASTER_KEY = base64.urlsafe_b64encode(os.urandom(32)).decode()
os.environ['PAT_MASTER_KEY'] = MASTER_KEY
import tempfile
import unittest
import json
import base64
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
        # store credentials for integrations
        from storage.credentials import CredentialStore
        import sys
        sys.path.insert(0, '.')
        from tests.test_approval_api import MASTER_KEY
        key = MASTER_KEY
        cs = CredentialStore(db=self.db, tenant_id="local", user_id="local", key=key)
        cs.save("email", json.dumps({"host": "smtp.example.com", "port": 587, "username": "u", "password": "p", "sender": "u@example.com", "use_starttls": True}))
        cs.save("calendar", json.dumps({"access_token": "tok", "calendar_id": "primary"}))
        cs.save("media", json.dumps({"api_key": "sk-test", "model": "dall-e-3"}))

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

    def _run_integration(self, tool, args, mock_patch, mock_return=None):
        r = self.client.post("/agents/approvals/tool", json={"agent_id": self._agent_for(tool), "tool": tool, "args": args})
        aid = r.json()["approval_id"]
        self.client.post(f"/agents/approvals/tool/{aid}/approve")
        with mock_patch as m:
            if mock_return is not None:
                m.return_value.__enter__.return_value = mock_return
            r2 = self.client.post(f"/agents/{self._agent_for(tool)}/run", json={"task": "x", "tool_calls": [{"tool": tool, "args": args, "approval_id": aid}]})
            return r2, m

    def _agent_for(self, tool):
        return {"email_send": "communications", "calendar_create": "executive_assistant", "image_generate": "communications"}[tool]

    def test_email_approved_calls_smtp(self):
        import unittest.mock as m
        srv = m.MagicMock()
        r2, mock = self._run_integration("email_send", {"to": "a@b.com", "subject": "s", "body": "b"}, m.patch("smtplib.SMTP"), srv)
        self.assertEqual(r2.status_code, 200)
        self.assertTrue(srv.send_message.called)

    def test_email_unapproved_never_smtp(self):
        import unittest.mock as m
        with m.patch("smtplib.SMTP") as smtp:
            r = self.client.post("/agents/communications/run", json={"task": "x", "tool_calls": [{"tool": "email_send", "args": {"to": "a@b.com"}, "approved": True}]})
            self.assertEqual(smtp.call_count, 0)

    def test_calendar_approved_calls_api(self):
        import unittest.mock as m, json as j
        resp = m.MagicMock(); resp.read.return_value = j.dumps({"id": "e1"}).encode(); resp.__enter__.return_value = resp
        r2, mock = self._run_integration("calendar_create", {"title": "t", "start": "2024-01-01T10:00:00", "end": "2024-01-01T11:00:00"}, m.patch("urllib.request.urlopen", return_value=resp))
        self.assertEqual(r2.status_code, 200)

    def test_image_approved_calls_api(self):
        import base64, json as j, unittest.mock as m
        b64 = base64.b64encode(b"x").decode()
        resp = m.MagicMock(); resp.read.return_value = j.dumps({"data": [{"b64_json": b64}]}).encode(); resp.__enter__.return_value = resp
        r2, mock = self._run_integration("image_generate", {"prompt": "a cat"}, m.patch("urllib.request.urlopen", return_value=resp))
        self.assertEqual(r2.status_code, 200)

    def test_modified_args_invalidates(self):
        r = self.client.post("/agents/approvals/tool", json={"agent_id": "communications", "tool": "email_send", "args": {"to": "a@b.com", "subject": "s", "body": "b"}})
        aid = r.json()["approval_id"]
        self.client.post(f"/agents/approvals/tool/{aid}/approve")
        import unittest.mock as m
        with m.patch("smtplib.SMTP") as smtp:
            srv = m.MagicMock(); smtp.return_value.__enter__.return_value = srv
            r2 = self.client.post("/agents/communications/run", json={"task": "x", "tool_calls": [{"tool": "email_send", "args": {"to": "DIFFERENT@b.com", "subject": "s", "body": "b"}, "approval_id": aid}]})
            self.assertEqual(smtp.call_count, 0)

    def test_approval_reuse_rejected(self):
        r = self.client.post("/agents/approvals/tool", json={"agent_id": "communications", "tool": "email_send", "args": {"to": "a@b.com", "subject": "s", "body": "b"}})
        aid = r.json()["approval_id"]
        self.client.post(f"/agents/approvals/tool/{aid}/approve")
        import unittest.mock as m
        with m.patch("smtplib.SMTP") as smtp:
            srv = m.MagicMock(); smtp.return_value.__enter__.return_value = srv
            self.client.post("/agents/communications/run", json={"task": "x", "tool_calls": [{"tool": "email_send", "args": {"to": "a@b.com", "subject": "s", "body": "b"}, "approval_id": aid}]})
        with m.patch("smtplib.SMTP") as smtp:
            srv = m.MagicMock(); smtp.return_value.__enter__.return_value = srv
            self.client.post("/agents/communications/run", json={"task": "x", "tool_calls": [{"tool": "email_send", "args": {"to": "a@b.com", "subject": "s", "body": "b"}, "approval_id": aid}]})
            self.assertEqual(smtp.call_count, 0)


if __name__ == "__main__":
    unittest.main()