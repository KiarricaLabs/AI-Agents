"""V1.6.10.2 — read-only agent run history API tests."""
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.app import app
from core.auth import issue_token
from core.model_router import ModelResult
from storage.database import Database
from config.settings import DB_PATH

_GOOD = ModelResult("hello from test", "ollama", "llama3.1", "local:ollama:llama3.1")


class _FakeRouter:
    def _resolve(self, spec=None):
        return ("ollama", "llama3.1")

    def complete(self, agent_id, prompt, system="", model_spec=None, context=None):
        return _GOOD


class TestAgentRunsApi(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.tok = issue_token("u1", "t1", "user", 3600)
        db = Database(path=DB_PATH, tenant_id="t1")
        db.execute("DELETE FROM agent_run_history WHERE tenant_id='t1' AND user_id='u1'")

    def test_unauthenticated_rejected(self):
        r = self.client.get("/agents/runs", headers={"x-token": "bad"})
        self.assertEqual(r.status_code, 401)

    @patch("core.runtime.ModelRouter", return_value=_FakeRouter())
    def test_retrieve_own_history(self, _m):
        self.client.post("/agents/tutor/run", json={"task": "hi"}, headers={"x-token": self.tok})
        r = self.client.get("/agents/runs", headers={"x-token": self.tok})
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["items"][0]["agent_id"], "tutor")

    @patch("core.runtime.ModelRouter", return_value=_FakeRouter())
    def test_agent_filter(self, _m):
        self.client.post("/agents/tutor/run", json={"task": "hi"}, headers={"x-token": self.tok})
        r = self.client.get("/agents/runs?agent=strategist", headers={"x-token": self.tok})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["count"], 0)

    @patch("core.runtime.ModelRouter", return_value=_FakeRouter())
    def test_status_filter(self, _m):
        self.client.post("/agents/tutor/run", json={"task": "hi"}, headers={"x-token": self.tok})
        r = self.client.get("/agents/runs?status=completed", headers={"x-token": self.tok})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["count"], 1)
        r2 = self.client.get("/agents/runs?status=failed", headers={"x-token": self.tok})
        self.assertEqual(r2.json()["count"], 0)

    def test_invalid_status(self):
        r = self.client.get("/agents/runs?status=queued", headers={"x-token": self.tok})
        self.assertEqual(r.status_code, 422)

    def test_invalid_limit(self):
        r = self.client.get("/agents/runs?limit=0", headers={"x-token": self.tok})
        self.assertEqual(r.status_code, 422)
        r2 = self.client.get("/agents/runs?limit=500", headers={"x-token": self.tok})
        self.assertEqual(r2.status_code, 422)

    def test_invalid_offset(self):
        r = self.client.get("/agents/runs?offset=-1", headers={"x-token": self.tok})
        self.assertEqual(r.status_code, 422)

    @patch("core.runtime.ModelRouter", return_value=_FakeRouter())
    def test_pagination(self, _m):
        for _ in range(3):
            self.client.post("/agents/tutor/run", json={"task": "hi"}, headers={"x-token": self.tok})
        r = self.client.get("/agents/runs?limit=2&offset=0", headers={"x-token": self.tok})
        self.assertEqual(r.json()["count"], 2)
        r2 = self.client.get("/agents/runs?limit=2&offset=2", headers={"x-token": self.tok})
        self.assertEqual(r2.json()["count"], 1)

    @patch("core.runtime.ModelRouter", return_value=_FakeRouter())
    def test_excludes_sensitive_fields(self, _m):
        self.client.post("/agents/tutor/run", json={"task": "secret"}, headers={"x-token": self.tok})
        r = self.client.get("/agents/runs", headers={"x-token": self.tok})
        item = r.json()["items"][0]
        for key in ("tenant_id", "user_id", "task", "reply", "result_json"):
            self.assertNotIn(key, item)
        self.assertIn("run_id", item)

    def test_empty_history(self):
        r = self.client.get("/agents/runs", headers={"x-token": self.tok})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["count"], 0)


if __name__ == "__main__":
    unittest.main()
